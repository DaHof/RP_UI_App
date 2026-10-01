"""HLK-LD2450 mmWave radar: reader lifecycle that degrades instead of crashing.

Mirrors ``hardware.py``'s pattern for the PN532 exactly, for the same reason:
``pyserial`` and an actual sensor on ``/dev/serial0`` are both Pi-only, so a
guarded import and a mock fallback keep the dashboard usable on a dev machine
and keep a missing/unplugged sensor from taking the process down.

Wiring (see README / data/pins.yaml): the LD2450 is 3.3V native and talks UART
at 256000 baud -- VCC to pin 2 (5V), GND to pin 6, TX to pin 10 (GPIO15/RXD0),
RX to pin 8 (GPIO14/TXD0). No level shifter needed. Those pins are unused by
the PN532 (I2C: 1/3/5/6) and the IR hardware (2/12/16), so there is no header
conflict with the engine's existing wiring.

Frame decode: each 30-byte frame is ``AA FF 03 00`` + three 8-byte target
blocks (X, Y, speed, distance-resolution, each little-endian uint16) + ``55
CC``. X/Y/speed are not two's complement -- bit 15 is a sign flag (1 =
positive) and the low 15 bits are the magnitude. That decode matches the one
used by Home Assistant's and ESPHome's ld2450 integrations, which is the
closest thing this protocol has to a public reference, but it has not been
checked against a capture from this project's own unit -- verify against real
hardware before trusting it for anything precise.
"""

from __future__ import annotations

import math
import os
import struct
import threading
import time
from dataclasses import dataclass, field

MAX_TARGETS = 3
FRAME_HEADER = b"\xaa\xff\x03\x00"
FRAME_FOOTER = b"\x55\xcc"
FRAME_LEN = 4 + MAX_TARGETS * 8 + 2  # 30
DEFAULT_PORT = "/dev/serial0"
DEFAULT_BAUD = 256000


@dataclass(frozen=True)
class Target:
    slot: int
    x_mm: int
    y_mm: int
    speed_mm_s: int

    def as_dict(self) -> dict:
        return {
            "slot": self.slot,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "speed_mm_s": self.speed_mm_s,
            "distance_mm": round(math.hypot(self.x_mm, self.y_mm), 1),
        }


def _decode_signed(raw: int) -> int:
    magnitude = raw & 0x7FFF
    return magnitude if raw & 0x8000 else -magnitude


def parse_frame(frame: bytes) -> list[Target]:
    """Parse one 30-byte LD2450 frame. Empty target slots (x=y=0) are dropped."""
    targets: list[Target] = []
    body = frame[4:-2]
    for slot in range(MAX_TARGETS):
        chunk = body[slot * 8 : slot * 8 + 8]
        if len(chunk) < 8:
            continue
        x_raw, y_raw, speed_raw, _res = struct.unpack("<HHHH", chunk)
        x, y, speed = _decode_signed(x_raw), _decode_signed(y_raw), _decode_signed(speed_raw)
        if x == 0 and y == 0:
            continue
        targets.append(Target(slot, x, y, speed))
    return targets


class BaseMmwaveReader:
    def __init__(self) -> None:
        self._callback = None

    def set_callback(self, callback) -> None:
        self._callback = callback

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def _emit(self, targets: list[Target]) -> None:
        if self._callback:
            self._callback(targets)


class MockMmwaveReader(BaseMmwaveReader):
    """Two targets drifting on looping paths, so the radar view has something
    to draw with no sensor attached -- same role ``MockPN532Reader.simulate_tag``
    plays for the NFC screen."""

    INTERVAL = 0.1

    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _loop(self) -> None:
        t0 = time.monotonic()
        while self._running:
            t = time.monotonic() - t0
            targets = [
                Target(0, int(900 * math.sin(t * 0.6)), int(1800 + 500 * math.cos(t * 0.4)),
                       int(400 * math.cos(t * 0.6))),
                Target(1, int(-1400 + 300 * math.sin(t * 0.25)), int(2600 + 300 * math.sin(t * 0.5)),
                       int(-150 * math.sin(t * 0.25))),
            ]
            self._emit(targets)
            time.sleep(self.INTERVAL)


