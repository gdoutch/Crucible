"""Regression tests.

    python -m unittest discover -s tests -v

Everything here runs without a C compiler: the language layer is exercised
through Python, and the C-specific logic that can be tested without invoking a
compiler (diagnostic cleanup, exit-code description) is tested directly.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crucible import __main__ as crucible_main
from crucible import guides, i18n, languages, profiles, randomise, runner, workspace
from crucible.languages import asm_lang, native_compiler
from crucible.languages.asm_lang import AsmX64MasmLanguage
from crucible.languages.c_lang import CLanguage
from crucible.languages.csharp_lang import CSharpLanguage
from crucible.languages.vhdl_lang import VhdlLanguage
from crucible.problem import ProblemError, load_library, load_problem

PROBLEMS_ROOT = Path(__file__).resolve().parents[1] / "problems"


# ---------------------------------------------------------------------------
# output comparison
# ---------------------------------------------------------------------------

class TestNormalisation(unittest.TestCase):
    def test_trailing_newlines_ignored(self):
        self.assertTrue(runner.outputs_match("15", "15\n"))
        self.assertTrue(runner.outputs_match("15", "15\n\n\n"))

    def test_windows_line_endings_ignored(self):
        self.assertTrue(runner.outputs_match("a\nb", "a\r\nb\r\n"))

    def test_trailing_spaces_per_line_ignored(self):
        self.assertTrue(runner.outputs_match("1 2 3", "1 2 3   \n"))

    def test_leading_whitespace_is_significant(self):
        self.assertFalse(runner.outputs_match("abc", "  abc"))

    def test_interior_blank_lines_are_significant(self):
        self.assertFalse(runner.outputs_match("a\nb", "a\n\nb"))

    def test_empty_expected_matches_empty_output(self):
        self.assertTrue(runner.outputs_match("", ""))
        self.assertTrue(runner.outputs_match("", "\n"))

    def test_empty_expected_does_not_match_content(self):
        self.assertFalse(runner.outputs_match("", "0"))


class TestDiffNote(unittest.TestCase):
    def test_identical_gives_no_note(self):
        self.assertEqual(runner.diff_note("a", "a"), "")

    def test_no_output(self):
        self.assertEqual(runner.diff_note("a", ""), "produced no output")

    def test_case_difference_is_called_out(self):
        self.assertIn("case", runner.diff_note("Fizz", "fizz"))

    def test_line_count_difference(self):
        self.assertIn("line", runner.diff_note("a\nb\nc", "a\nb"))

    def test_first_differing_line_reported(self):
        self.assertIn("line 2", runner.diff_note("a\nb\nc", "a\nX\nc"))


# ---------------------------------------------------------------------------
# problem loading
# ---------------------------------------------------------------------------

MINIMAL = {
    "id": "demo",
    "title": "Demo",
    "language": "python",
    "statement": "Do a thing.",
    "harness": "print(1)",
    "reference_solution": "x = 1",
    "tests": [{"name": "only", "stdin": "", "expected_stdout": "1"}],
}


def write_problem(directory: Path, **overrides) -> Path:
    data = dict(MINIMAL)
    data.update(overrides)
    for key, value in list(data.items()):
        if value is None:
            del data[key]
    path = directory / f"{data.get('id', 'demo')}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestProblemLoading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_minimal_problem_loads(self):
        problem = load_problem(write_problem(self.dir))
        self.assertEqual(problem.title, "Demo")
        self.assertEqual(len(problem.tests), 1)
        self.assertEqual(problem.reference.source, "x = 1")

    def test_missing_required_field_is_rejected(self):
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, statement=None))
        self.assertIn("statement", str(ctx.exception))

    def test_reference_solution_is_required(self):
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, reference_solution=None))
        self.assertIn("reference solution is required", str(ctx.exception))

    def test_unknown_language_is_rejected(self):
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, language="brainfuck"))
        self.assertIn("unknown language", str(ctx.exception).lower())

    def test_empty_test_list_is_rejected(self):
        with self.assertRaises(ProblemError):
            load_problem(write_problem(self.dir, tests=[]))

    def test_duplicate_test_names_are_rejected(self):
        duplicated = [{"name": "same", "expected_stdout": "1"},
                      {"name": "same", "expected_stdout": "2"}]
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, tests=duplicated))
        self.assertIn("duplicated", str(ctx.exception))

    def test_test_without_expected_output_is_rejected(self):
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, tests=[{"name": "x"}]))
        self.assertIn("expected_stdout", str(ctx.exception))

    def test_base64_reference_is_decoded(self):
        encoded = base64.b64encode(b"y = 2").decode()
        problem = load_problem(write_problem(
            self.dir, reference_solution=None, reference_solution_b64=encoded))
        self.assertEqual(problem.reference.source, "y = 2")
        self.assertTrue(problem.reference.encoded)

    def test_both_reference_forms_is_rejected(self):
        encoded = base64.b64encode(b"y = 2").decode()
        with self.assertRaises(ProblemError):
            load_problem(write_problem(self.dir, reference_solution_b64=encoded))

    def test_invalid_base64_is_rejected(self):
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, reference_solution=None,
                                       reference_solution_b64="not base64!!"))
        self.assertIn("base64", str(ctx.exception))

    def test_invalid_json_is_reported_with_line_number(self):
        path = self.dir / "bad.json"
        path.write_text("{ not json", encoding="utf-8")
        with self.assertRaises(ProblemError) as ctx:
            load_problem(path)
        self.assertIn("line", str(ctx.exception))

    def test_bad_difficulty_is_rejected(self):
        with self.assertRaises(ProblemError):
            load_problem(write_problem(self.dir, difficulty="impossible"))

    def test_library_collects_errors_without_raising(self):
        write_problem(self.dir, id="good")
        (self.dir / "broken.json").write_text("{", encoding="utf-8")
        library = load_library(self.dir)
        self.assertEqual(len(library.problems), 1)
        self.assertEqual(len(library.errors), 1)

    def test_duplicate_ids_are_reported(self):
        (self.dir / "one").mkdir()
        (self.dir / "two").mkdir()
        write_problem(self.dir / "one", id="dupe")
        write_problem(self.dir / "two", id="dupe")
        library = load_library(self.dir)
        self.assertTrue(any("Duplicate" in e for e in library.errors))


# ---------------------------------------------------------------------------
# translated problem content
# ---------------------------------------------------------------------------

def write_overlay(directory: Path, locale: str, problem_id: str = "demo", **fields) -> Path:
    path = directory / f"{problem_id}.{locale}.json"
    path.write_text(json.dumps(fields), encoding="utf-8")
    return path


class TestProblemLocaleOverlay(unittest.TestCase):
    """A problem's prose may be translated by dropping a `<stem>.<locale>.json`
    sibling next to it -- see `crucible.problem._load_locale_overlay`. This is
    a different mechanism from `crucible.i18n` (which never sees problem
    content at all), so it gets its own coverage rather than piggybacking on
    `TestI18n`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self._original_locale = i18n.get_locale()
        self.addCleanup(i18n.set_locale, self._original_locale)

    def tearDown(self):
        self._tmp.cleanup()

    def test_overlay_is_ignored_under_the_default_locale(self):
        write_problem(self.dir)
        write_overlay(self.dir, "fr_FR", title="Démo")
        problem = load_problem(self.dir / "demo.json")
        self.assertEqual(problem.title, "Demo")

    def test_overlay_translates_title_and_statement(self):
        write_problem(self.dir)
        write_overlay(self.dir, "fr_FR", title="Démo", statement="Fais une chose.")
        i18n.set_locale("fr_FR")
        problem = load_problem(self.dir / "demo.json")
        self.assertEqual(problem.title, "Démo")
        self.assertEqual(problem.statement, "Fais une chose.")

    def test_overlay_field_left_blank_falls_back_to_english(self):
        write_problem(self.dir)
        write_overlay(self.dir, "fr_FR", title="Démo")  # no 'statement'
        i18n.set_locale("fr_FR")
        problem = load_problem(self.dir / "demo.json")
        self.assertEqual(problem.title, "Démo")
        self.assertEqual(problem.statement, "Do a thing.")

    def test_missing_overlay_file_leaves_everything_in_english(self):
        write_problem(self.dir)
        i18n.set_locale("fr_FR")
        problem = load_problem(self.dir / "demo.json")
        self.assertEqual(problem.title, "Demo")
        self.assertEqual(problem.statement, "Do a thing.")

    def test_overlay_translates_test_names_and_descriptions_by_position(self):
        tests = [{"name": "first", "stdin": "a", "expected_stdout": "1",
                 "description": "the first case"},
                {"name": "second", "stdin": "b", "expected_stdout": "2"}]
        write_problem(self.dir, tests=tests)
        write_overlay(self.dir, "fr_FR", tests=[
            {"name": "premier", "description": "le premier cas"},
            {"name": "second"},
        ])
        i18n.set_locale("fr_FR")
        problem = load_problem(self.dir / "demo.json")
        self.assertEqual(problem.fixed_tests[0].name, "premier")
        self.assertEqual(problem.fixed_tests[0].description, "le premier cas")
        self.assertEqual(problem.fixed_tests[1].name, "second")
        # stdin/expected_stdout are data, not prose -- the overlay never
        # touches them even though it could set them by key.
        self.assertEqual(problem.fixed_tests[0].stdin, "a")
        self.assertEqual(problem.fixed_tests[1].expected_stdout, "2")

    def test_malformed_overlay_is_reported_against_the_overlay_file(self):
        """The error names the overlay file itself, not the base problem --
        and is reported through `t()` in the active locale like any other
        `ProblemError`, so this checks the overlay's filename rather than
        any particular language's wording for 'line'."""
        write_problem(self.dir)
        (self.dir / "demo.fr_FR.json").write_text("{ not json", encoding="utf-8")
        i18n.set_locale("fr_FR")
        with self.assertRaises(ProblemError) as ctx:
            load_problem(self.dir / "demo.json")
        self.assertIn("demo.fr_FR.json", str(ctx.exception))

    def test_overlay_starter_code_and_reference_are_never_translated(self):
        """Code fields are deliberately outside `_OVERLAY_FIELDS` -- an
        overlay cannot rewrite them even if it tries."""
        write_problem(self.dir)
        write_overlay(self.dir, "fr_FR", starter_code="// pas de ceci",
                      reference_solution="not_python(")
        i18n.set_locale("fr_FR")
        problem = load_problem(self.dir / "demo.json")
        self.assertEqual(problem.starter_code, "")
        self.assertEqual(problem.reference.source, "x = 1")


