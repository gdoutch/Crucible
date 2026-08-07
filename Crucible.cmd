@echo off
rem Launch Crucible. Double-click this, or run it from a terminal.
rem
rem Prefers pythonw so the GUI opens without a console window behind it, and
rem falls back to python if pythonw is not on PATH (which also means any
rem startup error stays visible instead of vanishing silently).
cd /d "%~dp0"
where pythonw >nul 2>&1 && (
    start "" pythonw -m crucible %*
) || (
    python -m crucible %*
)
