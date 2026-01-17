from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, List, Optional


HEADER_LINES: tuple[str, ...] = ()
ACCEPTED_FILETYPES = {
    "Filetype: IR library file",
    "Filetype: IR signals file",
}


@dataclass(frozen=True)
class FlipperIRSignal:
    name: str
    signal_type: str
    protocol: Optional[str] = None
    address: Optional[str] = None
    command: Optional[str] = None
    frequency: Optional[int] = None
    duty_cycle: Optional[float] = None
    data: Optional[List[int]] = None


@dataclass(frozen=True)
class FlipperIRLibrarySignal:
    model: str
    signal: FlipperIRSignal


def serialize_signals(signals: Iterable[FlipperIRSignal]) -> str:
    lines: List[str] = [*HEADER_LINES]
    first = True
    for signal in signals:
        if not first:
            lines.append("")
        first = False
        lines.append("#")
        lines.append(f"name: {signal.name}")
        lines.append(f"type: {signal.signal_type}")
        if signal.signal_type == "parsed":
            if signal.protocol:
                lines.append(f"protocol: {signal.protocol}")
            if signal.address:
                lines.append(f"address: {signal.address}")
            if signal.command:
                lines.append(f"command: {signal.command}")
        else:
            if signal.frequency is not None:
                lines.append(f"frequency: {signal.frequency}")
            if signal.duty_cycle is not None:
                lines.append(f"duty_cycle: {signal.duty_cycle:.6f}")
            if signal.data:
                lines.append("data: " + " ".join(str(value) for value in signal.data))
    return "\n".join(lines) + "\n"


def parse_signals(text: str) -> List[FlipperIRSignal]:
    signals: List[FlipperIRSignal] = []
    current: dict[str, object] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in ACCEPTED_FILETYPES or stripped == "Version: 1":
            continue
        if stripped.startswith("#"):
            if current:
                signals.append(_build_signal(current))
                current = {}
            continue
        if ":" not in stripped:
            continue
        key, value = (part.strip() for part in stripped.split(":", 1))
        current[key] = value
    if current:
        signals.append(_build_signal(current))
    return signals


def parse_library_signals(text: str) -> List[FlipperIRLibrarySignal]:
    signals: List[FlipperIRLibrarySignal] = []
    current: dict[str, object] = {}
    current_model = "Unknown"
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in ACCEPTED_FILETYPES or stripped == "Version: 1":
            continue
        if stripped.startswith("#"):
            if current:
                signals.append(FlipperIRLibrarySignal(current_model, _build_signal(current)))
                current = {}
            comment = stripped.lstrip("#").strip()
            while comment.startswith("#"):
                comment = comment[1:].strip()
            if comment:
                current_model = _parse_model_comment(comment)
            continue
        if ":" not in stripped:
            continue
        key, value = (part.strip() for part in stripped.split(":", 1))
        current[key] = value
    if current:
        signals.append(FlipperIRLibrarySignal(current_model, _build_signal(current)))
    return signals


def _build_signal(payload: dict[str, object]) -> FlipperIRSignal:
    signal_type = str(payload.get("type", "parsed"))
    data: Optional[List[int]] = None
    if signal_type != "parsed" and "data" in payload:
        data_values = str(payload["data"]).split()
        data = []
        for value in data_values:
            try:
                data.append(int(value, 0))
            except ValueError:
                continue
    duty_cycle: Optional[float] = None
    if "duty_cycle" in payload:
        try:
            duty_cycle = float(payload["duty_cycle"])
        except ValueError:
            duty_cycle = None
    frequency: Optional[int] = None
    if "frequency" in payload:
        try:
            frequency = int(payload["frequency"])
        except ValueError:
            frequency = None
    return FlipperIRSignal(
        name=str(payload.get("name", "Unknown")),
        signal_type=signal_type,
        protocol=_optional_str(payload.get("protocol")),
        address=_optional_str(payload.get("address")),
        command=_optional_str(payload.get("command")),
        frequency=frequency,
        duty_cycle=duty_cycle,
        data=data,
    )


def _optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_model_comment(comment: str) -> str:
    match = re.match(r"model:\s*(.+)$", comment, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return comment.strip() or "Unknown"