# ---------------------------------------------------------------------------
# randomised test data
# ---------------------------------------------------------------------------

#: A problem whose answer is a pure function of its input, so a test can assert
#: the relationship between a generated input and its captured expected output
#: without knowing what the generator happened to produce.
SHOUTING = {
    "id": "shout",
    "title": "Shout",
    "language": "python",
    "statement": "Upper-case the line.",
    "harness": "import sys\nfrom solution import shout\n"
               "print(shout(sys.stdin.readline().rstrip('\\n')))\n",
    "reference_solution": "def shout(text):\n    return text.upper()\n",
    "tests": [{"name": "a word", "stdin": "abc\n", "expected_stdout": "ABC"}],
}

WORD_GENERATOR = textwrap.dedent("""\
    def generate(rng, count):
        return [{"name": "word %d" % i,
                 "stdin": "".join(rng.choice("abcdef") for _ in range(6)),
                 "description": "a random word"}
                for i in range(count)]
    """)


def randomised_problem(directory: Path, source: str = WORD_GENERATOR, **overrides):
    generator = {"count": 3, "source": source}
    generator.update(overrides.pop("generator", {}))
    return load_problem(write_problem(directory, generator=generator,
                                      **{**SHOUTING, **overrides}))


class TestGeneratorSchema(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_problem_without_a_generator_is_not_randomised(self):
        problem = load_problem(write_problem(self.dir))
        self.assertFalse(problem.randomised)
        self.assertEqual(problem.generated_tests, ())

    def test_generator_is_loaded(self):
        problem = randomised_problem(self.dir)
        self.assertTrue(problem.randomised)
        self.assertEqual(problem.generator.count, 3)

    def test_generator_source_must_parse(self):
        with self.assertRaises(ProblemError) as ctx:
            randomised_problem(self.dir, source="def generate(rng, count)\n")
        self.assertIn("does not parse", str(ctx.exception))

    def test_generator_must_define_generate(self):
        with self.assertRaises(ProblemError) as ctx:
            randomised_problem(self.dir, source="x = 1\n")
        self.assertIn("generate(rng, count)", str(ctx.exception))

    def test_generator_count_is_bounded(self):
        with self.assertRaises(ProblemError) as ctx:
            randomised_problem(self.dir, generator={"count": 500})
        self.assertIn("between 1 and", str(ctx.exception))

    def test_generator_must_be_an_object(self):
        with self.assertRaises(ProblemError):
            load_problem(write_problem(self.dir, generator="def generate(): pass"))

    def test_tests_may_be_empty_when_a_generator_supplies_them(self):
        problem = randomised_problem(self.dir, tests=[])
        self.assertEqual(problem.fixed_tests, ())

    def test_tests_may_not_be_empty_without_a_generator(self):
        with self.assertRaises(ProblemError) as ctx:
            load_problem(write_problem(self.dir, tests=[]))
        self.assertIn("generator", str(ctx.exception))


class TestGeneration(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_expected_output_comes_from_the_reference_solution(self):
        problem = randomised_problem(self.dir)
        suite = randomise.generate(problem, seed=1234)
        self.assertTrue(suite.ok, suite.error)
        self.assertEqual(len(suite.tests), 3)
        for test in suite.tests:
            # Nothing in the generator knows what the answer is; this is the
            # reference solution's opinion, captured.
            self.assertEqual(test.expected_stdout, test.stdin.strip().upper())
            self.assertTrue(test.generated)

    def test_the_same_seed_gives_the_same_data(self):
        problem = randomised_problem(self.dir)
        first = randomise.generate(problem, seed=77)
        second = randomise.generate(problem, seed=77)
        self.assertEqual(first.tests, second.tests)

    def test_a_different_seed_gives_different_data(self):
        problem = randomised_problem(self.dir)
        first = randomise.generate(problem, seed=1)
        second = randomise.generate(problem, seed=2)
        self.assertNotEqual([t.stdin for t in first.tests],
                            [t.stdin for t in second.tests])

    def test_generated_cases_are_appended_to_the_hand_written_ones(self):
        problem = randomised_problem(self.dir)
        randomise.apply(problem, randomise.generate(problem, seed=5))
        self.assertEqual(len(problem.tests), 4)
        self.assertEqual(problem.tests[0], problem.fixed_tests[0])
        self.assertEqual(problem.seed, 5)

    def test_a_generator_may_not_state_the_expected_output(self):
        """The one rule: generators describe inputs. A generator that also
        answered the problem could disagree with the reference, and the
        disagreement would land on the candidate as an impossible case."""
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                return [{"stdin": "abc", "expected_stdout": "WRONG"}]
            """))
        suite = randomise.generate(problem, seed=1)
        self.assertFalse(suite.ok)
        self.assertIn("expected_stdout", suite.error)

    def test_a_generator_that_raises_is_reported_not_propagated(self):
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                raise ValueError("no data today")
            """))
        suite = randomise.generate(problem, seed=1)
        self.assertFalse(suite.ok)
        self.assertIn("no data today", suite.error)
        self.assertEqual(suite.tests, ())

    def test_a_generator_that_never_returns_is_timed_out(self):
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                while True:
                    pass
            """))
        original = randomise.GENERATOR_TIMEOUT
        randomise.GENERATOR_TIMEOUT = 1.0
        try:
            suite = randomise.generate(problem, seed=1)
        finally:
            randomise.GENERATOR_TIMEOUT = original
        self.assertFalse(suite.ok)
        self.assertIn("endless loop", suite.error)

    def test_a_generator_that_returns_rubbish_is_rejected(self):
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                return ["not a case"]
            """))
        self.assertIn("not an object", randomise.generate(problem, seed=1).error)

    def test_a_case_without_stdin_is_rejected(self):
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                return [{"name": "nameless"}]
            """))
        self.assertIn("stdin", randomise.generate(problem, seed=1).error)

    def test_stray_printing_in_a_generator_does_not_corrupt_the_cases(self):
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                print("left-over debugging")
                return [{"stdin": "abc"}]
            """))
        suite = randomise.generate(problem, seed=1)
        self.assertTrue(suite.ok, suite.error)
        self.assertEqual(suite.tests[0].expected_stdout, "ABC")

    def test_an_input_the_reference_cannot_run_is_dropped_and_reported(self):
        """A generator can wander outside the problem's own contract. When it
        does, there is no trustworthy expected output, so the case must not
        become a test -- and the author has to be told which one."""
        problem = randomised_problem(
            self.dir,
            reference_solution="def shout(text):\n"
                               "    if text == 'boom':\n"
                               "        raise RuntimeError('bang')\n"
                               "    return text.upper()\n",
            source=textwrap.dedent("""\
                def generate(rng, count):
                    return [{"name": "fine", "stdin": "abc"},
                            {"name": "poison", "stdin": "boom"}]
                """))
        suite = randomise.generate(problem, seed=1)
        self.assertFalse(suite.ok)
        self.assertIn("poison", suite.error)
        self.assertEqual([t.name for t in suite.tests], ["fine"])

    def test_generated_names_never_collide_with_hand_written_ones(self):
        problem = randomised_problem(self.dir, source=textwrap.dedent("""\
            def generate(rng, count):
                return [{"name": "a word", "stdin": "xyz"}]
            """))
        randomise.apply(problem, randomise.generate(problem, seed=1))
        names = [t.name for t in problem.tests]
        self.assertEqual(len(names), len(set(names)))

    def test_a_problem_with_no_generator_generates_nothing_and_is_happy(self):
        problem = load_problem(write_problem(self.dir))
        suite = randomise.generate(problem, seed=1)
        self.assertTrue(suite.ok)
        self.assertEqual(suite.tests, ())

    def test_seeds_are_four_digit_numbers(self):
        for _ in range(50):
            self.assertRegex(str(randomise.new_seed()), r"^\d{4}$")


