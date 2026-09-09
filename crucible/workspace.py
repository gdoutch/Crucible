"""Per-user state: in-progress drafts, chosen data sets, and UI settings.

Kept outside the project directory so that pulling down a new set of problems
never clobbers someone's half-finished work.

Drafts and data-set seeds belong to one *profile* -- see `crucible.profiles`,
which is what supplies the `root` a caller passes in below. Only `settings.json`
(theme, font size, window layout) has no profile in it: those are preferences
for the machine, not the person sitting at it, so whoever opens the app next
finds the window the way it was left rather than the way a stranger left it.
"""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from .i18n import DEFAULT_LOCALE

APP_DIR_NAME = ".crucible"

DEFAULT_SETTINGS = {
    "theme": "dark",
    "font_size": 11,
    "autosave": True,
    #: Which `crucible.i18n` locale the app's own UI is shown in. Applied at
    #: startup (see `crucible.__main__.main`), before any window exists, not
    #: hot-swapped while running -- same reason `theme` isn't: the menus and
    #: dialogs already built from `t(...)` calls stay in whatever language
    #: they were built in until the next launch.
    "locale": DEFAULT_LOCALE,
    #: Window size, pane sizes and which panes are collapsed. Opaque here --
    #: the shape of it belongs to ui/panes.py, and every reader of it treats a
    #: missing or malformed entry as "lay the window out from scratch".
    "layout": {},
    #: Directories picked by hand from the compiler status page's Browse
    #: button, one per language id, for a compiler auto-detection could not
    #: find. See `apply_compiler_path_overrides` -- this is machine state
    #: rather than a language plugin concern, because every plugin's existing
    #: `which()`-based search already consults PATH, so prepending onto it
    #: here is the whole mechanism. No plugin needs its own "browse" code.
    "compiler_path_overrides": {},
}


def app_dir() -> Path:
    root = Path(os.environ.get("CRUCIBLE_HOME", Path.home() / APP_DIR_NAME))
    root.mkdir(parents=True, exist_ok=True)
    return root


