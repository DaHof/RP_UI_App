from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import tempfile
import time
from typing import Iterable, Iterator, List, Optional, Tuple

from ir.ir_decode import decode_raw_timings

@dataclass(frozen=True)
class IRRemote:
    name: str
    buttons: List[str]


class LircClient:
    """Minimal LIRC wrapper for IR capture/send integration."""

    _PROTOCOL_ALIASES = {
        "kaseikyo": "kaseikyo",
        "nec": "nec",
        "nec42": "nec",
        "necext": "necx",
        "nec_ext": "necx",
        "nec-x": "necx",
        "pioneer": "pioneer",
        "rc5": "rc5",
        "rc5x": "rc5x",
        "rc6": "rc6",
        "rca": "rca",
        "samsung32": "samsung32",
        "sirc": "sony",
        "sirc15": "sony15",
        "sirc20": "sony20",
    }

    def __init__(self) -> None:
        self._rx_device: Optional[str] = None

    def set_rx_device(self, device: Optional[str]) -> None:
        value = device.strip() if device else ""
        if value and not value.startswith("/dev/"):
            value = f"/dev/{value}"
        self._rx_device = value or None

    def list_remotes(self) -> Iterable[IRRemote]:
        raise NotImplementedError("LIRC integration not wired yet.")

    def send_once(self, remote: str, button: str) -> None:
        raise NotImplementedError("LIRC integration not wired yet.")

    def send_parsed(
        self, protocol: str, address: Optional[str], command: Optional[str]
    ) -> Tuple[bool, str]:
        if not protocol or not address or not command:
            return False, "Missing protocol, address, or command."
        device = self._select_tx_device()
        if not device:
            return False, "No writable /dev/lirc* device found."
        if not shutil.which("ir-ctl"):
            return False, "ir-ctl not available."
        normalized_protocol = self._normalize_protocol(protocol)
        scancode = self._build_scancode(normalized_protocol, address, command)
        if not scancode:
            return False, "Unsupported or invalid parsed signal."
        command = ["ir-ctl", "-d", device, "-S", f"{normalized_protocol}:{scancode}"]
        result = subprocess.run(
            command, capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip()
            return False, message or "ir-ctl failed to send."
        return True, "Sent."

    def decode_scancode(self, protocol: str, scancode: str) -> Tuple[str, str]:
        value = self._parse_scancode_value(scancode)
        if value is None:
            return "00", "00"
        normalized = self._normalize_protocol(protocol)
        if normalized == "nec":
            bytes_ = self._int_to_bytes(value, length=4)
            address = self._format_bytes(bytes_[:1])
            command = self._format_bytes(bytes_[2:3])
            return address, command
        if normalized in {"necx", "nec_ext", "necext"}:
            bytes_ = self._int_to_bytes(value, length=4)
            address = self._format_bytes(bytes_[:2])
            command = self._format_bytes(bytes_[2:4])
            return address, command
        if normalized in {"sony", "sony15", "sony20"}:
            command_value = value & 0x7F
            address_value = value >> 7
            address = self._format_int(address_value)
            command = self._format_int(command_value)
            return address, command
        return "00", self._format_int(value)

    def send_raw(
        self,
        frequency: Optional[int],
        duty_cycle: Optional[float],
        data: Optional[List[int]],
    ) -> Tuple[bool, str]:
        if not data:
            return False, "Missing raw signal data."
        device = self._select_tx_device()
        if not device:
            return False, "No writable /dev/lirc* device found."
        if not shutil.which("ir-ctl"):
            return False, "ir-ctl not available."
        lines: List[str] = []
        if frequency:
            lines.append(f"carrier {frequency}")
        if duty_cycle is not None:
            lines.append(f"duty_cycle {duty_cycle:.6f}")
        for index, value in enumerate(data):
            label = "pulse" if index % 2 == 0 else "space"
            lines.append(f"{label} {value}")
        content = "\n".join(lines) + "\n"
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False
            ) as handle:
                handle.write(content)
                temp_path = handle.name
            command = ["ir-ctl", "-d", device, "-s", temp_path]
            result = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
            if result.returncode != 0:
                message = result.stderr.strip() or result.stdout.strip()
                return False, message or "ir-ctl failed to send raw signal."
            return True, "Sent."
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def start_capture(self) -> None:
        raise NotImplementedError("LIRC integration not wired yet.")

    def capture_signal(
        self,
        stop_event: threading.Event,
        timeout_s: float = 12.0,
    ) -> Optional[dict[str, object]]:
        capture_stop = threading.Event()
        raw_result: dict[str, object] = {}
        raw_ready = threading.Event()
        raw_attempted = False
        use_raw_only = bool(self._rx_device)

        def raw_worker() -> None:
            raw = self._capture_raw_signal(stop_event, capture_stop, timeout_s)
            if raw:
                raw_result.update(raw)
            raw_ready.set()

        if shutil.which("ir-ctl"):
            raw_attempted = True
            if use_raw_only:
                raw_worker()
            else:
                raw_thread = threading.Thread(target=raw_worker, daemon=True)
                raw_thread.start()
        else:
            raw_thread = None

        if raw_result.get("has_data"):
            decoded, selected = self._decode_best_burst(raw_result.get("data") or [])
            if decoded:
                return {
                    "name": decoded.protocol,
                    "signal_type": "parsed",
                    "protocol": decoded.protocol,
                    "address": decoded.address,
                    "command": decoded.command,
                    "scancode": None,
                    "source": raw_result.get("source") or "ir-ctl",
                    "frequency": None,
                    "duty_cycle": None,
                    "data": None,
                    "raw_frequency": raw_result.get("frequency"),
                    "raw_duty_cycle": raw_result.get("duty_cycle"),
                    "raw_data": selected,
                    "raw_attempted": raw_attempted,
                    "raw_device": raw_result.get("device"),
                    "raw_command": raw_result.get("command"),
                    "raw_error": raw_result.get("error"),
                    "raw_lines": raw_result.get("raw_lines"),
                }
            return {
                "name": "RAW",
                "signal_type": "raw",
                "protocol": "RAW",
                "address": None,
                "command": None,
                "scancode": None,
                "source": raw_result.get("source") or "ir-ctl",
                "frequency": raw_result.get("frequency"),
                "duty_cycle": raw_result.get("duty_cycle"),
                "data": selected,
                "raw_command": raw_result.get("command"),
                "raw_error": raw_result.get("error"),
                "raw_lines": raw_result.get("raw_lines"),
                "raw_attempted": raw_attempted,
                "raw_device": raw_result.get("device"),
            }

        parsed = None if use_raw_only else self._capture_keytable_event(
            stop_event, capture_stop, timeout_s
        )
        if parsed:
            if raw_thread:
                raw_ready.wait(timeout=1.0)
                capture_stop.set()
                raw_thread.join(timeout=0.5)
            protocol = str(parsed.get("protocol") or "unknown")
            scancode = str(parsed.get("data") or "")
            address, command = self.decode_scancode(protocol, scancode)
            result = {
                "name": str(parsed.get("name") or "Unknown"),
                "signal_type": "parsed",
                "protocol": protocol.upper(),
                "address": address,
                "command": command,
                "scancode": scancode,
                "source": parsed.get("source") or "ir-keytable",
                "frequency": None,
                "duty_cycle": None,
                "data": None,
                "raw_attempted": raw_attempted,
                "raw_device": raw_result.get("device"),
                "raw_command": raw_result.get("command"),
                "raw_error": raw_result.get("error"),
                "keytable_command": parsed.get("command"),
            }
            if raw_result:
                result.update(
                    {
                        "raw_frequency": raw_result.get("frequency"),
                        "raw_duty_cycle": raw_result.get("duty_cycle"),
                        "raw_data": raw_result.get("data"),
                        "raw_lines": raw_result.get("raw_lines"),
                    }
                )
            return result

        if raw_thread:
            capture_stop.set()
            raw_ready.wait(timeout=0.2)
            raw_thread.join(timeout=0.5)
        return None

    def iter_keytable_events(
        self, stop_event: threading.Event
    ) -> Iterator[dict[str, str]]:
        process = subprocess.Popen(
            ["ir-keytable", "-t"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.stdout is None:
            return
        for line in process.stdout:
            if stop_event.is_set():
                break
            event = self._parse_keytable_line(line)
            if event:
                yield event
        process.terminate()

    def _parse_keytable_line(self, line: str) -> dict[str, str] | None:
        if "scancode" not in line.lower():
            return None
        protocol_match = re.search(
            r"(?:protocol|proto)\s*[:=]?\s*([\w-]+)", line, re.IGNORECASE
        )
        scancode_match = re.search(
            r"scancode\s*(?:=|:)?\s*(0x[0-9a-fA-F]+)", line
        )
        if not scancode_match:
            scancode_match = re.search(
                r"scancode\s*(?:=|:)?\s*([0-9a-fA-F]+)", line
            )
        key_match = re.search(r"(?:key|keycode)\s*[:=]?\s*([\w-]+)", line, re.IGNORECASE)
        protocol = protocol_match.group(1) if protocol_match else "unknown"
        scancode = scancode_match.group(1) if scancode_match else "unknown"
        key = key_match.group(1) if key_match else "unknown"
        return {
            "protocol": protocol,
            "data": scancode,
            "source": "ir-keytable",
            "name": key,
        }

    def _select_tx_device(self) -> Optional[str]:
        devices = sorted(str(path) for path in Path("/dev").glob("lirc*"))
        writable = [device for device in devices if os.access(device, os.W_OK)]
        if writable:
            return writable[0]
        return devices[0] if devices else None

    def _select_rx_device(self) -> Optional[str]:
        if self._rx_device and Path(self._rx_device).exists():
            return self._rx_device
        env_device = os.environ.get("IR_RX_DEVICE")
        if env_device and Path(env_device).exists():
            return env_device
        preferred = "/dev/lirc1"
        if Path(preferred).exists():
            return preferred
        device = self._detect_rx_device()
        if device:
            return device
        devices = sorted(str(path) for path in Path("/dev").glob("lirc*"))
        readable = [device for device in devices if os.access(device, os.R_OK)]
        if readable:
            return readable[0]
        return devices[0] if devices else None

    def _detect_rx_device(self) -> Optional[str]:
        if not shutil.which("ir-keytable"):
            return None
        result = subprocess.run(
            ["ir-keytable"], capture_output=True, text=True, check=False
        )
        output = result.stdout or ""
        match = re.search(r"LIRC device:\s*(/dev/lirc\d+)", output)
        if match:
            return match.group(1)
        return None

    def _capture_keytable_event(
        self,
        stop_event: threading.Event,
        capture_stop: threading.Event,
        timeout_s: float,
    ) -> Optional[dict[str, str]]:
        if not shutil.which("ir-keytable"):
            return None
        command = ["ir-keytable", "-t"]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.stdout is None:
            return None
        deadline = time.monotonic() + timeout_s
        for line in process.stdout:
            if stop_event.is_set() or capture_stop.is_set():
                break
            if time.monotonic() > deadline:
                break
            event = self._parse_keytable_line(line)
            if event:
                event["command"] = " ".join(command)
                process.terminate()
                return event
        process.terminate()
        return None

    def _capture_raw_signal(
        self,
        stop_event: threading.Event,
        capture_stop: threading.Event,
        timeout_s: float,
    ) -> Optional[dict[str, object]]:
        device = self._select_rx_device()
        if not device:
            return {
                "device": None,
                "frequency": None,
                "duty_cycle": None,
                "data": [],
                "signed_data": [],
                "raw_lines": [],
                "command": None,
                "source": "ir-ctl",
                "has_data": False,
                "error": "rx device not found",
            }
        command = ["ir-ctl", "-r", "-d", device]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.stdout is None:
            return None
        signed_data: List[int] = []
        frequency: Optional[int] = None
        duty_cycle: Optional[float] = None
        raw_lines: List[str] = []
        deadline = time.monotonic() + timeout_s
        for line in process.stdout:
            if stop_event.is_set() or capture_stop.is_set():
                break
            if time.monotonic() > deadline:
                break
            stripped = line.strip()
            if stripped:
                raw_lines.append(stripped)
            if not stripped:
                if data:
                    break
                continue
            lower = stripped.lower()
            if lower.startswith("carrier"):
                match = re.search(r"(\d+)", stripped)
                if match:
                    frequency = int(match.group(1))
                continue
            if lower.startswith("duty"):
                match = re.search(r"([0-9]*\.?[0-9]+)", stripped)
                if match:
                    try:
                        duty_cycle = float(match.group(1))
                    except ValueError:
                        duty_cycle = None
                continue
            if "timeout" in lower:
                if data:
                    break
                continue
            tokens = re.findall(r"[+-]\d+", stripped)
            if tokens:
                for token in tokens:
                    signed_data.append(int(token))
                continue
            match = re.search(r"(pulse|space)\s+(\d+)", lower)
            if match:
                value = int(match.group(2))
                signed_data.append(value if match.group(1) == "pulse" else -value)
                continue
            value_match = re.search(r"(\d+)", stripped)
            if value_match:
                signed_data.append(int(value_match.group(1)))
        process.terminate()
        data = self._normalize_signed_timings(signed_data)
        return {
            "device": device,
            "frequency": frequency,
            "duty_cycle": duty_cycle,
            "data": data,
            "signed_data": signed_data,
            "raw_lines": raw_lines,
            "command": " ".join(command),
            "source": "ir-ctl",
            "has_data": bool(data),
        }

    def _split_bursts(self, data: List[int]) -> List[List[int]]:
        if not data:
            return []
        bursts: List[List[int]] = []
        current: List[int] = []
        for value in data:
            if value > 1000000 and current:
                if len(current) % 2 == 1:
                    current = current[:-1]
                if current:
                    bursts.append(current)
                current = []
                continue
            current.append(value)
        if current:
            if len(current) % 2 == 1:
                current = current[:-1]
            if current:
                bursts.append(current)
        return bursts

    def _decode_best_burst(
        self, data: List[int]
    ) -> Tuple[Optional["DecodedIR"], List[int]]:
        bursts = self._split_bursts(data)
        if not bursts:
            return None, data
        best: List[int] = max(bursts, key=len)
        decoded_best: Optional["DecodedIR"] = None
        decoded_burst: List[int] = []
        for burst in bursts:
            if len(burst) < 60:
                continue
            decoded = decode_raw_timings(burst)
            if decoded and len(burst) > len(decoded_burst):
                decoded_best = decoded
                decoded_burst = burst
        if decoded_best:
            return decoded_best, decoded_burst
        return None, best

    def _normalize_signed_timings(self, signed_data: List[int]) -> List[int]:
        if not signed_data:
            return []
        values = [value for value in signed_data if value != 0]
        if not values:
            return []
        if values[0] < 0:
            values = values[1:]
        abs_values = [abs(value) for value in values]
        if len(abs_values) % 2 == 1:
            abs_values = abs_values[:-1]
        if abs_values and abs_values[-1] > 15000:
            abs_values = abs_values[:-1]
            if len(abs_values) % 2 == 1:
                abs_values = abs_values[:-1]
        return abs_values

    def _build_scancode(self, protocol: str, address: str, command: str) -> Optional[str]:
        addr_bytes = self._compact_bytes(self._parse_hex_bytes(address))
        cmd_bytes = self._compact_bytes(self._parse_hex_bytes(command))
        if not addr_bytes or not cmd_bytes:
            return None
        protocol_key = self._normalize_protocol(protocol)
        if protocol_key in {"nec"} and len(addr_bytes) >= 1 and len(cmd_bytes) >= 1:
            addr = addr_bytes[0]
            cmd = cmd_bytes[0]
            scancode = (
                (addr << 24)
                | ((addr ^ 0xFF) << 16)
                | (cmd << 8)
                | (cmd ^ 0xFF)
            )
            return f"0x{scancode:08x}"
        if protocol_key in {"necext", "nec_ext", "necx"}:
            addr = self._bytes_to_int(addr_bytes[:2])
            cmd = self._bytes_to_int(cmd_bytes[:2])
            scancode = (addr << 16) | cmd
            return f"0x{scancode:08x}"
        addr = self._bytes_to_int(addr_bytes[:2])
        cmd = self._bytes_to_int(cmd_bytes[:2])
        bytes_used = len(addr_bytes[:2]) + len(cmd_bytes[:2])
        scancode = (addr << (8 * len(cmd_bytes[:2]))) | cmd
        return f"0x{scancode:0{max(1, bytes_used) * 2}x}"

    def _normalize_protocol(self, protocol: str) -> str:
        normalized = protocol.strip().lower()
        return self._PROTOCOL_ALIASES.get(normalized, normalized)

    def _parse_scancode_value(self, value: str) -> Optional[int]:
        match = re.search(r"(?:0x)?([0-9a-fA-F]+)", value or "")
        if not match:
            return None
        return int(match.group(1), 16)

    def _parse_hex_bytes(self, value: str) -> List[int]:
        tokens = re.findall(r"[0-9a-fA-F]{2}", value)
        return [int(token, 16) for token in tokens]

    def _int_to_bytes(self, value: int, length: Optional[int] = None) -> List[int]:
        if length:
            return [
                (value >> (8 * (length - 1 - idx))) & 0xFF
                for idx in range(length)
            ]
        byte_count = max(1, (value.bit_length() + 7) // 8)
        return list(value.to_bytes(byte_count, "big"))

    def _format_bytes(self, values: List[int]) -> str:
        if not values:
            return "00"
        return " ".join(f"{value:02X}" for value in values)

    def _format_int(self, value: int) -> str:
        return self._format_bytes(self._int_to_bytes(value))

    def _compact_bytes(self, values: List[int]) -> List[int]:
        if not values:
            return []
        trimmed = list(values)
        while len(trimmed) > 1 and trimmed[-1] == 0:
            trimmed.pop()
        return trimmed

    def _bytes_to_int(self, values: List[int]) -> int:
        total = 0
        for value in values:
            total = (total << 8) | value
        return total
