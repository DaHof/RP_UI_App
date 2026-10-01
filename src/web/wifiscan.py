"""Wi-Fi network scanner, LAN device list, and (gated) per-AP client capture.

Three different capabilities live here, each with its own privilege model and
its own honesty constraints:

1. **Access point scan** (``ScanService``) -- a plain managed-mode ``iw scan``.
   SSID, signal, channel, security, nothing more. Needs ``iw`` to carry
   CAP_NET_ADMIN (scripts/install-tools.sh sets this up via setcap, the same
   reasoning as the module docstring originally had: wrapping one internal
   probe call in sudo is the wrong pattern for a capability the backend
   should just have).

2. **LAN device list** (``LanScanService``) -- a different thing entirely:
   who's on *your own* subnet right now, via ARP (``arp-scan``), not Wi-Fi at
   all. No monitor mode, works over Ethernet too. Needs ``arp-scan`` to carry
   CAP_NET_RAW, same setcap pattern as ``iw``.

3. **Per-AP client capture** (``ClientScanService``) -- who's *connected* to
   a specific AP. This is the one genuinely invasive capability here, because
   it requires monitor mode, and putting the dashboard's own network
   interface into monitor mode would disconnect the dashboard from itself (or
   the Pi from the network entirely, if Wi-Fi is how you reached it). So this
   never touches ``WIFI_IFACE``. It only runs against a *separately configured*
   interface named by ``WIFI_MONITOR_IFACE`` -- unset by default, meaning this
   feature does nothing until you deliberately point it at a second adapter
   you've already put into monitor mode yourself. This dashboard does not
   flip interface modes for you; that's exactly the kind of action that
   should require you to have typed the command and watched it happen.
   Capture itself shells out to ``airodump-ng`` (part of aircrack-ng, which
   Wifite already depends on) for a bounded burst and parses its CSV output --
   reusing a tool built for this instead of writing 802.11 frame parsing from
   scratch, the same reasoning that kept this module from reimplementing any
   part of Kismet.
"""

from __future__ import annotations

import os
import re
import socket
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import shell

DEFAULT_IFACE = os.environ.get("WIFI_IFACE", "wlan0")
MONITOR_IFACE = os.environ.get("WIFI_MONITOR_IFACE", "").strip()
SCAN_TIMEOUT = 12.0
LAN_SCAN_TIMEOUT = 10.0
CLIENT_CAPTURE_SECONDS = 8.0
HISTORY_LEN = 20

_BSS_RE = re.compile(r"^BSS ([0-9a-f:]{17})", re.IGNORECASE | re.MULTILINE)
_SIGNAL_RE = re.compile(r"signal:\s*(-?\d+(?:\.\d+)?)\s*dBm")
_SSID_RE = re.compile(r"^\tSSID:[ \t]?(.*)$", re.MULTILINE)
_FREQ_RE = re.compile(r"freq:\s*(\d+)")
_ARP_LINE_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})\t([0-9a-f:]{17})\t(.*)$", re.IGNORECASE)


# ===========================================================================
# 1. Access point scan
# ===========================================================================

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


def _flag_networks(nets: list[dict]) -> None:
    """Adds a ``flags`` list to each network dict, in place. Pure analysis of
    data already collected -- no extra privilege, no extra scan.

    * ``open``/``weak-encryption`` -- the network itself offers no real
      protection (Open) or one broken long ago (WEP).
    * ``duplicate-ssid`` -- more than one BSSID is advertising the same
      non-empty SSID. That's the classic evil-twin/rogue-AP shape, but it is
      also exactly what legitimate multi-AP mesh/roaming setups look like, so
      this is flagged as "worth a second look", not asserted as an attack.
    """
    by_ssid: dict[str, list[dict]] = {}
    for net in nets:
        if net["ssid"] != "(hidden)":
            by_ssid.setdefault(net["ssid"], []).append(net)

    for net in nets:
        flags: list[str] = []
        if net["security"] == "Open":
            flags.append("open")
        elif net["security"] == "WEP":
            flags.append("weak-encryption")
        if len(by_ssid.get(net["ssid"], [])) > 1:
            flags.append("duplicate-ssid")
        net["flags"] = flags