class TestSeedStorage(unittest.TestCase):
    """Data set numbers live beside the drafts: pick a problem back up
    tomorrow and the cases you were reading are still the ones you get."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = os.environ.get("CRUCIBLE_HOME")
        os.environ["CRUCIBLE_HOME"] = self._tmp.name

    def tearDown(self):
        if self._home is None:
            del os.environ["CRUCIBLE_HOME"]
        else:
            os.environ["CRUCIBLE_HOME"] = self._home
        self._tmp.cleanup()

    def test_seeds_survive_a_round_trip(self):
        workspace.save_seeds({"py_two_sum": 4321})
        self.assertEqual(workspace.load_seeds(), {"py_two_sum": 4321})

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(workspace.load_seeds(), {})

    def test_corrupt_file_is_ignored(self):
        (Path(self._tmp.name) / "seeds.json").write_text("{ nonsense")
        self.assertEqual(workspace.load_seeds(), {})

    def test_non_integer_seeds_are_discarded(self):
        (Path(self._tmp.name) / "seeds.json").write_text(
            '{"good": 1234, "bad": "banana"}')
        self.assertEqual(workspace.load_seeds(), {"good": 1234})

    def test_a_root_scopes_seeds_away_from_the_default(self):
        scoped = Path(self._tmp.name) / "someone-else"
        workspace.save_seeds({"py_two_sum": 1}, root=scoped)
        workspace.save_seeds({"py_two_sum": 2})  # the unscoped, default location
        self.assertEqual(workspace.load_seeds(root=scoped), {"py_two_sum": 1})
        self.assertEqual(workspace.load_seeds(), {"py_two_sum": 2})

    def test_a_root_scopes_drafts_away_from_the_default(self):
        scoped = Path(self._tmp.name) / "someone-else"
        workspace.save_draft("py_two_sum", ".py", "# scoped", root=scoped)
        workspace.save_draft("py_two_sum", ".py", "# default")
        self.assertEqual(workspace.load_draft("py_two_sum", ".py", root=scoped),
                         "# scoped")
        self.assertEqual(workspace.load_draft("py_two_sum", ".py"), "# default")


class TestSettingsLocale(unittest.TestCase):
    """The Language menu (crucible.ui.app._set_locale) persists its choice
    through workspace.save_settings/load_settings -- the same file theme
    and font size already live in, not a separate mechanism of its own."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = os.environ.get("CRUCIBLE_HOME")
        os.environ["CRUCIBLE_HOME"] = self._tmp.name

    def tearDown(self):
        if self._home is None:
            del os.environ["CRUCIBLE_HOME"]
        else:
            os.environ["CRUCIBLE_HOME"] = self._home
        self._tmp.cleanup()

    def test_default_settings_locale_matches_i18n_default(self):
        self.assertEqual(workspace.DEFAULT_SETTINGS["locale"], i18n.DEFAULT_LOCALE)

    def test_missing_settings_file_defaults_to_en_gb(self):
        self.assertEqual(workspace.load_settings()["locale"], "en_GB")

    def test_locale_survives_a_round_trip(self):
        settings = workspace.load_settings()
        settings["locale"] = "fr_FR"
        workspace.save_settings(settings)
        self.assertEqual(workspace.load_settings()["locale"], "fr_FR")


class TestCompilerPathOverrides(unittest.TestCase):
    """The compiler status page's Browse button, minus the file dialog and
    the Tk window around it -- see crucible.ui.compiler_status_dialog."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = os.environ.get("CRUCIBLE_HOME")
        os.environ["CRUCIBLE_HOME"] = self._tmp.name
        self._path = os.environ.get("PATH", "")

    def tearDown(self):
        if self._home is None:
            os.environ.pop("CRUCIBLE_HOME", None)
        else:
            os.environ["CRUCIBLE_HOME"] = self._home
        os.environ["PATH"] = self._path
        self._tmp.cleanup()

    def test_default_settings_has_no_overrides(self):
        self.assertEqual(workspace.DEFAULT_SETTINGS["compiler_path_overrides"], {})

    def test_set_override_round_trips_through_disk(self):
        settings = workspace.load_settings()
        workspace.set_compiler_path_override("c", r"C:\tools\gcc\bin", settings)
        self.assertEqual(
            workspace.load_settings()["compiler_path_overrides"]["c"],
            r"C:\tools\gcc\bin")

    def test_set_override_mutates_the_caller_s_dict_in_place(self):
        """The dialog holds one long-lived settings dict (the same one
        CrucibleApp.settings is) rather than reloading after every action, so
        the call has to update it directly rather than only the file."""
        settings = workspace.load_settings()
        workspace.set_compiler_path_override("java", r"C:\jdk\bin", settings)
        self.assertEqual(settings["compiler_path_overrides"]["java"], r"C:\jdk\bin")

    def test_set_override_prepends_it_onto_this_process_s_path(self):
        settings = workspace.load_settings()
        workspace.set_compiler_path_override("vhdl", r"C:\ghdl\bin", settings)
        entries = os.environ["PATH"].split(os.pathsep)
        self.assertEqual(entries[0], r"C:\ghdl\bin")

    def test_applying_twice_does_not_duplicate_the_path_entry(self):
        settings = workspace.load_settings()
        workspace.set_compiler_path_override("vhdl", r"C:\ghdl\bin", settings)
        workspace.apply_compiler_path_overrides(settings)
        workspace.apply_compiler_path_overrides(settings)
        entries = os.environ["PATH"].split(os.pathsep)
        self.assertEqual(entries.count(r"C:\ghdl\bin"), 1)

    def test_clear_override_removes_it_from_settings(self):
        settings = workspace.load_settings()
        workspace.set_compiler_path_override("c", r"C:\tools\gcc\bin", settings)
        workspace.clear_compiler_path_override("c", settings)
        self.assertNotIn("c", workspace.load_settings()["compiler_path_overrides"])

    def test_clear_override_does_not_touch_a_running_process_s_path(self):
        """Documented in workspace.clear_compiler_path_override: stripping an
        entry back out of a live PATH is not attempted. A directory that was
        genuinely found there does no harm sitting on PATH unused; getting
        the removal wrong would."""
        settings = workspace.load_settings()
        workspace.set_compiler_path_override("c", r"C:\tools\gcc\bin", settings)
        workspace.clear_compiler_path_override("c", settings)
        self.assertIn(r"C:\tools\gcc\bin", os.environ["PATH"].split(os.pathsep))


# ---------------------------------------------------------------------------
# profiles
# ---------------------------------------------------------------------------

class TestProfiles(unittest.TestCase):
    """Profiles store nothing but a username -- these lock that contract in,
    since it is the one thing about this feature that must never regress
    quietly under a future "just add one more field" change."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = os.environ.get("CRUCIBLE_HOME")
        os.environ["CRUCIBLE_HOME"] = self._tmp.name

    def tearDown(self):
        if self._home is None:
            del os.environ["CRUCIBLE_HOME"]
        else:
            os.environ["CRUCIBLE_HOME"] = self._home
        self._tmp.cleanup()

    def test_the_same_username_returns_the_same_profile(self):
        first = profiles.open_profile("Alice")
        second = profiles.open_profile("Alice")
        self.assertEqual(first.id, second.id)

    def test_usernames_are_matched_case_sensitively(self):
        lower = profiles.open_profile("alice")
        upper = profiles.open_profile("Alice")
        self.assertNotEqual(lower.id, upper.id)
        self.assertEqual({p.username for p in profiles.list_profiles()},
                         {"alice", "Alice"})

    def test_slug_collisions_do_not_merge_different_usernames(self):
        """Two usernames that sanitise to the same directory slug -- this
        matters doubly on Windows, where directory names are case-insensitive
        regardless of what the slug itself looks like."""
        a = profiles.open_profile("Alice!")
        b = profiles.open_profile("Alice?")
        self.assertNotEqual(a.id, b.id)

    def test_surrounding_and_repeated_whitespace_is_collapsed(self):
        a = profiles.open_profile("Alice")
        b = profiles.open_profile("  Alice  ")
        self.assertEqual(a.id, b.id)

    def test_blank_username_is_rejected(self):
        with self.assertRaises(ValueError):
            profiles.open_profile("   ")

    def test_opening_a_profile_makes_it_current(self):
        profiles.open_profile("Alice")
        bob = profiles.open_profile("Bob")
        self.assertEqual(profiles.current_profile().id, bob.id)

    def test_no_profiles_means_no_current_profile(self):
        self.assertIsNone(profiles.current_profile())

    def test_deleting_a_profile_removes_it_and_its_directory(self):
        alice = profiles.open_profile("Alice")
        profile_path = profiles.profile_dir(alice.id)
        self.assertTrue(profile_path.is_dir())
        profiles.delete_profile(alice.id)
        self.assertNotIn(alice.id, {p.id for p in profiles.list_profiles()})
        self.assertFalse(profile_path.exists())

    def test_deleting_the_current_profile_clears_current(self):
        alice = profiles.open_profile("Alice")
        profiles.delete_profile(alice.id)
        self.assertIsNone(profiles.current_profile())

    def test_on_disk_record_holds_only_the_documented_fields(self):
        """No email, no real name, no OS account -- just a username and the
        bookkeeping needed to find it again."""
        profiles.open_profile("Alice")
        stored = json.loads((Path(self._tmp.name) / "profiles.json").read_text())
        for entry in stored["profiles"]:
            self.assertLessEqual(
                set(entry.keys()),
                {"id", "username", "created", "last_opened", "last_problem"})

    def test_missing_index_file_is_not_an_error(self):
        self.assertEqual(profiles.list_profiles(), [])

    def test_corrupt_index_file_is_ignored(self):
        (Path(self._tmp.name) / "profiles.json").write_text("{ not json")
        self.assertEqual(profiles.list_profiles(), [])
        # and it is still possible to start fresh afterwards
        profiles.open_profile("Alice")
        self.assertEqual(len(profiles.list_profiles()), 1)

    def test_malformed_entries_are_dropped_not_raised(self):
        (Path(self._tmp.name) / "profiles.json").write_text(json.dumps(
            {"profiles": [{"id": "a"}, {"username": "b"}, "nope", 7,
                          {"id": "ok", "username": "Fine"}]}))
        self.assertEqual([p.username for p in profiles.list_profiles()], ["Fine"])

    def test_current_pointing_at_a_deleted_profile_is_ignored(self):
        (Path(self._tmp.name) / "profiles.json").write_text(json.dumps(
            {"current": "ghost", "profiles": [{"id": "a", "username": "A"}]}))
        self.assertIsNone(profiles.current_profile())


