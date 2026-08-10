"""User profiles.

A profile is nothing but a username -- no email, no real name, nothing tied
to the machine's own account. It exists so that different people practising
on the same computer each get their own drafts, their own randomised data
sets, and their own record of which problems they have solved, without the
app knowing -- or needing to know -- anything else about who they are.

Everything about one profile lives under one directory:

    ~/.crucible/
      profiles.json          the index: id, username and timestamps for
                              every profile, and which one is current
      profiles/<id>/
        seeds.json            -- read and written by workspace.load_seeds /
        drafts/                  save_seeds / load_draft / save_draft, scoped
                                  here by passing `profile_dir(id)` as `root`
        progress.json         -- which problems this profile has solved

`<id>` is a filesystem slug derived from the username, not the username
itself. Usernames are matched case-sensitively -- "Alice" and "alice" are two
different people typing at the same keyboard, not a typo to fold together --
but Windows and macOS both treat directory names as the same file regardless
of case, so the id is lowercased and disambiguated with a numeric suffix
rather than trusted to keep two such usernames apart on disk.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import workspace

#: Kept short so a profile directory name is never the reason a path is too
#: long for the filesystem, and so the picker list stays readable.
MAX_USERNAME_LENGTH = 40


@dataclass
class Profile:
    id: str
    username: str
    created: str = ""
    last_opened: str = ""
    #: The problem to reopen to when this profile is next activated.
    last_problem: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slugify(username: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", username.lower()).strip("-")
    return slug[:24] or "profile"


def _unique_id(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    for suffix in range(2, 10_000):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    raise RuntimeError("could not find a free profile id")  # 10000 collisions


def _validate_username(username: str) -> str:
    # Collapses runs of whitespace and trims the ends, so "Alice" and
    # "Alice  " -- almost certainly the same person, typo'd -- do not
    # silently become two profiles.
    username = " ".join(username.split())
    if not username:
        raise ValueError("Enter a username.")
    return username[:MAX_USERNAME_LENGTH]


# -- the index ----------------------------------------------------------

def _index_path() -> Path:
    return workspace.app_dir() / "profiles.json"


def _load_index() -> dict:
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_index(data: dict) -> None:
    try:
        _index_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass  # a failed save here costs a reshuffle of profiles, not any work


def _entries(data: dict) -> list[dict]:
    """The usable profile records in `data`, filtering out anything a hand
    edit of the file may have left malformed. These are the *same* dict
    objects `data` holds, not copies, so a caller may mutate one in place and
    then hand `data` back to `_save_index` -- which is also how a write here
    quietly drops anything that failed this filter."""
    raw = data.get("profiles")
    if not isinstance(raw, list):
        return []
    return [e for e in raw
            if isinstance(e, dict)
            and isinstance(e.get("id"), str) and e["id"]
            and isinstance(e.get("username"), str) and e["username"]]


def _to_profile(entry: dict) -> Profile:
    return Profile(
        id=entry["id"],
        username=entry["username"],
        created=str(entry.get("created") or ""),
        last_opened=str(entry.get("last_opened") or ""),
        last_problem=str(entry.get("last_problem") or ""),
    )


# -- directories ----------------------------------------------------------

def profiles_dir() -> Path:
    path = workspace.app_dir() / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir(profile_id: str) -> Path:
    path = profiles_dir() / profile_id
    path.mkdir(parents=True, exist_ok=True)
    return path


# -- reading ----------------------------------------------------------------

def list_profiles() -> list[Profile]:
    """Every profile, most recently opened first."""
    entries = _entries(_load_index())
    entries.sort(key=lambda e: e.get("last_opened") or "", reverse=True)
    return [_to_profile(e) for e in entries]


def current_profile() -> Profile | None:
    """The profile that was active when the app last closed, if any still
    exists -- `None` on the very first run, or if it was since deleted."""
    data = _load_index()
    current_id = data.get("current")
    if not isinstance(current_id, str):
        return None
    for entry in _entries(data):
        if entry["id"] == current_id:
            return _to_profile(entry)
    return None


# -- writing ------------------------------------------------------------

def open_profile(username: str) -> Profile:
    """Find the profile for this username, or create a blank one, and make
    it current.

    Matching is exact and case-sensitive: a username here is a label picked
    at the keyboard, not a verified identity, so there is nothing to
    normalise it against. Calling this always activates the result -- it
    becomes `current_profile()` and its `last_opened` moves to now -- which
    is what makes it the one function both "switch profile" and "new
    profile" need.

    Raises `ValueError` if `username` is empty once whitespace is trimmed.
    """
    username = _validate_username(username)
    data = _load_index()
    entries = _entries(data)

    entry = next((e for e in entries if e["username"] == username), None)
    if entry is None:
        entry = {
            "id": _unique_id(_slugify(username), {e["id"] for e in entries}),
            "username": username,
            "created": _now(),
            "last_problem": "",
        }
        entries.append(entry)
    entry["last_opened"] = _now()

    data["profiles"] = entries
    data["current"] = entry["id"]
    _save_index(data)
    profile_dir(entry["id"])  # exists from here even before anything is saved into it
    return _to_profile(entry)


def set_last_problem(profile_id: str, problem_id: str) -> None:
    data = _load_index()
    entries = _entries(data)
    for entry in entries:
        if entry["id"] == profile_id:
            entry["last_problem"] = problem_id
            data["profiles"] = entries
            _save_index(data)
            return


def delete_profile(profile_id: str) -> None:
    """Forget a profile and everything it recorded: drafts, data sets, and
    solved problems. There is no undo -- callers confirm before calling this."""
    data = _load_index()
    entries = [e for e in _entries(data) if e["id"] != profile_id]
    data["profiles"] = entries
    if data.get("current") == profile_id:
        data["current"] = entries[0]["id"] if entries else None
    _save_index(data)
    shutil.rmtree(profile_dir(profile_id), ignore_errors=True)


# -- progress -----------------------------------------------------------
#
# One JSON file per profile, keyed by problem id. Deliberately small: whether
# it has ever been solved, and a one-line summary of the most recent attempt
# -- not a full history, which nobody asked for and which would make this file
# grow without bound.

def _progress_path(profile_id: str) -> Path:
    return profile_dir(profile_id) / "progress.json"


def load_progress(profile_id: str) -> dict[str, dict]:
    try:
        data = json.loads(_progress_path(profile_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def _save_progress(profile_id: str, progress: dict[str, dict]) -> None:
    try:
        _progress_path(profile_id).write_text(
            json.dumps(progress, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def record_attempt(profile_id: str, problem_id: str, *,
                   passed: bool, summary: str) -> dict:
    """Log the result of one Go. Returns the updated entry for this problem.

    `solved` only ever turns on, never off -- passing once is what "solved"
    means here, and a later attempt that breaks it again should not erase
    that it was done. `attempts` and `last_attempt` move on every call,
    passed or not, so a run of failed tries is part of the record too.
    """
    progress = load_progress(profile_id)
    entry = progress.get(problem_id)
    if not isinstance(entry, dict):
        entry = {"solved": False, "first_solved": "", "attempts": 0}

    entry["attempts"] = int(entry.get("attempts") or 0) + 1
    entry["last_attempt"] = _now()
    entry["last_summary"] = summary
    if passed and not entry.get("solved"):
        entry["first_solved"] = _now()
    entry["solved"] = entry.get("solved") or passed

    progress[problem_id] = entry
    _save_progress(profile_id, progress)
    return entry