class ScanService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scanning = False
        self._networks: list[dict] = []
        self._history: dict[str, list[float]] = {}
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
                    nets = [n.as_dict() for n in parse_scan(result.stdout)]
                    for net in nets:
                        hist = self._history.setdefault(net["bssid"], [])
                        hist.append(net["signal_dbm"])
                        del hist[:-HISTORY_LEN]
                        net["history"] = list(hist)
                    _flag_networks(nets)
                    self._networks = nets
                    self._error = ""
                else:
                    self._error = result.detail
                self._updated_at = time.time()
        finally:
            with self._lock:
                self._scanning = False
        return self.snapshot()


# ===========================================================================
# 2. LAN device list (ARP scan of the local subnet -- not Wi-Fi specific)
# ===========================================================================

def _reverse_dns(ip: str, timeout_s: float = 0.4) -> str:
    """Best-effort hostname lookup. A quiet LAN device with no PTR record
    (most phones, IoT gear) is the common case, not an error."""
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout_s)
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""
    finally:
        socket.setdefaulttimeout(old_timeout)


@dataclass(frozen=True)
class LanDevice:
    ip: str
    mac: str
    vendor: str

    def as_dict(self) -> dict:
        return {
            "ip": self.ip,
            "mac": self.mac,
            "vendor": self.vendor or "Unknown",
            "hostname": _reverse_dns(self.ip),
        }


def parse_arp_scan(stdout: str) -> list[LanDevice]:
    """Parses ``arp-scan --localnet``'s ``ip<TAB>mac<TAB>vendor`` lines.
    Its banner/summary lines don't match this pattern and are skipped, not
    specifically filtered for -- same "only take what parses" approach as
    the AP scan."""
    devices: list[LanDevice] = []
    for line in stdout.splitlines():
        m = _ARP_LINE_RE.match(line)
        if not m:
            continue
        ip, mac, vendor = m.groups()
        vendor = vendor.strip()
        if vendor == "(Unknown)":  # arp-scan's own marker; as_dict() has one consistent label
            vendor = ""
        devices.append(LanDevice(ip=ip, mac=mac.lower(), vendor=vendor))
    devices.sort(key=lambda d: tuple(int(p) for p in d.ip.split(".")))
    return devices


class LanScanService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scanning = False
        self._devices: list[dict] = []
        self._updated_at = 0.0
        self._error = ""

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "scanning": self._scanning,
                "devices": list(self._devices),
                "updated_at": self._updated_at,
                "error": self._error,
            }

    def scan(self) -> dict | None:
        with self._lock:
            if self._scanning:
                return None
            self._scanning = True

        try:
            result = shell.run(["arp-scan", "--localnet"], timeout=LAN_SCAN_TIMEOUT)
            with self._lock:
                if result.ok:
                    self._devices = [d.as_dict() for d in parse_arp_scan(result.stdout)]
                    self._error = ""
                else:
                    self._error = result.detail
                self._updated_at = time.time()
        finally:
            with self._lock:
                self._scanning = False
        return self.snapshot()


# ===========================================================================
# 3. Per-AP client capture (monitor mode -- gated behind WIFI_MONITOR_IFACE)
# ===========================================================================

_STATION_HEADER = "Station MAC"