class TestProfileProgress(unittest.TestCase):
    """Whether *this* profile has solved a problem, tracked separately from
    whether the problem's own reference solution is healthy."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = os.environ.get("CRUCIBLE_HOME")
        os.environ["CRUCIBLE_HOME"] = self._tmp.name
        self.alice = profiles.open_profile("Alice")

    def tearDown(self):
        if self._home is None:
            del os.environ["CRUCIBLE_HOME"]
        else:
            os.environ["CRUCIBLE_HOME"] = self._home
        self._tmp.cleanup()

    def test_a_passing_attempt_is_recorded_as_solved(self):
        entry = profiles.record_attempt(self.alice.id, "c_sum_array",
                                        passed=True, summary="7/7 tests passed")
        self.assertTrue(entry["solved"])
        self.assertEqual(entry["attempts"], 1)
        self.assertTrue(entry["first_solved"])

    def test_a_failing_attempt_is_not_solved(self):
        entry = profiles.record_attempt(self.alice.id, "c_sum_array",
                                        passed=False, summary="3/7 tests passed")
        self.assertFalse(entry["solved"])

    def test_solved_stays_true_after_a_later_failure(self):
        profiles.record_attempt(self.alice.id, "c_sum_array",
                                passed=True, summary="7/7 tests passed")
        entry = profiles.record_attempt(self.alice.id, "c_sum_array",
                                        passed=False, summary="6/7 tests passed")
        self.assertTrue(entry["solved"])
        self.assertEqual(entry["attempts"], 2)

    def test_first_solved_does_not_move_on_a_second_pass(self):
        first = profiles.record_attempt(self.alice.id, "c_sum_array",
                                        passed=True, summary="ok")
        second = profiles.record_attempt(self.alice.id, "c_sum_array",
                                         passed=True, summary="ok again")
        self.assertEqual(first["first_solved"], second["first_solved"])

    def test_progress_survives_a_round_trip(self):
        profiles.record_attempt(self.alice.id, "c_sum_array",
                                passed=True, summary="7/7 tests passed")
        reloaded = profiles.load_progress(self.alice.id)
        self.assertTrue(reloaded["c_sum_array"]["solved"])

    def test_progress_is_isolated_between_profiles(self):
        bob = profiles.open_profile("Bob")
        profiles.record_attempt(self.alice.id, "c_sum_array",
                                passed=True, summary="7/7 tests passed")
        self.assertEqual(profiles.load_progress(bob.id), {})

    def test_missing_progress_file_is_not_an_error(self):
        self.assertEqual(profiles.load_progress(self.alice.id), {})

    def test_corrupt_progress_file_is_ignored_and_still_writable(self):
        (profiles.profile_dir(self.alice.id) / "progress.json").write_text("{ bad")
        self.assertEqual(profiles.load_progress(self.alice.id), {})
        entry = profiles.record_attempt(self.alice.id, "c_sum_array",
                                        passed=True, summary="ok")
        self.assertTrue(entry["solved"])


# ---------------------------------------------------------------------------
# the shipped problem library
# ---------------------------------------------------------------------------

class TestShippedProblems(unittest.TestCase):
    """The spec's headline requirement: every reference solution must pass
    every one of its own test cases before the problem is offered.

    The suite is built the way the app builds it -- randomised cases included
    -- so this covers the generators too. A generator that emits input the
    reference cannot handle fails here, and so does one whose input makes the
    reference give a different answer on the second run than it gave when the
    expected output was captured.
    """

    #: Not a round number, and not one of the shipped data sets, so a
    #: generator that only works on the seeds it was written against has
    #: nowhere to hide.
    SEED = 8317

    @classmethod
    def setUpClass(cls):
        cls.library = load_library(PROBLEMS_ROOT)
        cls.generation = {}
        for problem in cls.library.problems:
            suite = randomise.generate(problem, cls.SEED)
            randomise.apply(problem, suite)
            cls.generation[problem.id] = suite

    def test_library_loads_without_errors(self):
        self.assertEqual(self.library.errors, [])
        self.assertGreater(len(self.library.problems), 0)

    def test_every_generator_produces_a_full_data_set(self):
        for problem in self.library.problems:
            if not problem.randomised:
                continue
            with self.subTest(problem=problem.id):
                suite = self.generation[problem.id]
                if suite.toolchain_missing:
                    self.skipTest(f"no toolchain for {problem.language_id}")
                self.assertEqual(suite.error, "")
                self.assertEqual(len(suite.tests), problem.generator.count)

    def test_generated_cases_carry_a_captured_expected_output(self):
        for problem in self.library.problems:
            for test in problem.generated_tests:
                with self.subTest(problem=problem.id, case=test.name):
                    self.assertTrue(test.generated)
                    self.assertTrue(test.stdin)
                    # FizzBuzz with n = 0 would legitimately print nothing, but
                    # no generator here produces an input that empty.
                    self.assertTrue(test.expected_stdout)

    def test_every_problem_has_a_hidden_reference(self):
        for problem in self.library.problems:
            with self.subTest(problem=problem.id):
                self.assertTrue(problem.reference.source.strip())

    def test_every_problem_shows_its_tests(self):
        for problem in self.library.problems:
            with self.subTest(problem=problem.id):
                self.assertGreater(len(problem.visible_tests), 0,
                                   "test cases are meant to be visible")

    def test_reference_solutions_pass_their_own_suites(self):
        for problem in self.library.problems:
            with self.subTest(problem=problem.id):
                # Skip inside the subTest so one uninstalled toolchain does not
                # silently skip the problems that *can* be verified.
                if not problem.language.toolchain().available:
                    self.skipTest(f"no toolchain for {problem.language_id}")
                result = runner.verify_reference(problem)
                self.assertTrue(
                    result.all_passed,
                    f"{problem.title}: {result.summary()}\n"
                    + "\n".join(f"  {o.test.name}: expected "
                                f"{o.test.expected_stdout!r} got {o.actual!r}"
                                for o in result.failures()))


# ---------------------------------------------------------------------------
# hint and worked-solution guides
# ---------------------------------------------------------------------------

class TestGuideLookup(unittest.TestCase):
    """The naming convention is the only registration guides have, so it is
    worth pinning down on its own rather than only through the shipped set."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.problem = load_problem(write_problem(self.dir))

    def tearDown(self):
        self._tmp.cleanup()

    def test_path_is_derived_from_the_problem_filename(self):
        self.assertEqual(guides.guide_path(self.problem, guides.HINT),
                         self.dir / "demo.hint.html")
        self.assertEqual(guides.guide_path(self.problem, guides.SOLUTION),
                         self.dir / "demo.solution.html")

    def test_absent_guides_are_reported_not_invented(self):
        self.assertIsNone(guides.find(self.problem, guides.HINT))
        self.assertEqual(guides.find_all(self.problem), {})
        self.assertEqual(sorted(guides.missing(self.problem)),
                         sorted(guides.REQUIRED))

    def test_a_missing_diagram_is_not_a_gap(self):
        """Most problems have no diagram to draw, so `missing` must not nag
        about one -- otherwise --guides is noise and nobody reads it."""
        for kind in guides.REQUIRED:
            (self.dir / f"demo.{kind}.html").write_text("x", encoding="utf-8")
        self.assertEqual(guides.missing(self.problem), [])
        self.assertNotIn(guides.DIAGRAM, guides.find_all(self.problem))
        self.assertIn(guides.DIAGRAM, guides.KINDS)

    def test_a_guide_is_found_once_the_file_exists(self):
        (self.dir / "demo.hint.html").write_text("<h1>Demo</h1>",
                                                 encoding="utf-8")
        guide = guides.find(self.problem, guides.HINT)
        self.assertIsNotNone(guide)
        self.assertEqual(guide.kind, guides.HINT)
        self.assertEqual(guide.path, self.dir / "demo.hint.html")
        self.assertEqual(list(guides.find_all(self.problem)), [guides.HINT])
        self.assertEqual(guides.missing(self.problem), [guides.SOLUTION])

    def test_a_directory_of_the_right_name_is_not_a_guide(self):
        (self.dir / "demo.hint.html").mkdir()
        self.assertIsNone(guides.find(self.problem, guides.HINT))

    def test_a_problem_with_no_source_file_has_no_guides(self):
        self.problem.source_path = None
        self.assertIsNone(guides.guide_path(self.problem, guides.HINT))
        self.assertIsNone(guides.find(self.problem, guides.HINT))
        self.assertEqual(guides.find_all(self.problem), {})


