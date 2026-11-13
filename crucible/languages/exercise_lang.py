"""The pen-and-paper "language".

An exercise is answered on paper -- a diagram, a design, an argument -- so
there is nothing to compile, run, randomise or mark. It still needs a
`Language` because the app groups, labels and filters problems by language;
this one exists to be that label, and to say plainly if anything ever does try
to build one.

The editor stays usable as a scratch pad (`notes.txt`), but nothing reads it.
"""

from __future__ import annotations

from pathlib import Path

from ..i18n import t
from .base import BuildResult, Language, ToolchainStatus


class ExerciseLanguage(Language):
    id = "exercise"
    solution_filename = "notes.txt"
    harness_filename = ""
    line_comment = "#"
    keywords = ()

    @property
    def display_name(self) -> str:  # type: ignore[override]
        return t("languages.exercise.display_name")

    def detect_toolchain(self) -> ToolchainStatus:
        return ToolchainStatus(
            available=True,
            summary=t("languages.exercise.summary"),
            detail=t("languages.exercise.detail"),
        )

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        return BuildResult(ok=False, output=t("languages.exercise.not_runnable"))

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        raise RuntimeError(t("languages.exercise.not_runnable"))
