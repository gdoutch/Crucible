#!/usr/bin/env python3
"""Crucible -- launcher.

    python -m crucible                 open the GUI
    python -m crucible --verify        run every reference solution, exit 1
                                       on any failure (use this in CI)
    python -m crucible --list          list the problems that loaded
    python -m crucible --toolchains    report which compilers were found

On Windows, Crucible.cmd double-clicks straight into the GUI.

`--verify` is the authoring workflow: it is the same pre-flight the GUI runs
before offering a problem, just without a window.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import languages, runner
from .problem import load_library

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
        print(f"  [{problem.language_id:<6}] {problem.title}")
        print(f"           {problem.difficulty}, {visible} visible test(s){extra}"
              f"  id={problem.id}")
    return 0


def cmd_verify(root: Path) -> int:
    """Pre-test every problem's suite against its reference solution."""
    library = load_library(root)
    for error in library.errors:
        print(f"  ! {error}")
    if not library.problems:
        print(f"No problems found under {root}")
        return 1

    print(f"Verifying {len(library.problems)} problem(s) against their "
          f"reference solutions\n")

    broken = 0
    skipped = 0
    for problem in library.problems:
        status = problem.language.toolchain()
        if not status.available:
            print(f"  SKIP  {problem.title}  ({status.summary})")
            skipped += 1
            continue

        result = runner.verify_reference(problem)
        if result.all_passed:
            print(f"  OK    {problem.title}  ({result.total} tests)")
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
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true",
                       help="verify every reference solution and exit")
    group.add_argument("--list", action="store_true",
                       help="list available problems and exit")
    group.add_argument("--toolchains", action="store_true",
                       help="report detected compilers and exit")
    args = parser.parse_args(argv)

    root = args.problems.expanduser().resolve()

    if args.toolchains:
        return cmd_toolchains()
    if args.list:
        return cmd_list(root)
    if args.verify:
        return cmd_verify(root)

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
