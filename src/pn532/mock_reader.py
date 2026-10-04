from __future__ import annotations

import threading
from typing import Optional, Tuple

from pn532.reader_base import BasePN532Reader, TagDetection, build_ndef_text_message


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

    def write_ndef_text(self, text: str) -> Tuple[bool, str]:
        if not self._running:
            return False, "Reader not started"
        try:
            message = build_ndef_text_message(text)
        except ValueError as exc:
            return False, str(exc)
        blocks = -(-len(message) // 4)  # ceil div, same chunking the real writer uses
        return True, f"(mock) wrote {len(message)} bytes ({blocks} blocks) -- no real tag, nothing physically written"

    def dump_mifare_classic(self) -> Tuple[bool, str, Optional[str]]:
        if not self._running:
            return False, "Reader not started", None
        fake_dump = ("00" * 16) * 64  # 1K card shape, all-zero placeholder
        return True, "(mock) dumped 16/16 sectors -- no real tag, this is placeholder data", fake_dump

    def clone_uid_to_magic(self, uid_hex: str) -> Tuple[bool, str]:
        if not self._running:
            return False, "Reader not started"
        clean = uid_hex.replace(":", "").replace(" ", "")
        try:
            uid_bytes = bytes.fromhex(clean)
        except ValueError:
            return False, "UID must be hex bytes, e.g. 04A1B2C3"
        if len(uid_bytes) != 4:
            return False, "Only 4-byte UIDs are supported for Gen1a block-0 write"
        return True, f"(mock) wrote UID {clean.upper()} to block 0 -- no real tag, nothing physically written"
