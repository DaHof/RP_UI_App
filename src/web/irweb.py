"""IR features for the web dashboard: library, universal scan, send, capture.

Ports the four Tkinter IR tabs (Saved Remotes, Universal Remotes, Learn New
Remote, Settings) without touching the Tkinter app.

Two things this module deliberately does differently from the engine:

* **Sending goes through ``shell.run``, not ``LircClient``.**
  ``LircClient.send_parsed`` and ``send_raw`` call ``subprocess.run`` with no
  timeout (lirc_client.py:74 and :135), so a wedged ``/dev/lirc`` would hang a
  request worker forever. The protocol knowledge still comes from LircClient --
  its scancode tables are the real thing -- but process control is ours.

* **Listing does not parse.**
  ``IRLibraryStore.list_remotes()`` parses all 1,836 ``.ir`` files to count
  signals, which measures at ~2.2s. Far too slow for a request, so the tree is
  walked for names only and cached; a remote's signals are parsed when opened.
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import paths
import shell
import sim
from ir.flipper_ir import FlipperIRSignal, parse_library_signals
from ir.ir_library import IRLibraryStore, _sanitize_path
from ir.lirc_client import LircClient

SEND_TIMEOUT = 6.0
CAPTURE_TIMEOUT = 12.0

# Device label -> filename, mirroring src/ui/app.py:2486.
UNIVERSAL_FILES = {
    "TV": "tv.ir",
    "Audio System": "audio.ir",
    "Projector": "projector.ir",
    "Air Conditioner": "ac.ir",
    "LED": "led.ir",
}


def _signal_dict(signal: FlipperIRSignal) -> dict:
    return {
        "name": signal.name,
        "type": signal.signal_type,
        "protocol": signal.protocol,
        "address": signal.address,
        "command": signal.command,
        "frequency": signal.frequency,
        "duty_cycle": signal.duty_cycle,
        "data_len": len(signal.data) if signal.data else 0,
    }


def _entry_label(entry) -> str:
    """What to show while sweeping.

    The shipped universal files (data/ir/universal/*.ir) separate entries with a
    bare "#" and carry no "model:" comment, so parse_library_signals reports
    every model as "Unknown". The protocol and code actually being transmitted
    are the useful identifier -- that is what tells you which one worked.
    """
    signal = entry.signal
    if entry.model and entry.model != "Unknown":
        return entry.model
    parts = [signal.protocol or "raw"]
    if signal.address and signal.command:
        addr = signal.address.split()[0]
        cmd = signal.command.split()[0]
        parts.append(f"{addr}:{cmd}")
    return " ".join(parts)


def _signal_from_dict(payload: dict) -> FlipperIRSignal:
    data = payload.get("data")
    return FlipperIRSignal(
        name=str(payload.get("name") or "signal"),
        signal_type=str(payload.get("type") or "parsed"),
        protocol=payload.get("protocol"),
        address=payload.get("address"),
        command=payload.get("command"),
        frequency=payload.get("frequency"),
        duty_cycle=payload.get("duty_cycle"),
        data=list(data) if isinstance(data, list) else None,
    )


@dataclass
class ScanState:
    """A universal-remote sweep: one button, fired at every known model."""
    running: bool = False
    device: str = ""
    button: str = ""
    index: int = 0
    total: int = 0
    current_model: str = ""
    cancelled: bool = False
    finished_at: str = ""
    error: str = ""
    sent: int = 0
    failed: int = 0

    def as_dict(self) -> dict:
        return {
            "running": self.running, "device": self.device, "button": self.button,
            "index": self.index, "total": self.total, "current_model": self.current_model,
            "cancelled": self.cancelled, "finished_at": self.finished_at,
            "error": self.error, "sent": self.sent, "failed": self.failed,
        }


@dataclass
class CaptureState:
    running: bool = False
    result: dict | None = None
    error: str = ""
    started_at: float = 0.0

    def as_dict(self) -> dict:
        return {
            "running": self.running,
            "result": self.result,
            "error": self.error,
            "elapsed": round(time.monotonic() - self.started_at, 1) if self.running else 0,
        }


class IRService:
    def __init__(self) -> None:
        self._client = LircClient()          # used for its pure protocol helpers
        self._store = IRLibraryStore(paths.IR_SAVED_DIR)
        self._tree: list[str] | None = None
        self._tree_lock = threading.Lock()

        self._scan = ScanState()
        self._scan_stop = threading.Event()
        self._scan_lock = threading.Lock()

        self._capture = CaptureState()
        self._capture_stop = threading.Event()
        self._capture_lock = threading.Lock()

        self._client.set_rx_device(self.settings().get("rx_device") or "")

    # -- settings ----------------------------------------------------------

    def settings(self) -> dict:
        try:
            payload = json.loads(paths.IR_SETTINGS_JSON.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("universal_delay", 0.2)
        payload.setdefault("rx_device", "")
        return payload

    def save_settings(self, *, universal_delay=None, rx_device=None) -> dict:
        payload = self.settings()
        if universal_delay is not None:
            payload["universal_delay"] = max(0.0, min(4.0, float(universal_delay)))
        if rx_device is not None:
            value = str(rx_device).strip()
            if value and not value.startswith("/dev/"):
                value = f"/dev/{value}"
            payload["rx_device"] = value
            self._client.set_rx_device(value)
        try:
            paths.IR_SETTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
            paths.IR_SETTINGS_JSON.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            payload["error"] = str(exc)
        return payload

    # -- saved remote library ---------------------------------------------

    def _load_tree(self, force: bool = False) -> list[str]:
        with self._tree_lock:
            if self._tree is None or force:
                try:
                    root = paths.IR_SAVED_DIR
                    self._tree = sorted(
                        p.relative_to(root).with_suffix("").as_posix()
                        for p in root.rglob("*.ir")
                    )
                except OSError:
                    self._tree = []
            return self._tree

    def categories(self) -> list[dict]:
        counts: dict[str, int] = {}
        for name in self._load_tree():
            top = name.split("/", 1)[0]
            counts[top] = counts.get(top, 0) + 1
        return [{"name": k, "count": v} for k, v in sorted(counts.items())]

    def remotes(self, category: str = "", query: str = "", limit: int = 300) -> dict:
        names = self._load_tree()
        needle = query.strip().lower()
        if category:
            prefix = category.rstrip("/") + "/"
            names = [n for n in names if n.startswith(prefix)]
        if needle:
            names = [n for n in names if needle in n.lower()]
        return {
            "total": len(names),
            "limit": limit,
            "remotes": [{"name": n, "label": n.split("/")[-1]} for n in names[:limit]],
        }

    def remote(self, name: str) -> dict:
        signals = self._store.load_remote(name)
        return {
            "name": name,
            "count": len(signals),
            "signals": [_signal_dict(s) for s in signals],
        }

    def delete_remote(self, name: str) -> None:
        self._store.delete_remote(name)
        self._load_tree(force=True)

    def save_remote(self, name: str, signals: list[FlipperIRSignal]) -> str:
        # IRLibraryStore.save_remote writes without creating the parent
        # directory (ir_library.py:50), unlike save_remote_signals which does
        # (:55). So any nested name -- "LivingRoom/TV" -- raises FileNotFoundError.
        # The engine is shared with the Tkinter app, so make the directory here
        # rather than change it. _sanitize_path is reused so this agrees with
        # the name the store will actually pick.
        safe = _sanitize_path(name)
        (paths.IR_SAVED_DIR / safe).parent.mkdir(parents=True, exist_ok=True)
        target = self._store.save_remote(name, signals)
        self._load_tree(force=True)
        try:
            return target.relative_to(paths.IR_SAVED_DIR).with_suffix("").as_posix()
        except ValueError:
            return name

    def signal_at(self, remote: str, index: int) -> FlipperIRSignal | None:
        signals = self._store.load_remote(remote)
        return signals[index] if 0 <= index < len(signals) else None

    # -- universal remotes -------------------------------------------------

    def universal_devices(self) -> list[dict]:
        out = []
        for label, filename in UNIVERSAL_FILES.items():
            path = paths.IR_UNIVERSAL_DIR / filename
            out.append({
                "id": label, "file": filename, "available": path.exists(),
            })
        return out

    def _universal_signals(self, device: str) -> list:
        filename = UNIVERSAL_FILES.get(
            device, f"{device.lower().replace(' ', '_')}.ir"
        )
        path = paths.IR_UNIVERSAL_DIR / filename
        if not path.exists():
            return []
        try:
            return parse_library_signals(path.read_text(encoding="utf-8"))
        except OSError:
            return []

    def universal_buttons(self, device: str) -> dict:
        entries = self._universal_signals(device)
        buttons: dict[str, int] = {}
        models: set[str] = set()
        for entry in entries:
            buttons[entry.signal.name] = buttons.get(entry.signal.name, 0) + 1
            models.add(entry.model)
        return {
            "device": device,
            "models": len(models),
            "buttons": [
                {"name": k, "models": v}
                for k, v in sorted(buttons.items(), key=lambda kv: -kv[1])
            ],
        }

    # -- sending -----------------------------------------------------------

    def tx_device(self) -> str | None:
        if sim.active():
            return "/dev/lirc0"
        try:
            import os

            devices = sorted(str(p) for p in Path("/dev").glob("lirc*"))
        except OSError:
            return None
        if not devices:
            return None
        writable = [d for d in devices if os.access(d, os.W_OK)]
        return writable[0] if writable else devices[0]

    def send(self, signal: FlipperIRSignal) -> tuple[bool, str]:
        """Transmit one signal. Guarded -- unlike LircClient's own send."""
        device = self.tx_device()
        if not device:
            return False, "No /dev/lirc* device found"

        if signal.signal_type == "parsed":
            if not (signal.protocol and signal.address and signal.command):
                return False, "Signal is missing protocol, address or command"
            protocol = self._client._normalize_protocol(signal.protocol)
            scancode = self._client._build_scancode(
                protocol, signal.address, signal.command
            )
            if not scancode:
                return False, f"Unsupported protocol: {signal.protocol}"
            result = shell.run(
                ["ir-ctl", "-d", device, "-S", f"{protocol}:{scancode}"],
                timeout=SEND_TIMEOUT,
            )
            return (True, "Sent") if result.ok else (False, result.detail)

        if not signal.data:
            return False, "Raw signal has no timing data"
        lines: list[str] = []
        if signal.frequency:
            lines.append(f"carrier {signal.frequency}")
        if signal.duty_cycle is not None:
            lines.append(f"duty_cycle {signal.duty_cycle:.6f}")
        for index, value in enumerate(signal.data):
            lines.append(f"{'pulse' if index % 2 == 0 else 'space'} {value}")

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False, suffix=".ir"
            ) as handle:
                handle.write("\n".join(lines) + "\n")
                temp_path = handle.name
            result = shell.run(
                ["ir-ctl", "-d", device, "-s", temp_path], timeout=SEND_TIMEOUT
            )
            return (True, "Sent") if result.ok else (False, result.detail)
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    # -- universal scan ----------------------------------------------------

    @property
    def scan_state(self) -> dict:
        return self._scan.as_dict()

    def start_scan(self, device: str, button: str) -> tuple[bool, str]:
        with self._scan_lock:
            if self._scan.running:
                return False, "A scan is already running"
            entries = [e for e in self._universal_signals(device) if e.signal.name == button]
            if not entries:
                return False, f"No models define '{button}' for {device}"
            self._scan_stop.clear()
            self._scan = ScanState(
                running=True, device=device, button=button, total=len(entries)
            )
        threading.Thread(
            target=self._scan_worker, args=(entries,), name="ir-scan", daemon=True
        ).start()
        return True, f"Sweeping {len(entries)} models"

    def _scan_worker(self, entries: list) -> None:
        delay = float(self.settings().get("universal_delay", 0.2))
        try:
            for index, entry in enumerate(entries, start=1):
                if self._scan_stop.is_set():
                    self._scan.cancelled = True
                    break
                self._scan.index = index
                self._scan.current_model = _entry_label(entry)
                ok, _ = self.send(entry.signal)
                if ok:
                    self._scan.sent += 1
                else:
                    self._scan.failed += 1
                # Interruptible sleep, so Cancel does not wait out the delay.
                if self._scan_stop.wait(delay):
                    self._scan.cancelled = True
                    break
        except Exception as exc:
            self._scan.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._scan.running = False
            self._scan.finished_at = time.strftime("%H:%M:%S")

    def cancel_scan(self) -> bool:
        if not self._scan.running:
            return False
        # Flag it here as well as in the worker, so the response that answers
        # the Cancel tap already reports the cancellation.
        self._scan.cancelled = True
        self._scan_stop.set()
        return True

    # -- capture (Learn New Remote) ---------------------------------------

    @property
    def capture_state(self) -> dict:
        return self._capture.as_dict()

    def start_capture(self) -> tuple[bool, str]:
        with self._capture_lock:
            if self._capture.running:
                return False, "A capture is already running"
            self._capture_stop.clear()
            self._capture = CaptureState(running=True, started_at=time.monotonic())
        threading.Thread(target=self._capture_worker, name="ir-capture", daemon=True).start()
        return True, "Point the remote at the receiver and press a button"

    def _capture_worker(self) -> None:
        try:
            if sim.active():
                time.sleep(1.2)
                self._capture.result = {
                    "name": "NEC", "signal_type": "parsed", "protocol": "NEC",
                    "address": "20 DF 00 00", "command": "10 EF 00 00",
                    "simulated": True,
                }
                return
            captured = self._client.capture_signal(self._capture_stop, CAPTURE_TIMEOUT)
            if captured is None:
                self._capture.error = "No signal captured before the timeout"
            else:
                self._capture.result = {
                    k: v for k, v in captured.items()
                    if k in ("name", "signal_type", "protocol", "address", "command",
                             "frequency", "duty_cycle", "source")
                }
                data = captured.get("data") or captured.get("raw_burst")
                if isinstance(data, list):
                    self._capture.result["data"] = data
                    self._capture.result["data_len"] = len(data)
        except Exception as exc:
            self._capture.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._capture.running = False

    def cancel_capture(self) -> bool:
        if not self._capture.running:
            return False
        self._capture_stop.set()
        return True


service = IRService()
