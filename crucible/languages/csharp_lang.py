"""C# language support.

Submissions are compiled as part of a small, disposable SDK-style project
built fresh in the workdir on every submission:

    solution.cs    <- exactly what the candidate typed, byte for byte
    harness.cs     <- problem-supplied Main(); declares the signature it needs
    crucible.csproj <- generated here, never shown to the candidate

Both source files land in one assembly the same way C's two translation units
land in one executable, and for the same reason: a candidate cannot
accidentally redefine `Main`, and compiler diagnostics carry the real
filename and line number the editor shows.

`dotnet build` rather than a bare `csc` invocation, because the SDK is what
resolves which reference assemblies a plain compiler invocation would
otherwise need spelled out by hand -- the project file is the whole of that
argument, regenerated identically every time rather than templated by a
project-creation step that could drift from it. The first build on a given
machine restores the SDK's own reference packages into the shared NuGet
cache (a few seconds); every build after that, in whatever fresh temp
directory, reuses the cache and is fast.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..i18n import t
from .base import BuildResult, Language, ToolchainStatus, run_process, _NO_WINDOW

_IS_WINDOWS = platform.system() == "Windows"
_EXE = ".exe" if _IS_WINDOWS else ""

#: Places `dotnet` commonly lands but which are occasionally missing from
#: PATH -- the official installers normally add it themselves, so this is a
#: rarer fallback than the equivalent list for a C compiler.
_WINDOWS_HINTS = (r"C:\Program Files\dotnet", r"C:\Program Files (x86)\dotnet")
_POSIX_HINTS = ("/usr/local/share/dotnet", "/usr/share/dotnet", "/opt/dotnet")

#: A stable, long-term-support target framework rather than whatever the
#: newest installed SDK defaults to -- the same submission should build the
#: same way next year, on a machine with a newer SDK alongside it.
_TARGET_FRAMEWORK = "net8.0"
_ASSEMBLY_NAME = "prog"

_CSPROJ = f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>{_TARGET_FRAMEWORK}</TargetFramework>
    <LangVersion>latest</LangVersion>
    <Nullable>disable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
    <AssemblyName>{_ASSEMBLY_NAME}</AssemblyName>
    <InvariantGlobalization>true</InvariantGlobalization>
  </PropertyGroup>
</Project>
'''


def _install_help() -> str:
    return t("languages.csharp.install_help_windows" if _IS_WINDOWS
             else "languages.csharp.install_help_posix")


#: One link works for every platform here -- unlike the GCC-family remedies,
#: which fork into "here is a zip" on Windows and "here is a package manager
#: command" on POSIX, the .NET SDK's own download page already does that
#: fork itself.
_DOTNET_DOWNLOAD_URL = "https://dotnet.microsoft.com/download"


def _which_dotnet() -> str | None:
    """`shutil.which`, falling back to well known install directories."""
    found = shutil.which("dotnet")
    if found:
        return found
    hints = _WINDOWS_HINTS if _IS_WINDOWS else _POSIX_HINTS
    for hint in hints:
        candidate = Path(hint) / ("dotnet" + _EXE)
        if candidate.is_file():
            return str(candidate)
    return None


def _probe_version(dotnet: str) -> str:
    """`dotnet --version` -- and, deliberately, nothing more forgiving than
    that. A runtime-only install (no SDK) has a `dotnet` on PATH that runs
    applications perfectly well but exits non-zero here with no version
    printed, which is exactly the distinction `detect_toolchain` needs: a
    working `dotnet` is not the same claim as a working *build*.
    """
    try:
        proc = subprocess.run(
            [dotnet, "--version"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    first = (proc.stdout or "").strip().splitlines()
    return first[0] if first else ""


class CSharpLanguage(Language):
    id = "csharp"
    display_name = "C#"
    solution_filename = "solution.cs"
    harness_filename = "harness.cs"
    line_comment = "//"
    keywords = (
        "abstract", "as", "base", "bool", "break", "byte", "case", "catch",
        "char", "checked", "class", "const", "continue", "decimal", "default",
        "delegate", "do", "double", "else", "enum", "event", "explicit",
        "extern", "false", "finally", "fixed", "float", "for", "foreach",
        "goto", "if", "implicit", "in", "int", "interface", "internal", "is",
        "lock", "long", "namespace", "new", "null", "object", "operator",
        "out", "override", "params", "private", "protected", "public",
        "readonly", "record", "ref", "return", "sbyte", "sealed", "short",
        "sizeof", "static", "string", "struct", "switch", "this", "throw",
        "true", "try", "typeof", "uint", "ulong", "unchecked", "unsafe",
        "ushort", "using", "var", "virtual", "void", "volatile", "while",
        "yield", "async", "await",
    )

    def __init__(self) -> None:
        super().__init__()
        self._dotnet: str | None = None

    # -- toolchain -----------------------------------------------------------

    def detect_toolchain(self) -> ToolchainStatus:
        self._dotnet = None
        dotnet = _which_dotnet()
        if not dotnet:
            return ToolchainStatus(
                available=False,
                summary=t("languages.csharp.summary_not_found"),
                detail=t("languages.csharp.detail_not_found"),
                remedy=_install_help(),
                download_url=_DOTNET_DOWNLOAD_URL,
            )

        version = _probe_version(dotnet)
        if not version:
            return ToolchainStatus(
                available=False,
                summary=t("languages.csharp.summary_no_sdk"),
                detail=t("languages.csharp.detail_no_sdk", path=dotnet),
                remedy=_install_help(),
                download_url=_DOTNET_DOWNLOAD_URL,
            )

        self._dotnet = dotnet
        return ToolchainStatus(
            available=True,
            summary=t("languages.csharp.summary", version=version),
            detail=t("languages.csharp.detail", path=dotnet),
        )

    # -- build -----------------------------------------------------------------

    def build(self, workdir: Path, solution: str, harness: str) -> BuildResult:
        status = self.toolchain()
        if not status.available or not self._dotnet:
            return BuildResult(ok=False, output=status.remedy or status.detail)

        (workdir / self.solution_filename).write_text(solution, encoding="utf-8")
        (workdir / self.harness_filename).write_text(harness, encoding="utf-8")
        (workdir / "crucible.csproj").write_text(_CSPROJ, encoding="utf-8")

        out_dir = workdir / "bin"
        command = [self._dotnet, "build", "-c", "Release", "-o", str(out_dir),
                  "--nologo", "-v", "quiet"]

        started = time.perf_counter()
        # A generous timeout: the very first build on a machine also restores
        # the SDK's reference packages into the shared NuGet cache, which can
        # take longer than a candidate's actual compile ever will again.
        result = run_process(command, workdir, timeout=90)
        elapsed = time.perf_counter() - started

        if result.launch_error:
            return BuildResult(ok=False, output=result.launch_error,
                               command=" ".join(command), duration=elapsed)

        raw = "\n".join(part for part in (result.stdout, result.stderr)
                        if part.strip())
        raw = raw.replace(str(workdir) + os.sep, "").replace(str(workdir), "")
        output = self.clean_diagnostics(self._strip_msbuild_noise(raw))

        apphost = out_dir / (_ASSEMBLY_NAME + _EXE)
        dll = out_dir / f"{_ASSEMBLY_NAME}.dll"
        ok = result.exit_code == 0 and dll.is_file()
        if result.timed_out:
            ok, output = False, t("languages.csharp.build_timeout")
        artifact = None
        if ok:
            artifact = apphost if apphost.is_file() else dll
        return BuildResult(
            ok=ok,
            output=output.strip(),
            command=" ".join(command),
            artifact=artifact,
            duration=elapsed,
        )

    def exec_command(self, workdir: Path, build: BuildResult) -> list[str]:
        # The native apphost (`prog.exe` / `prog`) starts noticeably faster
        # than going through `dotnet <dll>`, which pays its own CLI-parsing
        # cost on top of the same runtime start-up -- worth preferring
        # whenever the SDK produced one, which is the default on every
        # platform this app targets.
        if build.artifact is not None and build.artifact.suffix != ".dll":
            return [str(build.artifact)]
        dll = build.artifact or (workdir / "bin" / f"{_ASSEMBLY_NAME}.dll")
        return [self._dotnet or "dotnet", str(dll)]

    # -- diagnostics -------------------------------------------------------

    def clean_diagnostics(self, text: str) -> str:
        """Collapse `C:\\...\\temp\\crucible_x\\solution.cs(4,9): error CS...`
        down to `solution.cs(4,9): error CS...`, and drop the
        `[C:\\...\\crucible.csproj]` MSBuild appends to every diagnostic line --
        the project path is workdir-specific and never something the
        candidate can act on."""
        if not text:
            return ""
        for name in (self.solution_filename, self.harness_filename):
            text = re.sub(r"\S*[\\/]" + re.escape(name), name, text)
        text = re.sub(r" \[\S*crucible\.csproj\]", "", text)
        return text

    def _strip_msbuild_noise(self, text: str) -> str:
        """MSBuild reprints every error and warning a second time in its
        summary, and always adds a tally line and an elapsed-time line --
        none of which tells the candidate anything the first occurrence of
        each diagnostic did not."""
        seen: set[str] = set()
        kept: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if (stripped in ("Build succeeded.", "Build FAILED.")
                    or re.fullmatch(r"\d+ (Warning|Error)\(s\)", stripped)
                    or stripped.startswith("Time Elapsed")):
                continue
            if stripped in seen:
                continue
            seen.add(stripped)
            kept.append(line)
        return "\n".join(kept)

    def describe_exit(self, exit_code: int | None) -> str:
        """Turn a raw exit status into something a C# learner can act on."""
        if exit_code is None:
            return ""

        if _IS_WINDOWS:
            # The CLR's own unhandled-exception marker (COMPLUS_EXCEPTION,
            # 0xE0434352 -- "ECSharp" read loosely). Not a Windows NTSTATUS in
            # the usual sense, but reported through the same channel, so it is
            # checked the same way c_lang checks its own crash codes.
            if (exit_code & 0xFFFFFFFF) == 0xE0434352:
                return t("languages.csharp.exit.unhandled_exception")
            return t("languages.common.exited_with_status", code=exit_code)

        if exit_code == -6:
            return t("languages.csharp.exit.sigabrt")
        if exit_code < 0:
            return t("languages.csharp.exit.killed_by_signal", signal=-exit_code)
        return t("languages.common.exited_with_status", code=exit_code)
