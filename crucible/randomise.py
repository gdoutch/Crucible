"""Randomised test data.

A problem with a `generator` grows extra test cases whose data changes with the
*data set number* -- a seed. Practise the same problem next week and the
numbers are different, so what is being tested is whether you can solve it
rather than whether you remember what came out last time.

The whole design rests on one restriction:

    a generator produces inputs; it never states the expected output.

The expected output for a generated case is captured from the problem's own
reference solution, run through the same build-and-run pipeline a submission
faces. That is what keeps generated data and expected results in step: there is
exactly one thing in the system that decides what an input should produce, and
it is the same thing that has always decided it. A generator that also computed
the answer would be a second implementation of the problem, free to disagree
with the first, and the disagreement would surface as a test case nobody can
pass.

Two consequences worth being explicit about:

  * Generation needs a working toolchain, because it runs the reference. With
    no compiler installed a problem simply keeps its hand-written cases.
  * An input the reference cannot handle -- it crashes, or never returns -- is
    dropped rather than turned into a test case, and the author is told. The
    generator wandered outside the problem's own contract.

Generators are always written in Python, whatever language the problem is in.
They describe data, not solutions, so there is no reason to make an author
write them in C.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import runner
from .languages.base import run_process
from .problem import MAX_GENERATED_CASES, Problem, TestCase

#: Data set numbers are four digits so they are easy to read out, quote in a
#: bug report, or type back in with `--seed`.
SEED_LOW, SEED_HIGH = 1000, 10000

#: A generator is a handful of `rng` calls; anything slower than this is a bug
#: in the generator, not a slow machine. Unrelated to the problem's own
#: per-case timeout, which budgets for the candidate's code.
GENERATOR_TIMEOUT = 10.0

_SOURCE_MODULE = "_crucible_generator"

#: Runs the author's `generate` and prints the cases as JSON.
#:
#: stdout is redirected while `generate` runs, so a stray `print` left in a
#: generator ends up on stderr as a diagnostic instead of corrupting the JSON
#: this driver is trying to hand back.
_DRIVER = f'''\
import contextlib
import io
import json
import random
import sys

import {_SOURCE_MODULE} as author

if not hasattr(author, "generate"):
    sys.exit("the generator must define generate(rng, count)")

seed, count = int(sys.argv[1]), int(sys.argv[2])

chatter = io.StringIO()
with contextlib.redirect_stdout(chatter):
    cases = list(author.generate(random.Random(seed), count))

sys.stderr.write(chatter.getvalue())
json.dump(cases, sys.stdout)
'''


def new_seed() -> int:
    """A fresh data set number."""
    return random.randrange(SEED_LOW, SEED_HIGH)


@dataclass
class GeneratedSuite:
    """The outcome of building one data set."""

    seed: int
    tests: tuple[TestCase, ...] = ()
    #: Why this is not a complete data set. Aimed at the problem's author.
    error: str = ""
    #: Nothing was generated because the language's compiler is missing. Not a
    #: fault in the problem, and must never be reported as one.
    toolchain_missing: bool = False

    @property
    def ok(self) -> bool:
        return not self.error and not self.toolchain_missing


def generate(problem: Problem, seed: int) -> GeneratedSuite:
    """Build one data set for `problem`.

    Deterministic: the same problem and seed always give the same cases, which
    is what lets the app remember which data set you were working on and lets
    `--seed` reproduce a failure exactly.
    """
    if problem.generator is None:
        return GeneratedSuite(seed=seed)

    cases, error = _run_generator(problem, seed)
    if error:
        return GeneratedSuite(seed=seed, error=error)

    captured = runner.capture_outputs(problem, [case["stdin"] for case in cases])
    if captured.toolchain_missing:
        return GeneratedSuite(seed=seed, toolchain_missing=True)
    if not captured.build.ok:
        first = (captured.build.output or "").strip().splitlines()
        return GeneratedSuite(
            seed=seed,
            error="cannot generate data: the reference solution did not build"
                  + (f" ({first[0]})" if first else ""))

    tests: list[TestCase] = []
    taken = {test.name for test in problem.fixed_tests}
    rejected: list[str] = []

    for case, capture in zip(cases, captured.captures):
        if not capture.ok:
            rejected.append(f"{case['name']}: {capture.reason}")
            continue
        name = _unique(case["name"], taken)
        taken.add(name)
        tests.append(TestCase(
            name=name,
            stdin=case["stdin"],
            expected_stdout=capture.output,
            description=case["description"],
            hidden=case["hidden"],
            generated=True,
        ))

    error = ""
    if rejected:
        error = (f"{len(rejected)} generated case(s) were dropped -- the "
                 f"reference solution could not run them: "
                 + "; ".join(rejected[:3]))
    return GeneratedSuite(seed=seed, tests=tuple(tests), error=error)


def apply(problem: Problem, suite: GeneratedSuite) -> None:
    """Attach a data set to a problem, replacing any previous one."""
    problem.generated_tests = suite.tests
    problem.seed = suite.seed


# ---------------------------------------------------------------------------
# running the author's generator
# ---------------------------------------------------------------------------

def _run_generator(problem: Problem, seed: int) -> tuple[list[dict], str]:
    """Execute the generator and return validated cases, or an error message.

    It runs as its own process for the same reasons every test case does:
    a generator that loops forever is timed out rather than taking the app's
    worker thread with it, and it cannot reach into the app's state.
    """
    generator = problem.generator
    assert generator is not None  # only called when there is one

    workdir = Path(tempfile.mkdtemp(prefix=f"crucible_gen_{problem.id}_"))
    try:
        (workdir / f"{_SOURCE_MODULE}.py").write_text(generator.source,
                                                      encoding="utf-8")
        driver = workdir / "_crucible_driver.py"
        driver.write_text(_DRIVER, encoding="utf-8")

        result = run_process(
            [sys.executable, str(driver), str(seed), str(generator.count)],
            cwd=workdir, timeout=GENERATOR_TIMEOUT)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if result.launch_error:
        return [], f"could not start the generator: {result.launch_error}"
    if result.timed_out:
        return [], (f"the generator did not finish in {GENERATOR_TIMEOUT:g}s "
                    f"-- check it for an endless loop")
    if result.exit_code != 0:
        detail = result.stderr.strip().splitlines()
        return [], ("the generator failed: "
                    + (detail[-1] if detail else f"exit status {result.exit_code}"))

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return [], "the generator did not return cases that could be encoded as JSON"

    return _validate(raw)


def _validate(raw: object) -> tuple[list[dict], str]:
    """Check the generator's output before any of it reaches a test case."""
    if not isinstance(raw, list):
        return [], "generate(rng, count) must return a list of cases"
    if not raw:
        return [], "generate(rng, count) returned no cases"
    if len(raw) > MAX_GENERATED_CASES:
        return [], (f"generate(rng, count) returned {len(raw)} cases; "
                    f"the limit is {MAX_GENERATED_CASES}")

    cases: list[dict] = []
    for index, item in enumerate(raw, start=1):
        where = f"generated case {index}"
        if not isinstance(item, dict):
            return [], f"{where} is not an object"
        if "expected_stdout" in item:
            return [], (f"{where} sets 'expected_stdout'. Generators supply "
                        f"inputs only -- the expected output is taken from the "
                        f"reference solution")
        stdin = item.get("stdin")
        if not isinstance(stdin, str):
            return [], f"{where} has no 'stdin' string"
        name = item.get("name") or f"randomised case {index}"
        if not isinstance(name, str):
            return [], f"{where} has a 'name' that is not a string"
        cases.append({
            # Harnesses read lines or scan tokens, so an input that stops
            # mid-line is a trap the generator's author did not mean to set.
            "stdin": stdin if stdin.endswith("\n") or not stdin else stdin + "\n",
            "name": name,
            "description": str(item.get("description", "")),
            "hidden": bool(item.get("hidden", False)),
        })
    return cases, ""


def _unique(name: str, taken: set[str]) -> str:
    """Test names are how a case is identified in the UI, so two cases must
    never share one -- even when a generator is careless about naming."""
    if name not in taken:
        return name
    for suffix in range(2, len(taken) + 3):
        candidate = f"{name} ({suffix})"
        if candidate not in taken:
            return candidate
    return name  # unreachable: the range is longer than the set
