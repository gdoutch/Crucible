"""Hint and worked-solution pages, and how they are found.

Each problem may ship two HTML guides beside its JSON file:

    problems/c/c_sum_array.json
    problems/c/c_sum_array.hint.html        a nudge -- no answer in it
    problems/c/c_sum_array.solution.html    the whole answer, explained

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

from .problem import Problem

HINT = "hint"
SOLUTION = "solution"

#: Menu labels and dialog wording, so the UI has no strings of its own to
#: drift out of step with these.
KINDS = {
    HINT: "Hint",
    SOLUTION: "Worked solution",
}


@dataclass(frozen=True)
class Guide:
    kind: str
    path: Path

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, self.kind)


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
    """Which kinds this problem is short of -- for `--guides` and the tests."""
    return [kind for kind in KINDS if find(problem, kind) is None]


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
