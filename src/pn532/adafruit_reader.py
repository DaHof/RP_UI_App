from __future__ import annotations

import threading
import time
from typing import Optional

import board
import busio
from adafruit_pn532.i2c import PN532_I2C

from pn532.reader_base import BasePN532Reader, TagDetection


class AdafruitPN532Reader(BasePN532Reader):
    def __init__(self, poll_interval: float = 0.5) -> None:
        super().__init__()
        self._poll_interval = poll_interval
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._pn532 = None

    def start(self) -> None:
        self._running = True
        i2c = busio.I2C(board.SCL, board.SDA)
        self._pn532 = PN532_I2C(i2c, debug=False)
        self._pn532.SAM_configuration()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def _poll_loop(self) -> None:
        while self._running and self._pn532:
            uid = self._pn532.read_passive_target(timeout=0.2)
            if uid is not None:
                uid_hex = ":".join(f"{byte:02X}" for byte in uid)
                detection = TagDetection(
                    uid=uid_hex,
                    tag_type="ISO14443A",
                    technologies=["ISO14443A", "NFC-A"],
                )
                self._emit(detection)
                time.sleep(1.0)
            time.sleep(self._poll_interval)