class TestLocalisedGuideLookup(unittest.TestCase):
    """A translated guide is one more dotted qualifier on the same naming
    convention -- `{stem}.{kind}.{locale}.html` -- found the same way, and
    falling back to the English page when there is no translation yet."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.problem = load_problem(write_problem(self.dir))
        self._original_locale = i18n.get_locale()
        self.addCleanup(i18n.set_locale, self._original_locale)

    def tearDown(self):
        self._tmp.cleanup()

    def test_localised_guide_is_preferred_when_it_exists(self):
        (self.dir / "demo.hint.html").write_text("<h1>Demo</h1>", encoding="utf-8")
        (self.dir / "demo.hint.fr_FR.html").write_text("<h1>Démo</h1>", encoding="utf-8")
        i18n.set_locale("fr_FR")
        guide = guides.find(self.problem, guides.HINT)
        self.assertEqual(guide.path, self.dir / "demo.hint.fr_FR.html")

    def test_falls_back_to_english_when_not_translated(self):
        (self.dir / "demo.hint.html").write_text("<h1>Demo</h1>", encoding="utf-8")
        i18n.set_locale("fr_FR")
        guide = guides.find(self.problem, guides.HINT)
        self.assertEqual(guide.path, self.dir / "demo.hint.html")

    def test_english_page_is_used_under_the_default_locale_even_if_translated(self):
        (self.dir / "demo.hint.html").write_text("<h1>Demo</h1>", encoding="utf-8")
        (self.dir / "demo.hint.fr_FR.html").write_text("<h1>Démo</h1>", encoding="utf-8")
        guide = guides.find(self.problem, guides.HINT)
        self.assertEqual(guide.path, self.dir / "demo.hint.html")

    def test_guide_path_always_names_the_english_file(self):
        """`guide_path` backs '--guides' reporting and stays locale-agnostic
        -- `find` is the layer that adds translation preference."""
        (self.dir / "demo.hint.fr_FR.html").write_text("x", encoding="utf-8")
        i18n.set_locale("fr_FR")
        self.assertEqual(guides.guide_path(self.problem, guides.HINT),
                         self.dir / "demo.hint.html")


class TestShippedGuides(unittest.TestCase):
    """Every shipped problem must come with both pages, and the pages must be
    usable off the disk -- no missing stylesheet, no broken cross-link."""

    HREF = re.compile(r'href="([^"]+)"')

    @classmethod
    def setUpClass(cls):
        cls.library = load_library(PROBLEMS_ROOT)
        cls.pages = {}
        for problem in cls.library.problems:
            for kind, guide in guides.find_all(problem).items():
                cls.pages[(problem.id, kind)] = guide.path.read_text(
                    encoding="utf-8")

    def each_page(self):
        for problem in self.library.problems:
            for kind in guides.KINDS:
                page = self.pages.get((problem.id, kind))
                if page is not None:
                    yield problem, kind, page

    def test_every_problem_ships_both_guides(self):
        for problem in self.library.problems:
            with self.subTest(problem=problem.id):
                self.assertEqual(
                    guides.missing(problem), [],
                    f"{problem.title} is missing a guide -- "
                    f"see 'python -m crucible --guides'")

    def test_every_page_says_which_problem_it_is_about(self):
        for problem, kind, page in self.each_page():
            with self.subTest(problem=problem.id, kind=kind):
                self.assertIn(problem.title, page)
                self.assertIn(guides.KINDS[kind], page)

    def test_every_page_has_content_rather_than_a_stub(self):
        for problem, kind, page in self.each_page():
            with self.subTest(problem=problem.id, kind=kind):
                self.assertGreater(len(page), 1500)
                self.assertIn("<h2", page)

    def test_a_worked_solution_shows_code_and_a_hint_does_not_show_the_answer(self):
        for problem, kind, page in self.each_page():
            with self.subTest(problem=problem.id, kind=kind):
                if kind == guides.SOLUTION:
                    self.assertIn("<pre><code>", page)
                else:
                    # A hint may show a skeleton, and a diagram page shows the
                    # spec -- but neither may carry the finished function.
                    escaped = (problem.reference.source
                               .replace("&", "&amp;")
                               .replace("<", "&lt;")
                               .replace(">", "&gt;")
                               .strip())
                    self.assertNotIn(escaped, page)

    def test_the_hint_and_the_solution_link_to_each_other(self):
        for problem, kind, page in self.each_page():
            if kind not in guides.REQUIRED:
                continue
            other = guides.SOLUTION if kind == guides.HINT else guides.HINT
            target = guides.guide_path(problem, other)
            with self.subTest(problem=problem.id, kind=kind):
                self.assertIn(f'href="{target.name}"', page)

    def test_a_diagram_page_matches_the_statement_it_illustrates(self):
        """The Mermaid source lives twice -- in the statement, where the app
        can always show it, and in the diagram page, where a browser can draw
        it. Two copies drift; this is what stops them."""
        seen = 0
        for problem, kind, page in self.each_page():
            if kind != guides.DIAGRAM:
                continue
            seen += 1
            with self.subTest(problem=problem.id):
                blocks = re.findall(
                    r'<pre class="mermaid">(.*?)</pre>', page, re.DOTALL)
                self.assertEqual(len(blocks), 1,
                                 "expected exactly one Mermaid block")
                source = html.unescape(blocks[0]).strip()
                self.assertRegex(source, r"^(stateDiagram|sequenceDiagram|"
                                         r"classDiagram|flowchart|graph)")
                self.assertIn(source, problem.statement,
                              "the diagram page and the problem statement "
                              "have drifted apart")
        self.assertGreater(seen, 0, "no diagram pages found to check")

    def test_a_diagram_page_degrades_without_its_renderer(self):
        """Mermaid is fetched from a CDN, so the offline reader gets the
        <pre> as written. It has to say so rather than look broken."""
        for problem, kind, page in self.each_page():
            if kind != guides.DIAGRAM:
                continue
            with self.subTest(problem=problem.id):
                self.assertIn("mermaid-note", page)
                self.assertIn("window.mermaid", page,
                              "the init must be guarded so a failed CDN "
                              "fetch does not throw")

    def test_every_local_link_resolves(self):
        for problem, kind, page in self.each_page():
            directory = guides.guide_path(problem, kind).parent
            for href in self.HREF.findall(page):
                if "://" in href or href.startswith("#"):
                    continue
                with self.subTest(problem=problem.id, kind=kind, href=href):
                    self.assertTrue((directory / href).is_file(),
                                    f"{href} does not resolve from {directory}")

    def test_the_shared_stylesheet_is_linked_and_present(self):
        for problem, kind, page in self.each_page():
            with self.subTest(problem=problem.id, kind=kind):
                self.assertIn('rel="stylesheet"', page)


class TestShippedCSharpTranslations(unittest.TestCase):
    """The French translation covers the C# problems specifically (and the
    app chrome, via `fr_FR.json` -- see `TestI18n`), not every language --
    this pins that down the same way `TestShippedGuides` pins down the
    English guides, scoped to `problems/csharp` and loaded under `fr_FR`."""

    @classmethod
    def setUpClass(cls):
        cls._original_locale = i18n.get_locale()
        cls.english = load_library(PROBLEMS_ROOT).by_language("csharp")
        i18n.set_locale("fr_FR")
        cls.french = load_library(PROBLEMS_ROOT).by_language("csharp")

    @classmethod
    def tearDownClass(cls):
        i18n.set_locale(cls._original_locale)

    def test_every_csharp_problem_was_found_in_both_passes(self):
        self.assertGreater(len(self.english), 0)
        self.assertEqual({p.id for p in self.english}, {p.id for p in self.french})

    def test_every_csharp_title_and_statement_is_actually_translated(self):
        """Not just present -- different from the English source. A file
        that exists but was never filled in would pass a bare
        `assertTrue(problem.title)` check without anyone noticing."""
        by_id = {p.id: p for p in self.english}
        for problem in self.french:
            with self.subTest(problem=problem.id):
                english = by_id[problem.id]
                self.assertNotEqual(problem.title, english.title)
                self.assertNotEqual(problem.statement, english.statement)

    def test_every_csharp_test_case_name_is_translated(self):
        by_id = {p.id: p for p in self.english}
        for problem in self.french:
            with self.subTest(problem=problem.id):
                english = by_id[problem.id]
                for fr_case, en_case in zip(problem.fixed_tests, english.fixed_tests):
                    self.assertNotEqual(fr_case.name, en_case.name)
                    # data, not prose -- translation must never touch these
                    self.assertEqual(fr_case.stdin, en_case.stdin)
                    self.assertEqual(fr_case.expected_stdout, en_case.expected_stdout)

    def test_every_csharp_problem_has_translated_guides(self):
        for problem in self.french:
            with self.subTest(problem=problem.id):
                self.assertEqual(guides.missing(problem), [])
                for kind in guides.REQUIRED:
                    guide = guides.find(problem, kind)
                    self.assertEqual(guide.path.suffixes[-3:],
                                     [f".{kind}", ".fr_FR", ".html"],
                                     f"{guide.path.name} is not a translated {kind} page")

    def test_translated_guide_pages_name_the_translated_title(self):
        for problem in self.french:
            for kind in guides.REQUIRED:
                with self.subTest(problem=problem.id, kind=kind):
                    page = guides.find(problem, kind).path.read_text(encoding="utf-8")
                    self.assertIn(problem.title, page)

    def test_translated_guide_pages_cross_link_each_other(self):
        for problem in self.french:
            with self.subTest(problem=problem.id):
                hint_path = guides.find(problem, guides.HINT).path
                solution_path = guides.find(problem, guides.SOLUTION).path
                hint_page = hint_path.read_text(encoding="utf-8")
                solution_page = solution_path.read_text(encoding="utf-8")
                self.assertIn(solution_path.name, hint_page)
                self.assertIn(hint_path.name, solution_page)


# ---------------------------------------------------------------------------
# running submissions
# ---------------------------------------------------------------------------

class TestRunSubmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        library = load_library(PROBLEMS_ROOT)
        cls.problem = library.get("py_run_length_encode")
        if cls.problem is None:
            raise unittest.SkipTest("py_run_length_encode not present")

    def test_correct_solution_passes_everything(self):
        result = runner.run_submission(self.problem, self.problem.reference.source)
        self.assertTrue(result.build.ok)
        self.assertTrue(result.all_passed)

    def test_wrong_solution_fails_everything(self):
        result = runner.run_submission(
            self.problem, "def encode(text):\n    return 'nope'\n")
        self.assertTrue(result.build.ok)
        self.assertEqual(result.passed, 0)
        self.assertTrue(all(o.status == runner.FAIL for o in result.outcomes))

    def test_syntax_error_is_a_build_failure_not_a_test_failure(self):
        result = runner.run_submission(self.problem, "def encode(text)\n  pass\n")
        self.assertFalse(result.build.ok)
        self.assertEqual(result.outcomes, [])
        self.assertIn("solution.py:1", result.build.output)

    def test_exception_at_runtime_is_an_error_not_a_fail(self):
        result = runner.run_submission(
            self.problem, "def encode(text):\n    raise ValueError('boom')\n")
        self.assertTrue(result.build.ok)
        self.assertTrue(all(o.status == runner.ERROR for o in result.outcomes))
        self.assertIn("ValueError", result.outcomes[0].stderr)

    def test_infinite_loop_times_out_per_case(self):
        slow = textwrap.dedent("""\
            def encode(text):
                while True:
                    pass
            """)
        problem = self.problem
        object.__setattr__(problem, "timeout_seconds", 1.0)
        try:
            result = runner.run_submission(problem, slow)
            self.assertTrue(all(o.status == runner.TIMEOUT for o in result.outcomes))
        finally:
            object.__setattr__(problem, "timeout_seconds", 5.0)

    def test_progress_callback_fires_once_per_test(self):
        seen = []
        runner.run_submission(self.problem, self.problem.reference.source,
                              progress=lambda o, i, n: seen.append(i))
        self.assertEqual(seen, list(range(1, len(self.problem.tests) + 1)))


# ---------------------------------------------------------------------------
# language layer
# ---------------------------------------------------------------------------

class TestLanguageRegistry(unittest.TestCase):
    def test_c_and_python_are_registered(self):
        self.assertIn("c", languages.known_ids())
        self.assertIn("python", languages.known_ids())

    def test_an_assembly_target_is_registered_under_its_own_id(self):
        """Each assembly target is a language in its own right rather
        than a variant of a shared "asm" -- see `asm_lang`."""
        self.assertIn("asm_x64_masm", languages.known_ids())

    def test_unknown_language_raises_with_a_helpful_message(self):
        with self.assertRaises(KeyError) as ctx:
            languages.get("cobol")
        self.assertIn("Registered", str(ctx.exception))

    def test_python_toolchain_is_always_available(self):
        self.assertTrue(languages.get("python").toolchain().available)

    def test_toolchain_result_is_cached(self):
        language = languages.get("python")
        self.assertIs(language.toolchain(), language.toolchain())


class TestCDiagnostics(unittest.TestCase):
    """Testable without a compiler installed."""

    def setUp(self):
        self.c = CLanguage()

    def test_temp_paths_are_stripped_from_diagnostics(self):
        import os
        raw = f"C:{os.sep}long{os.sep}temp{os.sep}crucible_x{os.sep}solution.c:4:9: error: bad"
        self.assertEqual(self.c.clean_diagnostics(raw), "solution.c:4:9: error: bad")

    @unittest.skipIf(sys.platform == "win32", "POSIX signal encoding")
    def test_posix_segfault_is_described_in_english(self):
        self.assertIn("segmentation fault", self.c.describe_exit(-11))

    @unittest.skipUnless(sys.platform == "win32", "Windows NTSTATUS encoding")
    def test_windows_access_violation_is_described(self):
        self.assertIn("access violation", self.c.describe_exit(0xC0000005))

    @unittest.skipUnless(sys.platform == "win32", "Windows NTSTATUS encoding")
    def test_windows_clean_exit_is_not_called_a_crash(self):
        self.assertNotIn("crash", self.c.describe_exit(1))

    def test_msvc_filename_echo_is_stripped(self):
        self.c._kind = "msvc"
        noisy = "solution.c\nharness.c\nsolution.c(5): error C2143: bad\nGenerating Code..."
        self.assertEqual(self.c._strip_msvc_noise(noisy),
                         "solution.c(5): error C2143: bad")

    def test_missing_compiler_reports_a_remedy(self):
        status = self.c.toolchain()
        if status.available:
            self.skipTest("a C compiler is installed")
        self.assertTrue(status.remedy)
        self.assertIn("compiler", status.remedy.lower())


class TestCSharpDiagnostics(unittest.TestCase):
    """Testable without the .NET SDK installed."""

    def setUp(self):
        self.cs = CSharpLanguage()

    def test_temp_paths_are_stripped_from_diagnostics(self):
        import os
        raw = (f"C:{os.sep}long{os.sep}temp{os.sep}crucible_x{os.sep}solution.cs"
               f"(4,9): error CS1525: bad [C:{os.sep}long{os.sep}temp"
               f"{os.sep}crucible_x{os.sep}crucible.csproj]")
        self.assertEqual(self.cs.clean_diagnostics(raw),
                         "solution.cs(4,9): error CS1525: bad")

    def test_msbuild_reprint_and_tally_lines_are_stripped(self):
        noisy = ("solution.cs(3,1): error CS1525: bad [x.csproj]\n"
                 "\n"
                 "Build FAILED.\n"
                 "\n"
                 "solution.cs(3,1): error CS1525: bad [x.csproj]\n"
                 "    1 Warning(s)\n"
                 "    1 Error(s)\n"
                 "\n"
                 "Time Elapsed 00:00:01.50\n")
        cleaned = self.cs._strip_msbuild_noise(noisy)
        self.assertEqual(cleaned, "solution.cs(3,1): error CS1525: bad [x.csproj]")

    @unittest.skipUnless(sys.platform == "win32", "Windows-only exit code")
    def test_unhandled_exception_is_described(self):
        self.assertIn("unhandled exception", self.cs.describe_exit(0xE0434352))

    def test_clean_exit_is_not_called_a_crash(self):
        self.assertNotIn("crash", self.cs.describe_exit(0))
        self.assertIn("0", self.cs.describe_exit(0))

    def test_missing_sdk_reports_a_remedy(self):
        status = self.cs.toolchain()
        if status.available:
            self.skipTest(".NET SDK is installed")
        self.assertTrue(status.remedy)
        self.assertIn("sdk", status.remedy.lower())


class TestAsmX64MasmDiagnostics(unittest.TestCase):
    """Testable without an assembler installed."""

    def setUp(self):
        self.asm = AsmX64MasmLanguage()

    def test_temp_paths_are_stripped_from_diagnostics(self):
        raw = (f"C:{os.sep}long{os.sep}temp{os.sep}crucible_x{os.sep}"
               f"solution.asm(4) : error A2006: bad")
        self.assertEqual(self.asm.clean_diagnostics(raw),
                         "solution.asm(4) : error A2006: bad")

    def test_tool_filename_echo_is_stripped(self):
        noisy = (" Assembling: solution.asm\n"
                 "harness.c\n"
                 "solution.asm(5) : error A2207: bad\n"
                 "Generating Code...")
        self.assertEqual(self.asm._strip_tool_noise(noisy),
                         "solution.asm(5) : error A2207: bad")

    @unittest.skipUnless(sys.platform == "win32", "Windows NTSTATUS encoding")
    def test_access_violation_is_described(self):
        self.assertIn("access violation", self.asm.describe_exit(0xC0000005))

    @unittest.skipUnless(sys.platform == "win32", "Windows NTSTATUS encoding")
    def test_clean_exit_is_not_called_a_crash(self):
        self.assertNotIn("crash", self.asm.describe_exit(1))

    def test_a_non_windows_host_is_reported_as_unavailable(self):
        """The MASM target is Windows-only, and has to say so rather than
        claim a toolchain it cannot have."""
        with mock.patch.object(native_compiler, "IS_WINDOWS", False):
            status = self.asm.detect_toolchain()
        self.assertFalse(status.available)
        self.assertIn("Windows", status.summary)

    def test_a_non_x86_64_host_is_reported_as_unavailable(self):
        """The check that keeps `--verify` honest. An ARM machine with Visual
        Studio installed can find ml64.exe on disk and cannot use it: without
        this, the language would claim to be available and every problem in it
        would then fail in a way that looks like the candidate's fault rather
        than the machine's."""
        with mock.patch.object(native_compiler, "IS_WINDOWS", True), \
                mock.patch.object(asm_lang.platform, "machine",
                                  return_value="ARM64"):
            status = self.asm.detect_toolchain()
        self.assertFalse(status.available)
        self.assertIn("ARM64", status.detail)

    def test_missing_assembler_reports_a_remedy(self):
        status = self.asm.toolchain()
        if status.available:
            self.skipTest("an assembler is installed")
        if not nc_available_elsewhere(status):
            self.skipTest("not applicable on this host")
        self.assertTrue(status.remedy)
        self.assertIn("ml64", status.remedy.lower())


