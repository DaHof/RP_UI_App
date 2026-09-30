"""Run an external command safely and return a structured result.

The repo has no shared helper for this. The one correct implementation is
``IRDiagnosticService._run_command`` in ``src/ir/diagnostics.py``, but it is
private, returns a bare tuple, and is wired into eight steps of the live Tkinter
tool -- refactoring it to share would put the working app at risk for no gain.
This duplicates its exception handling instead, which is the part worth copying.

Two rules this module exists to enforce:

* **It never raises.** A probe that explodes would take down the health snapshot
  that the whole dashboard polls.
* **It never uses a shell.** ``argv`` is always a list, so nothing that reaches
  here can be interpreted as shell syntax.

Note that ``LircClient`` and ``BlueZClient`` elsewhere in the repo call
``subprocess`` without a timeout, so they can hang indefinitely. Nothing on a
request path should call them directly.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

import sim

IS_LINUX = sys.platform.startswith("linux")


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    code: int
    stdout: str = ""
    stderr: str = ""
    missing: bool = False       # binary not on PATH
    timed_out: bool = False
    unsupported: bool = False   # Linux-only command on a non-Linux host
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.code == 0 and not (self.missing or self.timed_out or self.unsupported)

    @property
    def detail(self) -> str:
        """One short line suitable for a probe's detail field."""
        if self.unsupported:
            return f"{self.argv[0]} is Linux-only; not available on this host"
        if self.missing:
            return f"{self.argv[0]} not installed"
        if self.timed_out:
            return f"{self.argv[0]} timed out"
        if self.ok:
            return self.stdout.splitlines()[0] if self.stdout else "ok"
        return (self.stderr or self.stdout or f"exit {self.code}").splitlines()[0]


def run(cmd: list[str], timeout: float = 3.0, *, linux_only: bool = True) -> CommandResult:
    """Execute ``cmd`` and describe what happened. Never raises."""
    argv = tuple(cmd)
    started = time.monotonic()

    def done(code: int, out: str = "", err: str = "", **flags) -> CommandResult:
        return CommandResult(
            argv=argv,
            code=code,
            stdout=out.strip(),
            stderr=err.strip(),
            duration_ms=int((time.monotonic() - started) * 1000),
            **flags,
        )

    if not argv:
        return done(1, err="No command given.")

    # Simulation is checked before the platform guard, so canned Pi output is
    # reachable from a dev machine.
    canned = sim.command(list(argv))
    if canned is not None:
        code, out, err = canned
        return done(code, out, err, missing=(code == 127))

    if linux_only and not IS_LINUX:
        return done(127, err=f"{argv[0]} is Linux-only.", unsupported=True)

    if shutil.which(argv[0]) is None:
        return done(127, err="Command not found.", missing=True)

    try:
        proc = subprocess.run(list(argv), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return done(127, err="Command not found.", missing=True)
    except PermissionError as exc:
        return done(126, err=f"Permission denied: {exc}")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = exc.stderr if isinstance(exc.stderr, str) else "Timed out."
        return done(124, out, err, timed_out=True)
    except OSError as exc:
        return done(125, err=str(exc))
    except Exception as exc:  # never let a probe take down the snapshot
        return done(1, err=f"{type(exc).__name__}: {exc}")

    return done(proc.returncode, proc.stdout or "", proc.stderr or "")


def which(binary: str) -> bool:
    """True if ``binary`` is runnable here (honouring simulation)."""
    if sim.active():
        code, _, _ = sim.command([binary]) or (127, "", "")
        return code != 127
    return shutil.which(binary) is not None
