"""Regression tests.

    python -m unittest discover -s tests -v

Everything here runs without a C compiler: the language layer is exercised
through Python, and the C-specific logic that can be tested without invoking a
compiler (diagnostic cleanup, exit-code description) is tested directly.
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crucible import languages, runner
from crucible.languages.c_lang import CLanguage
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
# the shipped problem library
# ---------------------------------------------------------------------------

class TestShippedProblems(unittest.TestCase):
    """The spec's headline requirement: every reference solution must pass
    every one of its own test cases before the problem is offered."""

    @classmethod
    def setUpClass(cls):
        cls.library = load_library(PROBLEMS_ROOT)

    def test_library_loads_without_errors(self):
        self.assertEqual(self.library.errors, [])
        self.assertGreater(len(self.library.problems), 0)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