class SerialMmwaveReader(BaseMmwaveReader):
    """Reads real LD2450 frames off UART. Import of ``serial`` is deferred to
    ``start()`` the same way ``AdafruitPN532Reader`` defers ``board``/``busio``,
    so merely selecting this class on a non-Pi machine cannot raise."""

    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD) -> None:
        super().__init__()
        self.port = port
        self.baud = baud
        self._running = False
        self._thread: threading.Thread | None = None
        self._ser = None

    def start(self) -> None:
        import serial  # noqa: PLC0415 -- deferred, see class docstring

        self._ser = serial.Serial(self.port, self.baud, timeout=0.5)
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass

    def _loop(self) -> None:
        buf = b""
        while self._running:
            try:
                chunk = self._ser.read(64)
            except Exception:
                return  # port pulled or died; polling property will report it
            if chunk:
                buf += chunk
            while True:
                start = buf.find(FRAME_HEADER)
                if start < 0:
                    buf = buf[-(len(FRAME_HEADER) - 1):] if buf else buf
                    break
                if len(buf) < start + FRAME_LEN:
                    buf = buf[start:]
                    break
                frame = buf[start : start + FRAME_LEN]
                buf = buf[start + FRAME_LEN :]
                if frame[-2:] == FRAME_FOOTER:
                    self._emit(parse_frame(frame))


@dataclass(frozen=True)
class ReaderStatus:
    requested: str
    active: str
    degraded: bool
    started: bool
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "requested": self.requested,
            "active": self.active,
            "degraded": self.degraded,
            "started": self.started,
            "reason": self.reason,
        }


class MmwaveService:
    """Owns the reader and the most recent target list -- a snapshot, not a
    buffer, since unlike NFC tags a stale radar frame is simply replaced."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._targets: list[dict] = []
        self._updated_at: float = 0.0
        self.reader: BaseMmwaveReader = MockMmwaveReader()
        self.status = ReaderStatus("mock", "mock", False, False)

    def start(self) -> ReaderStatus:
        requested = os.environ.get("MMWAVE_READER", "mock").strip().lower()
        reader, degraded, reason = self._build(requested)

        reader.set_callback(self._on_targets)
        started = True
        try:
            reader.start()
        except Exception as exc:
            started = False
            reason = reason or f"{type(exc).__name__}: {exc}"
            if requested != "mock":
                reader = MockMmwaveReader()
                reader.set_callback(self._on_targets)
                degraded = True
                try:
                    reader.start()
                    started = True
                except Exception as fallback_exc:
                    reason = f"{reason} (mock fallback also failed: {fallback_exc})"

        active = "mock" if isinstance(reader, MockMmwaveReader) else requested
        self.reader = reader
        self.status = ReaderStatus(requested, active, degraded, started, reason)
        return self.status

    def _build(self, requested: str) -> tuple[BaseMmwaveReader, bool, str]:
        if requested != "serial":
            return MockMmwaveReader(), False, ""
        port = os.environ.get("MMWAVE_PORT", DEFAULT_PORT)
        try:
            import serial  # noqa: F401 -- presence check only; real import is in start()

            return SerialMmwaveReader(port=port), False, ""
        except Exception as exc:
            hint = " (pyserial not installed)" if isinstance(exc, ImportError) else ""
            return MockMmwaveReader(), True, f"{type(exc).__name__}: {exc}{hint}"

    def stop(self) -> None:
        try:
            self.reader.stop()
        except Exception:
            pass

    @property
    def polling(self) -> bool:
        if not self.status.started:
            return False
        thread = getattr(self.reader, "_thread", None)
        if thread is None:
            return True
        return bool(thread.is_alive())

    def _on_targets(self, targets: list[Target]) -> None:
        with self._lock:
            self._targets = [t.as_dict() for t in targets]
            self._updated_at = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "targets": list(self._targets),
                "updated_at": self._updated_at,
            }


service = MmwaveService()
