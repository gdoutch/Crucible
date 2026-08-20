"""Python language support.

This module exists as much to prove the plugin seam as to be useful: it is the
whole of what a new language costs. Compare it with `c_lang.py` -- same three
methods, no changes anywhere else in the app.

Layout mirrors C: the candidate's code is its own module, imported by the
problem's harness, so tracebacks carry real editor line numbers.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from ..i18n import t
from .base import BuildResult, Language, ToolchainStatus


class PythonLanguage(Language):
    id = "python"
    display_name = "Python"
    solution_filename = "solution.py"
    harness_filename = "harness.py"
    line_comment = "#"
    keywords = (
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "False", "finally", "for",
        "from", "global", "if", "import", "in", "is", "lambda", "None",
        "nonlocal", "not", "or", "pass", "raise", "return", "True", "try",
        "while", "with", "yield", "self",
    )

    def detect_toolchain(self) -> ToolchainStatus:
        return ToolchainStatus(
            available=True,
            summary=t("languages.python.summary", version=sys.version.split()[0]),
            detail=t("languages.python.interpreter_detail", executable=sys.executable),
        )

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        """There is nothing to link, but we still compile the submission so
        syntax errors surface as a build failure rather than as every single
        test case blowing up with the same traceback."""
        started = time.perf_counter()
        (workdir / self.solution_filename).write_text(solution, encoding="utf-8")
        (workdir / self.harness_filename).write_text(harness, encoding="utf-8")

        try:
            compile(solution, self.solution_filename, "exec")
        except SyntaxError as exc:
            caret = " " * max((exc.offset or 1) - 1, 0) + "^"
            detail = t("languages.python.syntax_error_detail",
                      file=self.solution_filename, line=exc.lineno, message=exc.msg)
            if exc.text:
                detail += t("languages.python.syntax_error_context",
                            text=exc.text.rstrip(), caret=caret)
            return BuildResult(ok=False, output=detail,
                               duration=time.perf_counter() - started)

        return BuildResult(
            ok=True,
            command=f"{Path(sys.executable).name} {self.harness_filename}",
            artifact=workdir / self.harness_filename,
            duration=time.perf_counter() - started,
        )

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        # No -I / -P here: the harness does `import solution`, which relies on
        # the script's own directory being prepended to sys.path.
        return [sys.executable, str(workdir / self.harness_filename)]

    def describe_exit(self, exit_code: int | None) -> str:
        if exit_code is None:
            return ""
        return ("" if exit_code == 0
                else t("languages.common.exited_with_status", code=exit_code))
