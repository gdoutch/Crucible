"""Crucible -- a practice harness for programming problems.

Layered so that the interesting parts are testable without a display:

    languages/   toolchain discovery, build, run      (no UI, no problems)
    problem.py   problem schema and loading           (no UI)
    runner.py    build + execute + judge              (no UI)
    ui/          Tkinter front end                    (everything above)
"""

__version__ = "1.0.0"
