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
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field
from pathlib import Path

from . import languages

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
        return f"{self.name} (hidden)" if self.hidden else self.name


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
        raise ProblemError(f"{path.name}: missing required field '{key}'")
    value = data[key]
    if not isinstance(value, kind):
        raise ProblemError(
            f"{path.name}: field '{key}' must be {kind.__name__}, "
            f"got {type(value).__name__}"
        )
    if kind is str and not value.strip():
        raise ProblemError(f"{path.name}: field '{key}' must not be empty")
    return value


def _load_reference(data: dict, path: Path) -> ReferenceSolution:
    plain = data.get("reference_solution")
    encoded = data.get("reference_solution_b64")

    if plain and encoded:
        raise ProblemError(
            f"{path.name}: set 'reference_solution' or "
            f"'reference_solution_b64', not both"
        )
    if isinstance(plain, str) and plain.strip():
        return ReferenceSolution(plain, encoded=False)
    if isinstance(encoded, str) and encoded.strip():
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ProblemError(
                f"{path.name}: 'reference_solution_b64' is not valid "
                f"base64-encoded UTF-8 ({exc})"
            ) from None
        if not decoded.strip():
            raise ProblemError(f"{path.name}: decoded reference solution is empty")
        return ReferenceSolution(decoded, encoded=True)

    raise ProblemError(
        f"{path.name}: a reference solution is required -- the test suite "
        f"cannot be pre-verified without one"
    )


def _load_generator(data: dict, path: Path) -> Generator | None:
    raw = data.get("generator")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ProblemError(
            f"{path.name}: 'generator' must be an object with a 'source' field"
        )

    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ProblemError(f"{path.name}: 'generator.source' must be Python source")
    try:
        compile(source, f"{path.name}:generator", "exec")
    except SyntaxError as exc:
        raise ProblemError(
            f"{path.name}: 'generator.source' does not parse as Python "
            f"(line {exc.lineno}: {exc.msg})"
        ) from None
    if "def generate" not in source:
        raise ProblemError(
            f"{path.name}: 'generator.source' must define generate(rng, count)"
        )

    count = raw.get("count", DEFAULT_GENERATED_CASES)
    if not isinstance(count, int) or isinstance(count, bool):
        raise ProblemError(f"{path.name}: 'generator.count' must be an integer")
    if not 1 <= count <= MAX_GENERATED_CASES:
        raise ProblemError(
            f"{path.name}: 'generator.count' must be between 1 and "
            f"{MAX_GENERATED_CASES}"
        )

    return Generator(source=source, count=count)


def _load_tests(data: dict, path: Path,
                generator: Generator | None) -> tuple[TestCase, ...]:
    raw = data.get("tests", [])
    if not isinstance(raw, list):
        raise ProblemError(f"{path.name}: 'tests' must be a list")
    if not raw and generator is None:
        raise ProblemError(
            f"{path.name}: 'tests' must be a non-empty list unless the problem "
            f"has a 'generator' to supply cases"
        )

    tests: list[TestCase] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        where = f"{path.name}: tests[{index}]"
        if not isinstance(item, dict):
            raise ProblemError(f"{where} must be an object")
        name = item.get("name") or f"case {index + 1}"
        if not isinstance(name, str):
            raise ProblemError(f"{where}.name must be a string")
        if name in seen:
            raise ProblemError(f"{where}.name '{name}' is duplicated")
        seen.add(name)
        if "expected_stdout" not in item:
            raise ProblemError(f"{where} is missing 'expected_stdout'")
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


def load_problem(path: Path) -> Problem:
    """Parse and validate one problem file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProblemError(f"{path.name}: invalid JSON at line {exc.lineno}: {exc.msg}") from None
    except OSError as exc:
        raise ProblemError(f"{path.name}: cannot read file ({exc})") from None

    if not isinstance(data, dict):
        raise ProblemError(f"{path.name}: top level must be a JSON object")

    language_id = str(_require(data, "language", path))
    if language_id not in languages.known_ids():
        raise ProblemError(
            f"{path.name}: unknown language '{language_id}'. "
            f"Registered languages: {', '.join(languages.known_ids())}"
        )

    difficulty = str(data.get("difficulty", "easy")).lower()
    if difficulty not in DIFFICULTIES:
        raise ProblemError(
            f"{path.name}: difficulty '{difficulty}' must be one of "
            f"{', '.join(DIFFICULTIES)}"
        )

    try:
        timeout = float(data.get("timeout_seconds", DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        raise ProblemError(f"{path.name}: 'timeout_seconds' must be a number") from None
    if not 0 < timeout <= 120:
        raise ProblemError(f"{path.name}: 'timeout_seconds' must be between 0 and 120")

    topics = data.get("topics", [])
    if not isinstance(topics, list):
        raise ProblemError(f"{path.name}: 'topics' must be a list")

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


def load_library(root: Path) -> Library:
    """Load every `*.json` under `root`, recursively.

    A bad file never takes the app down -- it is collected into `errors` and
    reported in the UI so the author can fix it.
    """
    library = Library()
    if not root.is_dir():
        library.errors.append(f"Problem directory not found: {root}")
        return library

    for path in sorted(root.rglob("*.json")):
        try:
            library.problems.append(load_problem(path))
        except ProblemError as exc:
            library.errors.append(str(exc))

    duplicates = _duplicate_ids(library.problems)
    for dupe in duplicates:
        library.errors.append(f"Duplicate problem id '{dupe}' -- ids must be unique")

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
