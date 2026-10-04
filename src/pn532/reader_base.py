from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class TagDetection:
    uid: str
    tag_type: str
    technologies: List[str]


tag_callback = Callable[[TagDetection], None]

NTAG_USER_MEMORY_START_BLOCK = 4  # blocks 0-3 are UID/lock/capability container

# Keys that keep showing up on real-world access cards because they were
# never changed from a vendor default -- standard first pass in any
# legitimate key-recovery audit (same list class as mfoc/mfcuk ship with).
MIFARE_DEFAULT_KEYS: List[bytes] = [
    bytes.fromhex("FFFFFFFFFFFF"),
    bytes.fromhex("A0A1A2A3A4A5"),
    bytes.fromhex("D3F7D3F7D3F7"),
    bytes.fromhex("000000000000"),
    bytes.fromhex("B0B1B2B3B4B5"),
    bytes.fromhex("4D3A99C351DD"),
    bytes.fromhex("1A982C7E459A"),
]


def build_ndef_text_message(text: str, lang: str = "en") -> bytes:
    """TLV-wrapped single NDEF Text Record, for NTAG2xx user memory.

    Layout: [0x03, msg_len] + [header=0xD1, type_len=1, payload_len, 'T']
    + [lang_len, lang bytes, text bytes (UTF-8)] + [0xFE terminator].
    Short-record form only (payload must fit in one byte, i.e. <= 255).
    """
    lang_bytes = lang.encode("ascii")
    text_bytes = text.encode("utf-8")
    payload = bytes([len(lang_bytes)]) + lang_bytes + text_bytes
    if len(payload) > 255:
        raise ValueError("text too long for a short NDEF record")
    record = bytes([0xD1, 0x01, len(payload), ord("T")]) + payload
    return bytes([0x03, len(record)]) + record + bytes([0xFE])


class BasePN532Reader:
    def __init__(self) -> None:
        self._callback: Optional[tag_callback] = None

    def set_callback(self, callback: tag_callback) -> None:
        self._callback = callback

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def write_ndef_text(self, text: str) -> Tuple[bool, str]:
        """Write a short NDEF Text record to a tag held to the reader.
        Returns (ok, detail). Default: unsupported."""
        return False, "This reader does not support writing"

    def dump_mifare_classic(self) -> Tuple[bool, str, Optional[str]]:
        """Attempt a full MIFARE Classic 1K dump (16 sectors x 4 blocks)
        using MIFARE_DEFAULT_KEYS. Returns (ok, detail, hex_dump).
        Default: unsupported."""
        return False, "This reader does not support dumping", None

    def clone_uid_to_magic(self, uid_hex: str) -> Tuple[bool, str]:
        """Write a new 4-byte UID to block 0 of a Gen1a 'magic' MIFARE
        Classic blank via its backdoor unlock sequence. Returns (ok, detail).
        Default: unsupported."""
        return False, "This reader does not support magic UID writes"

    def _emit(self, detection: TagDetection) -> None:
        if self._callback:
            self._callback(detection)