def parse_airodump_clients(csv_text: str, target_bssid: str) -> list[dict]:
    """Pulls the station (client) rows for one BSSID out of an airodump-ng
    CSV capture. The file has two tables -- APs, then a blank line, then
    stations -- so this only looks at rows after the stations header."""
    lines = csv_text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith(_STATION_HEADER)), None)
    if start is None:
        return []

    target = target_bssid.lower()
    clients: list[dict] = []
    for line in lines[start + 1 :]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        mac, _first_seen, last_seen, power, packets, bssid = parts[:6]
        if bssid.lower() != target or not re.match(r"^[0-9a-f:]{17}$", mac, re.IGNORECASE):
            continue
        try:
            power_dbm = int(power)
        except ValueError:
            power_dbm = None
        clients.append({"mac": mac.lower(), "power_dbm": power_dbm, "last_seen": last_seen})
    return clients


class ClientScanService:
    """One capture result cached per BSSID, so re-opening an AP's detail
    shows the last capture without re-running an 8-second packet grab."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._capturing: set[str] = set()
        self._results: dict[str, dict] = {}

    def configured(self) -> bool:
        return bool(MONITOR_IFACE)

    def status(self, bssid: str) -> dict:
        with self._lock:
            return self._results.get(
                bssid.lower(),
                {"clients": [], "updated_at": 0.0, "error": "", "capturing": bssid.lower() in self._capturing},
            )

    def capture(self, bssid: str, channel: int | None) -> dict:
        bssid = bssid.lower()
        if not MONITOR_IFACE:
            return {
                "clients": [],
                "updated_at": 0.0,
                "error": (
                    "Client capture needs a dedicated monitor-mode adapter, set via "
                    "WIFI_MONITOR_IFACE. Not attempted on the scanning interface -- "
                    "that would mean losing its normal network connection."
                ),
                "capturing": False,
            }

        with self._lock:
            if bssid in self._capturing:
                return self._results.get(bssid, {"clients": [], "updated_at": 0.0, "error": "", "capturing": True})
            self._capturing.add(bssid)

        try:
            info = shell.run(["iw", "dev", MONITOR_IFACE, "info"], timeout=3.0)
            if not info.ok or "type monitor" not in info.stdout:
                result = {
                    "clients": [],
                    "updated_at": time.time(),
                    "error": (
                        f"{MONITOR_IFACE} is not in monitor mode. This dashboard won't "
                        f"switch it for you -- set it up yourself first, e.g.:\n"
                        f"  sudo ip link set {MONITOR_IFACE} down\n"
                        f"  sudo iw dev {MONITOR_IFACE} set type monitor\n"
                        f"  sudo ip link set {MONITOR_IFACE} up"
                    ),
                    "capturing": False,
                }
            else:
                result = self._run_capture(bssid, channel)
        finally:
            with self._lock:
                self._capturing.discard(bssid)
                self._results[bssid] = result
        return result

    def _run_capture(self, bssid: str, channel: int | None) -> dict:
        with tempfile.TemporaryDirectory(prefix="pipui-airodump-") as tmp:
            prefix = str(Path(tmp) / "capture")
            argv = ["airodump-ng", "--bssid", bssid, "--write", prefix, "--output-format", "csv"]
            if channel:
                argv += ["--channel", str(channel)]
            argv.append(MONITOR_IFACE)

            # airodump-ng runs until killed; shell.run's subprocess timeout
            # both bounds the capture and is what stops it -- a TimeoutExpired
            # here is the normal, expected way this call ends, not a failure.
            result = shell.run(argv, timeout=CLIENT_CAPTURE_SECONDS)
            if not (result.timed_out or result.ok):
                return {"clients": [], "updated_at": time.time(), "error": result.detail, "capturing": False}

            csv_path = Path(f"{prefix}-01.csv")
            if not csv_path.exists():
                return {
                    "clients": [],
                    "updated_at": time.time(),
                    "error": "Capture produced no output file.",
                    "capturing": False,
                }
            clients = parse_airodump_clients(csv_path.read_text(encoding="utf-8", errors="replace"), bssid)
            return {"clients": clients, "updated_at": time.time(), "error": "", "capturing": False}


service = ScanService()
lan_service = LanScanService()
client_service = ClientScanService()
