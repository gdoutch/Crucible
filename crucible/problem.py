"""Problem definitions: schema, loading and validation.

A problem is a single JSON file. The important structural idea is that the
*test cases* and the *reference solution* live in the same file but are treated
completely differently by the application:

  * test cases  -> shown to the candidate, always, in full. They are the
                   specification and the main learning aid.
  * reference   -> never rendered anywhere in the UI. It exists so the app can
                   prove the test suite is satisfiable before anyone is asked
                   to satisfy it.

See `ReferenceSolution` for what "hidden" does and does not mean here.

A problem may also carry a `Generator`, which adds randomised cases to the
authored ones so the same exercise can be practised more than once without the
answers becoming a memory test. A generator writes *inputs only* -- see
`crucible.randomise` for why that restriction is the whole trick.

A problem's prose -- `title`, `statement`, and each test's `name` and
`description` -- may be translated for the active locale by dropping a
sibling `<stem>.<locale>.json` file next to it (see `_load_locale_overlay`).
This is separate from `crucible.i18n`, which only covers application chrome;
see 'Internationalisation' in the README for why the two are deliberately
different mechanisms with different owners.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import i18n, languages
from .i18n import t

DIFFICULTIES = ("easy", "medium", "hard", "fiendish")
DEFAULT_TIMEOUT = 5.0
DEFAULT_GENERATED_CASES = 4
MAX_GENERATED_CASES = 25


class ProblemError(ValueError):
    """A problem file is malformed. Message is shown to the author, not the
    candidate, so it should be precise about which field is wrong."""


@dataclass(frozen=True)
class TestCase:
    """One visible unit test.

    `stdin` is fed to the harness; `expected_stdout` is what the harness must
    print. Both are shown to the candidate verbatim.
    """

    name: str
    stdin: str
    expected_stdout: str
    description: str = ""
    hidden: bool = False
    #: True when the input was randomly generated and `expected_stdout` was
    #: captured from the reference solution rather than written by hand. The
    #: UI says so on the case, because "where did this expected output come
    #: from" is a fair question to ask of a number that was not there before.
    generated: bool = False

    @property
    def display_name(self) -> str:
        return (t("problem.test_case.hidden_suffix", name=self.name) if self.hidden
                else self.name)


@dataclass(frozen=True)
class ReferenceSolution:
    """The known-good solution used to pre-verify the test suite.

    Being honest about the threat model: this file sits on the candidate's own
    disk, so a determined person can read it. `encoded=True` (via the
    `reference_solution_b64` field) stops *casual* discovery -- someone opening
    the JSON to read the test cases will not have the answer land in their lap.
    It is not a security boundary. If you are running this as a real assessment
    rather than as self-practice, serve problems from somewhere the candidate
    cannot read.
    """

    source: str
    encoded: bool = False


@dataclass(frozen=True)
class Generator:
    """A recipe for randomised test *inputs*.

    `source` is a Python program -- always Python, whatever language the
    problem itself is in -- defining:

        def generate(rng, count) -> list[dict]

    `rng` is a `random.Random` seeded from the data set number, so the same
    seed always yields the same cases. Each returned dict describes one case:
    `stdin` (required) plus optional `name`, `description` and `hidden`.

    Deliberately *not* in that dict: `expected_stdout`. A generator that also
    stated the answer would be a second implementation of the problem, free to
    drift out of step with the reference solution. Instead the expected output
    is captured from the reference. See `crucible.randomise`.

    The source is stored in plain text, not base64. Unlike the reference
    solution there is nothing here to spoil: knowing the shape of the inputs
    is knowing the specification, which the candidate is entitled to.
    """

    source: str
    count: int = DEFAULT_GENERATED_CASES


@dataclass
class Problem:
    id: str
    title: str
    language_id: str
    statement: str
    starter_code: str
    harness: str
    #: Cases written out by hand in the problem file. These are the edge cases
    #: -- empty input, one element, the awkward semantics -- and they are the
    #: same every time, because an edge case you might not meet this run is not
    #: doing its job.
    fixed_tests: tuple[TestCase, ...]
    reference: ReferenceSolution
    generator: Generator | None = None
    difficulty: str = "easy"
    topics: tuple[str, ...] = ()
    timeout_seconds: float = DEFAULT_TIMEOUT
    source_path: Path | None = None
    #: Filled in by `crucible.randomise.generate`. Empty until then, so a
    #: problem is always usable -- just with fewer cases -- if generation has
    #: not run or could not run.
    generated_tests: tuple[TestCase, ...] = ()
    #: Which data set `generated_tests` came from. None means "not generated".
    seed: int | None = None

    @property
    def language(self) -> languages.Language:
        return languages.get(self.language_id)

    @property
    def tests(self) -> tuple[TestCase, ...]:
        """Everything that will be run, hand-written cases first."""
        return self.fixed_tests + self.generated_tests

    @property
    def randomised(self) -> bool:
        return self.generator is not None

    @property
    def visible_tests(self) -> tuple[TestCase, ...]:
        return tuple(t for t in self.tests if not t.hidden)

    def __str__(self) -> str:  # pragma: no cover - display helper
        return f"{self.title} [{self.language_id}/{self.difficulty}]"


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def _require(data: dict, key: str, path: Path, kind: type = str) -> object:
    if key not in data:
        raise ProblemError(t("problem.error.missing_field", file=path.name, key=key))
    value = data[key]
    if not isinstance(value, kind):
        raise ProblemError(t("problem.error.wrong_type", file=path.name, key=key,
                             expected=kind.__name__, actual=type(value).__name__))
    if kind is str and not value.strip():
        raise ProblemError(t("problem.error.empty_field", file=path.name, key=key))
    return value


def _load_reference(data: dict, path: Path) -> ReferenceSolution:
    plain = data.get("reference_solution")
    encoded = data.get("reference_solution_b64")

    if plain and encoded:
        raise ProblemError(t("problem.error.reference_both_set", file=path.name))
    if isinstance(plain, str) and plain.strip():
        return ReferenceSolution(plain, encoded=False)
    if isinstance(encoded, str) and encoded.strip():
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ProblemError(t("problem.error.reference_bad_base64",
                                 file=path.name, error=exc)) from None
        if not decoded.strip():
            raise ProblemError(t("problem.error.reference_decoded_empty", file=path.name))
        return ReferenceSolution(decoded, encoded=True)

    raise ProblemError(t("problem.error.reference_required", file=path.name))


def _load_generator(data: dict, path: Path) -> Generator | None:
    raw = data.get("generator")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProblemError(t("problem.error.generator_not_object", file=path.name))

    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ProblemError(t("problem.error.generator_source_not_string", file=path.name))
    try:
        compile(source, f"{path.name}:generator", "exec")
    except SyntaxError as exc:
        raise ProblemError(t("problem.error.generator_source_syntax_error",
                             file=path.name, line=exc.lineno, message=exc.msg)) from None
    if "def generate" not in source:
        raise ProblemError(t("problem.error.generator_missing_generate", file=path.name))

    count = raw.get("count", DEFAULT_GENERATED_CASES)
    if not isinstance(count, int) or isinstance(count, bool):
        raise ProblemError(t("problem.error.generator_count_not_int", file=path.name))
    if not 1 <= count <= MAX_GENERATED_CASES:
        raise ProblemError(t("problem.error.generator_count_out_of_range",
                             file=path.name, max=MAX_GENERATED_CASES))

    return Generator(source=source, count=count)


def _load_tests(data: dict, path: Path,
                generator: Generator | None) -> tuple[TestCase, ...]:
    raw = data.get("tests", [])
    if not isinstance(raw, list):
        raise ProblemError(t("problem.error.tests_not_list", file=path.name))
    if not raw and generator is None:
        raise ProblemError(t("problem.error.tests_empty_without_generator", file=path.name))

    tests: list[TestCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        where = t("problem.error.test_where", file=path.name, index=index)
        if not isinstance(item, dict):
            raise ProblemError(t("problem.error.test_not_object", where=where))
        name = item.get("name") or t("problem.test_case.default_name", index=index + 1)
        if not isinstance(name, str):
            raise ProblemError(t("problem.error.test_name_not_string", where=where))
        if name in seen:
            raise ProblemError(t("problem.error.test_name_duplicated", where=where, name=name))
        seen.add(name)
        if "expected_stdout" not in item:
            raise ProblemError(t("problem.error.test_missing_expected_stdout", where=where))
        tests.append(
            TestCase(
                name=name,
                stdin=str(item.get("stdin", "")),
                expected_stdout=str(item["expected_stdout"]),
                description=str(item.get("description", "")),
                hidden=bool(item.get("hidden", False)),
            )
        )
    return tuple(tests)


#: The problem fields a locale overlay is allowed to translate. Deliberately
#: narrow: `starter_code`, `harness` and the reference solution stay English
#: (and C#, and C, ...) everywhere, because they are code, not prose, and
#: translating a doc-comment inside them would be one more thing to keep in
#: sync with no compiler to catch a slip. `tests[].name` and
#: `tests[].description` are handled separately, matched by position -- see
#: `_apply_locale_overlay`.
_OVERLAY_FIELDS = ("title", "statement")


def _locale_overlay_path(path: Path, locale: str) -> Path:
    """Where a translated sibling of `path` would live for `locale`.

    Mirrors the guide-file convention in `crucible.guides`: the locale is
    another dotted qualifier on the filename, not a subdirectory or a field
    inside the English file -- so `cs_count_vowels.json` translated into
    French is `cs_count_vowels.fr_FR.json`, sitting right next to it.
    """
    return path.with_name(f"{path.stem}.{locale}.json")


def _load_locale_overlay(path: Path, locale: str) -> dict:
    """The translated fields for `path`'s problem in `locale`, or `{}` if
    there is no overlay file -- translating a problem is optional, and an
    untranslated one still loads, showing English throughout.

    This is problem content, not app chrome, so it deliberately does not go
    through `crucible.i18n` (see 'Internationalisation' in the README): there
    is no `locales/fr_FR.json` entry for one exercise's statement. What it
    does borrow from `i18n` is the fallback *philosophy* -- a locale that
    only translates some fields, or some problems, still works, falling back
    to English field by field rather than needing to be complete before it
    can ship.
    """
    overlay_path = _locale_overlay_path(path, locale)
    if not overlay_path.is_file():
        return {}
    try:
        overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProblemError(t("problem.error.invalid_json", file=overlay_path.name,
                             line=exc.lineno, message=exc.msg)) from None
    except OSError as exc:
        raise ProblemError(t("problem.error.cannot_read_file", file=overlay_path.name,
                             error=exc)) from None
    if not isinstance(overlay, dict):
        raise ProblemError(t("problem.error.top_level_not_object", file=overlay_path.name))
    return overlay


def _apply_locale_overlay(data: dict, overlay: dict) -> dict:
    """`data` with any translated fields from `overlay` merged on top.

    Per field, not all-or-nothing: an overlay field that is absent, blank, or
    not a string leaves the English value in `data` in place rather than
    blanking it out, exactly as a missing key in a `locales/*.json` file
    falls back to `en_GB` in `i18n.t`. `tests` is matched by position against
    the base list -- the overlay only needs to carry the fields it
    translates, not a full copy of every test case.
    """
    if not overlay:
        return data

    merged = dict(data)
    for field_name in _OVERLAY_FIELDS:
        value = overlay.get(field_name)
        if isinstance(value, str) and value.strip():
            merged[field_name] = value

    overlay_tests = overlay.get("tests")
    base_tests = data.get("tests")
    if isinstance(overlay_tests, list) and isinstance(base_tests, list):
        merged_tests = []
        for index, base_test in enumerate(base_tests):
            if not isinstance(base_test, dict):
                merged_tests.append(base_test)
                continue
            translated_test = dict(base_test)
            if index < len(overlay_tests) and isinstance(overlay_tests[index], dict):
                for field_name in ("name", "description"):
                    value = overlay_tests[index].get(field_name)
                    if isinstance(value, str) and value.strip():
                        translated_test[field_name] = value
            merged_tests.append(translated_test)
        merged["tests"] = merged_tests

    return merged


def load_problem(path: Path) -> Problem:
    """Parse and validate one problem file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProblemError(t("problem.error.invalid_json", file=path.name,
                             line=exc.lineno, message=exc.msg)) from None
    except OSError as exc:
        raise ProblemError(t("problem.error.cannot_read_file", file=path.name,
                             error=exc)) from None

    if not isinstance(data, dict):
        raise ProblemError(t("problem.error.top_level_not_object", file=path.name))

    locale = i18n.get_locale()
    if locale != i18n.DEFAULT_LOCALE:
        data = _apply_locale_overlay(data, _load_locale_overlay(path, locale))

    language_id = str(_require(data, "language", path))
    if language_id not in languages.known_ids():
        raise ProblemError(t("problem.error.unknown_language", file=path.name,
                             language=language_id,
                             known=", ".join(languages.known_ids())))

    difficulty = str(data.get("difficulty", "easy")).lower()
    if difficulty not in DIFFICULTIES:
        raise ProblemError(t("problem.error.unknown_difficulty", file=path.name,
                             difficulty=difficulty,
                             choices=", ".join(DIFFICULTIES)))

    try:
        timeout = float(data.get("timeout_seconds", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        raise ProblemError(t("problem.error.timeout_not_number", file=path.name)) from None
    if not 0 < timeout <= 120:
        raise ProblemError(t("problem.error.timeout_out_of_range", file=path.name))

    topics = data.get("topics", [])
    if not isinstance(topics, list):
        raise ProblemError(t("problem.error.topics_not_list", file=path.name))

    generator = _load_generator(data, path)

    return Problem(
        id=str(data.get("id") or path.stem),
        title=str(_require(data, "title", path)),
        language_id=language_id,
        statement=str(_require(data, "statement", path)),
        starter_code=str(data.get("starter_code", "")),
        harness=str(_require(data, "harness", path)),
        fixed_tests=_load_tests(data, path, generator),
        reference=_load_reference(data, path),
        generator=generator,
        difficulty=difficulty,
        topics=tuple(str(t) for t in topics),
        timeout_seconds=timeout,
        source_path=path,
    )


@dataclass
class Library:
    """Every problem found on disk, plus whatever failed to load and why."""

    problems: list[Problem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def by_language(self, language_id: str) -> list[Problem]:
        return [p for p in self.problems if p.language_id == language_id]

    def get(self, problem_id: str) -> Problem | None:
        return next((p for p in self.problems if p.id == problem_id), None)

    @property
    def languages_present(self) -> list[str]:
        seen = {p.language_id for p in self.problems}
        return [lang.id for lang in languages.all_languages() if lang.id in seen]


def _is_locale_overlay(path: Path) -> bool:
    """True for a `<stem>.<locale>.json` translation file -- `path` itself is
    never a standalone problem, only ever read as a sibling of one by
    `_load_locale_overlay`, so `load_library`'s sweep must step over it
    rather than trying to load it as a problem in its own right (it has none
    of the required fields, and would only ever fail)."""
    stem = path.stem  # "cs_count_vowels.fr_FR" for "cs_count_vowels.fr_FR.json"
    _, dot, suffix = stem.rpartition(".")
    return bool(dot) and suffix in i18n.available_locales()


def load_library(root: Path) -> Library:
    """Load every `*.json` under `root`, recursively -- except a translated
    sibling of a problem (`<stem>.<locale>.json`, see `_is_locale_overlay`),
    which is content for an existing problem rather than one of its own.

    A bad file never takes the app down -- it is collected into `errors` and
    reported in the UI so the author can fix it.
    """
    library = Library()
    if not root.is_dir():
        library.errors.append(t("problem.error.directory_not_found", root=root))
        return library

    for path in sorted(root.rglob("*.json")):
        if _is_locale_overlay(path):
            continue
        try:
            library.problems.append(load_problem(path))
        except ProblemError as exc:
            library.errors.append(str(exc))

    duplicates = _duplicate_ids(library.problems)
    for dupe in duplicates:
        library.errors.append(t("problem.error.duplicate_id", id=dupe))

    library.problems.sort(key=lambda p: (p.language_id,
                                         DIFFICULTIES.index(p.difficulty),
                                         p.title))
    return library


def _duplicate_ids(problems: list[Problem]) -> list[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for problem in problems:
        if problem.id in seen:
            dupes.add(problem.id)
        seen.add(problem.id)
    return sorted(dupes)
