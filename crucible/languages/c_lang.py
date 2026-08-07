"""C language support.

Submissions are compiled as a *separate translation unit* from the problem's
harness:

    solution.c   <- exactly what the candidate typed, byte for byte
    harness.c    <- problem-supplied main(); declares the prototype it needs

Both are compiled and linked into one executable. Keeping them separate means
compiler errors point at real line numbers in the editor, with no prelude
offset to correct for, and it stops a candidate from accidentally (or
deliberately) redefining the harness.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

from .base import BuildResult, Language, ToolchainStatus, run_process, _NO_WINDOW

_IS_WINDOWS = platform.system() == "Windows"
_EXE = ".exe" if _IS_WINDOWS else ""

#: Compilers we know how to drive, in order of preference. GCC and Clang share
#: a command line; MSVC gets its own.
_GNU_LIKE = ("gcc", "clang", "cc")

#: Places a Windows C compiler commonly lands but which are frequently missing
#: from PATH. Searched only after PATH itself comes up empty.
_WINDOWS_HINTS = (
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

_POSIX_HINTS = ("/usr/bin", "/usr/local/bin", "/opt/homebrew/bin", "/opt/local/bin")

_INSTALL_HELP_WINDOWS = (
    "No C compiler found.\n\n"
    "Pick whichever is easiest for you:\n\n"
    "  1. w64devkit  -- a single portable zip, no installer, ~80 MB.\n"
    "     https://github.com/skeeto/w64devkit/releases\n"
    "     Unzip it, then add its bin\\ folder to PATH (or just relaunch this\n"
    "     app -- C:\\w64devkit\\bin is auto-detected).\n\n"
    "  2. MSYS2      -- full package manager, best long term.\n"
    "     https://www.msys2.org  then:  pacman -S mingw-w64-ucrt-x86_64-gcc\n\n"
    "  3. Visual Studio -- you already have VS installed, but without the C++\n"
    "     toolset. Open the Visual Studio Installer, click Modify, and tick\n"
    "     'Desktop development with C++'.\n\n"
    "Re-check from the Tools menu once installed -- no restart needed."
)

_INSTALL_HELP_POSIX = (
    "No C compiler found.\n\n"
    "  Debian/Ubuntu:  sudo apt install build-essential\n"
    "  Fedora:         sudo dnf install gcc\n"
    "  macOS:          xcode-select --install\n\n"
    "Re-check from the Tools menu once installed."
)


def _which(name: str) -> str | None:
    """`shutil.which`, falling back to well known install directories."""
    found = shutil.which(name)
    if found:
        return found
    hints = _WINDOWS_HINTS if _IS_WINDOWS else _POSIX_HINTS
    for hint in hints:
        candidate = Path(hint) / (name + _EXE)
        if candidate.is_file():
            return str(candidate)
    return None


def _probe_version(path: str) -> str:
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


def _msvc_environment() -> dict[str, str] | None:
    """Locate MSVC via vswhere and capture the environment vcvars sets up.

    `cl.exe` refuses to work without INCLUDE/LIB/PATH being configured, so we
    shell out to vcvarsall.bat once and keep the variables it exports.
    """
    if not _IS_WINDOWS:
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
    vcvars = Path(install[0]) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not vcvars.is_file():
        return None

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

    env: dict[str, str] = {}
    for line in dump.stdout.decode("utf-16-le", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.upper() in {"PATH", "INCLUDE", "LIB", "LIBPATH"}:
            env[key.upper()] = value
    return env or None


class CLanguage(Language):
    id = "c"
    display_name = "C"
    solution_filename = "solution.c"
    harness_filename = "harness.c"
    line_comment = "//"
    keywords = (
        "auto", "break", "case", "char", "const", "continue", "default", "do",
        "double", "else", "enum", "extern", "float", "for", "goto", "if",
        "inline", "int", "long", "register", "restrict", "return", "short",
        "signed", "sizeof", "static", "struct", "switch", "typedef", "union",
        "unsigned", "void", "volatile", "while", "bool", "size_t", "NULL",
        "true", "false",
    )

    def __init__(self) -> None:
        super().__init__()
        self._compiler: str | None = None
        self._kind: str = ""          # "gnu" | "msvc"
        self._env: dict[str, str] = {}

    # -- toolchain ---------------------------------------------------------

    def detect_toolchain(self) -> ToolchainStatus:
        self._compiler = None
        self._kind = ""
        self._env = {}

        for name in _GNU_LIKE:
            path = _which(name)
            if path:
                self._compiler, self._kind = path, "gnu"
                version = _probe_version(path) or name
                return ToolchainStatus(
                    available=True,
                    summary=f"C: {version}",
                    detail=f"Compiler: {path}\nMode: GCC-compatible command line",
                )

        # MSVC, either already on PATH (dev prompt) or via vcvars.
        cl_on_path = shutil.which("cl")
        env = _msvc_environment()
        if env:
            cl = shutil.which("cl", path=env.get("PATH", ""))
            if cl:
                self._compiler, self._kind, self._env = cl, "msvc", env
                return ToolchainStatus(
                    available=True,
                    summary="C: Microsoft Visual C++ (MSVC)",
                    detail=f"Compiler: {cl}\nEnvironment initialised from vcvars64.bat",
                )
        elif cl_on_path:
            self._compiler, self._kind = cl_on_path, "msvc"
            return ToolchainStatus(
                available=True,
                summary="C: Microsoft Visual C++ (MSVC, from current environment)",
                detail=f"Compiler: {cl_on_path}",
            )

        return ToolchainStatus(
            available=False,
            summary="C: no compiler found",
            detail="Searched PATH and the usual install locations for "
                   + ", ".join(_GNU_LIKE) + " and cl.exe.",
            remedy=_INSTALL_HELP_WINDOWS if _IS_WINDOWS else _INSTALL_HELP_POSIX,
        )

    # -- build -------------------------------------------------------------

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        status = self.toolchain()
        if not status.available or not self._compiler:
            return BuildResult(ok=False, output=status.remedy or status.detail)

        (workdir / self.solution_filename).write_text(solution, encoding="utf-8")
        (workdir / self.harness_filename).write_text(harness, encoding="utf-8")
        exe = workdir / ("prog" + _EXE)

        if self._kind == "msvc":
            # /Z7 rather than /Zi: debug info goes into the .obj files, so no
            # PDB is written and the two translation units cannot contend over
            # one. Object files default to the cwd, which is already workdir --
            # passing /Fo with a relative name would point at a subdirectory
            # that does not exist.
            command = [
                self._compiler, "/nologo", "/W3", "/TC", "/Od", "/Z7",
                # The harness uses scanf/fgets, which MSVC flags as "unsafe" in
                # favour of its non-portable _s variants. Without this every
                # correct submission would come back with warnings the
                # candidate did not cause and cannot fix.
                "/D_CRT_SECURE_NO_WARNINGS",
                f"/Fe:{exe.name}",
                self.solution_filename, self.harness_filename,
            ]
        else:
            command = [
                self._compiler, "-std=c11", "-O0", "-g", "-Wall", "-Wextra",
                self.solution_filename, self.harness_filename,
                "-o", exe.name, "-lm",
            ]

        started = time.perf_counter()
        result = run_process(command, workdir, timeout=60, env=self._env or None)
        elapsed = time.perf_counter() - started

        if result.launch_error:
            return BuildResult(ok=False, output=result.launch_error,
                               command=" ".join(command), duration=elapsed)

        raw = "\n".join(part for part in (result.stdout, result.stderr)
                        if part.strip())
        # Strip the temp directory by exact match first -- that is reliable even
        # when the path contains spaces -- then fall back to the generic rule.
        raw = raw.replace(str(workdir) + os.sep, "").replace(str(workdir), "")
        if self._kind == "msvc":
            raw = self._strip_msvc_noise(raw)
        output = self.clean_diagnostics(raw)
        ok = result.exit_code == 0 and exe.is_file()
        if result.timed_out:
            ok, output = False, "Compilation timed out after 60s."
        return BuildResult(
            ok=ok,
            output=output.strip(),
            command=" ".join(command),
            artifact=exe if ok else None,
            duration=elapsed,
        )

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        target = build.artifact or (workdir / ("prog" + _EXE))
        return [str(target)]

    # -- diagnostics -------------------------------------------------------

    def clean_diagnostics(self, text: str) -> str:
        """Collapse `C:\\...\\temp\\crucible_x\\solution.c:4:9: error:` down to
        `solution.c:4:9: error:`.

        Only the directory part of a path token is removed, so leading prose
        such as "In file included from " survives untouched.
        """
        if not text:
            return ""
        for name in (self.solution_filename, self.harness_filename):
            text = re.sub(r"\S*[\\/]" + re.escape(name), name, text)
        return text

    def _strip_msvc_noise(self, text: str) -> str:
        """cl echoes each source filename as it compiles it, and announces the
        link step. Neither tells the candidate anything, and both crowd out the
        diagnostic that does."""
        noise = {self.solution_filename, self.harness_filename,
                 "Generating Code..."}
        return "\n".join(line for line in text.splitlines()
                         if line.strip() not in noise)

    def describe_exit(self, exit_code: int | None) -> str:
        """Turn a raw exit status into something a C learner can act on."""
        if exit_code is None:
            return ""

        # Windows reports crashes as an NTSTATUS, POSIX as a negative signal
        # number. Decide by platform rather than by sign: an NTSTATUS that
        # arrived signed would otherwise be read as a (nonsensical) signal.
        if _IS_WINDOWS:
            status = {
                0xC0000005: "access violation (bad pointer / buffer overrun)",
                0xC0000094: "integer division by zero",
                0xC00000FD: "stack overflow (runaway recursion?)",
                0xC000013A: "interrupted",
            }
            described = status.get(exit_code & 0xFFFFFFFF)
            return (f"crashed: {described}" if described
                    else f"exited with status {exit_code}")

        signals = {-11: "SIGSEGV (segmentation fault)", -6: "SIGABRT (abort)",
                   -8: "SIGFPE (arithmetic error, e.g. divide by zero)"}
        if exit_code in signals:
            return signals[exit_code]
        if exit_code < 0:
            return f"killed by signal {-exit_code}"
        return f"exited with status {exit_code}"