def nc_available_elsewhere(status) -> bool:
    """True when the toolchain is missing for a reason a remedy could fix.

    "Windows only" and "wrong architecture" are facts about the machine, not
    something an install would change, so those two report no remedy on
    purpose and this test has nothing to check.
    """
    return "Windows only" not in status.summary and "x86-64 machine" not in status.summary


class TestVhdlDiagnostics(unittest.TestCase):
    """Testable without GHDL installed."""

    def setUp(self):
        self.vhdl = VhdlLanguage()

    def test_temp_paths_are_stripped_from_diagnostics(self):
        raw = (f"C:{os.sep}long{os.sep}temp{os.sep}crucible_x{os.sep}"
               f"solution.vhd:12:5: syntax error")
        self.assertEqual(self.vhdl.clean_diagnostics(raw),
                         "solution.vhd:12:5: syntax error")

    def test_harness_paths_are_also_stripped(self):
        raw = (f"C:{os.sep}long{os.sep}temp{os.sep}crucible_x{os.sep}"
               f"harness.vhd:9:3: no declaration for \"solution\"")
        self.assertEqual(self.vhdl.clean_diagnostics(raw),
                         "harness.vhd:9:3: no declaration for \"solution\"")

    def test_clean_exit_reports_nothing(self):
        self.assertEqual(self.vhdl.describe_exit(0), "")
        self.assertEqual(self.vhdl.describe_exit(None), "")

    def test_nonzero_exit_points_at_stderr(self):
        message = self.vhdl.describe_exit(1)
        self.assertIn("1", message)

    def test_missing_ghdl_reports_unavailable_with_a_remedy(self):
        with mock.patch.object(native_compiler, "which", return_value=None):
            status = self.vhdl.detect_toolchain()
        self.assertFalse(status.available)
        self.assertIn("GHDL", status.summary)
        self.assertTrue(status.remedy)
        self.assertIn("ghdl", status.remedy.lower())

    def test_missing_ghdl_carries_a_download_link_on_windows(self):
        """The compiler status page's Download button needs somewhere to
        send the browser -- see ToolchainStatus.download_url."""
        with mock.patch.object(native_compiler, "which", return_value=None), \
                mock.patch.object(native_compiler, "IS_WINDOWS", True):
            status = self.vhdl.detect_toolchain()
        self.assertEqual(status.download_url,
                         "https://github.com/ghdl/ghdl/releases")

    def test_missing_ghdl_has_no_download_link_off_windows(self):
        """POSIX's remedy is apt/dnf/brew commands, which a browser tab
        cannot run -- so there is deliberately nothing for Download to open."""
        with mock.patch.object(native_compiler, "which", return_value=None), \
                mock.patch.object(native_compiler, "IS_WINDOWS", False):
            status = self.vhdl.detect_toolchain()
        self.assertEqual(status.download_url, "")

    def test_found_ghdl_reports_available(self):
        with mock.patch.object(native_compiler, "which", return_value="/usr/bin/ghdl"), \
                mock.patch.object(native_compiler, "probe_version", return_value="GHDL 4.1.0"):
            status = self.vhdl.detect_toolchain()
        self.assertTrue(status.available)
        self.assertIn("GHDL 4.1.0", status.summary)

    def test_exec_command_runs_the_fixed_harness_unit(self):
        with mock.patch.object(native_compiler, "which", return_value="ghdl"):
            command = self.vhdl.exec_command(Path("."), None)
        self.assertEqual(command, ["ghdl", "-r", "--std=08", "harness"])

    def test_registered_under_its_own_id(self):
        self.assertIn("vhdl", languages.known_ids())
        self.assertIs(languages.get("vhdl").__class__, VhdlLanguage)


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

