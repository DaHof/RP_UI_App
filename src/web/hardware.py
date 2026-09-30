"""Reader lifecycle that degrades instead of crashing.

``src/main.py`` builds its reader with no error handling, and
``pn532/adafruit_reader.py`` imports ``board``/``busio``/``adafruit_pn532`` at
module scope -- so on any machine without the CircuitPython stack, merely
importing it raises. A missing or unplugged PN532 therefore takes the whole
process down rather than showing a red LED.

Here both the import and ``start()`` are guarded, the failure reason is kept,
and the mock reader takes over so the rest of the dashboard stays usable.
"""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from pn532.mock_reader import MockPN532Reader
from pn532.reader_base import BasePN532Reader, TagDetection

MAX_RECENT = 50


@dataclass(frozen=True)
class ReaderStatus:
    requested: str          # what PN532_READER asked for
    active: str             # what we actually ended up running
    degraded: bool          # asked for hardware, fell back to mock
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ReaderService:
    """Owns the reader, its failure state, and the recent-scan buffer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recent: deque[dict] = deque(maxlen=MAX_RECENT)
        self.reader: BasePN532Reader = MockPN532Reader()
        self.status = ReaderStatus("mock", "mock", False, False)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> ReaderStatus:
        requested = os.environ.get("PN532_READER", "mock").strip().lower()
        reader, degraded, reason = self._build(requested)

        reader.set_callback(self._on_tag)
        started = True
        try:
            reader.start()
        except Exception as exc:
            started = False
            reason = reason or f"{type(exc).__name__}: {exc}"
            if requested != "mock":
                # Hardware start failed; fall back so the UI still works.
                reader = MockPN532Reader()
                reader.set_callback(self._on_tag)
                degraded = True
                try:
                    reader.start()
                    started = True
                except Exception as fallback_exc:
                    reason = f"{reason} (mock fallback also failed: {fallback_exc})"

        active = "mock" if isinstance(reader, MockPN532Reader) else requested
        self.reader = reader
        self.status = ReaderStatus(requested, active, degraded, started, reason)
        return self.status

    def _build(self, requested: str) -> tuple[BasePN532Reader, bool, str]:
        if requested != "adafruit":
            return MockPN532Reader(), False, ""
        try:
            # Deferred: importing this module touches board/busio at import time.
            from pn532.adafruit_reader import AdafruitPN532Reader

            return AdafruitPN532Reader(), False, ""
        except Exception as exc:
            hint = ""
            if isinstance(exc, ImportError):
                hint = " (CircuitPython stack not installed - Pi only)"
            return (
                MockPN532Reader(),
                True,
                f"{type(exc).__name__}: {exc}{hint}",
            )

    def stop(self) -> None:
        try:
            self.reader.stop()
        except Exception:
            pass

    # -- state -------------------------------------------------------------

    @property
    def polling(self) -> bool:
        """False if a hardware poll thread died mid-session.

        ``AdafruitPN532Reader._poll_loop`` calls ``read_passive_target``
        unguarded, so an I2C fault kills the thread silently and the reader
        looks healthy while reading nothing.
        """
        if not self.status.started:
            return False
        thread = getattr(self.reader, "_thread", None)
        if thread is None:
            return True          # mock reader has no poll thread to lose
        return bool(thread.is_alive())

    def _on_tag(self, detection: TagDetection) -> None:
        with self._lock:
            self._recent.appendleft(
                {
                    "uid": detection.uid,
                    "tag_type": detection.tag_type,
                    "technologies": list(detection.technologies),
                    "seen_at": _now(),
                }
            )

    def recent(self, limit: int = 20) -> list[dict]:
        with self._lock:
            return list(self._recent)[:limit]

    def simulate(self, uid: str, tag_type: str) -> bool:
        """Fire a fake detection. Only possible on the mock reader."""
        reader = self.reader
        if not isinstance(reader, MockPN532Reader):
            return False
        reader.simulate_tag(uid, tag_type)
        return True


service = ReaderService()
