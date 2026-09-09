"""C++ language support.

Submissions are compiled as a *separate translation unit* from the problem's
harness, the same split `c_lang` uses and for the same reason:

    solution.cpp   <- exactly what the candidate typed, byte for byte
    harness.cpp    <- problem-supplied main(); declares the prototype it needs

Both are compiled and linked into one executable, so compiler diagnostics
carry the real filename and line number the editor shows, and a candidate
cannot accidentally (or deliberately) redefine the harness.

Locating a compiler is shared with `c_lang` -- see `native_compiler` -- since
both languages are driven by the same GCC/Clang/MSVC family, and a machine
that can already build C can, in the overwhelming majority of cases, already
build C++ too: `g++`/`clang++` ship alongside `gcc`/`clang` in every mainstream
install (MSYS2, w64devkit, Debian/Ubuntu's `build-essential`, Xcode's command
line tools), and MSVC's `cl.exe` compiles both from the one install. Fedora is
the one common exception, where `gcc-c++` is a separate package from `gcc`.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

from .. import workspace
from ..i18n import t
from . import native_compiler as nc
from .base import BuildResult, Language, ToolchainStatus, run_process

_IS_WINDOWS = nc.IS_WINDOWS
_EXE = nc.EXE

#: Compilers we know how to drive, in order of preference. GCC and Clang share
#: a command line; MSVC gets its own.
_GNU_LIKE = ("g++", "clang++", "c++")


def _install_help() -> str:
    return t("languages.cpp.install_help_windows" if _IS_WINDOWS
             else "languages.cpp.install_help_posix")


class CppLanguage(Language):
    id = "cpp"
    display_name = "C++"
    solution_filename = "solution.cpp"
    harness_filename = "harness.cpp"
    line_comment = "//"
    keywords = (
        "alignas", "alignof", "auto", "bool", "break", "case", "catch",
        "char", "class", "const", "constexpr", "continue", "decltype",
        "default", "delete", "do", "double", "else", "enum", "explicit",
        "export", "extern", "false", "final", "float", "for", "friend",
        "goto", "if", "inline", "int", "long", "mutable", "namespace",
        "new", "noexcept", "nullptr", "operator", "override", "private",
        "protected", "public", "register", "return", "short", "signed",
        "sizeof", "static", "static_assert", "static_cast", "struct",
        "switch", "template", "this", "throw", "true", "try", "typedef",
        "typename", "union", "unsigned", "using", "virtual", "void",
        "volatile", "while",
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
            path = nc.which(name)
            if path:
                self._compiler, self._kind = path, "gnu"
                version = nc.probe_version(path) or name
                return ToolchainStatus(
                    available=True,
                    summary=t("languages.cpp.summary_gnu", version=version),
                    detail=t("languages.cpp.detail_gnu", path=path),
                )

        # MSVC, either already on PATH (dev prompt) or via vcvars. The same
        # cl.exe -- and the same captured environment -- that c_lang uses.
        cl_on_path = shutil.which("cl")
        env = nc.msvc_environment()
        if env:
            cl = shutil.which("cl", path=env.get("PATH", ""))
            if cl:
                self._compiler, self._kind, self._env = cl, "msvc", env
                return ToolchainStatus(
                    available=True,
                    summary=t("languages.cpp.summary_msvc"),
                    detail=t("languages.cpp.detail_msvc", path=cl),
                )
        elif cl_on_path:
            self._compiler, self._kind = cl_on_path, "msvc"
            return ToolchainStatus(
                available=True,
                summary=t("languages.cpp.summary_msvc_current_env"),
                detail=t("languages.cpp.detail_msvc_current_env", path=cl_on_path),
            )

        return ToolchainStatus(
            available=False,
            summary=t("languages.cpp.summary_not_found"),
            detail=t("languages.cpp.detail_not_found",
                    compilers=", ".join(_GNU_LIKE)),
            remedy=_install_help(),
            # Same reasoning as c_lang's download_url -- see there.
            download_url=("https://github.com/skeeto/w64devkit/releases"
                          if _IS_WINDOWS else ""),
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
            # /TP forces C++ mode -- unlike gcc/clang, cl.exe picks C vs C++ by
            # file extension, and picking it explicitly means a `.cpp` file
            # named oddly (there is none here, but the flag costs nothing)
            # could never be silently compiled as C. /EHsc turns on standard
            # C++ exception handling; without it, a `try`/`catch` -- or even
            # just a `std::vector` that might throw `bad_alloc` -- compiles
            # with a warning and unwinds incorrectly. /Z7 rather than /Zi:
            # debug info goes into the .obj files, so no PDB is written and
            # the two translation units cannot contend over one.
            command = [
                self._compiler, "/nologo", "/W3", "/TP", "/EHsc",
                "/std:c++17", "/Od", "/Z7",
                "/D_CRT_SECURE_NO_WARNINGS",
                f"/Fe:{exe.name}",
                self.solution_filename, self.harness_filename,
            ]
        else:
            command = [
                self._compiler, "-std=c++17", "-O0", "-g", "-Wall", "-Wextra",
                self.solution_filename, self.harness_filename,
                "-o", exe.name,
            ]

        started = time.perf_counter()
        result = run_process(command, workdir, timeout=60, env=self._env or None)
        if nc.is_stale_environment(self._kind, self._env, result):
            # The cached vcvars capture no longer describes this machine, in
            # some way the fingerprint could not see -- an SDK repaired in
            # place, say. Throw it away, recapture, and try once more. This is
            # the backstop that keeps a bad cache costing one slow build rather
            # than a compile error nobody can explain.
            self._recapture_environment()
            result = run_process(command, workdir, timeout=60,
                                 env=self._env or None)
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
            ok, output = False, t("languages.cpp.compile_timeout")
        return BuildResult(
            ok=ok,
            output=output.strip(),
            command=" ".join(command),
            artifact=exe if ok else None,
            duration=elapsed,
        )

    def _recapture_environment(self) -> None:
        """Discard the cached vcvars capture and take a fresh one."""
        workspace.clear_msvc_env()
        env = nc.msvc_environment(ignore_cache=True)
        if not env:
            return
        cl = shutil.which("cl", path=env.get("PATH", ""))
        if cl:
            self._compiler, self._env = cl, env

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        target = build.artifact or (workdir / ("prog" + _EXE))
        return [str(target)]

    # -- diagnostics -------------------------------------------------------

    def clean_diagnostics(self, text: str) -> str:
        """Collapse `C:\\...\\temp\\crucible_x\\solution.cpp:4:9: error:` down
        to `solution.cpp:4:9: error:`.

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
        """Turn a raw exit status into something a C++ learner can act on."""
        if exit_code is None:
            return ""

        # Windows reports crashes as an NTSTATUS, POSIX as a negative signal
        # number. Decide by platform rather than by sign: an NTSTATUS that
        # arrived signed would otherwise be read as a (nonsensical) signal.
        if _IS_WINDOWS:
            status = {
                0xC0000005: t("languages.cpp.exit.access_violation"),
                0xC0000094: t("languages.cpp.exit.divide_by_zero"),
                # INT_MIN / -1 (or INT_MIN % -1): the mathematically correct
                # result does not fit in a 32-bit int, and unlike +, - and *
                # this is not silently wrapped -- the division instruction
                # itself faults.
                0xC0000095: t("languages.cpp.exit.integer_overflow"),
                0xC00000FD: t("languages.cpp.exit.stack_overflow"),
                0xC000013A: t("languages.cpp.exit.interrupted"),
            }
            described = status.get(exit_code & 0xFFFFFFFF)
            return (t("languages.cpp.exit.crashed", description=described) if described
                    else t("languages.common.exited_with_status", code=exit_code))

        signals = {-11: t("languages.cpp.exit.sigsegv"),
                   -6: t("languages.cpp.exit.sigabrt"),
                   -8: t("languages.cpp.exit.sigfpe")}
        if exit_code in signals:
            return signals[exit_code]
        if exit_code < 0:
            return t("languages.cpp.exit.killed_by_signal", signal=-exit_code)
        return t("languages.common.exited_with_status", code=exit_code)
