# Crucible

A small Tkinter practice harness. Pick a problem, read the test cases, write
your code, press **Go**, and see which cases pass.

Built around one rule: **the test cases are always visible, the reference
solution never is.** Every problem's suite is proved satisfiable by running the
hidden reference against it *before* the problem is offered to anyone.

That same reference is what makes the data safe to randomise. Most problems mix
fixed edge cases with cases generated fresh from a seed, and the expected output
for a generated case is captured from the reference rather than written down —
so the data and the results it is checked against cannot drift apart. Press
**Ctrl+R** for a new set and solve the problem again.

```sh
python -m crucible
```

---

## Contents

- [Quick start](#quick-start)
- [Profiles](#profiles)
- [Installing a C compiler](#installing-a-c-compiler)
- [Installing the .NET SDK](#installing-the-net-sdk)
- [How a submission is run](#how-a-submission-is-run)
- [The reference-solution gate](#the-reference-solution-gate)
- [Randomised test data](#randomised-test-data)
- [Hints and worked solutions](#hints-and-worked-solutions)
- [What is in the box](#what-is-in-the-box)
- [Writing a problem](#writing-a-problem)
- [Adding a language](#adding-a-language)
- [Internationalisation](#internationalisation)
- [Command line](#command-line)
- [Tests](#tests)
- [Layout](#layout)
- [Limitations](#limitations)
- [License](#license)

---

## Quick start

Requires Python 3.10+ with Tkinter (bundled on Windows and macOS; on Debian or
Ubuntu, `sudo apt install python3-tk`). Nothing else — no third-party packages.

```sh
python -m crucible              # open the GUI
python -m crucible --toolchains # which compilers were found
python -m crucible --list       # what problems loaded
python -m crucible --verify     # prove every reference solution passes
python -m crucible --guides     # which problems lack a hint or solution page
```

On Windows, **`Crucible.cmd`** opens the GUI on a double-click.

The window is four panes, under one banner that reports on the problem itself:

```text
┌──────────────────────────────────────────────────────────────┐
│ ✓ Test suite verified — the reference passes all 9 cases     │
├───────────┬──────────────────────────────────────────────────┤
│ PROBLEMS  │ ▾ THE PROBLEM                                 ⤢  │
│           │   statement, examples, edge cases                │
│  Easy     ├──────────────────────────────────────────────────┤
│  Medium   │ ▾ YOUR SOLUTION                     solution.c ⤢ │
│   ★ done  │   editor, line numbers, syntax highlighting      │
│  Hard     ├──────────────────────────────────────────────────┤
│  Fiendish │ ▾ RESULTS                                     ⤢  │
│           │  ┌──────────────────┬────────────────────────┐   │
│           │  │ PASS  empty array│ INPUT     0            │   │
│           │  │ FAIL  last elem  │ EXPECTED  6            │   │
│           │  │ PASS  not found  │ YOUR OUT  -1           │   │
│           │  └──────────────────┴────────────────────────┘   │
└───────────┴──────────────────────────────────────────────────┘
```

The **Language** picker in the toolbar chooses what the PROBLEMS pane groups
by: **All** groups by language, same as the language picker itself; picking
one language regroups the list by difficulty instead, since the picker has
already answered "which language" and "how hard" is the question left. A
solved problem — every test passed at least once, by whoever is the current
profile — carries a small ★ beside it; a ✓ or ✗ instead means the problem's
*own* reference solution does or does not pass, which is a claim about the
problem, not about you (see [The reference-solution gate](#the-reference-solution-gate)).

Every pane collapses to its title bar — click the bar, or **Ctrl+1** to
**Ctrl+4**, and the space goes to its neighbours. **⤢** gives one pane the
whole window and puts it back again, which is the quick way to read a long
statement without losing your place. **Ctrl+0** restores the default
proportions. Pane sizes and the window size are remembered between sessions.

The banner sits above the panes rather than inside one, because what it
reports — suite verified, data set building, problem disabled — is about the
problem and not about any one pane. **Build Output** appears as a second tab
beside the results only once there is a build to talk about, and goes away
again when you move to another problem.

Keys: **F5** or **Ctrl+Enter** runs the suite. **Ctrl+R** draws a new
randomised data set. **Ctrl+S** saves a draft. **F1** opens the hint for the
current problem in your browser and **F2** its diagram, where it has one.

The editor has the whole-line commands you would expect from a modern
editor, all of them listed under the **Edit** menu:

| | |
| --- | --- |
| **Ctrl+X** / **Ctrl+C** | cut or copy the whole line when nothing is selected |
| **Ctrl+D** | duplicate the line or selected block |
| **Ctrl+Shift+K** | delete the line |
| **Alt+↑** / **Alt+↓** | move the line or block up and down |
| **Ctrl+/** | comment or uncomment |
| **Tab** / **Shift+Tab** | indent and dedent |
| **Ctrl+Backspace** / **Ctrl+Delete** | delete a word |
| **Ctrl+F** / **Ctrl+H** | find, and find with replace |
| **F3** / **Shift+F3** | next and previous match |

Each of those is one undo step, however many edits it is made of underneath —
a *replace all* comes back in a single **Ctrl+Z**.

Brackets and quotes close themselves. Typing `{` gives you `{}` with the
caret in the middle, and pressing **Enter** there opens the block out:

```c
void f() {
    |
}
```

Typing the closer steps over the one already there rather than doubling it,
**Backspace** between an empty pair removes both halves, and typing a bracket
with text selected wraps the selection instead of replacing it. It stays out
of the way where pairing would be wrong: no partner is added in front of a
word, so `(` before `foo` just inserts `(`, and an apostrophe in `don't` stays
a single character.

Your work is autosaved per problem, so closing the window mid-problem loses
nothing. *File → Reset to starter code* discards it. Where it is saved depends
on which profile is open -- see below.

## Profiles

Practising is per person, not per machine: **Profile → Switch profile…** lists
everyone who has used this copy of Crucible and lets you open one, or start a
new one by typing a username and pressing *Create & open*. The very first run
asks the same question, since there is nothing yet to resume.

A profile is a username and nothing else — no email, no real name, no link to
your OS account. It exists to keep drafts, randomised data sets, and which
problems you have solved separate between people sharing a machine, not to
identify anyone. Two profiles can even share a username in different case
(`Alice` and `alice`) — matching is exact, on the theory that a username typed
at a keyboard is a label, not a verified identity.

Everything is stored under `~/.crucible/`:

```text
~/.crucible/
  settings.json          theme, font size, window layout -- shared by everyone
  profiles.json           every profile's username and which one is current
  profiles/<id>/
    drafts/                your in-progress code, one file per problem
    seeds.json              which randomised data set each problem is on
    progress.json           which problems you have solved, and when
```

The status bar shows who is currently practising and how many problems they
have solved; **Profile → Current: `<name>`** shows the same thing. Deleting a
profile (from the switcher) removes its drafts, data sets and solved record
permanently -- there is no undo.

## Installing a C compiler

The app searches `PATH` and the usual install locations for `gcc`, `clang`,
`cc` and `cl.exe`. If none is found, C problems still open and their
hand-written test cases still display — only running is unavailable, and the
banner says so rather than pretending the problem is broken. Their randomised
cases do not appear, because generating one means running the reference
solution, which means compiling it.

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

## Installing a C++ compiler

The app searches for `g++`, `clang++`, `c++` and `cl.exe` the same way it
searches for a C compiler — and on most machines there is nothing to
install: `g++`/`clang++` ship in the same package as `gcc`/`clang` (MSYS2,
w64devkit, Debian/Ubuntu's `build-essential`, Xcode's command line tools),
and MSVC's `cl.exe` already compiles both from the one install. Locating
`cl.exe` and capturing its environment via `vcvars64.bat` is shared with the
C toolchain entirely — there is one MSVC install and one captured
environment per machine, not one per language.

| Option | How |
| --- | --- |
| **w64devkit** | Same zip as the C compiler — it includes `g++`. |
| **MSYS2** | `pacman -S mingw-w64-ucrt-x86_64-gcc` (this package includes `g++` too) |
| **Visual Studio** | Same *Desktop development with C++* workload as the C compiler. |
| **Linux** | `sudo apt install build-essential` (includes `g++`) — Fedora is the one common exception: `sudo dnf install gcc-c++` separately. |
| **macOS** | `xcode-select --install` |

Then *Tools → Re-check compilers*. Builds default to `-std=c++17` (or
`/std:c++17` under MSVC, with `/EHsc` for standard exception handling).

## Installing the .NET SDK

The app searches `PATH` and the usual install locations for `dotnet`. If it
is found but `dotnet --version` fails, that is a runtime-only install — it
can run a published app but not build one — reported as its own distinct
status rather than "no toolchain", because the remedy is different (install
the SDK, not reinstall .NET from scratch).

| Option | How |
| --- | --- |
| **Windows** | `winget install Microsoft.DotNet.SDK.8`, or the installer at <https://dotnet.microsoft.com/download> |
| **Linux** | `sudo apt install dotnet-sdk-8.0` / `sudo dnf install dotnet-sdk-8.0` |
| **macOS** | `brew install dotnet-sdk` |

Then *Tools → Re-check compilers*. Every submission builds as a small,
disposable `net8.0` console project generated fresh in a temp directory —
the first build on a machine restores the SDK's reference packages into the
shared NuGet cache (a few seconds); every build after that, anywhere, reuses
the cache and takes about as long as a C compile.

## Installing a JDK

The app searches `PATH`, `JAVA_HOME`, then the usual versioned install
directories (`C:\Program Files\Java\*`, `C:\Program Files\Eclipse
Adoptium\*`, `/usr/lib/jvm/*`, and similar) for `javac`. This is a genuinely
separate toolchain from C/C++/C# — nothing else on the machine already
provides it. Once `javac` is found, `java` is read from the exact same `bin`
directory next to it, deliberately never re-resolved from `PATH`
independently: a machine with more than one JDK/JRE installed can easily
have `javac` and a bare `java` resolve to different, mismatched installs,
and running freshly-compiled classes on the wrong one fails in ways that
have nothing to do with the candidate's code.

| Option | How |
| --- | --- |
| **Windows** | [Adoptium (Eclipse Temurin)](https://adoptium.net), or `winget install EclipseAdoptium.Temurin.21.JDK` |
| **Linux** | `sudo apt install default-jdk` / `sudo dnf install java-latest-openjdk-devel` |
| **macOS** | `brew install openjdk` |

Then *Tools → Re-check compilers*. Make sure the install provides a JDK, not
just a JRE — a JRE has `java` but no `javac`, and can run a program but not
compile one, which the app reports as its own distinct status rather than
"no toolchain found".

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
Randomised data sets use seed 5209  (--seed 5209 to repeat)

  OK    Binary Search  (8 tests, 4 randomised)
  BROKEN Two Sum  -- 6/7 tests passed
           FAIL     pair further in  first difference on line 1
             expected: '2 1'
             actual:   '1 2\n'
```

That example is real: it is the gate catching a test case whose expected output
had the indices the wrong way round.

## Randomised test data

Most problems ship a **generator** as well as hand-written cases. The
hand-written ones never change — they are the edge cases, and an edge case you
might not meet this run is not doing its job. The generated ones are new every
time you ask for them, so coming back to a problem next week is solving it
again rather than remembering what came out last time.

**Ctrl+R** (or *Run → New data set*) draws a fresh set. Your code is left
alone; the numbers change, not the exercise.

One rule makes the whole thing work:

> A generator produces **inputs**. It never states the expected output.

The expected output for a generated case is captured from the problem's own
reference solution, run through the same build-and-run pipeline your code goes
through:

```text
generator ──► stdin ──► reference solution ──► stdout ──► expected_stdout
                            (same compile, same per-case process)
```

So there is no "keeping the tests in sync with the data" problem to get wrong.
The data and the expected results cannot drift apart, because only one thing in
the system ever decides what an input should produce, and it is the same thing
that decided it before randomisation existed. A generator that also computed
the answer would be a second implementation of the problem, free to disagree
with the first — and the disagreement would land on you as a case nobody can
pass.

Two consequences fall out of that, and both are visible in the UI:

- Generation runs the reference, so it **needs a working toolchain**. With no C
  compiler installed, C problems keep their hand-written cases and say so.
- An input the reference **cannot** handle — it crashes, or never returns — is
  dropped rather than turned into a test case, and the author is told which
  one. The generator wandered outside the problem's own contract, and there is
  no defensible expected output to be had from it.

Each data set has a four-digit number shown in the banner. `--seed` replays
one, which is what makes a generated failure reproducible:

```sh
python -m crucible --verify --seed 8317
```

Data set numbers are remembered per problem in the active profile's
`seeds.json` (see [Profiles](#profiles)), alongside the drafts and for the
same reason: a half-written solution and the cases it was being written
against belong together.

### Writing a generator

Always Python, whatever language the problem is in — a generator describes
data, not solutions. It defines one function:

```python
def generate(rng, count):
    """rng is a random.Random seeded from the data set number."""
    return [{"name": "...", "stdin": "...", "description": "..."}
            for _ in range(count)]
```

`stdin` is the only required key; `name`, `description` and `hidden` are
optional. Setting `expected_stdout` is an error, not an override.

Two things worth doing, both visible in `problems/`:

- **Guarantee properties by construction, not by checking.** Two Sum's "no
  pair" case is all-even values with an odd target, so no two of them can
  reach it. That is a statement about the input; brute-forcing the array to
  confirm no pair exists would be solving the problem in the generator.
- **Keep the arithmetic inside the language's range.** The C array problems
  cap at a dozen values under a thousand, so no correct solution can overflow
  an `int`. An input whose answer depends on undefined behaviour has no
  expected output worth capturing.

A generator runs in its own process with a ten-second limit, so one with an
endless loop is reported rather than hanging the app, and a stray `print` left
in it turns up as a diagnostic instead of corrupting the data.

## Hints and worked solutions

Every problem ships two guide pages, opened from the **Guides** menu, and some
ship a third:

| | |
| --- | --- |
| **Hint** (`F1`) | The idea, the traps, the cases to think about — and a `Still stuck?` block that folds open into a stronger nudge. No finished answer in it. |
| **Worked solution** | The whole answer: the code, a table tracing it running on a real test case, why each edge case comes out right, the complexity, and the wrong turns worth recognising. |
| **Diagram** (`F2`) | Only for problems whose specification *is* a diagram. Renders the statement's Mermaid source as a picture. |

They are HTML files opened in your browser rather than rendered in the app,
which is not laziness. A guide is a document — headings, tables, a trace of the
algorithm step by step — and a Tk `Text` widget renders that badly while every
machine already has something that renders it well. It also means the guide sits
*beside* the editor instead of on top of it.

The pages live next to the problem and are found by name. There is no index and
nothing to register:

```text
problems/
  guides.css                     one stylesheet, shared by every page
  c/
    c_sum_array.json
    c_sum_array.hint.html
    c_sum_array.solution.html
  uml/
    uml_state_machine.json
    uml_state_machine.diagram.html      optional -- most problems have none
    ...
```

A diagram page holds the Mermaid source in a `<pre class="mermaid">` and pulls
the renderer from a CDN. With no network the source shows through as text,
which is the same specification — and it is in the problem statement as well,
so the app itself never needs the network. One `<script>` tag to delete if you
would rather it did not try.

Two things follow from keeping them in separate files rather than in the problem
JSON:

- **`reference_solution_b64` still means something.** A worked solution written
  into the problem file would defeat it — opening the JSON to read the test
  cases would drop the answer in your lap. In a file of its own, reading it
  stays a deliberate act, which is also why the app asks before opening one
  (once per problem, per session).
- **The convention is the only wiring.** Drop the two files beside a new
  problem and the menu picks them up. Nothing warns you if you forget, so
  `--guides` is that warning, and it exits non-zero for CI:

```console
$ python -m crucible --guides
  OK    Binary Search
  MISSING Two Sum  -- no worked solution
           expected E:\Crucible\problems\python\py_two_sum.solution.html
```

The pages link `../guides.css` — a relative path that assumes the problem sits
one directory below `problems/`, which is where all the shipped ones live. If
the stylesheet does not load the pages are still ordinary readable HTML.

## What is in the box

90 problems — 47 in C, 12 in C++, 4 in Python, 15 in C#, 12 in Java. Every
one of them mixes hand-written edge cases with four randomised ones, and
ships a hint and a worked solution.

The C set is deliberately weighted towards the things C makes you think about
and other languages do not: what the pointer points at, who owns the memory,
what happens at the boundary, and what the standard actually promises. The C#
set asks the mirror question: what does the runtime hand you for free, and
where does trusting that abstraction stop being safe? A `struct` inside a
`List<T>`, integer division that overflow-checks when nothing else does, an
interface call that costs nothing to get right and everything to fake with a
type switch -- see [C#: what the compiler will not catch for
you](#c-what-the-compiler-will-not-catch-for-you) below. The C++ set sits
between the two: reference parameters and `const&` where C uses raw
pointers, but the same manual-memory-ownership questions C never lets you
forget, plus a few entirely new to it (`operator+` has to be the exact
overload a caller expects, `std::vector::erase` invalidates the iterator
that produced it). The Java set asks yet another version of the C# question
-- what does *this* runtime hand you for free -- with different (and
sometimes opposite) answers: `int` overflow never throws, ever, on any
operator; a collection detects and throws on concurrent mutation instead of
corrupting silently; boxed `Integer`s compare by reference under `==`,
correctly only by coincidence for small cached values.

Most problems start from an empty function. A few start from a *full* one that
is already wrong — the editor opens on plausible code carrying one planted
defect, and the job is to find it rather than to write it. Those are marked
with the `debugging` topic.

| | Language | Problem | Topics |
| --- | --- | --- | --- |
| **easy** | C | Sum of an Array | arrays, pointers, loops |
| | C | Count the Vowels | strings, ctype, loops |
| | C | Count the Words | strings, state machines |
| | C | Reverse a String In Place | strings, pointers, in-place |
| | C | FizzBuzz | control flow, modulo, output format |
| | C | Greatest Common Divisor | loops, arithmetic |
| | C | Count the Set Bits | bitwise, loops |
| | C | Extract a Register Field | bitwise, embedded, registers |
| | C | Byte-Swap a Register (Endianness) | bitwise, embedded, endianness |
| | C | Compute the Parity Bit | bitwise, embedded, error-detection |
| | C | Slew-Rate Limit a Demand Signal | embedded, control, signal-processing |
| | C | Check Whether a Sensor Reading Is In Range (MISRA Essential Types) | embedded, calibration, essential-types, misra |
| | C++ | Reverse a String in Place | strings, references |
| | C++ | Sum a Vector Without Overflowing | vectors, loops, overflow |
| | C++ | Count Words With a String Stream | strings, streams |
| | Python | Two Sum | dictionaries, arrays |
| | C# | Count the Vowels | strings, loops |
| | C# | Palindrome Check | strings, two pointers |
| | C# | Min, Max and Sum as a Value Tuple | tuples, arrays, loops |
| | C# | Nullable Value or Fallback | nullable types, operators |
| | C# | Join a List Into a CSV Line | strings, lists |
| | Java | Reverse a String (Which You Cannot Mutate) | strings, immutability |
| | Java | Sum an Array Without Overflowing | arrays, loops, overflow |
| | Java | Count Words Without split()'s Empty-String Surprise | strings, scanner |
| **medium** | C | Binary Search | algorithms, arrays, search |
| | C | Palindrome Check | strings, two pointers, ctype |
| | C | Remove Duplicates From a Sorted Array | arrays, in-place, two pointers |
| | C | Sort an Array In Place | sorting, arrays |
| | C | Merge Two Sorted Arrays | arrays, pointers |
| | C | Rotate an Array Left | arrays, in-place |
| | C | Parse an Integer | strings, pointers |
| | C | Decimal to Roman Numeral String | strings, tables, greedy |
| | C | Primes up to N | arrays, loops |
| | C | Write a Register Field (Read-Modify-Write) | bitwise, embedded, registers, read-modify-write |
| | C | GPIO Set/Clear/Toggle (Read-Modify-Write) | bitwise, embedded, gpio, read-modify-write |
| | C | Linear Interpolation Over a Calibration Table | embedded, calibration, fixed-point, lookup-table, misra |
| | C | Multiply Two Q15 Fixed-Point Numbers | embedded, fixed-point, arithmetic |
| | C | Single-Producer/Single-Consumer Ring Buffer | embedded, data-structures, concurrency |
| | C | Add Hysteresis to a Noisy Threshold (Schmitt Trigger) | embedded, signal-processing, state |
| | C | A Shift-Based Low-Pass Filter (No Floats) | embedded, signal-processing, bitwise, fixed-point |
| | C | Classify a Diagnostic Fault Code (MISRA Switch Rules) | embedded, diagnostics, state, misra |
| | C | Elapsed Ticks Since a Free-Running Counter (MISRA Unsigned Arithmetic) | embedded, timers, unsigned-arithmetic, misra |
| | C | Fix the Sample Averager | debugging, code-review, pointers, arrays |
| | C++ | Remove Duplicates, Keep First-Seen Order | vectors, unordered_set, loops |
| | C++ | Word Frequency With operator[] | maps, strings, streams |
| | C++ | Balanced Brackets With std::stack | stacks, strings |
| | Python | Balanced Brackets | stacks, strings, parsing |
| | Python | Run-Length Encoding | strings, iteration |
| | C# | Group Anagrams | dictionaries, strings, linq |
| | C# | Keep Only the Valid Integers | parsing, strings, lists |
| | C# | Character Frequency Count | dictionaries, strings |
| | C# | Balanced Brackets, Three Kinds | stacks, strings |
| | C# | Total Area Through an Interface | interfaces, polymorphism, lists |
| | Java | Remove Duplicates, Keep First-Seen Order | collections, sets |
| | Java | Word Frequency Without a Null Pointer Exception | maps, autoboxing, strings |
| | Java | Balanced Brackets With an ArrayDeque | collections, strings |
| **hard** | C | Maximum Subarray Sum | algorithms, dynamic programming, arrays |
| | C | Reverse a Linked List | pointers, linked lists |
| | C | Edit Distance | dynamic programming, strings |
| | C | Extract a Signed Sensor Reading | bitwise, embedded, sign-extension, twos-complement |
| | C | Unpack a CAN Signal (Intel Byte Order) | embedded, can-bus, bitwise, sign-extension |
| | C | Validate a CAN Message's Rolling Counter and Checksum | embedded, can-bus, functional-safety, state |
| | C++ | Lower Bound: the Leftmost Insertion Point | algorithms, binary search |
| | C++ | Reverse a Singly Linked List | linked lists, pointers |
| | C++ | Sum Vectors With operator+ | operator overloading, structs |
| | C# | Sliding Window Maximum | algorithms, linked lists, arrays |
| | C# | Binary Search With an Insertion-Point Convention | algorithms, search, bitwise |
| | C# | Interleave Two Sequences, Lazily | iterators, yield, linq |
| | Java | Two Sum, Indices, in One Pass | hashmaps, arrays |
| | Java | Kth Largest With a Bounded Min-Heap | priorityqueue, heaps |
| | Java | A Stack That Tracks Its Own Minimum | stacks, data structures |
| **fiendish** | C | Compute a CRC-16/CCITT-FALSE Checksum | embedded, bitwise, checksum, error-detection, misra |
| | C | Decode a COBS-Framed Serial Buffer | embedded, framing, bitwise, error-detection |
| | C | Fixed-Capacity LRU Cache (No Dynamic Allocation) | data-structures, embedded, pointers, linked lists |
| | C | Match a Simplified Regular Expression ('.' and '*') | algorithms, dynamic programming, strings, recursion |
| | C | Decode a Multiplexed CAN Signal Group | embedded, can-bus, bitwise, sign-extension |
| | C++ | Erase-While-Iterating, Correctly | vectors, iterators, algorithms |
| | C++ | A Modulo That Is Never Negative | arithmetic, overflow |
| | C++ | Deep-Copying a Struct That Owns a Pointer | pointers, structs, ownership |
| | C# | Division With Two Distinct Failure Modes | arithmetic, enums, tuples, overflow |
| | C# | Mutating Structs Inside a List | structs, value semantics, lists |
| | Java | Remove While Iterating, Without ConcurrentModificationException | collections, iterators |
| | Java | Comparing Boxed Integers Without == | autoboxing, equality |
| | Java | Division Java Will Not Warn You About | arithmetic, overflow, records |

A few are worth calling out for what they are really testing:

- **Count the Set Bits** takes an `unsigned int` on purpose. A loop written
  around a signed `int` can spin forever on a value with the top bit set, and
  one of the fixed cases is exactly that value.
- **Rotate an Array Left** accepts a shift larger than the array. Reducing it
  modulo the length before checking the length for zero is a division by zero
  rather than a wrong answer.
- **Parse an Integer** rejects `"12a"`. Stopping at the first bad character and
  returning what you had is what `atoi` does, and is the habit the problem is
  there to break.
- **Decimal to Roman Numeral String** is a fix-up pass waiting to be deleted.
  Treat the six subtractive pairs as values in their own right — thirteen
  building blocks rather than seven — and a plain greedy walk produces `IV`
  and `CM` with no special cases left over. Its buffer is 16 bytes because
  that is the exact bound: 3888 is `MMMDCCCLXXXVIII`, and it is the only
  value in range fifteen characters long.
- **Reverse a Linked List** wants the nodes relinked, not the values copied
  into an array and written back. It declares `struct node` in both your file
  and the harness — separate translation units, same layout, which is what a
  shared header would have given you.
- **Fix the Sample Averager** hands you working-looking code and a bug report.
  The defect is `sizeof` applied to an array *parameter*, which is a pointer,
  so the element count it computes is a property of the target rather than of
  the data — four on a PC, two on a 32-bit part. One of the fixed cases passes
  both before and after the fix, because at that one block length the wrong
  count and the right count coincide; that case is in the suite to show what a
  test passing for the wrong reason looks like.

### Fiendish: composing more than one trap at once

**hard** is one well-known hazard per problem — a sign-extension, a
read-modify-write, a DP recurrence. **fiendish** is what happens when a
problem stops being satisfied with one: each of these five chains two or
three ideas from elsewhere in the set together, or pushes a familiar shape
to the one edge case that breaks a plausible-looking partial solution.

- **Compute a CRC-16/CCITT-FALSE Checksum** is unforgiving in a way most
  bugs are not: several other real, standard CRC-16 variants share this
  polynomial and differ only in initial value or bit order, so a wrong
  implementation is not "close" — it is a different checksum entirely,
  and it disagrees with the reference on every input rather than an edge
  case. The empty-input test exists because it is the one input where the
  initial value (`0xFFFF`, not `0x0000`) is the *entire* answer.
- **Decode a COBS-Framed Serial Buffer** has an inversion easy to get only
  half right: almost every block implies a trailing zero byte, except a
  full 254-byte block (code `0xFF`) and whichever block happens to be last
  in the frame — two independent exceptions to the same default, joined by
  one `&&`, and a fixed test built at exactly 254 non-zero bytes to prove
  both are actually implemented rather than one copied from the other.
- **Fixed-Capacity LRU Cache** asks for an intrusive doubly linked list
  threaded through array indices instead of pointers — the standard
  no-`malloc` shape — where a cache hit has to *move* the entry as a side
  effect of reading it, an update has to touch recency without evicting,
  and `capacity == 1` forces the detach/reinsert logic to correctly empty
  and immediately refill the list around a single self-referential slot.
- **Match a Simplified Regular Expression** takes edit distance's DP habit
  and applies it somewhere the recursion has two branches instead of three,
  one of which recurses on the *same* position — `a*` matching one more
  character keeps re-asking "does `a*` still match what's left" until it
  doesn't. A fixed test checks that `*` can be skipped in the *middle* of a
  pattern, not only at the end, where it is easy to only handle the case
  that happens to come up in the first example anyone tries.
- **Decode a Multiplexed CAN Signal Group** is *Unpack a CAN Signal* and
  *Extract a Signed Sensor Reading* combined and then given a third way to
  fail: which of two totally different bit layouts applies is decided by a
  multiplexor nibble that has to be masked out of a byte whose other nibble
  is reserved noise, and an unrecognised multiplexor has to be rejected
  outright rather than decoded as if it were one of the known ones —
  checked with a fixed test that sends a full 8-byte frame specifically so
  "plenty of bytes present" cannot be mistaken for "acceptable".

### Registers, not just algorithms

Six of the C problems are the kind of bit manipulation an electronics or
embedded engineer runs into on real hardware rather than in a textbook:
reading one field out of a packed status register, writing one back without
disturbing its neighbours, driving a GPIO port, sign-extending a sensor
reading, and swapping byte order at a hardware boundary. Same pipeline, same
kind of hand-written edge cases — just aimed at registers instead of arrays.

- **Extract a Register Field** and **Write a Register Field** both build a
  mask from `(1u << width) - 1u`, and both have a fixed test for
  `width == 32`. That shift is undefined behaviour — the amount reaches the
  type's own bit width — and on this app's compiler it silently comes back as
  `1u << 0`, turning "read the whole register" into "read nothing". The fix
  is one `width == 32` special case, not a cleverer formula.
- **Write a Register Field** is *Extract*'s mirror image, and a genuine
  read-modify-write: clear the field's old bits before OR-ing the new ones
  in, and mask the incoming value before you shift it, or bits that belong to
  a field you were never asked to touch pick up whatever was left over.
- **GPIO Set/Clear/Toggle** turns three register operations into three
  operators — `|`, `& ~`, `^` — and one of the fixed traces is built
  specifically to catch `reg & mask` written where `reg & ~mask` was meant
  for a clear. Its worked solution also covers why real GPIO ports (STM32's
  `BSRR`, for one) give set and clear their own atomic write-only register
  rather than trusting software to read-modify-write safely around an
  interrupt.
- **Extract a Signed Sensor Reading** combines field extraction with
  sign-extending a two's-complement value that is narrower than an `int`.
  Two of its fixed tests share the same surrounding status flags and differ
  only in which bit is the field's *own* sign bit — deliberately not lined up
  with bit 31 of the register — so that testing the wrong bit fails at least
  one of them however you get it wrong.
- **Byte-Swap a Register** and **Compute the Parity Bit** round out the set
  without a manufactured trap: the first is the everyday fix for hardware
  that hands you a multi-byte value most-significant-byte-first, the second
  is the classic XOR-fold, a genuinely different bit trick from *Count the
  Set Bits*'s Kernighan loop rather than a rerun of it.

### Calibration, control loops and the bus

Eight more C problems sit one level up from raw registers: the everyday
building blocks of a calibration-and-controls role rather than a peripheral
driver — a lookup table, a fixed-point multiply, a lock-free ring buffer, and
the small stateful filters (hysteresis, slew-rate limiting, a shift-based
low-pass filter) that turn a noisy signal into one a state machine can act on
without chattering. Two of them work directly with CAN frames, which is
where several of these ideas meet at once.

- **Linear Interpolation Over a Calibration Table** is the most
  role-specific problem in the whole set: read a breakpoint either side of
  the query, interpolate between them, and clamp rather than extrapolate
  outside the table. Its fixed test with a table spanning `0` to `100000` on
  both axes exists because the natural formula multiplies a y-difference by
  an x-difference *before* dividing — comfortably past `INT32_MAX` on a
  realistic-sized table unless that intermediate product is widened to 64
  bits first. It is also one of four problems written to **MISRA C:2012**
  — see below.
- **Multiply Two Q15 Fixed-Point Numbers** is fixed-point arithmetic without
  an FPU: multiply the raw integers in a wide type, shift back down by 15,
  round rather than truncate, and saturate. `q15_multiply(-32768, -32768)` —
  `-1.0 * -1.0`, mathematically `1.0` — is a fixed test precisely because
  `1.0` does not fit in Q15's range and the correct answer is the clamped
  `32767`, not a value that has wrapped around negative.
- **Single-Producer/Single-Consumer Ring Buffer** asks for the standard
  reserved-slot convention: a buffer of capacity N holds at most `N - 1`
  items, which is what lets `head == tail` mean empty and
  `(head + 1) % capacity == tail` mean full with no separate counter to keep
  in sync. A fixed test fills a capacity-4 buffer with four pushes and
  requires the fourth to report full.
- **Add Hysteresis to a Noisy Threshold** and **A Shift-Based Low-Pass
  Filter** are two different answers to "the signal is noisy" — one absorbs
  noise in the *value* with a dead zone between two thresholds, the other
  smooths noise *over time* with an integer exponential moving average
  (`output += (sample - output) >> shift`). The filter's worked solution is
  upfront about a real property of that formula: a small enough persistent
  gap shifts to zero and the filter gets permanently stuck short of its
  target, which is the specification working correctly, not a bug to fix.
- **Slew-Rate Limit a Demand Signal** caps how fast an output can move
  toward a target in either direction — the fixed test that ramps up and
  then reverses exists specifically to catch a clamp written for only the
  rising case.
- **Unpack a CAN Signal** does DBC-style Intel-byte-order signal extraction:
  assemble 8 payload bytes into a 64-bit little-endian value, then extract
  and sign-extend a field from it exactly as in *Extract a Signed Sensor
  Reading*, before applying a scale and offset. Its fixed tests check the
  byte order in the direction that is actually easy to get backwards, and
  its return type is `long long` because `raw * scale` overflows a 32-bit
  `int` well before the raw value itself does.
- **Validate a CAN Message's Rolling Counter and Checksum** is end-to-end
  protection on a safety-relevant signal: a checksum that has to fold in the
  frame's alive counter (or a stale replay with unchanged payload slips
  through undetected), and a counter that must advance by exactly one from
  the last *accepted* frame — never from a frame that failed its own check.
  A fixed test sends a good frame, a corrupted one, and a frame that is only
  valid counted from *before* the corrupted one arrived, proving a rejected
  frame never moves the baseline.

### Written to MISRA C:2012

Five C problems are written to **MISRA C:2012**, the coding standard most
safety-critical C shops build against — not just correct, but shaped the way
a reviewer at an automotive or aerospace shop would expect. Nothing in
Crucible runs a static analyser over a submission; the tests only check
behaviour. What "written to MISRA" buys instead is that each reference
solution, and the problem's own function signature, follow a specific rule
or two closely enough that the statement can name them and mean it. Each one
leans on a different corner of the standard, deliberately:

- **Linear Interpolation Over a Calibration Table** — Directive 4.6 (sized
  `<stdint.h>` types throughout, never `int` or `long long`), Rule 15.5 (a
  single point of exit, so the natural three-early-return shape becomes one
  `if` / `else if` / `else` assigning to a result variable), and an explicit
  cast at every place a value crosses between `int32_t` and `int64_t`.
- **Classify a Diagnostic Fault Code** — Rule 16.4 (every `switch` needs a
  `default` clause) and Rule 16.3 (every clause ends with an unconditional
  `break`, no accidental fallthrough), combined with the same single-exit
  shape: skip the `default` and the value a single-exit `return` reads back
  is never written in the first place.
- **Check Whether a Sensor Reading Is In Range** — the essential type model,
  demonstrated on a genuine C footgun rather than a hypothetical one:
  `low <= value <= high` compiles, reads naturally, and is wrong, because
  relational operators are left-associative and the *result* of the first
  comparison is what gets compared against `high`. MISRA's essential types
  rule this shape out at the type level — a Boolean result is not a valid
  operand of another relational operator — which is exactly the mismatch
  that produces the bug.
- **Elapsed Ticks Since a Free-Running Counter** — Directive 4.6 again, but
  for a reason beyond precision: `uint32_t`'s defined-overflow subtraction is
  what makes `now - start` the entire correct answer for a wrapping tick
  counter, wrap or no wrap, in one line with no branch. Casting to a signed
  type to "check the sign" reintroduces the undefined-overflow bug the
  unsigned type exists to avoid.
- **Compute a CRC-16/CCITT-FALSE Checksum** — Rule 10.3 (an expression shall
  not be assigned to an object of a narrower essential type): the running
  16-bit register is computed through an `int`-promoted XOR and shift at
  every step, and each explicit cast back down to `uint16_t` is the rule's
  requirement made visible in the code rather than left for a reader to
  infer from two operands' types.

### C#: what the compiler will not catch for you

Fifteen problems, spread across all four difficulty tiers, in a language
where the compiler is unusually good at catching real mistakes -- which is
exactly what makes the ones it does not catch worth building a whole track
around. None of these are C ported into C# syntax; each one is chosen
because the trap only exists *because* of something C# specifically gives
you: a nullable value type, a value-tuple return, `Dictionary<TKey,TValue>`'s
indexer, a `yield return` state machine, an interface's virtual dispatch.

- **Mutating Structs Inside a List** is the fiendish centrepiece of the set.
  `counters[i].Increment();` compiles cleanly, throws nothing, and changes
  nothing: `List<T>`'s indexer returns a *copy* of a struct element, so the
  mutation lands on a temporary that is discarded the instant the statement
  ends. The fix -- read into a local, mutate the local, write the local
  back -- is three statements where the broken version only needed one, and
  there is no compiler warning marking the difference.
- **Division With Two Distinct Failure Modes** trades on a fact most C#
  developers have never had reason to learn: unlike `+`, `-` and `*`,
  which only overflow-check inside a `checked` block, integer *division*
  overflow-checks unconditionally. `int.MinValue / -1` throws
  `OverflowException` every time, `checked` or not, and it is a completely
  different failure from `b == 0` -- the fixed tests check that a solution
  reports which one occurred rather than catching both under one name.
- **Total Area Through an Interface** hides an undocumented third
  `IShape` implementation in one fixed test, specifically to catch a
  solution that pattern-matches on `is Circle` / `is Rectangle` instead of
  trusting `shape.Area()` to dispatch correctly on its own -- the entire
  point of an interface, demonstrated by what breaks when code quietly
  routes around it.
- **Sliding Window Maximum** and **Interleave Two Sequences, Lazily** both
  ask for a specific *shape* of solution, not just a correct answer: a
  monotonic deque built from `LinkedList<int>` for the first, two
  hand-managed `IEnumerator<int>`s inside a `yield return` iterator for the
  second -- because the whole lesson in each is a C# collection or language
  feature that a `List<T>.Contains` scan or a pair of `foreach` loops would
  quietly sidestep.
- **Group Anagrams** is a reminder that `Dictionary<TKey, TValue>`'s
  enumeration order is an implementation detail, not part of its contract:
  the fixed test checking output order is built so that relying on
  insertion-order-shaped enumeration (which happens to hold on today's
  runtime) gives the wrong answer the moment the specification's actual
  rule -- order of first appearance in the input, tracked explicitly --
  is not the rule being followed.

The toolchain is the .NET SDK (`dotnet build`), targeting `net8.0` for the
same reason the C track picks a real standard rather than a compiler's
latest defaults: a submission should build the same way next year. Nullable
reference types are off project-wide -- these problems are about nullable
*value* types, structs, iterators and interfaces, not about fighting the
compiler's reference-nullability warnings on every problem regardless of
whether that problem has anything to do with them.

### Beyond writing algorithms

Five problems sit next to programming rather than in it — reading a UML
diagram, and the mechanical parts of safety engineering. They are ordinary
Crucible problems: same pipeline, same visible test cases, same reference
solution proving the suite before you see it.

| | Language | Problem | Topics |
| --- | --- | --- | --- |
| **easy** | C | ASIL Determination | safety, ISO 26262, tables |
| **medium** | C | State Machine From a Diagram | UML, state machines, tables |
| | Python | Trace From a Sequence Diagram | UML, sequence diagrams, control flow |
| **hard** | C | Smallest Cut Set of a Fault Tree | safety, fault trees, recursion |
| | C | Level Crossing Interlock | safety, interlocks, invariants |

That they fit at all comes down to one question: **can the reference answer be
run?** Where it can, nothing in the app has to change. Where it cannot — "is
this a good abstraction", "did you find the right hazards" — no amount of
harness makes it checkable, and those problems are deliberately absent rather
than faked with an answer key the gate cannot test.

The two UML problems put a **Mermaid diagram** in the statement and draw it on
a [diagram page](#hints-and-worked-solutions). The specification is the
picture; the tests check that your code agrees with it.

- **State Machine From a Diagram** gives you five states and six events —
  thirty pairs, of which the diagram draws six. The other twenty-four are
  refusals, which is what makes a transition *table* the answer and a nest of
  `if`s merely a passing one.
- **Trace From a Sequence Diagram** asks for the message trace, replies
  included. Nested `alt` and `loop` fragments are scopes: with nothing in
  stock the payment gateway is never reached, whatever else the scenario says.

The safety three are chosen for having exactly one right answer:

- **ASIL Determination** is a lookup the standard specifies completely. Its
  worked solution argues the interesting bit — the table has a two-line closed
  form, and you should still write the table, because a reviewer can check
  thirty-six cells against the standard and cannot check an argument as
  easily.
- **Smallest Cut Set of a Fault Tree** is `min` at an OR and `sum` at an AND.
  An answer of `1` is a single point of failure. The sum is only valid because
  no basic event is shared — the guide is explicit about what that assumption
  buys and what it costs.
- **Level Crossing Interlock** is the one to look at if you look at one. The
  candidate writes a pure controller; the **harness owns the safety monitor**,
  the same way it owns `main`, and checks after every decision that no train
  was ever in the crossing without the barrier down and the signal never
  showed green over a barrier that was not up. Randomised event sequences are
  generated with enough warning time by construction, so a correct controller
  is always safe and an incomplete one meets an arrival it did not picture.
  One fixed case is deliberately unsurvivable — proving the monitor can fire,
  because a check that has never failed is indistinguishable from one that is
  wired up wrong.

## Writing a problem

One JSON file under `problems/`. Subdirectories are searched recursively and
carry no meaning — group them however you like.

```jsonc
{
  "id": "c_sum_array",           // unique; defaults to the filename
  "title": "Sum of an Array",
  "language": "c",               // must be a registered language id
  "difficulty": "easy",          // easy | medium | hard | fiendish
  "topics": ["arrays", "pointers"],
  "timeout_seconds": 5,          // per test case

  "statement": "...",            // lightweight markdown, see below

  "starter_code": "...",         // what the editor opens with
  "harness": "...",              // supplies main(); declares the prototype

  "reference_solution": "...",     // plain, or:
  "reference_solution_b64": "...", // base64 — keeps it out of casual view

  "generator": {                 // optional; see Randomised test data
    "count": 4,                  // how many cases to add
    "source": "def generate(rng, count): ..."
  },

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

`tests` may be omitted entirely if a `generator` supplies the cases, though
most problems want at least the empty and single-element cases pinned down by
hand.

`statement` supports `# heading`, `## subheading`, `- bullet`,
`` `inline code` `` and ``` fenced blocks ```.

Fields are validated on load with messages aimed at the author — a malformed
file is listed in a warning dialog and skipped, never crashing the app.

**`hidden`** defaults to `false` and shipped problems do not use it. It exists
for the case where you want a held-out case to discourage hard-coding; hidden
cases still run and still count, and are labelled as hidden in the list. The
learning-aid default is that everything is shown.

Guides are not part of the schema. Drop `<id>.hint.html` and
`<id>.solution.html` beside the JSON — see
[Hints and worked solutions](#hints-and-worked-solutions) — and `--guides`
tells you which problems you have not got round to yet.

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

`crucible/languages/csharp_lang.py` sits between the two: like C, it produces
a genuine linked artifact (`dotnet build`, with a generated, throwaway
`.csproj` standing in for a compiler invocation's list of flags); like
Python, `detect_toolchain` is a single well-known executable search with no
environment-capture step, because the .NET SDK — unlike MSVC — needs nothing
beyond its own install directory to run.

`crucible/languages/cpp_lang.py` is C's near-twin: same GCC/Clang/MSVC
family, same two-translation-units split, same `/D_CRT_SECURE_NO_WARNINGS`
noise-filtering under MSVC — different enough only in which compiler names
it searches for and which flags it passes (`-std=c++17`, `/EHsc` for MSVC's
exception model) that the two do not just share code, they share a whole
module: `crucible/languages/native_compiler.py` holds every piece of
compiler-discovery and MSVC-environment-capture logic once, imported by
both `c_lang.py` and `cpp_lang.py`, because there is exactly one MSVC
toolchain and one captured environment per machine, not one per language
that happens to use it.

`crucible/languages/java_lang.py` looks like neither: there is no shared
native-compiler infrastructure to reuse, because locating a JDK is a
different kind of search entirely (`javac` on `PATH`, then `JAVA_HOME`, then
versioned install directories) with its own small pitfall worth knowing about
— see [Installing a JDK](#installing-a-jdk) for why `java` is read from
right beside the `javac` that was found rather than resolved independently.
Its harness/solution split works differently too: Java requires a file's
*public* top-level class to match the filename, so `Harness.java` declares
a package-private `class Harness` instead of a public one, which is exactly
what lets it sit next to a file named after its role rather than a class
inside it.

## Internationalisation

Every string the app or the CLI shows -- window titles, menu labels, dialog
text, status messages, validation errors, `--help` output -- is looked up by a
stable key rather than written inline where it is displayed:

```python
from .i18n import t

print(t("cli.toolchains.heading"))
label = t("app.pane.problems.title")
raise ProblemError(t("problem.error.unknown_difficulty",
                      file=path.name, difficulty=difficulty, choices=choices))
```

`crucible/i18n.py` is the whole mechanism: `t(key, **kwargs)` walks the key's
dotted path (`"app.menu.file.title"` → `data["app"]["menu"]["file"]["title"]`)
through the active locale's JSON file under `crucible/locales/`, formats the
result with `str.format(**kwargs)`, and hands back a string. There is exactly
one locale today, British English (`en_GB`), which doubles as the fallback of
last resort: a key missing from some future locale falls back to the `en_GB`
text rather than showing a blank label, but a key missing from `en_GB` itself
-- or a template whose placeholders do not match the keyword arguments it was
called with -- raises `TranslationError`. That asymmetry is deliberate: a
translation gap is recoverable by falling back to English, but a key that does
not exist anywhere, or a call site that got a placeholder wrong, is a bug in
the code that shipped it, and a shipped build should say so loudly rather than
show a raw dotted key or half-formatted text.

Keys are namespaced by where they are used -- `cli.*` for the command line,
`app.menu.*`, `app.banner.*`, `app.dialog.*` and so on for the GUI,
`problem.error.*` for schema-validation errors, `languages.c.*` for one
language plugin's own messages -- so a locale file, read top to bottom, is
roughly a map of the application, and two unrelated features are never
tempted to share one short phrase that later needs to drift apart.

**Adding a locale** is dropping `crucible/locales/<code>.json` with the same
keys as `en_GB.json` and switching to it:

```python
from crucible import i18n
i18n.set_locale("fr_FR")       # raises TranslationError if the file is missing
```

or by setting `CRUCIBLE_LOCALE=fr_FR` before launch. Nothing about the calling
code changes -- every call site already asks for a key, not for English text
-- and a locale that only translates *some* keys still works, falling back to
`en_GB` key by key rather than needing to be complete before it can ship.

**What is deliberately not in here**: problem statements, hints and worked
solutions. Those are authored, per-problem teaching content -- see
[Writing a problem](#writing-a-problem) -- not application chrome, and
translating fifty programming exercises is a different job with a different
owner than translating "Save draft" and "No compiler available". It is a
real job, though, not an unsupported one -- see "Translating a problem"
below for the separate, parallel mechanism that covers it.

### Translating a problem

A problem's prose -- `title`, `statement`, and each test's `name` and
`description` -- can be translated without touching `crucible/i18n.py` at
all, by dropping a sibling file next to the problem's JSON:

```
problems/csharp/cs_count_vowels.json
problems/csharp/cs_count_vowels.fr_FR.json     translated title/statement/tests
problems/csharp/cs_count_vowels.hint.fr_FR.html
problems/csharp/cs_count_vowels.solution.fr_FR.html
```

The locale is one more dotted qualifier on the filename, matching the
convention `crucible.guides` already uses for `.hint.html` /
`.solution.html`. `crucible.problem.load_problem` looks for
`<stem>.<locale>.json` when the active locale is not `en_GB`, and merges
whichever fields it finds -- `title`, `statement`, and per-test `name` /
`description`, matched to the base file's tests by position -- onto the
English original; a field the overlay omits (or every field, if there is no
overlay file at all) falls back to English, the same per-key fallback
`i18n.t` gives app strings. `starter_code`, `harness`, the generator and the
reference solution are never touched by an overlay: they are code, not
prose, in whatever language the problem itself is written in.
`crucible.guides.find` does the equivalent for the two guide pages,
preferring `<stem>.<kind>.<locale>.html` over the English page when a
translated one exists.

Translating a problem is optional and per-file -- a problem with no
overlay, or an overlay that only translates the statement and leaves the
tests in English, still loads and still works. Today only the C# problems
under `problems/csharp/` ship a French (`fr_FR`) translation; the other
languages' problems are untranslated, and stay that way until someone adds
the same sibling files for them.

## Command line

| Command | Does |
| --- | --- |
| `python -m crucible` | Open the GUI |
| `--verify` | Build a data set for every problem, then run every reference solution against its suite; exit 1 if any fail |
| `--list` | List loaded problems and their test counts |
| `--guides` | Report problems missing a hint or a worked-solution page; exit 1 if any are |
| `--toolchains` | Report which compilers were found and where |
| `--problems DIR` | Use a different problem directory |
| `--seed N` | Replay a particular data set instead of drawing a new one |

## Tests

```sh
python -m unittest discover -s tests -v
```

133 tests covering output normalisation and diff hints, problem-schema
validation (missing fields, bad base64, duplicate test names, unknown
languages, malformed JSON), the run pipeline (correct, wrong, syntax error,
runtime exception, timeout, progress callbacks), randomised data (determinism
per seed, expected output actually coming from the reference, generators that
raise, loop, print, return rubbish, or try to state the answer), data-set
storage, the language registry, and the C and C# diagnostic/exit-code helpers
that can be checked without a toolchain installed.

The guides are covered too: the lookup convention on its own, and then every
shipped page — both required ones exist, each names its problem, each links to
its counterpart, every relative link resolves off the disk, and a hint never
contains the whole reference solution. A diagram page must carry exactly one
Mermaid block, and that block must appear verbatim in the problem statement,
so the picture and the specification cannot drift apart.

The suite also asserts that every shipped reference solution passes its own
tests — including a freshly generated data set, which is what covers the
generators: one that emits input the reference cannot handle fails here, and so
does one whose input makes the reference answer differently on the second run
than it did when the expected output was captured. Problems whose toolchain is
missing are skipped *individually*, so one uninstalled compiler cannot silently
skip the rest.

`i18n` gets its own coverage: every key it resolves formats correctly, a key
absent from `en_GB` raises rather than returning a placeholder, and a
structural sweep of the locale file itself checks that every leaf is a
non-empty string -- catching a value that quietly became `""`, a number, or a
list in a hand edit, which passing JSON validation alone would not. One test
statically walks every `t("...")` call site in the package whose key is a
plain string literal and checks it actually resolves -- the source of truth
for "does this key exist" is the calling code, not a hand-maintained list
someone has to remember to update, so a typo'd key is caught here rather than
the first time a candidate clicks the one dialog that used it.

## Layout

```text
Crucible.cmd           Windows double-click launcher
crucible/
  __main__.py          entry point and CLI  (python -m crucible)
  problem.py           schema, loading, validation
  runner.py            build + execute + judge        (no UI)
  randomise.py         generators, and the reference-as-oracle
  workspace.py         drafts, data set numbers, settings -- profile-scoped
                       via a `root` argument, see profiles.py
  profiles.py          usernames, and per-profile solved-problem tracking
  guides.py            finds the hint / solution pages, opens them
  i18n.py              string lookup: t(key, **kwargs), locale fallback
  locales/
    en_GB.json         every user-facing string, the base locale
    fr_FR.json         full French translation of the app chrome
  languages/
    __init__.py        registry
    base.py            Language ABC, process runner, result types
    native_compiler.py compiler discovery + MSVC capture, shared by c/cpp
    c_lang.py          gcc / clang / cc / MSVC, toolchain discovery
    cpp_lang.py        g++ / clang++ / c++ / MSVC, C's near-twin
    python_lang.py     worked example of a second language
    csharp_lang.py     dotnet build, generated .csproj, native apphost
    java_lang.py       javac + java, JDK discovery (javac-then-JAVA_HOME)
  ui/
    app.py             main window
    editor.py          editor widget: gutter, highlighting, indentation
    panes.py           collapsible panes, and the sizing ttk will not do
    profile_dialog.py  the profile picker/switcher dialog
    theme.py           palettes and ttk styling
problems/
  guides.css           shared by every guide page
  c/                   42 problems, each with .json + .hint.html
  cpp/                 12 problems,            + .solution.html
  python/              3 problems,             + .solution.html
  csharp/              15 problems,            + .solution.html (+ fr_FR)
  java/                12 problems,            + .solution.html
  uml/                 2 problems,             + .diagram.html
  safety/              3 problems
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

## License

[MIT](LICENSE) — covers the application and everything under `problems/`.
