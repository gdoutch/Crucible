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
- [How a submission is run](#how-a-submission-is-run)
- [The reference-solution gate](#the-reference-solution-gate)
- [Randomised test data](#randomised-test-data)
- [Hints and worked solutions](#hints-and-worked-solutions)
- [What is in the box](#what-is-in-the-box)
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
│           │ ▾ RESULTS                                     ⤢  │
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
**Tab** / **Shift+Tab** indent and dedent the selection.

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

41 problems — 37 in C, 4 in Python. Every one of them mixes hand-written edge
cases with four randomised ones, and ships a hint and a worked solution.

The C set is deliberately weighted towards the things C makes you think about
and other languages do not: what the pointer points at, who owns the memory,
what happens at the boundary, and what the standard actually promises.

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
| | Python | Two Sum | dictionaries, arrays |
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
| | C | Linear Interpolation Over a Calibration Table | embedded, calibration, fixed-point, lookup-table |
| | C | Multiply Two Q15 Fixed-Point Numbers | embedded, fixed-point, arithmetic |
| | C | Single-Producer/Single-Consumer Ring Buffer | embedded, data-structures, concurrency |
| | C | Add Hysteresis to a Noisy Threshold (Schmitt Trigger) | embedded, signal-processing, state |
| | C | A Shift-Based Low-Pass Filter (No Floats) | embedded, signal-processing, bitwise, fixed-point |
| | Python | Balanced Brackets | stacks, strings, parsing |
| | Python | Run-Length Encoding | strings, iteration |
| **hard** | C | Maximum Subarray Sum | algorithms, dynamic programming, arrays |
| | C | Reverse a Linked List | pointers, linked lists |
| | C | Edit Distance | dynamic programming, strings |
| | C | Extract a Signed Sensor Reading | bitwise, embedded, sign-extension, twos-complement |
| | C | Unpack a CAN Signal (Intel Byte Order) | embedded, can-bus, bitwise, sign-extension |
| | C | Validate a CAN Message's Rolling Counter and Checksum | embedded, can-bus, functional-safety, state |

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
  an x-difference *before* dividing — comfortably past `INT_MAX` on a
  realistic-sized table unless that intermediate product is widened to 64
  bits first.
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
  "difficulty": "easy",          // easy | medium | hard
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

89 tests covering output normalisation and diff hints, problem-schema
validation (missing fields, bad base64, duplicate test names, unknown
languages, malformed JSON), the run pipeline (correct, wrong, syntax error,
runtime exception, timeout, progress callbacks), randomised data (determinism
per seed, expected output actually coming from the reference, generators that
raise, loop, print, return rubbish, or try to state the answer), data-set
storage, the language registry, and the C diagnostic/exit-code helpers that can
be checked without a compiler.

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
  languages/
    __init__.py        registry
    base.py            Language ABC, process runner, result types
    c_lang.py          gcc / clang / cc / MSVC, toolchain discovery
    python_lang.py     worked example of a second language
  ui/
    app.py             main window
    editor.py          editor widget: gutter, highlighting, indentation
    panes.py           collapsible panes, and the sizing ttk will not do
    profile_dialog.py  the profile picker/switcher dialog
    theme.py           palettes and ttk styling
problems/
  guides.css           shared by every guide page
  c/                   33 problems, each with .json + .hint.html
  python/              3 problems,             + .solution.html
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
