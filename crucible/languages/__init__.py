"""Language registry.

To add a language: write a `Language` subclass, import it here, and add it to
`_LANGUAGES`. Nothing else in the application needs to change -- problems
select their language by `id`, and the UI builds its menus from this registry.
"""

from __future__ import annotations

from .base import BuildResult, ExecResult, Language, ToolchainStatus, run_process
from .c_lang import CLanguage
from .cpp_lang import CppLanguage
from .csharp_lang import CSharpLanguage
from .java_lang import JavaLanguage
from .python_lang import PythonLanguage

_LANGUAGES: dict[str, Language] = {}


def register(language: Language) -> None:
    _LANGUAGES[language.id] = language


for _cls in (CLanguage, CppLanguage, PythonLanguage, CSharpLanguage, JavaLanguage):
    register(_cls())


def get(language_id: str) -> Language:
    try:
        return _LANGUAGES[language_id]
    except KeyError:
        known = ", ".join(sorted(_LANGUAGES)) or "none"
        raise KeyError(
            f"Unknown language {language_id!r}. Registered: {known}."
        ) from None


def all_languages() -> list[Language]:
    return list(_LANGUAGES.values())


def known_ids() -> list[str]:
    return sorted(_LANGUAGES)


__all__ = [
    "BuildResult", "ExecResult", "Language", "ToolchainStatus", "run_process",
    "CLanguage", "CppLanguage", "PythonLanguage", "CSharpLanguage", "JavaLanguage",
    "register", "get", "all_languages", "known_ids",
]
