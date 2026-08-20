"""User-facing strings: lookup, not literals.

Every string a candidate, an author, or a CI log reader actually reads --
window titles, menu labels, dialog text, status messages, CLI output,
validation errors -- lives in a locale file under `crucible/locales/`, not
inline in the code that displays it. The code asks for a string by a stable,
hierarchical key; a locale file answers with the text.

    from .i18n import t
    print(t("cli.toolchains.heading"))
    label = t("app.pane.problems.title")
    raise ProblemError(t("problem.error.unknown_difficulty",
                          file=path.name, value=difficulty,
                          choices=", ".join(DIFFICULTIES)))

Only one locale ships today -- `en_GB`, British English, which is also the
fallback of last resort so a missing translation in some future locale never
surfaces as a blank label or a raw dotted key. Adding a second locale is
"drop `crucible/locales/<code>.json` with the same keys" and nothing about
the calling code changes; a key present in `en_GB` but absent from a newer
locale falls back to the English text rather than breaking the page.

Keys are namespaced by where they are used (`cli.*`, `app.menu.*`,
`languages.c.*`...) so two unrelated features never fight over the same
short phrase, and a locale file reads, browsed top to bottom, roughly like a
map of the application.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Bundled locale files live next to this module.
LOCALES_DIR = Path(__file__).resolve().parent / "locales"

#: The locale every string is originally written in, and what any key
#: missing from another locale falls back to. Never itself allowed to be
#: missing a key -- see `available_locales` and the completeness test.
DEFAULT_LOCALE = "en_GB"

#: Sentinel returned by `_lookup` for "this key does not exist in this
#: locale at all", distinct from a legitimate string value of "" or None.
_MISSING = object()


class TranslationError(ValueError):
    """A key has no string in the default locale, or a template's
    placeholders do not match the keyword arguments `t()` was called with.
    Both are authoring bugs -- a missing key or a mismatched placeholder is
    never something a candidate did wrong -- so this is raised rather than
    papered over with a half-formatted string."""


@lru_cache(maxsize=None)
def _load(locale: str) -> dict[str, Any]:
    """Parse one locale file. Cached: a locale file is read once per process,
    however many thousand times `t()` is called against it."""
    path = LOCALES_DIR / f"{locale}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TranslationError(f"no locale file for '{locale}' at {path}") from None
    except json.JSONDecodeError as exc:
        raise TranslationError(f"{path.name} is not valid JSON: {exc}") from None


def available_locales() -> list[str]:
    """Locale codes with a bundled file, `DEFAULT_LOCALE` first."""
    codes = sorted(p.stem for p in LOCALES_DIR.glob("*.json"))
    if DEFAULT_LOCALE in codes:
        codes.remove(DEFAULT_LOCALE)
        codes.insert(0, DEFAULT_LOCALE)
    return codes


def _lookup(locale: str, key: str) -> Any:
    """Walk `key` ("app.menu.file.open") through the nested dict a locale
    file parses to. Returns `_MISSING` rather than raising, so callers can
    tell "not present" apart from a value that is falsy but real."""
    node: Any = _load(locale)
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


#: The active locale. Module-level rather than threaded through every call
#: site because it is a property of *who is running the app*, set once at
#: start-up (or per-process, for a CI log), not of any individual string --
#: the same reason a process's stdout encoding is not passed to every print.
_current = os.environ.get("CRUCIBLE_LOCALE", DEFAULT_LOCALE)


def get_locale() -> str:
    return _current


def set_locale(locale: str) -> None:
    """Switch the active locale. Validated eagerly -- against the locale's
    own file existing, not against every key it should contain -- so a typo
    in a locale code fails at the point it was set, not several screens
    later on whatever string happens to be requested first."""
    global _current
    _load(locale)  # raises TranslationError if the file is missing/invalid
    _current = locale


def t(key: str, /, **kwargs: object) -> str:
    """Look up `key` in the active locale, falling back to `DEFAULT_LOCALE`,
    and interpolate `kwargs` via `str.format`.

    A key missing from the active (non-default) locale falls back silently --
    that is the whole point of having a fallback. A key missing from
    `DEFAULT_LOCALE` too is a bug in the calling code, not a translation gap,
    and raises rather than showing a raw dotted key in a shipped build.
    """
    value = _lookup(_current, key)
    if value is _MISSING:
        value = _lookup(DEFAULT_LOCALE, key)
    if value is _MISSING:
        raise TranslationError(f"no string for key '{key}' in "
                                f"'{DEFAULT_LOCALE}' (the base locale)")
    if not isinstance(value, str):
        raise TranslationError(f"key '{key}' does not resolve to a string "
                                f"(got {type(value).__name__})")
    if not kwargs:
        return value
    try:
        return value.format(**kwargs)
    except (KeyError, IndexError) as exc:
        raise TranslationError(
            f"key '{key}' -- template {value!r} does not match the "
            f"arguments it was called with: {exc}"
        ) from None
