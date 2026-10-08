"""Per-channel hardware probes and the parsers they share with /api/diagnostics.

Status strings are deliberately the same literals the Tkinter app's IR
diagnostics already uses -- ``PASS`` / ``WARN`` / ``FAIL`` (see
``src/ir/diagnostics.py``) -- so both front ends speak one vocabulary.
``UNKNOWN`` is added for "the probe itself blew up", which the IR service has no
concept of because it runs synchronously in front of a user.

Every probe is wrapped so it can never raise: a failing probe must degrade to a
red LED, not take down the snapshot the whole dashboard polls.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import hardware
import mmwave
import shell
import sim
import wifiscan

PASS, WARN, FAIL, UNKNOWN = "PASS", "WARN", "FAIL", "UNKNOWN"

FAST, SLOW = "fast", "slow"

# USB vendor/product fragments worth surfacing on the diagnostics screen.
USB_INTEREST = (
    ("rtl", "RTL-SDR"),
    ("realtek semiconductor corp. rtl", "RTL-SDR"),
    ("proxmark", "Proxmark3"),
    ("westhues", "Proxmark3"),
    ("magtek", "MSR605X"),
    ("0801:0003", "MSR605X"),
    ("nfc", "NFC"),
    ("acr122", "NFC"),
)

_THROTTLE_BITS = {
    0: "under-voltage",
    1: "ARM frequency capped",
    2: "currently throttled",
    3: "soft temperature limit",
    16: "under-voltage has occurred",
    17: "ARM frequency capping has occurred",
    18: "throttling has occurred",
    19: "soft temperature limit has occurred",
}


# --------------------------------------------------------------------------
# Parsers (shared with the diagnostics endpoint)
# --------------------------------------------------------------------------

def parse_i2c_addresses(stdout: str) -> list[str]:
    """Pull ``0xNN`` addresses out of an ``i2cdetect -y 1`` grid."""
    found: list[str] = []
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        _, _, cells = line.partition(":")
        for cell in cells.split():
            if re.fullmatch(r"[0-9a-fA-F]{2}", cell):
                found.append(f"0x{cell.lower()}")
    return found


def parse_temp_c(stdout: str) -> float | None:
    match = re.search(r"temp=([\d.]+)", stdout)
    return float(match.group(1)) if match else None


def decode_throttled(stdout: str) -> tuple[int, list[str]]:
    """``throttled=0x50005`` -> (raw, ['under-voltage', ...])."""
    match = re.search(r"throttled=0x([0-9a-fA-F]+)", stdout)
    if not match:
        return 0, []
    raw = int(match.group(1), 16)
    return raw, [label for bit, label in _THROTTLE_BITS.items() if raw & (1 << bit)]


def filter_usb(stdout: str) -> list[dict]:
    """Keep only ``lsusb`` lines matching hardware this tool cares about."""
    devices: list[dict] = []
    for line in stdout.splitlines():
        low = line.lower()
        for needle, label in USB_INTEREST:
            if needle in low:
                devices.append({"kind": label, "line": line.strip()})
                break
    return devices


# --------------------------------------------------------------------------
# Probe results
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeResult:
    name: str
    label: str
    status: str
    detail: str
    checked_at: str
    duration_ms: int

    @property
    def ok(self) -> bool:
        return self.status == PASS

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "ok": self.ok,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at,
            "duration_ms": self.duration_ms,
        }


# --------------------------------------------------------------------------
# The probes themselves. Each returns (status, detail).
# --------------------------------------------------------------------------

def _probe_pn532() -> tuple[str, str]:
    status = hardware.service.status
    if status.degraded:
        return FAIL, status.reason or "PN532 unavailable; using mock reader"
    if not status.started:
        return FAIL, status.reason or "Reader did not start"
    if not hardware.service.polling:
        return WARN, "Reader started but its poll thread is no longer running"

    if status.active == "mock":
        return PASS, "Mock reader active (no hardware required)"

    result = shell.run(["i2cdetect", "-y", "1"], timeout=2.0)
    if result.ok:
        addresses = parse_i2c_addresses(result.stdout)
        if "0x24" in addresses:
            return PASS, "PN532 present at 0x24 on I2C bus 1"
        return WARN, f"Reader running but 0x24 absent; saw {', '.join(addresses) or 'nothing'}"
    return PASS, "Hardware reader running"


def _probe_mmwave() -> tuple[str, str]:
    status = mmwave.service.status
    if status.degraded:
        return FAIL, status.reason or "LD2450 unavailable; using mock reader"
    if not status.started:
        return FAIL, status.reason or "Reader did not start"
    if not mmwave.service.polling:
        return WARN, "Reader started but its read thread is no longer running"

    if status.active == "mock":
        return PASS, "Mock reader active (no hardware required)"

    snapshot = mmwave.service.snapshot()
    port = getattr(mmwave.service.reader, "port", "?")
    if not snapshot["updated_at"]:
        return WARN, f"Listening on {port}; no frames seen yet"
    age = time.time() - snapshot["updated_at"]
    if age > 3.0:
        return WARN, f"Listening on {port}; last frame {age:.0f}s ago"
    return PASS, f"LD2450 live on {port} ({len(snapshot['targets'])} target(s))"


def _probe_sdr() -> tuple[str, str]:
    result = shell.run(["rtl_test", "-t"], timeout=4.0)
    if result.unsupported or result.missing:
        return FAIL, result.detail
    # rtl_test writes its device list to stderr as often as stdout, and returns
    # non-zero once it finishes its test sweep -- so look at the text, not code.
    blob = f"{result.stdout}\n{result.stderr}"
    if "No supported devices found" in blob:
        return FAIL, "No RTL-SDR device found"
    match = re.search(r"Found (\d+) device", blob)
    if match:
        if "Failed to open" in blob:
            return WARN, f"{match.group(1)} device(s) found but one could not be opened (in use?)"
        return PASS, f"{match.group(1)} device(s) found"
    return WARN, result.detail


def _probe_proxmark() -> tuple[str, str]:
    result = shell.run(["pm3", "--version"], timeout=4.0)
    if result.ok:
        first = result.stdout.splitlines()[0] if result.stdout else "pm3 present"
        return PASS, first
    return FAIL, result.detail


def _probe_msr605x() -> tuple[str, str]:
    """Presence only, via HID enumeration -- cheap enough for the FAST tier
    (no subprocess, no opening the device) and never contends with an
    in-flight read/write the way actually opening it would."""
    try:
        from msr.msr605x_client import is_present
    except Exception as exc:
        return UNKNOWN, f"MSR605X support not available: {exc}"
    return (PASS, "MSR605X detected") if is_present() else (FAIL, "No MSR605X detected")


def _probe_ir() -> tuple[str, str]:
    if not shell.which("irsend") and not shell.which("ir-ctl"):
        return FAIL, "Neither irsend nor ir-ctl is installed"
    result = shell.run(["systemctl", "is-active", "lircd"], timeout=2.0)
    if result.unsupported:
        return FAIL, result.detail
    state = (result.stdout or result.stderr or "unknown").strip()
    if state == "active":
        return PASS, "lircd active"
    return WARN, f"IR tooling present but lircd is {state}"


def _probe_wifi() -> tuple[str, str]:
    result = shell.run(["iw", "list"], timeout=4.0)
    if result.unsupported or result.missing:
        return FAIL, result.detail
    if not result.ok:
        return WARN, result.detail
    if re.search(r"^\s*\*\s*monitor\s*$", result.stdout, re.MULTILINE):
        return PASS, "Monitor mode supported"
    return WARN, "Adapter present but monitor mode not advertised"


def _probe_wifiscan() -> tuple[str, str]:
    snap = wifiscan.service.snapshot()
    if snap["error"]:
        hint = " -- see scripts/install-tools.sh's setcap step" if "not permitted" in snap["error"].lower() else ""
        return FAIL, f"{snap['error']}{hint}"
    if not snap["updated_at"]:
        return WARN, f"Not scanned yet ({snap['iface']})"
    if not snap["networks"]:
        return WARN, f"Scan ran but found nothing on {snap['iface']}"
    return PASS, f"{len(snap['networks'])} network(s) seen on {snap['iface']}"


def _probe_lanscan() -> tuple[str, str]:
    snap = wifiscan.lan_service.snapshot()
    if snap["error"]:
        hint = " -- see scripts/install-tools.sh's setcap step" if "permission" in snap["error"].lower() else ""
        return FAIL, f"{snap['error']}{hint}"
    if not snap["updated_at"]:
        return WARN, "Not scanned yet"
    if not snap["devices"]:
        return WARN, "Scan ran but found no devices"
    return PASS, f"{len(snap['devices'])} device(s) on the LAN"


def _probe_thermal() -> tuple[str, str]:
    temp_result = shell.run(["vcgencmd", "measure_temp"], timeout=2.0)
    if temp_result.unsupported or temp_result.missing:
        return FAIL, temp_result.detail

    temp = parse_temp_c(temp_result.stdout)
    throttle_result = shell.run(["vcgencmd", "get_throttled"], timeout=2.0)
    _, flags = decode_throttled(throttle_result.stdout)

    now_flags = [f for f in flags if "has occurred" not in f]
    if temp is None:
        return WARN, "Could not read CPU temperature"

    label = f"{temp:.1f} degC"
    if now_flags:
        return FAIL, f"{label} - {', '.join(now_flags)}"
    if temp >= 80:
        return FAIL, f"{label} - at or above throttle threshold"
    if temp >= 70 or flags:
        extra = f" - {', '.join(flags)}" if flags else ""
        return WARN, f"{label}{extra}"
    return PASS, label


@dataclass(frozen=True)
class Probe:
    name: str
    label: str
    fn: Callable[[], tuple[str, str]]
    tier: str


PROBES: tuple[Probe, ...] = (
    Probe("pn532", "PN532", _probe_pn532, FAST),
    Probe("mmwave", "mmWave Radar", _probe_mmwave, FAST),
    Probe("thermal", "CPU / Thermal", _probe_thermal, FAST),
    Probe("ir", "IR / LIRC", _probe_ir, FAST),
    Probe("msr605x", "MSR605X", _probe_msr605x, FAST),
    Probe("sdr", "RTL-SDR", _probe_sdr, SLOW),
    Probe("proxmark", "Proxmark3", _probe_proxmark, SLOW),
    Probe("wifi", "Wi-Fi monitor", _probe_wifi, SLOW),
    Probe("wifiscan", "Wi-Fi scanner", _probe_wifiscan, FAST),
    Probe("lanscan", "LAN devices", _probe_lanscan, FAST),
)

BY_NAME = {p.name: p for p in PROBES}


def run_probe(probe: Probe) -> ProbeResult:
    """Run one probe. Cannot raise; a crash becomes an UNKNOWN result."""
    started = time.monotonic()
    try:
        canned = sim.probe(probe.name)
        status, detail = canned if canned else probe.fn()
    except Exception as exc:
        status, detail = UNKNOWN, f"Probe crashed: {type(exc).__name__}: {exc}"
    return ProbeResult(
        name=probe.name,
        label=probe.label,
        status=status,
        detail=detail,
        checked_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
