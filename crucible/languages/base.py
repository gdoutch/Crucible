"""Language plugin interface.

A language plugin knows three things and nothing else:
  * whether its toolchain is installed on this machine (`detect_toolchain`)
  * how to turn a submission + harness into something runnable (`build`)
  * how to invoke that runnable thing (`exec_command`)

Everything above this layer -- problems, the runner, the UI -- is language
agnostic. Adding a language means adding one subclass and registering it; see
`python_lang.py` for a ~60 line example.
"""

from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

# Keep console windows from flashing up on every compile/run on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class ToolchainStatus:
    """The result of looking for a language's compiler/interpreter."""

    available: bool
    summary: str
    detail: str = ""
    remedy: str = ""

    def __str__(self) -> str:  # pragma: no cover - display helper
        return self.summary


@dataclass
class BuildResult:
    """Outcome of compiling (or syntax-checking) a submission."""

    ok: bool
    output: str = ""
    command: str = ""
    artifact: Path | None = None
    duration: float = 0.0


@dataclass
class ExecResult:
    """Raw outcome of running one test case. No pass/fail judgement here --
    that belongs to the runner, which owns the comparison rules."""

    stdout: str
    stderr: str
    exit_code: int | None
    duration: float
    timed_out: bool = False
    launch_error: str = ""


def run_process(
    command: list[str],
    cwd: Path,
    stdin_data: str = "",
    timeout: float = 10.0,
    env: dict[str, str] | None = None,
) -> ExecResult:
    """Run `command`, feeding it `stdin_data`, and capture everything.

    Shared by every language plugin so that timeout handling, encoding and
    Windows console suppression behave identically no matter what is running.
    """
    started = time.perf_counter()
    try:
        proc = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
            env={**os.environ, **(env or {})},
        )
    except OSError as exc:
        return ExecResult("", "", None, time.perf_counter() - started,
                          launch_error=f"Could not start process: {exc}")

    try:
        stdout, stderr = proc.communicate(stdin_data, timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        timed_out = True

    return ExecResult(
        stdout=stdout or "",
        stderr=stderr or "",
        exit_code=proc.returncode,
        duration=time.perf_counter() - started,
        timed_out=timed_out,
    )


class Language(ABC):
    """Base class for a supported language."""

    #: stable identifier used in problem files (`"language": "c"`)
    id: str = ""
    #: human readable name for the UI
    display_name: str = ""
    #: filename the candidate's code is written to
    solution_filename: str = ""
    #: filename the problem's harness is written to
    harness_filename: str = ""
    #: comment prefix, used when generating starter files
    line_comment: str = "//"
    #: keywords for the editor's syntax highlighter
    keywords: tuple[str, ...] = ()

    def __init__(self) -> None:
        self._toolchain: ToolchainStatus | None = None

    # -- toolchain ---------------------------------------------------------

    @abstractmethod
    def detect_toolchain(self) -> ToolchainStatus:
        """Look for the compiler/interpreter. Called rarely; may be slow."""

    def toolchain(self, refresh: bool = False) -> ToolchainStatus:
        """Cached `detect_toolchain`."""
        if self._toolchain is None or refresh:
            self._toolchain = self.detect_toolchain()
        return self._toolchain

    # -- build / run -------------------------------------------------------

    @abstractmethod
    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        """Write the sources into `workdir` and produce a runnable artifact.

        Implementations must keep the candidate's code in its own translation
        unit so that compiler diagnostics carry line numbers matching the
        editor exactly -- no offset arithmetic anywhere in the app.
        """

    @abstractmethod
    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        """The argv used to run one test case against a successful build."""

    # -- helpers -----------------------------------------------------------

    def run_test(
        self,
        workdir: Path,
        build: BuildResult,
        stdin_data: str,
        timeout: float,
    ) -> ExecResult:
        return run_process(
            self.exec_command(workdir, build), workdir, stdin_data, timeout
        )

    def clean_diagnostics(self, text: str) -> str:
        """Strip absolute temp paths out of compiler output so the candidate
        sees `solution.c:4:9: error:` rather than a 200 character path."""
        return text
