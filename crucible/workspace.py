"""Per-user state: in-progress drafts and UI settings.

Kept outside the project directory so that pulling down a new set of problems
never clobbers someone's half-finished work.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

APP_DIR_NAME = ".crucible"

DEFAULT_SETTINGS = {
    "theme": "dark",
    "font_size": 11,
    "last_problem": "",
    "autosave": True,
}


def app_dir() -> Path:
    root = Path(os.environ.get("CRUCIBLE_HOME", Path.home() / APP_DIR_NAME))
    root.mkdir(parents=True, exist_ok=True)
    return root


def drafts_dir() -> Path:
    path = app_dir() / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(problem_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", problem_id) or "problem"


def draft_path(problem_id: str, extension: str) -> Path:
    return drafts_dir() / f"{_safe_name(problem_id)}{extension}"


def load_draft(problem_id: str, extension: str) -> str | None:
    path = draft_path(problem_id, extension)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def save_draft(problem_id: str, extension: str, source: str) -> None:
    try:
        draft_path(problem_id, extension).write_text(source, encoding="utf-8")
    except OSError:
        pass  # a failed autosave must never interrupt the candidate


def clear_draft(problem_id: str, extension: str) -> None:
    try:
        draft_path(problem_id, extension).unlink()
    except OSError:
        pass


# -- settings ---------------------------------------------------------------

def _settings_path() -> Path:
    return app_dir() / "settings.json"


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(_settings_path().read_text(encoding="utf-8"))
        if isinstance(stored, dict):
            settings.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
    except (OSError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    try:
        payload = {k: v for k, v in settings.items() if k in DEFAULT_SETTINGS}
        _settings_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass
