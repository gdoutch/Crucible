"""Hint, worked-solution and diagram pages, and how they are found.

Each problem ships HTML guides beside its JSON file:

    problems/c/c_sum_array.json
    problems/c/c_sum_array.hint.html        a nudge -- no answer in it
    problems/c/c_sum_array.solution.html    the whole answer, explained
    problems/uml/uml_state_machine.diagram.html   the spec, drawn (optional)

They are plain files opened in the user's browser rather than rendered in the
app. That is deliberate. A guide is a document -- headings, tables, code
blocks, a trace of the algorithm running -- and a Tk `Text` widget renders that
badly, while every machine already has something that renders it well. It also
means a guide can be read side by side with the editor instead of covering it.

Two consequences of the naming convention are worth stating:

  * The convention is the only registration. There is no index and nothing to
    edit when a problem is added -- drop the files next to the JSON and the
    menu finds them. `--guides` reports what is missing.

  * The guides are stored next to the problem, not inside it. A worked solution
    written into the problem file would defeat `reference_solution_b64`:
    opening the JSON to read the test cases would drop the answer in your lap.
    Keeping it in a separate file means revealing it stays a deliberate act,
    which is the same reason the app asks before opening one.
"""

from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from pathlib import Path

from .i18n import t
from .problem import Problem

HINT = "hint"
SOLUTION = "solution"
DIAGRAM = "diagram"

#: The canonical English label for each kind, as it is written into every
#: generated guide page (`<p class="kind">Hint</p>` and the like) -- guide
#: pages are authored, per-problem content, deliberately outside the i18n
#: system (see the README), so this stays fixed English rather than following
#: the active locale. Order is menu order.
KINDS = {
    DIAGRAM: "Diagram",
    HINT: "Hint",
    SOLUTION: "Worked solution",
}

#: The two every problem is expected to have. A diagram is only meaningful for
#: a problem whose specification *is* a diagram, so it is optional -- and
#: `missing` reports against this rather than against `KINDS`, which is what
#: keeps `--guides` from nagging about a diagram FizzBuzz has no use for.
REQUIRED = (HINT, SOLUTION)


def kind_label(kind: str) -> str:
    """The locale-aware label for `kind`, for the live app's own menus and
    dialogs -- as opposed to `KINDS`, which names what a *generated guide
    page* calls itself and never changes with the locale."""
    return t(f"guides.kind.{kind}") if kind in KINDS else kind


@dataclass(frozen=True)
class Guide:
    kind: str
    path: Path

    @property
    def label(self) -> str:
        return kind_label(self.kind)


def guide_path(problem: Problem, kind: str) -> Path | None:
    """Where `kind` would live for this problem, or None if unknowable.

    Returns a path whether or not the file exists -- `find` is the one that
    checks. A problem loaded from somewhere other than a file (the tests build
    a few) has no source path and therefore no guides.
    """
    if problem.source_path is None:
        return None
    source = problem.source_path
    return source.with_name(f"{source.stem}.{kind}.html")


def find(problem: Problem, kind: str) -> Guide | None:
    """The guide of this kind for this problem, if the file is there."""
    path = guide_path(problem, kind)
    if path is None or not path.is_file():
        return None
    return Guide(kind=kind, path=path)


def find_all(problem: Problem) -> dict[str, Guide]:
    """Every guide this problem actually has, keyed by kind."""
    found = {kind: find(problem, kind) for kind in KINDS}
    return {kind: guide for kind, guide in found.items() if guide is not None}


def missing(problem: Problem) -> list[str]:
    """Which *required* kinds this problem is short of.

    Used by `--guides` and by the tests. A missing diagram is not a gap --
    most problems have no diagram to draw.
    """
    return [kind for kind in REQUIRED if find(problem, kind) is None]


def open_in_browser(guide: Guide) -> bool:
    """Hand the page to the user's browser. False if that did not work.

    `as_uri` is what makes this behave on Windows: a bare path with a drive
    letter and backslashes is not a URL, and browsers treat the drive letter as
    a scheme. The file:// form is unambiguous everywhere.
    """
    try:
        return webbrowser.open(guide.path.resolve().as_uri())
    except (OSError, ValueError):
        return False