class TestI18n(unittest.TestCase):
    """`crucible.i18n`: lookup, fallback, formatting -- and that the shipped
    `en_GB` locale is actually complete and well formed, since that file is
    hand-edited prose, not generated."""

    def setUp(self):
        # Every test restores the locale it found active, so a test that
        # switches locales (or fails while one is switched) cannot leak into
        # whichever test happens to run next.
        self._original_locale = i18n.get_locale()
        self.addCleanup(i18n.set_locale, self._original_locale)

    def test_default_locale_is_en_gb(self):
        self.assertEqual(i18n.DEFAULT_LOCALE, "en_GB")

    def test_en_gb_is_available(self):
        self.assertIn("en_GB", i18n.available_locales())

    def test_default_locale_is_listed_first(self):
        self.assertEqual(i18n.available_locales()[0], i18n.DEFAULT_LOCALE)

    def test_locale_display_name_is_the_locale_s_own_name_for_itself(self):
        """A language picker lists 'Français', never 'French' -- each locale
        names itself, regardless of which locale is currently active."""
        self.assertEqual(i18n.locale_display_name("en_GB"), "English")
        self.assertEqual(i18n.locale_display_name("fr_FR"), "Français")

    def test_locale_display_name_does_not_read_through_the_active_locale(self):
        # fr_FR's own name must come back the same whether English or French
        # is the currently active locale -- this is exactly what t() would
        # get wrong (falling back to en_GB's text while fr_FR is active).
        i18n.set_locale("fr_FR")
        self.assertEqual(i18n.locale_display_name("fr_FR"), "Français")
        self.assertEqual(i18n.locale_display_name("en_GB"), "English")

    def test_locale_display_name_falls_back_to_the_code_itself(self):
        self.assertEqual(i18n.locale_display_name("xx_XX"), "xx_XX")

    def test_plain_lookup(self):
        self.assertEqual(i18n.t("app.menu.file.title"), "File")

    def test_nested_lookup(self):
        self.assertEqual(i18n.t("app.menu.edit.title"), "Edit")

    def test_formatting_interpolates_kwargs(self):
        self.assertEqual(
            i18n.t("app.tree.group_row", name="Easy", count=3), "Easy  (3)")

    def test_missing_key_raises(self):
        with self.assertRaises(i18n.TranslationError):
            i18n.t("this.key.does.not.exist")

    def test_key_resolving_to_a_dict_raises(self):
        # "app.menu.file" is a real key, but it names a subtree, not a string.
        with self.assertRaises(i18n.TranslationError):
            i18n.t("app.menu.file")

    def test_unfilled_placeholder_raises_rather_than_showing_a_template(self):
        with self.assertRaises(i18n.TranslationError):
            i18n.t("app.tree.group_row", name="Easy")  # missing 'count'

    def test_set_locale_rejects_unknown_code(self):
        with self.assertRaises(i18n.TranslationError):
            i18n.set_locale("xx_XX")
        # A rejected switch must not have changed the active locale.
        self.assertEqual(i18n.get_locale(), self._original_locale)

    def test_set_locale_round_trips(self):
        i18n.set_locale("en_GB")
        self.assertEqual(i18n.get_locale(), "en_GB")

    def test_every_difficulty_has_a_display_label(self):
        from crucible.problem import DIFFICULTIES
        for difficulty in DIFFICULTIES:
            label = i18n.t(f"app.difficulty.{difficulty}")
            self.assertTrue(label)

    def test_en_gb_has_no_empty_or_non_string_leaves(self):
        """Every leaf in the locale file is non-empty text. Catches a stray
        empty template or a value that quietly became a number/list/null
        during an edit -- `t()` would raise on the latter anyway, but a
        forgotten `""` left behind by a find-and-replace passes that check
        and would otherwise only be noticed by eye."""
        data = i18n._load("en_GB")  # noqa: SLF001 -- whole-file structural check

        def walk(node, path):
            if isinstance(node, dict):
                for key, child in node.items():
                    walk(child, f"{path}.{key}")
            else:
                self.assertIsInstance(node, str, f"{path} is not a string")
                self.assertTrue(node, f"{path} is an empty string")

        for top_key, value in data.items():
            walk(value, top_key)

    def test_locale_file_is_valid_json(self):
        path = i18n.LOCALES_DIR / "en_GB.json"
        json.loads(path.read_text(encoding="utf-8"))  # raises on malformed JSON

    def test_fr_fr_is_available(self):
        self.assertIn("fr_FR", i18n.available_locales())

    def test_fr_fr_locale_file_is_valid_json(self):
        path = i18n.LOCALES_DIR / "fr_FR.json"
        json.loads(path.read_text(encoding="utf-8"))  # raises on malformed JSON

    def test_fr_fr_has_no_empty_or_non_string_leaves(self):
        data = i18n._load("fr_FR")  # noqa: SLF001 -- whole-file structural check

        def walk(node, path):
            if isinstance(node, dict):
                for key, child in node.items():
                    walk(child, f"{path}.{key}")
            else:
                self.assertIsInstance(node, str, f"{path} is not a string")
                self.assertTrue(node, f"{path} is an empty string")

        for top_key, value in data.items():
            walk(value, top_key)

    def test_fr_fr_has_exactly_the_same_keys_as_en_gb(self):
        """`t()` falls back key-by-key, so `fr_FR` is allowed to be
        incomplete without breaking anything -- but it ships complete today,
        and a key silently dropped (or added somewhere it doesn't belong)
        during an edit is worth catching rather than only noticing by eye."""

        def leaf_paths(node, prefix=""):
            if isinstance(node, dict):
                for key, child in node.items():
                    yield from leaf_paths(child, f"{prefix}.{key}" if prefix else key)
            else:
                yield prefix

        en_keys = set(leaf_paths(i18n._load("en_GB")))  # noqa: SLF001
        fr_keys = set(leaf_paths(i18n._load("fr_FR")))  # noqa: SLF001
        self.assertEqual(en_keys, fr_keys,
                         f"only in en_GB: {sorted(en_keys - fr_keys)}\n"
                         f"only in fr_FR: {sorted(fr_keys - en_keys)}")

    def test_fr_fr_templates_use_the_same_placeholders_as_en_gb(self):
        """A translated template with a renamed or dropped `{placeholder}`
        would raise `TranslationError` the first time the app actually called
        `t()` for it under `fr_FR` -- with a real keyword argument, since a
        placeholder can appear anywhere in the template. Checked structurally
        here instead of by exercising every call site under every locale."""
        field_re = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^{}]*)?\}")

        def leaves(node, prefix=""):
            if isinstance(node, dict):
                for key, child in node.items():
                    yield from leaves(child, f"{prefix}.{key}" if prefix else key)
            else:
                yield prefix, node

        en_leaves = dict(leaves(i18n._load("en_GB")))  # noqa: SLF001
        fr_leaves = dict(leaves(i18n._load("fr_FR")))  # noqa: SLF001
        mismatches = []
        for key, en_value in en_leaves.items():
            fr_value = fr_leaves.get(key)
            if fr_value is None:
                continue  # covered by test_fr_fr_has_exactly_the_same_keys_as_en_gb
            en_fields = set(field_re.findall(en_value))
            fr_fields = set(field_re.findall(fr_value))
            if en_fields != fr_fields:
                mismatches.append(f"{key}: en={sorted(en_fields)} fr={sorted(fr_fields)}")
        self.assertEqual(mismatches, [], "\n".join(mismatches))

    def test_every_static_t_call_site_resolves(self):
        """Walks every `t("...")` call in the package whose key is a plain
        string literal (not built at runtime, like `f"guides.kind.{kind}"`)
        and checks the key actually resolves in `en_GB`.

        This is the one check in the suite that would have caught a typo'd
        key at the point it was written rather than the first time a candidate
        happened to click the one menu entry that used it -- the source of
        truth here is the call sites themselves, not a hand-maintained list of
        keys to check.
        """
        import ast

        package_root = Path(i18n.__file__).resolve().parent
        missing = []
        checked = 0
        for path in package_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                func = node.func
                name = (func.id if isinstance(func, ast.Name)
                       else func.attr if isinstance(func, ast.Attribute) else None)
                if name != "t":
                    continue
                key_arg = node.args[0]
                if not (isinstance(key_arg, ast.Constant)
                        and isinstance(key_arg.value, str)):
                    continue  # a dynamically built key -- nothing static to check
                checked += 1
                if i18n._lookup("en_GB", key_arg.value) is i18n._MISSING:  # noqa: SLF001
                    missing.append(f"{path.relative_to(package_root.parent)}:"
                                   f"{node.lineno} -> {key_arg.value!r}")

        self.assertGreater(checked, 0, "the scan itself found no t() call sites")
        self.assertEqual(missing, [], "key(s) with no entry in en_GB.json:\n"
                                      + "\n".join(missing))


