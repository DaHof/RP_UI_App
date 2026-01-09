from __future__ import annotations

import threading
from typing import Optional

from pn532.reader_base import BasePN532Reader, TagDetection


class MockPN532Reader(BasePN532Reader):
    def __init__(self) -> None:
        super().__init__()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)

    def simulate_tag(self, uid: str, tag_type: str) -> None:
        if not self._running:
            return
        technologies = ["ISO14443A", "NFC-A"] if tag_type else []
        detection = TagDetection(uid=uid, tag_type=tag_type, technologies=technologies)
        self._emit(detection)
