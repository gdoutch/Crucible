"""Shared machinery for driving a native, compiled-straight-to-a-binary
compiler in the GCC/Clang/MSVC family.

`c_lang` and `cpp_lang` differ only in *which* compiler executables they look
for (`gcc`/`clang`/`cc` vs `g++`/`clang++`/`c++`) and *which* flags they pass
once one is found -- not in how a compiler is located on disk, or in how
MSVC's environment is captured. That shared part lives here once rather than
twice, so a fix to (say) the vcvars cache's self-heal logic applies to both
languages automatically instead of needing to be made -- and kept in sync --
in two places.
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from .. import workspace
from .base import ExecResult, _NO_WINDOW

IS_WINDOWS = platform.system() == "Windows"
EXE = ".exe" if IS_WINDOWS else ""

#: Places a Windows C-family compiler commonly lands but which are frequently
#: missing from PATH. Searched only after PATH itself comes up empty.
WINDOWS_HINTS = (
    r"C:\msys64\ucrt64\bin",
    r"C:\msys64\mingw64\bin",
    r"C:\msys64\clang64\bin",
    r"C:\msys64\usr\bin",
    r"C:\MinGW\bin",
    r"C:\mingw64\bin",
    r"C:\TDM-GCC-64\bin",
    r"C:\w64devkit\bin",
    r"C:\ProgramData\chocolatey\bin",
    r"C:\Program Files\LLVM\bin",
    r"C:\Program Files\Git\mingw64\bin",
)

POSIX_HINTS = ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin")


def which(name: str) -> str | None:
    """`shutil.which`, falling back to well known install directories."""
    import shutil
    found = shutil.which(name)
    if found:
        return found
    hints = WINDOWS_HINTS if IS_WINDOWS else POSIX_HINTS
    for hint in hints:
        candidate = Path(hint) / (name + EXE)
        if candidate.is_file():
            return str(candidate)
    return None


def probe_version(path: str) -> str:
    try:
        proc = subprocess.run(
            [path, "--version"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        first = (proc.stdout or proc.stderr or "").strip().splitlines()
        return first[0] if first else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# -- MSVC ---------------------------------------------------------------
#
# `cl.exe` is the one compiler in this family that is not a self-contained
# executable on PATH: it refuses to run at all without INCLUDE/LIB/PATH set
# up by a Visual Studio developer prompt, and the only supported way to learn
# those is to run vcvarsall.bat, which takes ~12 seconds. That environment is
# identical whether the file about to be compiled is `.c` or `.cpp` -- there
# is exactly one MSVC toolchain, one vcvars script, one set of SDK headers --
# so it is captured and cached once here rather than once per language.

#: Environment variables worth keeping out of a vcvars dump. PATH is handled
#: separately -- see `_split_path_prefix`.
_VCVARS_KEEP = ("INCLUDE", "LIB", "LIBPATH")

#: Where the Windows SDK headers live. Its subdirectory names are the installed
#: SDK versions, and the captured environment names one of them, so a new SDK
#: appearing here is a reason to recapture.
_SDK_INCLUDE = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
    / "Windows Kits" / "10" / "Include"


def _vs_install_path() -> Path | None:
    """Ask vswhere where Visual Studio is. ~0.1s, so never cached: doing it
    fresh every time is what makes "VS was moved, removed, or a second edition
    is now the latest" impossible to get wrong."""
    if not IS_WINDOWS:
        return None
    vswhere = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) \
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.is_file():
        return None
    try:
        proc = subprocess.run(
            [str(vswhere), "-latest", "-products", "*",
             "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    install = (proc.stdout or "").strip().splitlines()
    if not install:
        return None  # VS is present but the C++ workload is not installed
    return Path(install[0])


def _msvc_fingerprint(install: Path, vcvars: Path) -> list:
    """A cheap stand-in for "would vcvars still print the same thing?".

    Every element is something the captured environment demonstrably depends
    on: the capture embeds an MSVC toolset version and a Windows SDK version
    as literal path components, and is produced by running vcvars64.bat out of
    a particular installation. Together these cost a few stats, against the
    ~12 seconds of the answer they stand in for.

    `Microsoft.VCToolsVersion.default.txt` is the useful one: it is how vcvars
    itself decides which toolset to select, so reading it asks the question
    almost directly rather than inferring it.
    """
    try:
        toolset = (install / "VC" / "Auxiliary" / "Build" /
                   "Microsoft.VCToolsVersion.default.txt").read_text(
                       encoding="utf-8").strip()
    except OSError:
        toolset = ""
    try:
        stamp = vcvars.stat()
        vcvars_stamp = [int(stamp.st_mtime), stamp.st_size]
    except OSError:
        vcvars_stamp = []
    try:
        sdks = sorted(p.name for p in _SDK_INCLUDE.iterdir() if p.is_dir())
    except OSError:
        sdks = []
    return [str(install), toolset, vcvars_stamp, sdks]


def _split_path_prefix(captured_path: str) -> list[str]:
    """Keep only the entries vcvars *added*, dropping the ambient PATH it
    inherited and echoed back.

    This matters because the capture is reused across sessions and
    `run_process` merges it as `{**os.environ, **env}` -- so a stored PATH
    overrides the live one. Keeping the whole thing would pin whatever PATH
    happened to be set the day it was captured, and quietly hide anything
    installed afterwards. Only the entries vcvars itself contributes -- about
    twenty, all under the VS install, the Windows Kits or the .NET framework
    directory -- are ours to remember; the rest is recomposed from the real
    environment at use time.

    Anything dropped for being ambient is still reachable, because it is in
    the live PATH by definition.
    """
    ambient = {p.rstrip("\\").lower()
               for p in os.environ.get("PATH", "").split(os.pathsep) if p}
    return [p for p in captured_path.split(os.pathsep)
            if p and p.rstrip("\\").lower() not in ambient]


def _compose_msvc_env(captured: dict) -> dict[str, str]:
    """Turn a stored capture back into a full environment overlay."""
    prefix = [p for p in captured.get("PATH_PREFIX", []) if p]
    live = os.environ.get("PATH", "")
    env = {k: str(captured[k]) for k in _VCVARS_KEEP if k in captured}
    env["PATH"] = os.pathsep.join(prefix + ([live] if live else []))
    return env


def _capture_vcvars(vcvars: Path) -> dict | None:
    """Run vcvars64.bat and keep what it exported. The slow path: ~12s."""
    # Must be passed as a raw string, not a list: list2cmdline would escape the
    # quotes around the (space-containing) vcvars path into \" , which cmd does
    # not understand. /u makes `set` emit UTF-16 so non-ASCII paths survive.
    try:
        dump = subprocess.run(
            f'cmd /u /c "{vcvars}" >nul && set',
            capture_output=True, timeout=120, creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if dump.returncode != 0:
        return None

    captured: dict = {}
    for line in dump.stdout.decode("utf-16-le", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.upper()
        if key in _VCVARS_KEEP:
            captured[key] = value
        elif key == "PATH":
            captured["PATH_PREFIX"] = _split_path_prefix(value)
    return captured or None


def msvc_environment(ignore_cache: bool = False) -> dict[str, str] | None:
    """Locate MSVC and return the environment `cl.exe` needs to run.

    The result changes only when Visual Studio does, so it is cached against
    `_msvc_fingerprint`, which costs a handful of stats to check -- shared by
    every native-language plugin that might ask for it, since the cache lives
    on the fingerprint alone, not on which language is asking.

    That leaves the vswhere call above as the whole cost of a warm start:
    ~0.12s against ~12s cold. Caching that too would save the last of it, but
    only by giving up the one check that cannot go stale, which is a poor
    trade for a tenth of a second on a background thread.

    `ignore_cache` forces a recapture, for a language's own self-heal when a
    build fails in a way that suggests the cached environment has gone stale.
    """
    install = _vs_install_path()
    if install is None:
        return None
    vcvars = install / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not vcvars.is_file():
        return None

    stamp = _msvc_fingerprint(install, vcvars)
    if not ignore_cache:
        cached = workspace.load_msvc_env(stamp)
        if cached is not None:
            return _compose_msvc_env(cached)

    captured = _capture_vcvars(vcvars)
    if captured is None:
        return None
    workspace.save_msvc_env(stamp, captured)
    return _compose_msvc_env(captured)


#: Compiler output that means "the environment is wrong", as distinct from
#: "the code is wrong". A missing standard header or a cl.exe that will not
#: start is not something a candidate's submission can cause, so it is the
#: signal that a cached vcvars capture has gone stale.
STALE_ENVIRONMENT_SIGNATURES = (
    "cannot open include file",
    "is not recognized as an internal or external command",
    "the system cannot find the path specified",
    "cannot open input file",
    "lnk1104",   # cannot open file -- usually a LIB path that has moved
    "lnk1181",
)


def is_stale_environment(kind: str, env: dict | None, result: ExecResult) -> bool:
    """Does this failed build look like a bad MSVC environment rather than
    bad candidate code? Only meaningful for `kind == "msvc"` -- a GNU-like
    compiler has no captured environment to go stale."""
    if kind != "msvc" or not env:
        return False
    if result.exit_code == 0:
        return False
    haystack = f"{result.stdout}\n{result.stderr}\n{result.launch_error}".lower()
    return any(sig in haystack for sig in STALE_ENVIRONMENT_SIGNATURES)
