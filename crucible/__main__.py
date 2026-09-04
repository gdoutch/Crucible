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

Every string this module prints comes from `crucible.i18n` rather than a
literal here -- see that module for why, and `crucible/locales/en_GB.json`
for the text itself.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import guides, i18n, languages, randomise, runner, workspace
from .i18n import t
from .problem import Problem, load_library

#: Repository root -- the package lives one level below it.
ROOT = Path(__file__).resolve().parent.parent


def _default_problems_dir() -> Path:
    return ROOT / "problems"


def _apply_saved_locale() -> None:
    """Switch to whichever locale the GUI's *Language* menu last saved,
    before anything -- the argument parser's own `--help` text included --
    gets built from `t(...)` calls.

    `CRUCIBLE_LOCALE` wins if set: that is the documented explicit override
    (for a CI log reader, say), and a stray saved preference on the machine
    running it should not silently outrank something set on the command
    line. Only consulted when it is absent, exactly like `i18n`'s own
    module-level default does.
    """
    if "CRUCIBLE_LOCALE" in os.environ:
        return
    locale = workspace.load_settings().get("locale", i18n.DEFAULT_LOCALE)
    if locale in i18n.available_locales():
        i18n.set_locale(locale)


def cmd_toolchains() -> int:
    print(t("cli.toolchains.heading"))
    missing = False
    # The row template pads the name to a minimum width, chosen back when the
    # longest one was "Python". Pre-padding to the longest name actually
    # registered keeps the summary column straight however long a later
    # language's name turns out to be, without widening every row to suit it.
    width = max(len(language.display_name)
                for language in languages.all_languages())
    for language in languages.all_languages():
        status = language.toolchain()
        mark = t("cli.toolchains.mark_ok") if status.available else t("cli.toolchains.mark_missing")
        print(t("cli.toolchains.row", mark=mark,
                name=language.display_name.ljust(width),
                summary=status.summary))
        if status.detail:
            for line in status.detail.splitlines():
                print(t("cli.toolchains.detail_line", line=line))
        if not status.available:
            missing = True
    if missing:
        print(t("cli.toolchains.some_missing"))
    return 0


def cmd_list(root: Path) -> int:
    library = load_library(root)
    if library.errors:
        print(t("cli.list.load_errors_heading"))
        for error in library.errors:
            print(t("cli.list.load_error_row", error=error))
        print()
    if not library.problems:
        print(t("cli.list.none_found", root=root))
        return 1
    print(t("cli.list.heading", count=len(library.problems), root=root))
    # Pre-padded for the same reason as the toolchain table: the row template
    # sets a minimum width that suited the ids it was written against, and a
    # longer one would otherwise push that column's titles out of line.
    width = max(len(problem.language_id) for problem in library.problems)
    for problem in library.problems:
        visible = len(problem.visible_tests)
        hidden = len(problem.tests) - visible
        extra = t("cli.list.hidden_suffix", hidden=hidden) if hidden else ""
        random_note = (t("cli.list.randomised_suffix", count=problem.generator.count)
                       if problem.generator else "")
        print(t("cli.list.row_title", language=problem.language_id.ljust(width),
                title=problem.title))
        print(t("cli.list.row_detail", difficulty=problem.difficulty,
                visible=visible, extra=extra, random_note=random_note,
                id=problem.id))
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
        print(t("cli.list.load_error_row", error=error))
    if not library.problems:
        print(t("cli.guides.none_found", root=root))
        return 1

    incomplete = 0
    for problem in library.problems:
        absent = guides.missing(problem)
        if not absent:
            extra = (t("cli.guides.diagram_suffix")
                     if guides.find(problem, guides.DIAGRAM) else "")
            print(t("cli.guides.ok_row", title=problem.title, extra=extra))
            continue
        incomplete += 1
        kinds = ", ".join(guides.kind_label(kind).lower() for kind in absent)
        print(t("cli.guides.missing_row", title=problem.title, kinds=kinds))
        for kind in absent:
            print(t("cli.guides.missing_path_row",
                    path=guides.guide_path(problem, kind)))

    print()
    if incomplete:
        print(t("cli.guides.some_incomplete", incomplete=incomplete,
                total=len(library.problems)))
        return 1
    print(t("cli.guides.all_complete", total=len(library.problems)))
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
        print(t("cli.list.load_error_row", error=error))
    if not library.problems:
        print(t("cli.verify.none_found", root=root))
        return 1

    if seed is None:
        seed = randomise.new_seed()

    print(t("cli.verify.heading", count=len(library.problems)))
    print(t("cli.verify.seed_note", seed=seed))

    broken = 0
    skipped = 0
    for problem in library.problems:
        status = problem.language.toolchain()
        if not status.available:
            print(t("cli.verify.skip_row", title=problem.title, summary=status.summary))
            skipped += 1
            continue

        generator_error = _build_data_set(problem, seed)
        if generator_error:
            broken += 1
            print(t("cli.verify.broken_generator_row", title=problem.title,
                    error=generator_error))
            continue

        result = runner.verify_reference(problem)
        if result.all_passed:
            random_note = (t("cli.verify.randomised_suffix", count=len(problem.generated_tests))
                           if problem.generated_tests else "")
            print(t("cli.verify.ok_row", title=problem.title, total=result.total,
                    random_note=random_note))
            continue

        broken += 1
        if not result.build.ok:
            print(t("cli.verify.broken_build_row", title=problem.title))
            for line in result.build.output.splitlines()[:8]:
                print(t("cli.verify.build_output_line", line=line))
            continue
        print(t("cli.verify.broken_row", title=problem.title, summary=result.summary()))
        for outcome in result.failures():
            print(t("cli.verify.failure_row", symbol=outcome.symbol,
                    name=outcome.test.name, message=outcome.message))
            print(t("cli.verify.failure_expected", expected=repr(outcome.test.expected_stdout)))
            print(t("cli.verify.failure_actual", actual=repr(outcome.actual)))

    print()
    if broken:
        print(t("cli.verify.broken_summary", count=broken))
    if skipped:
        print(t("cli.verify.skipped_summary", count=skipped))
    if not broken and not skipped:
        print(t("cli.verify.all_verified"))
    return 1 if broken else 0


def main(argv: list[str] | None = None) -> int:
    _apply_saved_locale()

    parser = argparse.ArgumentParser(
        prog="crucible",
        description=t("cli.description"))
    parser.add_argument("--problems", type=Path, default=_default_problems_dir(),
                        metavar="DIR", help=t("cli.arg_problems_help"))
    parser.add_argument("--seed", type=int, metavar="N",
                        help=t("cli.arg_seed_help"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--verify", action="store_true",
                       help=t("cli.arg_verify_help"))
    group.add_argument("--list", action="store_true",
                       help=t("cli.arg_list_help"))
    group.add_argument("--toolchains", action="store_true",
                       help=t("cli.arg_toolchains_help"))
    group.add_argument("--guides", action="store_true",
                       help=t("cli.arg_guides_help"))
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
        print(t("cli.no_tkinter"), file=sys.stderr)
        return 2

    from .ui import CrucibleApp

    app = CrucibleApp(root)
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
