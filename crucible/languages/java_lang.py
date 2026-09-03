"""Java language support.

Submissions are compiled as a *separate translation unit* from the problem's
harness, the same split `c_lang` and `cpp_lang` use and for the same reason:

    Solution.java   <- exactly what the candidate typed, byte for byte
    Harness.java    <- problem-supplied main(); calls the method it needs

`Solution.java` holds `public class Solution`, matching Java's rule that a
file's *public* top-level class must share its name. `Harness.java` holds a
plain, non-public `class Harness` with a `public static void main` -- Java
only enforces the filename/class-name match for a *public* class, so a
package-private one is free to live in a file named after its role (harness)
rather than its class name, which is what keeps this split working at all:
a file that had to be named after a public `Main` class could not also be
called `harness.java` the way every other language plugin's harness file is.

Locating a JDK is entirely unlike locating a C-family compiler -- there is no
MSVC-style captured environment, just a `javac`/`java` pair to find -- so it
gets its own small discovery routine rather than sharing `native_compiler`.
One thing it is deliberately careful about: once `javac` is found, `java` is
read from *the same directory*, never independently re-resolved from PATH.
A machine can easily have more than one JDK/JRE installed with the two not
agreeing about which one PATH favours for each -- `javac` resolving to one
JDK while a bare `java` resolves to an unrelated, older runtime -- and
running a candidate's freshly-compiled classes on a mismatched `java` is
exactly the kind of thing that would fail in a way that has nothing to do
with the candidate's code.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from glob import glob
from pathlib import Path

from ..i18n import t
from .base import BuildResult, Language, ToolchainStatus, run_process, _NO_WINDOW

_IS_WINDOWS = platform.system() == "Windows"
_EXE = ".exe" if _IS_WINDOWS else ""

#: Glob patterns for `javac`, checked after PATH and JAVA_HOME come up empty.
#: Each is tried with `glob()` and the matches sorted so a newer-looking
#: version directory (lexically greater) is preferred -- "jdk-21" over
#: "jdk-17" -- without needing to actually parse version numbers.
_WINDOWS_GLOBS = (
    r"C:\Program Files\Java\*\bin\javac.exe",
    r"C:\Program Files\Eclipse Adoptium\*\bin\javac.exe",
    r"C:\Program Files\Microsoft\jdk-*\bin\javac.exe",
    r"C:\Program Files\Zulu\*\bin\javac.exe",
    r"C:\Program Files\BellSoft\*\bin\javac.exe",
)
_POSIX_GLOBS = (
    "/usr/lib/jvm/*/bin/javac",
    "/opt/homebrew/opt/openjdk*/bin/javac",
    "/usr/local/opt/openjdk*/bin/javac",
    "/Library/Java/JavaVirtualMachines/*/Contents/Home/bin/javac",
)


def _install_help() -> str:
    return t("languages.java.install_help_windows" if _IS_WINDOWS
             else "languages.java.install_help_posix")


def _which_javac() -> str | None:
    """`javac` from PATH, then `JAVA_HOME`, then well-known install roots."""
    found = shutil.which("javac")
    if found:
        return found

    java_home = os.environ.get("JAVA_HOME")
    if java_home:
        candidate = Path(java_home) / "bin" / ("javac" + _EXE)
        if candidate.is_file():
            return str(candidate)

    for pattern in (_WINDOWS_GLOBS if _IS_WINDOWS else _POSIX_GLOBS):
        matches = sorted(glob(pattern), reverse=True)
        if matches:
            return matches[0]
    return None


def _java_beside(javac: str) -> str | None:
    """`java` from the same `bin` directory as `javac` -- deliberately never
    re-resolved from PATH independently; see the module docstring for why."""
    candidate = Path(javac).parent / ("java" + _EXE)
    if candidate.is_file():
        return str(candidate)
    return shutil.which("java")  # degraded fallback for an unusual install


def _probe_version(javac: str) -> str:
    try:
        proc = subprocess.run(
            [javac, "-version"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
        # JDK 10+ writes "javac 21.0.2" to stdout; JDK 8 writes it to stderr.
        # Either way, strip the leading "javac " -- {version} is interpolated
        # straight into "Java: JDK {version}", which would otherwise read
        # "Java: JDK javac 21.0.2".
        first = (proc.stdout or proc.stderr or "").strip().splitlines()
        line = first[0] if first else ""
        return line.removeprefix("javac ").strip()
    except (OSError, subprocess.SubprocessError):
        return ""


class JavaLanguage(Language):
    id = "java"
    display_name = "Java"
    solution_filename = "Solution.java"
    harness_filename = "Harness.java"
    line_comment = "//"
    keywords = (
        "abstract", "assert", "boolean", "break", "byte", "case", "catch",
        "char", "class", "const", "continue", "default", "do", "double",
        "else", "enum", "extends", "final", "finally", "float", "for",
        "goto", "if", "implements", "import", "instanceof", "int",
        "interface", "long", "native", "new", "package", "private",
        "protected", "public", "record", "return", "short", "static",
        "strictfp", "super", "switch", "synchronized", "this", "throw",
        "throws", "transient", "try", "void", "volatile", "while", "var",
        "true", "false", "null",
    )

    def __init__(self) -> None:
        super().__init__()
        self._javac: str | None = None
        self._java: str | None = None

    # -- toolchain -----------------------------------------------------------

    def detect_toolchain(self) -> ToolchainStatus:
        self._javac = None
        self._java = None

        javac = _which_javac()
        if not javac:
            return ToolchainStatus(
                available=False,
                summary=t("languages.java.summary_not_found"),
                detail=t("languages.java.detail_not_found"),
                remedy=_install_help(),
            )

        version = _probe_version(javac)
        if not version:
            return ToolchainStatus(
                available=False,
                summary=t("languages.java.summary_broken"),
                detail=t("languages.java.detail_broken", path=javac),
                remedy=_install_help(),
            )

        java = _java_beside(javac)
        if not java:
            return ToolchainStatus(
                available=False,
                summary=t("languages.java.summary_no_java"),
                detail=t("languages.java.detail_no_java", path=javac),
                remedy=_install_help(),
            )

        self._javac, self._java = javac, java
        return ToolchainStatus(
            available=True,
            summary=t("languages.java.summary", version=version),
            detail=t("languages.java.detail", javac=javac, java=java),
        )

    # -- build -----------------------------------------------------------------

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        status = self.toolchain()
        if not status.available or not self._javac or not self._java:
            return BuildResult(ok=False, output=status.remedy or status.detail)

        (workdir / self.solution_filename).write_text(solution, encoding="utf-8")
        (workdir / self.harness_filename).write_text(harness, encoding="utf-8")

        command = [
            self._javac, "-encoding", "UTF-8", "-d", ".",
            self.solution_filename, self.harness_filename,
        ]

        started = time.perf_counter()
        result = run_process(command, workdir, timeout=60)
        elapsed = time.perf_counter() - started

        if result.launch_error:
            return BuildResult(ok=False, output=result.launch_error,
                               command=" ".join(command), duration=elapsed)

        raw = "\n".join(part for part in (result.stdout, result.stderr)
                        if part.strip())
        raw = raw.replace(str(workdir) + os.sep, "").replace(str(workdir), "")
        output = self.clean_diagnostics(raw)

        harness_class = workdir / "Harness.class"
        ok = result.exit_code == 0 and harness_class.is_file()
        if result.timed_out:
            ok, output = False, t("languages.java.compile_timeout")
        return BuildResult(
            ok=ok,
            output=output.strip(),
            command=" ".join(command),
            artifact=harness_class if ok else None,
            duration=elapsed,
        )

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        # -Dfile.encoding pins the default charset Scanner/System.out use to
        # UTF-8 regardless of the platform's own default (notably Windows,
        # which is not UTF-8 by default before JDK 18's JEP 400) -- without
        # it, a harness reading non-ASCII stdin, or a JDK 17 install like the
        # one this plugin was written against, could silently mis-decode it.
        return [self._java or "java", "-Dfile.encoding=UTF-8",
               "-cp", ".", "Harness"]

    # -- diagnostics -------------------------------------------------------

    def clean_diagnostics(self, text: str) -> str:
        """Collapse `C:\\...\\temp\\crucible_x\\Solution.java:4: error:` down
        to `Solution.java:4: error:`.

        Usually a no-op: `javac` is invoked with the two source files named
        relatively (cwd is already the workdir), so its own diagnostics
        already read that way. This is a safety net for the rarer messages
        (a `-d` target, a classpath entry) that echo a path back in full.
        """
        if not text:
            return ""
        for name in (self.solution_filename, self.harness_filename):
            text = re.sub(r"\S*[\\/]" + re.escape(name), name, text)
        return text

    def describe_exit(self, exit_code: int | None) -> str:
        """Turn a raw exit status into something a Java learner can act on.

        Deliberately narrower than `c_lang`'s or `cpp_lang`'s: an uncaught
        exception or a `StackOverflowError` in Java is not a process crash --
        `java` catches it, prints the stack trace to stderr, and exits with
        an ordinary status (1), which candidate code could just as easily
        have returned on purpose via `System.exit(1)`. There is no unambiguous
        signature to detect there the way there is for a genuine NTSTATUS or
        signal, so exit code 1 is left to read as itself; the stack trace, if
        there is one, is already visible in the captured stderr.
        """
        if exit_code is None:
            return ""

        # A native JVM crash -- vanishingly rare for ordinary submissions,
        # but if it happens it is reported the same way a C/C++ crash is.
        if _IS_WINDOWS:
            status = {
                0xC0000005: t("languages.java.exit.access_violation"),
                0xC00000FD: t("languages.java.exit.stack_overflow"),
                0xC000013A: t("languages.java.exit.interrupted"),
            }
            described = status.get(exit_code & 0xFFFFFFFF)
            return (t("languages.java.exit.crashed", description=described) if described
                    else t("languages.common.exited_with_status", code=exit_code))

        signals = {-11: t("languages.java.exit.sigsegv"),
                   -6: t("languages.java.exit.sigabrt")}
        if exit_code in signals:
            return signals[exit_code]
        if exit_code < 0:
            return t("languages.java.exit.killed_by_signal", signal=-exit_code)
        return t("languages.common.exited_with_status", code=exit_code)
