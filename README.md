# Crucible

A small Tkinter practice harness. Pick a problem, read the test cases, write
your code, press **Go**, and see which cases pass.

Built around one rule: **the test cases are always visible, the reference
solution never is.** Every problem's suite is proved satisfiable by running the
hidden reference against it *before* the problem is offered to anyone.

```sh
python -m crucible
```

---

## Contents

- [Quick start](#quick-start)
- [Installing a C compiler](#installing-a-c-compiler)
- [How a submission is run](#how-a-submission-is-run)
- [The reference-solution gate](#the-reference-solution-gate)
- [Writing a problem](#writing-a-problem)
- [Adding a language](#adding-a-language)
- [Command line](#command-line)
- [Tests](#tests)
- [Layout](#layout)
- [Limitations](#limitations)

---

## Quick start

Requires Python 3.10+ with Tkinter (bundled on Windows and macOS; on Debian or
Ubuntu, `sudo apt install python3-tk`). Nothing else — no third-party packages.

```sh
python -m crucible              # open the GUI
python -m crucible --toolchains # which compilers were found
python -m crucible --list       # what problems loaded
python -m crucible --verify     # prove every reference solution passes
```

On Windows, **`Crucible.cmd`** opens the GUI on a double-click.

The window is four panes:

```text
┌───────────┬────────────────────────────────────────────────┐
│ PROBLEMS  │  THE PROBLEM      statement, examples, hints   │
│           ├────────────────────────────────────────────────┤
│  C        │  YOUR SOLUTION    editor, line numbers,        │
│   easy    │                   syntax highlighting          │
│   medium  ├────────────────────────────────────────────────┤
│  Python   │  ✓ suite verified — reference passes 9/9       │
│           │  ┌──────────────────┬───────────────────────┐  │
│           │  │ PASS  empty array│ INPUT     0           │  │
│           │  │ FAIL  last elem  │ EXPECTED  6           │  │
│           │  │ PASS  not found  │ YOUR OUT  -1          │  │
│           │  └──────────────────┴───────────────────────┘  │
└───────────┴────────────────────────────────────────────────┘
```

Keys: **F5** or **Ctrl+Enter** runs the suite. **Ctrl+S** saves a draft.
**Tab** / **Shift+Tab** indent and dedent the selection.

Your work is autosaved per problem to `~/.crucible/drafts/`, so closing the
window mid-problem loses nothing. *File → Reset to starter code* discards it.

## Installing a C compiler

The app searches `PATH` and the usual install locations for `gcc`, `clang`,
`cc` and `cl.exe`. If none is found, C problems still open and their test cases
still display — only running is unavailable, and the banner says so rather than
pretending the problem is broken.

Any one of these works:

| Option | How |
| --- | --- |
| **w64devkit** | Portable zip, no installer. Unzip to `C:\w64devkit` — that path is auto-detected, so no `PATH` edit is needed. |
| **MSYS2** | `pacman -S mingw-w64-ucrt-x86_64-gcc` |
| **Visual Studio** | Visual Studio Installer → Modify → tick *Desktop development with C++*. Detected automatically via `vswhere`; the app runs `vcvars64.bat` itself to pick up `INCLUDE`/`LIB`, so no developer prompt is required. |
| **Linux** | `sudo apt install build-essential` / `sudo dnf install gcc` |
| **macOS** | `xcode-select --install` |

Then *Tools → Re-check compilers*. No restart, and no developer command prompt
— the app captures the MSVC environment itself.

Under MSVC the build adds `/D_CRT_SECURE_NO_WARNINGS`, and `cl`'s filename echo
and `Generating Code...` are filtered out. Both exist so that a correct
submission produces genuinely empty build output, rather than warnings about
`scanf` that the candidate did not cause and cannot fix.

## How a submission is run

Your code and the problem's harness are compiled as **separate translation
units** and linked:

```text
solution.c   exactly what you typed, byte for byte
harness.c    problem-supplied main(); declares the prototype it needs
             ↓
          prog.exe
```

This matters for two reasons:

- **Line numbers are real.** `solution.c:12: error:` is line 12 in the editor.
  Nothing is prepended to your code, so there is no offset to mentally correct.
- **The harness is out of reach.** You cannot accidentally redefine `main` or
  shadow a helper the harness relies on.

Each test case then runs as **its own process**, fed the case's `stdin`:

- a segfault on case 3 leaves cases 4..n perfectly runnable
- an infinite loop is timed out on its own, not taken out of the whole suite
- a crash is reported as a crash, with the signal or NTSTATUS translated into
  English — `SIGSEGV (segmentation fault)`, `access violation (bad pointer /
  buffer overrun)` — rather than as a bare non-zero exit code

Output is compared after normalising line endings, trailing whitespace on each
line, and trailing blank lines. Leading whitespace and interior blank lines are
significant, because for most of these problems the exact shape of the output
*is* the exercise. On a mismatch you get a one-line hint — `output differs only
in letter case`, `expected 5 line(s), got 4`, `first difference on line 2`.

## The reference-solution gate

Every problem ships with a known-good solution that you never see. Before a
problem is offered, that solution is compiled and run against the full suite
through **the exact same pipeline** a candidate's code goes through — same
compiler flags, same harness, same per-case process, same comparison.

That equivalence is the point. "The reference passes" is then a claim about the
test suite, not about a separate and friendlier code path.

The result drives the UI:

| State | What you see |
| --- | --- |
| Reference passes all cases | `✓ Test suite verified — the reference solution passes all 9 cases`, and a `✓` beside the problem |
| Reference fails, or does not build | The problem is **disabled**: its own answer does not satisfy its tests, so it is broken and would waste your time. A *Run anyway* button overrides this for whoever is fixing it. |
| No compiler installed | Neither of the above — the problem is fine, the machine is not set up. Says exactly that. |

Verification runs in the background on a worker thread as problems load, so the
window never blocks. `--verify` does the same thing without a GUI and exits
non-zero if anything is broken, which makes it a usable CI check:

```console
$ python -m crucible --verify
  OK    Binary Search  (9 tests)
  BROKEN Two Sum  -- 6/7 tests passed
           FAIL     pair further in  first difference on line 1
             expected: '2 1'
             actual:   '1 2\n'
```

That example is real: it is the gate catching a test case whose expected output
had the indices the wrong way round.

## Writing a problem

One JSON file under `problems/`. Subdirectories are searched recursively and
carry no meaning — group them however you like.

```jsonc
{
  "id": "c_sum_array",           // unique; defaults to the filename
  "title": "Sum of an Array",
  "language": "c",               // must be a registered language id
  "difficulty": "easy",          // easy | medium | hard
  "topics": ["arrays", "pointers"],
  "timeout_seconds": 5,          // per test case

  "statement": "...",            // lightweight markdown, see below

  "starter_code": "...",         // what the editor opens with
  "harness": "...",              // supplies main(); declares the prototype

  "reference_solution": "...",     // plain, or:
  "reference_solution_b64": "...", // base64 — keeps it out of casual view

  "tests": [
    {
      "name": "empty array",
      "stdin": "0\n",
      "expected_stdout": "0",
      "description": "count is 0 and values may be NULL.",  // optional
      "hidden": false                                        // optional
    }
  ]
}
```

`statement` supports `# heading`, `## subheading`, `- bullet`,
`` `inline code` `` and ``` fenced blocks ```.

Fields are validated on load with messages aimed at the author — a malformed
file is listed in a warning dialog and skipped, never crashing the app.

**`hidden`** defaults to `false` and shipped problems do not use it. It exists
for the case where you want a held-out case to discourage hard-coding; hidden
cases still run and still count, and are labelled as hidden in the list. The
learning-aid default is that everything is shown.

### Keeping the reference out of sight

`reference_solution_b64` holds base64. All shipped problems use it, which is
why opening a problem file to read the test cases does not drop the answer in
your lap.

To encode one:

```sh
python -c "import base64,sys;print(base64.b64encode(open(sys.argv[1],'rb').read()).decode())" solution.c
```

Be clear about what this is: **obfuscation, not security.** The file is on the
candidate's own disk and base64 is trivially reversible. It stops casual
discovery. For a real assessment, serve problems from somewhere the candidate
cannot read.

## Adding a language

Write a `Language` subclass and register it. Nothing else changes — problems
select a language by `id`, and the UI builds its menus from the registry.

```python
class RustLanguage(Language):
    id = "rust"
    display_name = "Rust"
    solution_filename = "solution.rs"
    harness_filename = "harness.rs"
    line_comment = "//"
    keywords = ("fn", "let", "mut", "match", ...)   # drives highlighting

    def detect_toolchain(self) -> ToolchainStatus: ...
    def build(self, workdir, solution, harness) -> BuildResult: ...
    def exec_command(self, workdir, build) -> list[str]: ...
```

Then add it to `_LANGUAGES` in `crucible/languages/__init__.py`.

`crucible/languages/python_lang.py` is a complete worked example in about sixty
lines, and it is deliberately not a special case: it goes through the same
build-then-run pipeline as C, which is what keeps the seam honest. Its `build`
has nothing to link, so it compiles the source instead — that way a syntax
error is reported once as a build failure rather than n times as identical
tracebacks.

## Command line

| Command | Does |
| --- | --- |
| `python -m crucible` | Open the GUI |
| `--verify` | Run every reference solution against its suite; exit 1 if any fail |
| `--list` | List loaded problems and their test counts |
| `--toolchains` | Report which compilers were found and where |
| `--problems DIR` | Use a different problem directory |

## Tests

```sh
python -m unittest discover -s tests -v
```

46 tests covering output normalisation and diff hints, problem-schema
validation (missing fields, bad base64, duplicate test names, unknown
languages, malformed JSON), the run pipeline (correct, wrong, syntax error,
runtime exception, timeout, progress callbacks), the language registry, and the
C diagnostic/exit-code helpers that can be checked without a compiler.

The suite also asserts that every shipped reference solution passes its own
tests. Problems whose toolchain is missing are skipped *individually*, so one
uninstalled compiler cannot silently skip the rest.

## Layout

```text
Crucible.cmd           Windows double-click launcher
crucible/
  __main__.py          entry point and CLI  (python -m crucible)
  problem.py           schema, loading, validation
  runner.py            build + execute + judge        (no UI)
  workspace.py         drafts and settings
  languages/
    __init__.py        registry
    base.py            Language ABC, process runner, result types
    c_lang.py          gcc / clang / cc / MSVC, toolchain discovery
    python_lang.py     worked example of a second language
  ui/
    app.py             main window
    editor.py          editor widget: gutter, highlighting, indentation
    theme.py           palettes and ttk styling
problems/
  c/                   8 problems
  python/              3 problems
tests/
  test_crucible.py
```

Everything below `ui/` is importable and testable without a display, which is
what lets `--verify` and the unit tests run headless.

## Limitations

- **Submitted code is not sandboxed.** It compiles and runs with your full user
  privileges. That is fine for self-practice, which is what this is for. Do not
  point it at untrusted code without putting a container or VM around it. The
  per-case timeout is a guard against runaway loops, not against malice.
- **Hiding the reference is obfuscation only** — see above.
- Comparison is on stdout. Problems that would need to assert on internal state
  or on memory behaviour need a harness that prints something checkable.
- Theme changes apply on next launch.
