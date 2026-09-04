"""x86-64 assembly support, MASM flavour (`ml64.exe`, Microsoft x64 ABI).

Submissions are assembled as a *separate translation unit* from the problem's
harness, the same split every other compiled language here uses:

    solution.asm  <- exactly what the candidate typed, byte for byte
    harness.c     <- problem-supplied main(); declares the prototype it needs

The harness stays C. Nothing in the app requires a problem's harness to be
written in the problem's own language -- `harness` is just a string in the
JSON -- and reading stdin, parsing integers and printing results in assembly
would be a page of boilerplate wrapped around the two lines that are actually
the exercise. So the candidate writes one procedure with a C signature, and C
does the talking.

That also means this plugin needs *two* tools, not one: `ml64` to assemble the
submission and `cl` to compile the harness and link the pair. Both come out of
the same Visual Studio install and the same captured vcvars environment that
`native_compiler` already knows how to find for `c_lang` and `cpp_lang` -- so
locating a toolchain here is mostly a matter of asking for that environment
and looking in it.

Why the id names a target rather than just saying "assembly"
------------------------------------------------------------
A C problem is written once and runs everywhere. An assembly problem is not:
the syntax (MASM vs GAS vs NASM), the calling convention (Microsoft x64 passes
the first four integer arguments in rcx, rdx, r8, r9; System V uses rdi, rsi,
rdx, rcx) and the instruction set itself (x86-64 vs ARM64) all differ, and a
submission written against one combination is not merely unidiomatic on
another -- it does not assemble.

Rather than teach the problem format about targets, each target is simply its
own language: `asm_x64_masm` here, with room beside it for `asm_x64_gas` or
`asm_arm64` later. Problems already select a language by id and live in a
directory per language, so a second target costs a subclass and a directory,
and nothing in the loader, the runner or the UI has to learn what a "target"
is. A machine that cannot host a target reports its toolchain unavailable,
which is a state the app already understands and displays.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import time
from pathlib import Path

from .. import workspace
from ..i18n import t
from . import native_compiler as nc
from .base import BuildResult, ExecResult, Language, ToolchainStatus, run_process

#: The host this target can be built and run on. `ml64` emits Microsoft x64
#: objects, and the executable they link into is x86-64 -- so the check is
#: about the machine, not merely about whether an assembler happens to exist.
#: Without it, a machine with a Visual Studio install but a different
#: architecture would claim it could build these problems and then fail every
#: one of them in a way that looks like the candidate's fault.
_X86_64 = ("AMD64", "x86_64")


def _install_help() -> str:
    return t("languages.asm_x64_masm.install_help")


class AsmX64MasmLanguage(Language):
    id = "asm_x64_masm"
    display_name = "x86-64 Assembly (MASM)"
    solution_filename = "solution.asm"
    harness_filename = "harness.c"
    line_comment = ";"
    #: Mnemonics, registers and directives, for the editor's highlighter.
    #: MASM itself is case-insensitive; the highlighter matches exactly, so
    #: the forms people actually type are listed -- lower case for
    #: instructions and registers, both cases for the directives, which are
    #: conventionally shouted.
    keywords = (
        # control flow
        "call", "ret", "jmp", "je", "jne", "jz", "jnz", "jg", "jge", "jl",
        "jle", "ja", "jae", "jb", "jbe", "js", "jns", "jc", "jnc", "loop",
        # data movement
        "mov", "movzx", "movsx", "movsxd", "lea", "push", "pop", "xchg",
        "cmovg", "cmovl", "cmove", "cmovne", "cmovge", "cmovle",
        # arithmetic and logic
        "add", "sub", "imul", "mul", "idiv", "div", "inc", "dec", "neg",
        "and", "or", "xor", "not", "shl", "shr", "sal", "sar", "rol", "ror",
        "cmp", "test", "cdq", "cqo", "setg", "setl", "sete", "setne",
        # operand-size keywords
        "byte", "word", "dword", "qword", "ptr", "offset", "short",
        "BYTE", "WORD", "DWORD", "QWORD", "PTR", "OFFSET", "SHORT",
        # registers
        "rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
        "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15",
        "eax", "ebx", "ecx", "edx", "esi", "edi", "ebp", "esp",
        "r8d", "r9d", "r10d", "r11d", "r12d", "r13d", "r14d", "r15d",
        "ax", "bx", "cx", "dx", "al", "bl", "cl", "dl", "sil", "dil",
        # directives
        "PROC", "ENDP", "END", "PUBLIC", "EXTERN", "ALIGN", "EQU",
        "proc", "endp", "end", "public", "extern", "align", "equ",
        "code", "data", "const",
    )

    def __init__(self) -> None:
        super().__init__()
        self._ml64: str | None = None
        self._cl: str | None = None
        self._env: dict[str, str] = {}

    # -- toolchain ---------------------------------------------------------

    def detect_toolchain(self) -> ToolchainStatus:
        self._ml64 = None
        self._cl = None
        self._env = {}

        if not nc.IS_WINDOWS:
            return ToolchainStatus(
                available=False,
                summary=t("languages.asm_x64_masm.summary_not_windows"),
                detail=t("languages.asm_x64_masm.detail_not_windows",
                         system=platform.system()),
            )

        if platform.machine() not in _X86_64:
            return ToolchainStatus(
                available=False,
                summary=t("languages.asm_x64_masm.summary_wrong_arch"),
                detail=t("languages.asm_x64_masm.detail_wrong_arch",
                         machine=platform.machine()),
            )

        # A developer prompt already has both tools on PATH and the
        # environment they need; anything else means asking vcvars.
        ml64_on_path, cl_on_path = shutil.which("ml64"), shutil.which("cl")
        if ml64_on_path and cl_on_path:
            self._ml64, self._cl = ml64_on_path, cl_on_path
            return ToolchainStatus(
                available=True,
                summary=t("languages.asm_x64_masm.summary_current_env"),
                detail=t("languages.asm_x64_masm.detail_current_env",
                         ml64=ml64_on_path, cl=cl_on_path),
            )

        env = nc.msvc_environment()
        if env:
            ml64 = shutil.which("ml64", path=env.get("PATH", ""))
            cl = shutil.which("cl", path=env.get("PATH", ""))
            if ml64 and cl:
                self._ml64, self._cl, self._env = ml64, cl, env
                return ToolchainStatus(
                    available=True,
                    summary=t("languages.asm_x64_masm.summary"),
                    detail=t("languages.asm_x64_masm.detail", ml64=ml64, cl=cl),
                )
            if cl and not ml64:
                # Possible in principle -- the assembler is a separate file in
                # the toolset directory -- and worth naming precisely, because
                # a bare "no toolchain" would send someone off to install a
                # compiler they demonstrably already have.
                return ToolchainStatus(
                    available=False,
                    summary=t("languages.asm_x64_masm.summary_no_assembler"),
                    detail=t("languages.asm_x64_masm.detail_no_assembler", cl=cl),
                    remedy=_install_help(),
                )

        return ToolchainStatus(
            available=False,
            summary=t("languages.asm_x64_masm.summary_not_found"),
            detail=t("languages.asm_x64_masm.detail_not_found"),
            remedy=_install_help(),
        )

    # -- build -------------------------------------------------------------

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        status = self.toolchain()
        if not status.available or not self._ml64 or not self._cl:
            return BuildResult(ok=False, output=status.remedy or status.detail)

        (workdir / self.solution_filename).write_text(solution, encoding="utf-8")
        (workdir / self.harness_filename).write_text(harness, encoding="utf-8")
        obj = "solution.obj"
        exe = workdir / ("prog" + nc.EXE)

        assemble = [self._ml64, "/nologo", "/c", "/Fo", obj,
                    self.solution_filename]
        # /Z7 rather than /Zi, and no explicit /Fo for the harness: the same
        # reasoning as `c_lang` -- debug info goes in the object file so there
        # is no PDB for two translation units to contend over, and objects
        # land in the cwd, which is already workdir.
        #
        # No /TC here, though, which is where this parts company with
        # `c_lang`: /TC means "every input file is C source", and the inputs
        # here are one .c file and one .obj. cl would dutifully try to compile
        # the assembled object as C and bury the screen in syntax errors about
        # its binary contents. The harness is named .c, so it is compiled as C
        # on its extension alone, and the object goes to the linker untouched.
        link = [self._cl, "/nologo", "/W3", "/Od", "/Z7",
                # The harnesses use scanf/fgets, which MSVC calls "unsafe" in
                # favour of its non-portable _s variants. Without this every
                # correct submission comes back carrying warnings the
                # candidate did not cause and cannot fix.
                "/D_CRT_SECURE_NO_WARNINGS",
                f"/Fe:{exe.name}", self.harness_filename, obj]

        started = time.perf_counter()
        result = self._run_step(assemble, workdir)
        step = assemble
        if result.exit_code == 0 and not result.timed_out:
            # Only link once there is something to link. Running cl on a
            # missing .obj would bury the assembler's diagnostic -- the one
            # that actually names the line the candidate got wrong -- under a
            # linker error about a file it was never going to find.
            result = self._run_step(link, workdir)
            step = link
        elapsed = time.perf_counter() - started

        if result.launch_error:
            return BuildResult(ok=False, output=result.launch_error,
                               command=" ".join(step), duration=elapsed)

        raw = "\n".join(part for part in (result.stdout, result.stderr)
                        if part.strip())
        raw = raw.replace(str(workdir) + os.sep, "").replace(str(workdir), "")
        output = self.clean_diagnostics(self._strip_tool_noise(raw))
        ok = result.exit_code == 0 and exe.is_file()
        if result.timed_out:
            ok, output = False, t("languages.asm_x64_masm.build_timeout")
        return BuildResult(
            ok=ok,
            output=output.strip(),
            command=" ".join(step),
            artifact=exe if ok else None,
            duration=elapsed,
        )

    def _run_step(self, command: list[str], workdir: Path) -> ExecResult:
        """One build step, with the same stale-vcvars self-heal `c_lang`
        does: if the failure looks like a bad environment rather than bad
        code, recapture the environment and try the step once more."""
        result = run_process(command, workdir, timeout=60, env=self._env or None)
        if nc.is_stale_environment("msvc", self._env, result):
            self._recapture_environment()
            command = [self._resolved(command[0]), *command[1:]]
            result = run_process(command, workdir, timeout=60,
                                 env=self._env or None)
        return result

    def _resolved(self, tool: str) -> str:
        """Where a tool lives now, in case a recapture has moved it."""
        name = Path(tool).stem.lower()
        return {"ml64": self._ml64, "cl": self._cl}.get(name) or tool

    def _recapture_environment(self) -> None:
        """Discard the cached vcvars capture and take a fresh one."""
        workspace.clear_msvc_env()
        env = nc.msvc_environment(ignore_cache=True)
        if not env:
            return
        ml64 = shutil.which("ml64", path=env.get("PATH", ""))
        cl = shutil.which("cl", path=env.get("PATH", ""))
        if ml64 and cl:
            self._ml64, self._cl, self._env = ml64, cl, env

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        target = build.artifact or (workdir / ("prog" + nc.EXE))
        return [str(target)]

    # -- diagnostics -------------------------------------------------------

    def clean_diagnostics(self, text: str) -> str:
        """Collapse `C:\\...\\temp\\crucible_x\\solution.asm(4) : error` down
        to `solution.asm(4) : error`, so the line number the candidate is
        shown belongs to the file in front of them."""
        if not text:
            return ""
        for name in (self.solution_filename, self.harness_filename,
                     "solution.obj"):
            text = re.sub(r"\S*[\\/]" + re.escape(name), name, text)
        return text

    def _strip_tool_noise(self, text: str) -> str:
        """`ml64` announces each file as it assembles it and `cl` echoes each
        one as it compiles it. Neither tells the candidate anything, and both
        crowd out the diagnostic that does."""
        noise = {self.harness_filename, "Generating Code...",
                 f"Assembling: {self.solution_filename}"}
        return "\n".join(line for line in text.splitlines()
                         if line.strip() not in noise)

    def describe_exit(self, exit_code: int | None) -> str:
        """Turn a raw exit status into something an assembly learner can act
        on. Windows-only, unlike `c_lang`'s equivalent, because this target
        is: there is no POSIX signal path to cover.

        The faults worth naming are the ones hand-written assembly actually
        produces. A bad address in a `mov` is the usual one, and `idiv` is a
        trap all of its own -- it faults both on a zero divisor and, less
        obviously, when the quotient will not fit in the destination
        register, which is what INT_MIN / -1 does.
        """
        if exit_code is None:
            return ""
        status = {
            0xC0000005: t("languages.asm_x64_masm.exit.access_violation"),
            0xC0000094: t("languages.asm_x64_masm.exit.divide_by_zero"),
            0xC0000095: t("languages.asm_x64_masm.exit.integer_overflow"),
            0xC000001D: t("languages.asm_x64_masm.exit.illegal_instruction"),
            0xC00000FD: t("languages.asm_x64_masm.exit.stack_overflow"),
            0xC000013A: t("languages.asm_x64_masm.exit.interrupted"),
        }
        described = status.get(exit_code & 0xFFFFFFFF)
        return (t("languages.asm_x64_masm.exit.crashed", description=described)
                if described
                else t("languages.common.exited_with_status", code=exit_code))
