"""Test execution.

Two entry points, deliberately sharing one code path:

    run_submission(problem, source)   -- the candidate's code
    verify_reference(problem)         -- the author's known-good solution

They are the same function with a different source string, which is the whole
point: the reference solution is proven against the *exact* pipeline the
candidate's code will face, so "the reference passes" is a meaningful claim
about the tests rather than about a separate, friendlier code path.

Each test case runs as its own process. That costs a few milliseconds per case
and buys two things that matter a lot when the language is C: a segfault in
case 3 leaves cases 4..n perfectly runnable, and a hung loop can be timed out
individually instead of taking the suite with it.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from .languages import BuildResult, Language
from .problem import Problem, TestCase

# Outcome statuses.
PASS = "pass"
FAIL = "fail"
ERROR = "error"        # ran, but crashed or wrote to stderr with non-zero exit
TIMEOUT = "timeout"
SKIPPED = "skipped"    # cancelled before it got to run

ProgressFn = Callable[["TestOutcome", int, int], None]


@dataclass
class TestOutcome:
    test: TestCase
    status: str
    actual: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration: float = 0.0
    message: str = ""

    @property
    def passed(self) -> bool:
        return self.status == PASS

    @property
    def symbol(self) -> str:
        return {PASS: "PASS", FAIL: "FAIL", ERROR: "ERROR",
                TIMEOUT: "TIMEOUT", SKIPPED: "--"}.get(self.status, "?")


@dataclass
class SubmissionResult:
    build: BuildResult
    outcomes: list[TestOutcome] = field(default_factory=list)
    cancelled: bool = False
    #: True when nothing ran because the language's compiler is not installed.
    #: Distinct from a build failure: the problem is fine, the machine is not
    #: set up, and the two must never be reported to the candidate the same way.
    toolchain_missing: bool = False

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def passed(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def all_passed(self) -> bool:
        return self.build.ok and self.total > 0 and self.passed == self.total

    def summary(self) -> str:
        if not self.build.ok:
            return "Build failed"
        if self.cancelled:
            return f"Cancelled -- {self.passed}/{self.total} passed so far"
        return f"{self.passed}/{self.total} tests passed"

    def failures(self) -> list[TestOutcome]:
        return [o for o in self.outcomes if o.status in (FAIL, ERROR, TIMEOUT)]


# ---------------------------------------------------------------------------
# output comparison
# ---------------------------------------------------------------------------

def normalise(text: str) -> str:
    """Canonical form for comparing program output.

    Line endings are unified, trailing whitespace on each line is dropped, and
    trailing blank lines are ignored. Everything else -- including interior
    blank lines and leading whitespace -- is significant, because for most of
    these problems the exact shape of the output *is* the exercise.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in unified.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def outputs_match(expected: str, actual: str) -> bool:
    return normalise(expected) == normalise(actual)


def diff_note(expected: str, actual: str) -> str:
    """A one-line hint about *how* the output differs. Cheap to compute and
    saves the candidate from eyeballing two blocks of near-identical text."""
    exp, act = normalise(expected), normalise(actual)
    if exp == act:
        return ""
    if not act:
        return "produced no output"
    if exp.strip() == act.strip():
        return "output differs only in leading/trailing whitespace"
    if exp.lower() == act.lower():
        return "output differs only in letter case"
    exp_lines, act_lines = exp.split("\n"), act.split("\n")
    if len(exp_lines) != len(act_lines):
        return f"expected {len(exp_lines)} line(s), got {len(act_lines)}"
    for i, (e, a) in enumerate(zip(exp_lines, act_lines), start=1):
        if e != a:
            return f"first difference on line {i}"
    return "output differs"


# ---------------------------------------------------------------------------
# execution
# ---------------------------------------------------------------------------

def _run_cases(
    language: Language,
    problem: Problem,
    workdir: Path,
    build: BuildResult,
    tests: Iterable[TestCase],
    progress: ProgressFn | None,
    cancel: threading.Event | None,
) -> tuple[list[TestOutcome], bool]:
    outcomes: list[TestOutcome] = []
    tests = list(tests)
    total = len(tests)
    cancelled = False

    for index, test in enumerate(tests, start=1):
        if cancel is not None and cancel.is_set():
            cancelled = True
            outcomes.append(TestOutcome(test, SKIPPED, message="cancelled"))
            if progress:
                progress(outcomes[-1], index, total)
            continue

        exec_result = language.run_test(workdir, build, test.stdin,
                                        problem.timeout_seconds)
        outcome = _judge(language, test, exec_result, problem.timeout_seconds)
        outcomes.append(outcome)
        if progress:
            progress(outcome, index, total)

    return outcomes, cancelled


def _judge(language: Language, test: TestCase, exec_result, timeout: float) -> TestOutcome:
    """Turn a raw execution into a verdict.

    Ordering matters: a crash is reported as a crash even if the partial output
    happened to match, because "your program segfaulted" is more useful than
    "test passed".
    """
    outcome = TestOutcome(
        test=test,
        status=FAIL,
        actual=exec_result.stdout,
        stderr=exec_result.stderr,
        exit_code=exec_result.exit_code,
        duration=exec_result.duration,
    )

    if exec_result.launch_error:
        outcome.status = ERROR
        outcome.message = exec_result.launch_error
        return outcome

    if exec_result.timed_out:
        outcome.status = TIMEOUT
        outcome.message = (f"No result after {timeout:g}s -- "
                           f"likely an infinite loop or a blocking read")
        return outcome

    if exec_result.exit_code != 0:
        outcome.status = ERROR
        describe = getattr(language, "describe_exit", None)
        outcome.message = (describe(exec_result.exit_code) if describe
                           else f"exited with status {exec_result.exit_code}")
        return outcome

    if outputs_match(test.expected_stdout, exec_result.stdout):
        outcome.status = PASS
        return outcome

    outcome.status = FAIL
    outcome.message = diff_note(test.expected_stdout, exec_result.stdout)
    return outcome


def _execute(
    problem: Problem,
    source: str,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> SubmissionResult:
    language = problem.language

    status = language.toolchain()
    if not status.available:
        return SubmissionResult(
            build=BuildResult(ok=False,
                              output=status.remedy or status.detail or status.summary),
            toolchain_missing=True,
        )

    workdir = Path(tempfile.mkdtemp(prefix=f"crucible_{problem.id}_"))
    try:
        build = language.build(workdir, source, problem.harness)
        if not build.ok:
            return SubmissionResult(build=build)

        outcomes, cancelled = _run_cases(
            language, problem, workdir, build, problem.tests, progress, cancel
        )
        return SubmissionResult(build=build, outcomes=outcomes, cancelled=cancelled)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def run_submission(
    problem: Problem,
    source: str,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> SubmissionResult:
    """Compile and test the candidate's code."""
    return _execute(problem, source, progress, cancel)


def verify_reference(problem: Problem) -> SubmissionResult:
    """Run the hidden reference solution against the full suite.

    This is the gate described in the feature spec: if this does not come back
    green, the problem is broken and no candidate should be asked to attempt
    it. The UI surfaces the failure to the author rather than silently letting
    someone burn an afternoon on an unsatisfiable test.
    """
    return _execute(problem, problem.reference.source)


def verify_library(problems: list[Problem]) -> dict[str, SubmissionResult]:
    """Pre-verify a whole set of problems. Used by the startup self-check and
    by `--verify` on the command line."""
    return {problem.id: verify_reference(problem) for problem in problems}
