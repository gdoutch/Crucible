"""VHDL support, driven by GHDL (https://github.com/ghdl/ghdl).

Every other language plugin in this package follows the same shape because
every other language *is* the same shape: a program that reads stdin and
writes stdout. VHDL is not a program -- an entity has ports, not a main(),
and the normal way to check one is a self-checking testbench that runs once
and asserts. That does not fit `Language.exec_command`, which returns one
fixed argv and lets `run_test` vary only the stdin fed to it.

The fit turns out to be exact anyway, because `std.textio` already predeclares
`input`/`output` file objects bound to the simulation process's real stdin and
stdout (`STD_INPUT`/`STD_OUTPUT` -- see the TEXTIO package body). So instead of
a self-checking testbench, the problem's harness is a thin testbench that:

  1. reads one line of stimulus from `std.textio.input`,
  2. drives it onto the candidate's entity through a port map,
  3. waits long enough for a combinational result to settle,
  4. writes the result to `std.textio.output`,
  5. calls `std.env.finish` (VHDL-2008).

One elaborated simulation binary, launched once per test case exactly like
every C or Python harness -- Crucible's existing pass/fail comparison against
`expected_stdout` never has to know it is looking at a circuit.

That mapping only covers *combinational* problems: whatever a test case's
stimulus is, the entity's ports settle to their final value within one fixed
delay and stay there. A clocked, stateful design (a counter, an FSM) needs a
waveform over many cycles per test case rather than one line of stdin, which
is a different execution model -- one this plugin does not attempt.

Layout mirrors every other compiled language here:

    solution.vhd  <- the candidate's entity + architecture, named `solution`
    harness.vhd   <- the problem-supplied testbench, entity `harness`

`solution` is instantiated from `harness` by direct entity instantiation
(`entity work.solution`), so there is no component declaration to keep in
step with the port list a problem asks for.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from ..i18n import t
from . import native_compiler as nc
from .base import BuildResult, ExecResult, Language, ToolchainStatus, run_process

#: The testbench's entity name is fixed by convention -- same idea as every
#: other plugin's fixed harness_filename, just one level up, since GHDL names
#: simulation units by entity name rather than by file.
_TOP_UNIT = "harness"

#: Matches only at the *start* of GHDL's own trailer line -- ".match", not
#: ".fullmatch" -- so a GHDL build that appends extra detail after the time
#: value (a process count, say) is still recognised as the same line.
_RUNTIME_TRAILER = re.compile(r"simulation finished @\S+")


def _strip_ghdl_runtime_noise(stdout: str) -> str:
    if not stdout:
        return stdout
    lines = stdout.splitlines(keepends=True)
    if lines and _RUNTIME_TRAILER.match(lines[-1]):
        lines.pop()
    return "".join(lines)

#: VHDL-2008 is what makes `std.env.finish` and direct entity instantiation
#: without a preceding component declaration both unconditionally available,
#: so every ghdl invocation below asks for it explicitly rather than trusting
#: whatever a given GHDL build defaults to.
_STD = "--std=08"


def _install_help() -> str:
    return t("languages.vhdl.install_help_windows" if nc.IS_WINDOWS
             else "languages.vhdl.install_help_posix")


#: The releases page has prebuilt Windows zips; on POSIX the remedy text's
#: package-manager commands need a terminal rather than a browser tab, the
#: same reasoning c_lang and cpp_lang use for their own download_url.
_RELEASES_URL = "https://github.com/ghdl/ghdl/releases"


class VhdlLanguage(Language):
    id = "vhdl"
    display_name = "VHDL"
    solution_filename = "solution.vhd"
    harness_filename = "harness.vhd"
    line_comment = "--"
    keywords = (
        "architecture", "array", "assert", "begin", "case", "component",
        "constant", "downto", "else", "elsif", "end", "entity", "exit",
        "for", "function", "generic", "generate", "if", "in", "inout",
        "is", "library", "loop", "map", "not", "null", "of", "others",
        "out", "port", "process", "procedure", "range", "record", "report",
        "return", "signal", "std_logic", "std_logic_vector", "subtype",
        "then", "to", "type", "use", "variable", "wait", "when", "while",
        "with", "and", "or", "xor", "nand", "nor", "xnor",
    )

    # -- toolchain -----------------------------------------------------

    def detect_toolchain(self) -> ToolchainStatus:
        path = nc.which("ghdl")
        if not path:
            return ToolchainStatus(
                available=False,
                summary=t("languages.vhdl.summary_not_found"),
                detail=t("languages.vhdl.detail_not_found"),
                remedy=_install_help(),
                download_url=_RELEASES_URL if nc.IS_WINDOWS else "",
            )
        version = nc.probe_version(path) or "ghdl"
        return ToolchainStatus(
            available=True,
            summary=t("languages.vhdl.summary", version=version),
            detail=t("languages.vhdl.detail", path=path),
        )

    # -- build -----------------------------------------------------------

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        status = self.toolchain()
        if not status.available:
            return BuildResult(ok=False, output=status.remedy or status.detail)
        ghdl = nc.which("ghdl")

        (workdir / self.solution_filename).write_text(solution, encoding="utf-8")
        (workdir / self.harness_filename).write_text(harness, encoding="utf-8")

        started = time.perf_counter()

        # Analysed in dependency order: the testbench instantiates `solution`
        # directly (`entity work.solution`), so its own analysis fails with a
        # confusing "unit not found" unless solution.vhd was analysed first.
        analyse_cmd = [ghdl, "-a", _STD,
                       self.solution_filename, self.harness_filename]
        analyse = run_process(analyse_cmd, workdir, timeout=30)
        if analyse.launch_error:
            return BuildResult(ok=False, output=analyse.launch_error,
                               command=" ".join(analyse_cmd),
                               duration=time.perf_counter() - started)
        if analyse.timed_out:
            return BuildResult(ok=False, output=t("languages.vhdl.build_timeout"),
                               command=" ".join(analyse_cmd),
                               duration=time.perf_counter() - started)
        if analyse.exit_code != 0:
            output = self.clean_diagnostics(analyse.stderr or analyse.stdout)
            return BuildResult(ok=False, output=output.strip(),
                               command=" ".join(analyse_cmd),
                               duration=time.perf_counter() - started)

        elaborate_cmd = [ghdl, "-e", _STD, _TOP_UNIT]
        elaborate = run_process(elaborate_cmd, workdir, timeout=30)
        elapsed = time.perf_counter() - started
        if elaborate.launch_error:
            return BuildResult(ok=False, output=elaborate.launch_error,
                               command=" ".join(elaborate_cmd), duration=elapsed)
        if elaborate.timed_out:
            return BuildResult(ok=False, output=t("languages.vhdl.build_timeout"),
                               command=" ".join(elaborate_cmd), duration=elapsed)
        if elaborate.exit_code != 0:
            output = self.clean_diagnostics(elaborate.stderr or elaborate.stdout)
            return BuildResult(ok=False, output=output.strip(),
                               command=" ".join(elaborate_cmd), duration=elapsed)

        return BuildResult(
            ok=True,
            command=f"{ghdl} -r {_STD} {_TOP_UNIT}",
            # Nothing to point at beyond "the elaborated design library that
            # now lives in workdir" -- ghdl -r finds it by name, not by path,
            # the same way `ghdl -r` always does.
            artifact=workdir,
            duration=elapsed,
        )

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        ghdl = nc.which("ghdl") or "ghdl"
        return [ghdl, "-r", _STD, _TOP_UNIT]

    def run_test(self, workdir: Path, build: BuildResult,
                stdin_data: str, timeout: float) -> ExecResult:
        """As `Language.run_test`, except GHDL's own runtime gets a word
        first.

        Every run that completes without being killed for time -- pass, fail
        or a caught assertion -- has GHDL append its own `simulation
        finished @<time>` line to stdout once the design goes quiet. That is
        not the testbench speaking; it is the simulator's own trailer, and
        left in it would fail every otherwise-correct submission's output
        comparison by exactly one extra line.
        """
        result = super().run_test(workdir, build, stdin_data, timeout)
        result.stdout = _strip_ghdl_runtime_noise(result.stdout)
        return result

    # -- diagnostics -------------------------------------------------------

    def clean_diagnostics(self, text: str) -> str:
        """Collapse `C:\\...\\temp\\crucible_x\\solution.vhd:12:5:` down to
        `solution.vhd:12:5:`, the same trick every compiled-language plugin
        here uses."""
        if not text:
            return ""
        for name in (self.solution_filename, self.harness_filename):
            text = re.sub(r"\S*[\\/]" + re.escape(name), name, text)
        return text

    def describe_exit(self, exit_code: int | None) -> str:
        """GHDL's own diagnostic -- an assertion failure, a bounds check, a
        `std.textio.read` that could not parse its input -- already lands in
        stderr as readable text, so there is no NTSTATUS/signal table to
        maintain here the way c_lang and asm_lang need. Only the fact that
        the run did not exit cleanly is worth adding."""
        if not exit_code:
            return ""
        return t("languages.vhdl.exit.runtime_error", code=exit_code)