# ---------------------------------------------------------------------------
# GUI locale bootstrap (crucible.__main__._apply_saved_locale)
# ---------------------------------------------------------------------------

class TestApplySavedLocale(unittest.TestCase):
    """The Language menu (crucible.ui.app._set_locale) only ever saves a
    choice to settings.json -- crucible.__main__._apply_saved_locale is what
    turns that into the active locale, once, before anything is built from a
    t(...) call. `CRUCIBLE_LOCALE` is the documented explicit override and
    has to keep winning over a saved preference sitting on the machine."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._home = os.environ.get("CRUCIBLE_HOME")
        os.environ["CRUCIBLE_HOME"] = self._tmp.name
        self._env_locale = os.environ.pop("CRUCIBLE_LOCALE", None)
        self._original_locale = i18n.get_locale()
        self.addCleanup(i18n.set_locale, self._original_locale)

    def tearDown(self):
        if self._home is None:
            del os.environ["CRUCIBLE_HOME"]
        else:
            os.environ["CRUCIBLE_HOME"] = self._home
        if self._env_locale is not None:
            os.environ["CRUCIBLE_LOCALE"] = self._env_locale
        elif "CRUCIBLE_LOCALE" in os.environ:
            del os.environ["CRUCIBLE_LOCALE"]
        self._tmp.cleanup()

    def test_applies_the_saved_locale(self):
        workspace.save_settings({"locale": "fr_FR"})
        i18n.set_locale("en_GB")
        crucible_main._apply_saved_locale()
        self.assertEqual(i18n.get_locale(), "fr_FR")

    def test_env_var_overrides_the_saved_locale(self):
        workspace.save_settings({"locale": "fr_FR"})
        os.environ["CRUCIBLE_LOCALE"] = "en_GB"
        i18n.set_locale("en_GB")
        crucible_main._apply_saved_locale()
        self.assertEqual(i18n.get_locale(), "en_GB")  # the saved fr_FR never applied

    def test_an_unknown_saved_locale_is_ignored_not_raised(self):
        workspace.save_settings({"locale": "xx_XX"})
        i18n.set_locale("en_GB")
        crucible_main._apply_saved_locale()  # must not raise
        self.assertEqual(i18n.get_locale(), "en_GB")

    def test_no_settings_file_leaves_the_default_locale(self):
        crucible_main._apply_saved_locale()
        self.assertEqual(i18n.get_locale(), "en_GB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
