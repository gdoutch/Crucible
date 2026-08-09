#!/usr/bin/env python3
"""Crucible -- launcher.

    python -m crucible                 open the GUI
    python -m crucible --verify        run every reference solution, exit 1
                                       on any failure (use this in CI)
    python -m crucible --list          list the problems that loaded
    python -m crucible --toolchains    report which compilers were found
    python -m crucible --guides        report problems missing a hint or a
                                       worked solution, exit 1 if any are

On Windows, Crucible.cmd double-clicks straight into the GUI.

`--verify` is the authoring workflow: it is the same pre-flight the GUI runs
before offering a problem, just without a window. For a problem with randomised
data it builds a data set first, so the seed it used is printed -- pass it back
with `--seed` to reproduce a failure exactly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import guides, languages, randomise, runner
from .problem import Problem, load_library

#: Repository root -- the package lives one level below it.
ROOT = Path(__file__).resolve().parent.parent


def _default_problems_dir() -> Path:
    return ROOT / "problems"


def cmd_toolchains() -> int:
    print("Toolchains\n")
    missing = False
    for language in languages.all_languages():
        status = language.toolchain()
        mark = "OK " if status.available else "-- "
        print(f"  {mark} {language.display_name:<10} {status.summary}")
        if status.detail:
            for line in status.detail.splitlines():
                print(f"         {line}")
        if not status.available:
            missing = True
    if missing:
        print("\nOne or more toolchains are missing. Run with --verify for detail,")
        print("or open the GUI and use Help -> Compiler status for install steps.")
    return 0


def cmd_list(root: Path) -> int:
    library = load_library(root)
    if library.errors:
        print("Problems that failed to load:")
        for error in library.errors:
            print(f"  ! {error}")
        print()
    if not library.problems:
        print(f"No problems found under {root}")
        return 1
    print(f"{len(library.problems)} problem(s) under {root}\n")
    for problem in library.problems:
        visible = len(problem.visible_tests)
        hidden = len(problem.tests) - visible
        extra = f" (+{hidden} hidden)" if hidden else ""
        random_note = (f" + {problem.generator.count} randomised"
                       if problem.generator else "")
        print(f"  [{problem.language_id:<6}] {problem.title}")
        print(f"           {problem.difficulty}, {visible} visible test(s)"
              f"{extra}{random_note}  id={problem.id}")
    return 0


def cmd_guides(root: Path) -> int:
    """Report which problems are missing a hint or a worked solution.

    Guides are found by filename, so there is no registry to fall out of step
    with the problems -- but nothing warns you about a problem you forgot to
    write them for either. This is that warning, and it exits non-zero so it
    can sit in CI beside `--verify`.
    """
    library = load_library(root)
    for error in library.errors:
        print(f"  ! {error}")
    if not library.problems:
        print(f"No problems found under {root}")
        return 1

    incomplete = 0
    for problem in library.problems:
        absent = guides.missing(problem)
        if not absent:
            print(f"  OK    {problem.title}")
            continue
        incomplete += 1
        print(f"  MISSING {problem.title}  -- no "
              f"{', '.join(guides.KINDS[kind].lower() for kind in absent)}")
        for kind in absent:
            print(f"           expected {guides.guide_path(problem, kind)}")

    print()
    if incomplete:
        print(f"{incomplete} of {len(library.problems)} problem(s) are missing "
              f"a guide.")
        return 1
    print(f"All {len(library.problems)} problems have both guides.")
    return 0


def _build_data_set(problem: Problem, seed: int) -> str:
    """Attach a randomised data set, returning "" or why it is incomplete.

    Only called once the toolchain is known to be present, so a missing
    compiler is the caller's SKIP rather than anything reported here.
    """
    if not problem.randomised:
        return ""
    suite = randomise.generate(problem, seed)
    randomise.apply(problem, suite)
    return suite.error


def cmd_verify(root: Path, seed: int | None) -> int:
    """Pre-test every problem's suite against its reference solution.

    Randomised problems get a data set built first, so this covers the
    generators too: it catches one that emits inputs the reference cannot
    handle, and -- because the expected output is captured and then checked by
    running the reference a second time -- one whose inputs make the reference
    behave differently from one run to the next.
    """
    library = load_library(root)
    for error in library.errors:
        print(f"  ! {error}")
    if not library.problems:
        print(f"No problems found under {root}")
        return 1

    if seed is None:
        seed = randomise.new_seed()

    print(f"Verifying {len(library.problems)} problem(s) against their "
          f"reference solutions")
    print(f"Randomised data sets use seed {seed}  (--seed {seed} to repeat)\n")

    broken = 0
    skipped = 0
    for problem in library.problems:
        status = problem.language.toolchain()
        if not status.available:
            print(f"  SKIP  {problem.title}  ({status.summary})")
            skipped += 1
            continue

        generator_error = _build_data_set(problem, seed)
        if generator_error:
            broken += 1
            print(f"  BROKEN {problem.title}  -- {generator_error}")
            continue

        result = runner.verify_reference(problem)
        if result.all_passed:
            random_note = (f", {len(problem.generated_tests)} randomised"
                           if problem.generated_tests else "")
            print(f"  OK    {problem.title}  ({result.total} tests{random_note})")
            continue

        broken += 1
        if not result.build.ok:
            print(f"  BROKEN {problem.title}  -- reference did not build")
            for line in result.build.output.splitlines()[:8]:
                print(f"           {line}")
            continue
        print(f"  BROKEN {problem.title}  -- {result.summary()}")
        for outcome in result.failures():
            print(f"           {outcome.symbol:<8} {outcome.test.name}"
                  f"  {outcome.message}")
            print(f"             expected: {outcome.test.expected_stdout!r}")
            print(f"             actual:   {outcome.actual!r}")

    print()
    if broken:
        print(f"{broken} problem(s) are broken -- fix these before use.")
    if skipped:
        print(f"{skipped} problem(s) skipped: no toolchain installed.")
    if not broken and not skipped:
        print("All problems verified.")
    return 1 if broken else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="crucible",
        description="Crucible -- a Tkinter coding practice harness for C "
                    "(and other languages).")
    parser.add_argument("--problems", type=Path, default=_default_problems_dir(),
                        metavar="DIR", help="problem directory (default: ./problems)")
    parser.add_argument("--seed", type=int, metavar="N",
                        help="data set number for randomised cases "
                             "(default: a new one each run)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true",
                       help="verify every reference solution and exit")
    group.add_argument("--list", action="store_true",
                       help="list available problems and exit")
    group.add_argument("--toolchains", action="store_true",
                       help="report detected compilers and exit")
    group.add_argument("--guides", action="store_true",
                       help="report which problems are missing a hint or a "
                            "worked solution; exit 1 if any are")
    args = parser.parse_args(argv)

    root = args.problems.expanduser().resolve()

    if args.toolchains:
        return cmd_toolchains()
    if args.list:
        return cmd_list(root)
    if args.guides:
        return cmd_guides(root)
    if args.verify:
        return cmd_verify(root, args.seed)

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("Tkinter is not available in this Python installation.\n"
              "On Debian/Ubuntu:  sudo apt install python3-tk\n"
              "On Windows/macOS:  reinstall Python with the Tcl/Tk option ticked.",
              file=sys.stderr)
        return 2

    from .ui import CrucibleApp

    app = CrucibleApp(root)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
