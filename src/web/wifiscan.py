"""Wi-Fi network scanner: lists nearby access points via ``iw scan``.

This is a plain managed-mode scan -- not the monitor-mode capture Kismet and
Wifite do. No promiscuous mode, no client/device tracking, just "what SSIDs
can this adapter see and how strong are they", the way any phone's Wi-Fi
settings screen works. That's a deliberate scope choice: client tracking over
monitor mode is already covered by the Kismet/Wifite tiles, and a single
stationary antenna can't give a real bearing on anything it sees anyway (the
same honesty problem flagged for the mmWave radar's evaluation) -- a signal
list avoids pretending otherwise.

Triggering a scan needs CAP_NET_ADMIN, which the dashboard's systemd service
does not have (it runs as a normal user, not root). Rather than wrap this one
call in sudo -- that pattern in launcher.py is for processes the dashboard
starts and stops as a deliberate privileged action, not an internal probe --
this expects the ``iw`` binary itself to carry the capability:

    sudo setcap cap_net_admin,cap_net_raw+eip "$(readlink -f "$(command -v iw)")"

scripts/install-tools.sh does this. Without it, a scan fails with "Operation
not permitted", which is reported back as a normal status, not raised.

Active scans take a few seconds, so -- like the IR boot diagnostic -- this
runs behind a single-slot lock and caches its last result. Nothing on a
request path blocks waiting for one; the frontend polls the cached snapshot
and separately triggers a scan when asked.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass

import shell

DEFAULT_IFACE = os.environ.get("WIFI_IFACE", "wlan0")
SCAN_TIMEOUT = 12.0

_BSS_RE = re.compile(r"^BSS ([0-9a-f:]{17})", re.IGNORECASE | re.MULTILINE)
_SIGNAL_RE = re.compile(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_SSID_RE = re.compile(r"^\tSSID:[ \t]?(.*)$", re.MULTILINE)
_FREQ_RE = re.compile(r"freq:\s*(\d+)")


def _freq_to_channel(freq_mhz: int) -> int | None:
    """Best-effort frequency -> channel number, 2.4/5/6 GHz. ``None`` for
    anything outside those ranges rather than guessing."""
    if freq_mhz == 2484:
        return 14
    if 2412 <= freq_mhz <= 2472:
        return (freq_mhz - 2412) // 5 + 1
    if 5955 <= freq_mhz <= 7115:
        return (freq_mhz - 5950) // 5 + 1
    if 5000 <= freq_mhz <= 5895:
        return (freq_mhz - 5000) // 5
    return None


def _security(block: str) -> str:
    """Coarse security label from the information elements iw prints --
    RSN is WPA2/WPA3 (iw doesn't distinguish them without -vv), bare WPA is
    WPA1, "Privacy" with neither is WEP, and its absence is an open network."""
    if "RSN:" in block:
        return "WPA2/3"
    if "WPA:" in block:
        return "WPA"
    if "Privacy" in block:
        return "WEP"
    return "Open"


@dataclass(frozen=True)
class Network:
    bssid: str
    ssid: str
    signal_dbm: float
    freq_mhz: int
    channel: int | None
    security: str

    def as_dict(self) -> dict:
        return {
            "bssid": self.bssid,
            "ssid": self.ssid or "(hidden)",
            "signal_dbm": self.signal_dbm,
            "freq_mhz": self.freq_mhz,
            "channel": self.channel,
            "band": "5/6 GHz" if self.freq_mhz >= 5000 else "2.4 GHz",
            "security": self.security,
        }


def parse_scan(stdout: str) -> list[Network]:
    """Parses ``iw dev <iface> scan`` output into networks, strongest first.

    Never raises: a BSS block missing a field this cares about is skipped
    rather than guessed at, matching every other parser in this dashboard.
    """
    networks: list[Network] = []
    # Split right before each "BSS " line so every chunk is one AP's block,
    # including its own BSS line -- re.split with a lookahead keeps it there.
    for block in re.split(r"(?=^BSS )", stdout, flags=re.MULTILINE):
        bss_match = _BSS_RE.match(block)
        signal_match = _SIGNAL_RE.search(block)
        freq_match = _FREQ_RE.search(block)
        if not (bss_match and signal_match and freq_match):
            continue
        ssid_match = _SSID_RE.search(block)
        freq_mhz = int(freq_match.group(1))
        networks.append(
            Network(
                bssid=bss_match.group(1).lower(),
                ssid=(ssid_match.group(1).strip() if ssid_match else ""),
                signal_dbm=float(signal_match.group(1)),
                freq_mhz=freq_mhz,
                channel=_freq_to_channel(freq_mhz),
                security=_security(block),
            )
        )
    networks.sort(key=lambda n: n.signal_dbm, reverse=True)
    return networks


class ScanService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scanning = False
        self._networks: list[dict] = []
        self._updated_at = 0.0
        self._error = ""
        self.iface = DEFAULT_IFACE

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scanning": self._scanning,
                "iface": self.iface,
                "networks": list(self._networks),
                "updated_at": self._updated_at,
                "error": self._error,
            }

    def scan(self) -> dict | None:
        """Runs one scan synchronously (call this from a threadpool -- it
        blocks for SCAN_TIMEOUT worst case). Returns ``None`` instead of
        running if a scan is already in flight, same single-slot gate as
        the IR boot diagnostic."""
        with self._lock:
            if self._scanning:
                return None
            self._scanning = True

        try:
            result = shell.run(["iw", "dev", self.iface, "scan"], timeout=SCAN_TIMEOUT)
            with self._lock:
                if result.ok:
                    self._networks = [n.as_dict() for n in parse_scan(result.stdout)]
                    self._error = ""
                else:
                    self._error = result.detail
                self._updated_at = time.time()
        finally:
            with self._lock:
                self._scanning = False
        return self.snapshot()


service = ScanService()