def drafts_dir(root: Path | None = None) -> Path:
    """`root` scopes this to one profile -- see `crucible.profiles`. Omitting
    it is only for callers with no notion of a profile (the test suite)."""
    path = (root or app_dir()) / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_name(problem_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", problem_id) or "problem"


def draft_path(problem_id: str, extension: str, root: Path | None = None) -> Path:
    return drafts_dir(root) / f"{_safe_name(problem_id)}{extension}"


def load_draft(problem_id: str, extension: str, root: Path | None = None) -> str | None:
    path = draft_path(problem_id, extension, root)
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def save_draft(problem_id: str, extension: str, source: str,
               root: Path | None = None) -> None:
    try:
        draft_path(problem_id, extension, root).write_text(source, encoding="utf-8")
    except OSError:
        pass  # a failed autosave must never interrupt the candidate


def clear_draft(problem_id: str, extension: str, root: Path | None = None) -> None:
    try:
        draft_path(problem_id, extension, root).unlink()
    except OSError:
        pass


# -- data sets --------------------------------------------------------------
#
# Which randomised data set each problem is currently on. This is remembered
# alongside the draft and for the same reason: a half-written solution and the
# test cases it was being written against belong together. Coming back to a
# problem tomorrow and finding the numbers changed underneath your notes would
# be its own small betrayal, so the data set only ever changes when asked for.

def _seeds_path(root: Path | None = None) -> Path:
    # Unlike `drafts_dir`, `root` here is not guaranteed to already exist --
    # `profiles.profile_dir` happens to create it first, but nothing enforces
    # that, and a missing directory would otherwise turn `save_seeds` into a
    # silent no-op (`write_text` raising `FileNotFoundError`, which the OSError
    # handler below swallows exactly like it swallows a real disk error).
    base = root or app_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / "seeds.json"


def load_seeds(root: Path | None = None) -> dict[str, int]:
    """`root` scopes this to one profile -- see `crucible.profiles`."""
    try:
        stored = json.loads(_seeds_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(stored, dict):
        return {}
    return {str(k): int(v) for k, v in stored.items()
            if isinstance(v, int) and not isinstance(v, bool)}


def save_seeds(seeds: dict[str, int], root: Path | None = None) -> None:
    try:
        _seeds_path(root).write_text(json.dumps(seeds, indent=2, sort_keys=True),
                                     encoding="utf-8")
    except OSError:
        pass  # losing a data set number costs one reshuffle, not any work


# -- settings ---------------------------------------------------------------

def _settings_path() -> Path:
    return app_dir() / "settings.json"


def load_settings() -> dict:
    # A deep copy, not `dict(DEFAULT_SETTINGS)`: a shallow copy shares the
    # *same* nested "layout"/"compiler_path_overrides" dict objects with the
    # module-level default, so mutating one in place -- which
    # set_compiler_path_override does -- would silently corrupt
    # DEFAULT_SETTINGS itself for the rest of the process.
    settings = copy.deepcopy(DEFAULT_SETTINGS)
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


# -- MSVC environment cache -------------------------------------------------
#
# Locating MSVC means shelling out to vcvars64.bat, which takes ~12 seconds --
# by a wide margin the slowest thing that happens at startup. The result only
# changes when Visual Studio does, so it is cached here against a fingerprint
# of the things it derives from (see `c_lang._msvc_fingerprint`). Checking that
# fingerprint is a handful of stats, some five orders of magnitude cheaper than
# recomputing the answer it guards.
#
# This is machine state, not user state, so it sits beside settings.json rather
# than inside a profile. Losing it costs one slow startup and nothing else,
# which is why every failure path here is a silent fall back to "no cache".

def _msvc_cache_path() -> Path:
    return app_dir() / "msvc-env.json"


def load_msvc_env(fingerprint: list) -> dict | None:
    """The cached vcvars capture, or None if absent or built for a different
    Visual Studio than the one on disk now."""
    try:
        stored = json.loads(_msvc_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(stored, dict):
        return None
    # json round-trips tuples as lists, so compare like for like.
    if stored.get("fingerprint") != json.loads(json.dumps(fingerprint)):
        return None
    captured = stored.get("captured")
    return captured if isinstance(captured, dict) else None


def save_msvc_env(fingerprint: list, captured: dict) -> None:
    try:
        _msvc_cache_path().write_text(
            json.dumps({"fingerprint": fingerprint, "captured": captured},
                       indent=2),
            encoding="utf-8")
    except OSError:
        pass  # a cache that cannot be written just means a slow next launch


def clear_msvc_env() -> None:
    """Drop the cache. Used as the self-heal when a build fails in a way that
    suggests the environment it was given no longer describes reality."""
    try:
        _msvc_cache_path().unlink()
    except OSError:
        pass


# -- manual compiler locations ----------------------------------------------
#
# The compiler status page's Browse button does not teach any language plugin
# to look in a new place -- it prepends the chosen directory onto this
# process's own PATH, so every plugin's existing `shutil.which` / `nc.which`
# search finds it exactly the way it would find anything else already on
# PATH. One mechanism, no plugin-specific "browse" code anywhere.

def set_compiler_path_override(language_id: str, directory: str,
                               settings: dict) -> None:
    """Remember `directory` for `language_id` and persist it. `settings` is
    updated in place (the same dict the caller already holds, e.g.
    `CrucibleApp.settings`) so the caller's own copy stays in sync.

    Replaces `settings["compiler_path_overrides"]` with a fresh dict rather
    than mutating whatever is there -- `settings.setdefault(...)` would hand
    back the *same* dict object `load_settings` copied from
    `DEFAULT_SETTINGS`, and mutating that in place corrupts the module-level
    default for the rest of the process. See `load_settings`.
    """
    overrides = dict(settings.get("compiler_path_overrides") or {})
    overrides[language_id] = directory
    settings["compiler_path_overrides"] = overrides
    save_settings(settings)
    apply_compiler_path_overrides(settings)


def clear_compiler_path_override(language_id: str, settings: dict) -> None:
    """Forget a manually chosen directory, reverting to plain auto-detection.

    The directory already prepended onto this process's PATH is deliberately
    left there -- stripping one entry back out of a live PATH that other code
    may have since read or copied is not worth the risk of getting it wrong,
    and a stale entry pointing at a real compiler does no harm. It simply
    will not be re-applied on the next launch.
    """
    overrides = dict(settings.get("compiler_path_overrides") or {})
    overrides.pop(language_id, None)
    settings["compiler_path_overrides"] = overrides
    save_settings(settings)


def apply_compiler_path_overrides(settings: dict | None = None) -> None:
    """Prepend every saved override directory onto this process's PATH.

    Idempotent, so it is safe to call again after every browse action as well
    as once at startup -- a directory already on PATH is never added twice,
    which matters here because a long-running session may call this many
    times and a PATH that grows without bound is its own slow, confusing bug.
    """
    overrides = (settings or load_settings()).get("compiler_path_overrides", {})
    if not isinstance(overrides, dict):
        return
    current = os.environ.get("PATH", "")
    entries = current.split(os.pathsep) if current else []
    seen = {e.rstrip("\\/").lower() for e in entries}
    prepend = []
    for directory in overrides.values():
        directory = str(directory)
        key = directory.rstrip("\\/").lower()
        if directory and key not in seen:
            prepend.append(directory)
            seen.add(key)
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend + entries)
