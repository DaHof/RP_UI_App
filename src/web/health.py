"""Background health monitor.

The header LEDs poll every few seconds, but the probes behind them are slow --
``rtl_test`` sweeps, ``pm3`` opens a serial port, and the IR boot diagnostic
alone takes about twelve seconds. Running any of that per request would make
the dashboard unusable.

So nothing is probed on the request path. One daemon thread refreshes a
snapshot on two cadences, and ``GET /api/health`` just hands back the current
dict. Reads are O(1); the polling rate is decoupled from probe cost entirely.

The IR diagnostic is excluded from the loop altogether. It is far too slow, and
the Tkinter app owns the same hardware -- so it runs only on explicit request,
behind a single-slot lock, and its last result is cached as a health channel.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import probes
import sim
from probes import FAIL, PASS, UNKNOWN, WARN, ProbeResult

FAST_INTERVAL = 5.0
SLOW_INTERVAL = 60.0
STALE_FACTOR = 3.0

# How many /proc/stat-derived samples the header's history bars keep. At one
# sample per FAST_INTERVAL tick, 20 bars span 100s -- recent enough to read as
# "now" without updating so often it's pointless over a 5s poll.
CPU_HISTORY_LEN = 20


def _read_cpu_times() -> tuple[int, int] | None:
    """(idle, total) jiffies from /proc/stat's aggregate ``cpu`` line.

    Linux-only, which is fine here: this file's whole reason to exist is
    polling Pi-only hardware (``vcgencmd``, ``i2cdetect``, ...), so a box
    without ``/proc/stat`` already can't run most of what's around it.
    """
    try:
        with open("/proc/stat", encoding="ascii") as f:
            line = f.readline()
        parts = [int(x) for x in line.split()[1:]]
        idle = parts[3] + parts[4]  # idle + iowait
        return idle, sum(parts)
    except Exception:
        return None


def _overall(statuses: list[str]) -> str:
    """FAIL dominates, then WARN -- matching ``diagnostics.py:_overall_status``."""
    if FAIL in statuses:
        return FAIL
    if WARN in statuses or UNKNOWN in statuses:
        return WARN
    return PASS


class HealthMonitor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: dict[str, ProbeResult] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

        self._ir_lock = threading.Lock()
        self._ir_result: dict | None = None

        self._cpu_prev: tuple[int, int] | None = None
        self._cpu_history: list[float] = []

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def wait_ready(self, timeout: float = 10.0) -> bool:
        """Block until the first full sweep lands, so the boot splash has data."""
        return self._ready.wait(timeout)

    def _loop(self) -> None:
        self.refresh(probes.FAST)
        self.refresh(probes.SLOW)
        self._sample_cpu()
        self._ready.set()

        last_slow = time.monotonic()
        while not self._stop.wait(FAST_INTERVAL):
            self.refresh(probes.FAST)
            self._sample_cpu()
            if time.monotonic() - last_slow >= SLOW_INTERVAL:
                self.refresh(probes.SLOW)
                last_slow = time.monotonic()

    def _sample_cpu(self) -> None:
        """Append one CPU-busy% sample, derived from the /proc/stat delta
        since the last tick -- the first tick after start has no prior
        reading to diff against, so it contributes nothing yet."""
        current = _read_cpu_times()
        if current is None:
            return
        prev = self._cpu_prev
        self._cpu_prev = current
        if prev is None:
            return
        idle_delta = current[0] - prev[0]
        total_delta = current[1] - prev[1]
        if total_delta <= 0:
            return
        busy_pct = max(0.0, min(100.0, 100.0 * (1 - idle_delta / total_delta)))
        with self._lock:
            self._cpu_history.append(round(busy_pct, 1))
            del self._cpu_history[:-CPU_HISTORY_LEN]

    # -- probing -----------------------------------------------------------

    def refresh(self, tier: str | None = None) -> None:
        targets = [p for p in probes.PROBES if tier is None or p.tier == tier]
        for probe in targets:
            result = probes.run_probe(probe)
            with self._lock:
                self._results[probe.name] = result

    def refresh_all(self) -> None:
        self.refresh(None)

    # -- reading -----------------------------------------------------------

    def snapshot(self) -> dict:
        now = datetime.now(timezone.utc)
        with self._lock:
            results = dict(self._results)

        channels = []
        for probe in probes.PROBES:
            result = results.get(probe.name)
            if result is None:
                channels.append(
                    {
                        "name": probe.name,
                        "label": probe.label,
                        "ok": False,
                        "status": UNKNOWN,
                        "detail": "Not probed yet",
                        "checked_at": None,
                        "duration_ms": 0,
                        "stale": True,
                    }
                )
                continue

            interval = FAST_INTERVAL if probe.tier == probes.FAST else SLOW_INTERVAL
            age = (now - datetime.fromisoformat(result.checked_at)).total_seconds()
            entry = result.as_dict()
            entry["stale"] = age > interval * STALE_FACTOR
            channels.append(entry)

        ir = self._ir_snapshot()
        if ir:
            channels.append(ir)

        with self._lock:
            cpu_history = list(self._cpu_history)

        return {
            "status": _overall([c["status"] for c in channels]),
            "checked_at": now.isoformat(timespec="seconds"),
            "simulated": sim.active(),
            "sim_mode": sim.mode(),
            "channels": channels,
            "cpu_history": cpu_history,
        }

    # -- IR diagnostic (explicit, slow, single-slot) ------------------------

    def _ir_snapshot(self) -> dict | None:
        with self._ir_lock:
            cached = self._ir_result
        if cached is None:
            return None
        return {
            "name": "ir_diagnostic",
            "label": "IR self-test",
            "ok": cached["status"] == PASS,
            "status": cached["status"],
            "detail": cached["summary"],
            "checked_at": cached["timestamp"],
            "duration_ms": cached.get("duration_ms", 0),
            "stale": False,
        }

    @property
    def ir_busy(self) -> bool:
        return self._ir_lock.locked()

    @property
    def ir_result(self) -> dict | None:
        return self._ir_result

    def run_ir_diagnostic(self) -> dict | None:
        """Run the Tkinter app's IR boot diagnostic. None if one is already running.

        Uses ``run_boot_diagnostic`` deliberately -- ``run_settings_diagnostic``
        blocks waiting on interactive prompts meant for a desktop message box.
        """
        if not self._ir_lock.acquire(blocking=False):
            return None
        started = time.monotonic()
        try:
            try:
                from ir.diagnostics import IRDiagnosticService
            except Exception as exc:
                result = {
                    "status": UNKNOWN,
                    "summary": f"IR diagnostics unavailable: {exc}",
                    "steps": [],
                    "devices": [],
                    "suggested_fixes": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "duration_ms": 0,
                }
                self._ir_result = result
                return result

            try:
                outcome = IRDiagnosticService().run_boot_diagnostic()
                result = {
                    "status": outcome.status,
                    "summary": outcome.summary_line(),
                    "steps": [
                        {"name": s.name, "status": s.status, "details": s.details}
                        for s in outcome.steps
                    ],
                    "devices": list(outcome.devices),
                    "suggested_fixes": list(outcome.suggested_fixes),
                    "timestamp": outcome.timestamp,
                }
            except Exception as exc:
                result = {
                    "status": UNKNOWN,
                    "summary": f"IR diagnostic crashed: {type(exc).__name__}: {exc}",
                    "steps": [],
                    "devices": [],
                    "suggested_fixes": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
            result["duration_ms"] = int((time.monotonic() - started) * 1000)
            self._ir_result = result
            return result
        finally:
            self._ir_lock.release()


monitor = HealthMonitor()
