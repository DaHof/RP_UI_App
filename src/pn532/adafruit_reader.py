from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

import board
import busio
from adafruit_pn532.i2c import PN532_I2C

from adafruit_pn532.adafruit_pn532 import MIFARE_CMD_AUTH_A

from pn532.reader_base import (
    MIFARE_DEFAULT_KEYS,
    NTAG_USER_MEMORY_START_BLOCK,
    BasePN532Reader,
    TagDetection,
    build_ndef_text_message,
)

# PN532 "InDataExchange" command code (NXP PN532 datasheet section 7.3.9),
# defined locally rather than importing the library's own leading-underscore
# _COMMAND_INDATAEXCHANGE -- that name is private to that module, not part of
# its public API, and could change across versions; this value itself is a
# stable protocol constant, not library-internal.
_COMMAND_INDATAEXCHANGE = 0x40

# Gen1a magic-card backdoor unlock bytes, sent as InDataExchange params (not
# PN532 command codes -- unrelated to _COMMAND_INDATAEXCHANGE above despite
# the first one sharing its value). This two-step sequence is the one widely
# reused across community PN532 tools (libnfc, various magic-card scripts)
# for unlocking Gen1a blanks; it is not documented anywhere in the
# adafruit_pn532 library itself, and this project has no magic card on hand
# to confirm it actually works against real hardware.
_MAGIC_UNLOCK_1 = 0x40
_MAGIC_UNLOCK_2 = 0x43


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

    def write_ndef_text(self, text: str) -> Tuple[bool, str]:
        """Writes a short NDEF Text record to an NTAG2xx tag held to the
        reader. Untested against real hardware -- built from the adafruit_pn532
        library's documented ntag2xx_write_block() API (4 bytes/block, user
        memory from block 4), not verified against a physical tag."""
        if not self._pn532:
            return False, "Reader not started"
        try:
            message = build_ndef_text_message(text)
        except ValueError as exc:
            return False, str(exc)

        # Pause the poll loop's own reads so it doesn't race this call for
        # the antenna field while we're mid-write.
        was_running = self._running
        self._running = False
        try:
            uid = self._pn532.read_passive_target(timeout=2.0)
            if uid is None:
                return False, "No tag present -- hold an NTAG2xx tag to the reader and try again"

            padded = message + b"\x00" * ((-len(message)) % 4)
            blocks_written = 0
            for offset in range(0, len(padded), 4):
                block_number = NTAG_USER_MEMORY_START_BLOCK + offset // 4
                chunk = padded[offset:offset + 4]
                if not self._pn532.ntag2xx_write_block(block_number, chunk):
                    return False, (
                        f"Write failed at block {block_number} after {blocks_written} block(s) "
                        "-- tag may be out of space, read-only, or was pulled away"
                    )
                blocks_written += 1
            return True, (
                f"Wrote {len(message)} bytes ({blocks_written} blocks) starting at "
                f"block {NTAG_USER_MEMORY_START_BLOCK}"
            )
        finally:
            self._running = was_running

    def dump_mifare_classic(self) -> Tuple[bool, str, Optional[str]]:
        """Dumps all 16 sectors (64 blocks) of a MIFARE Classic 1K tag,
        trying MIFARE_DEFAULT_KEYS on each sector's trailer block. A sector
        that doesn't authenticate with any of those keys is left as zeros in
        the dump rather than aborting the whole read -- partial recovery
        (e.g. one re-keyed sector among fifteen default ones) is still useful.
        Untested against real hardware."""
        if not self._pn532:
            return False, "Reader not started", None

        was_running = self._running
        self._running = False
        try:
            uid = self._pn532.read_passive_target(timeout=2.0)
            if uid is None:
                return False, "No tag present -- hold a MIFARE Classic tag to the reader and try again", None

            all_blocks = bytearray()
            sectors_read = 0
            for sector in range(16):
                trailer_block = sector * 4 + 3
                authed = any(
                    self._pn532.mifare_classic_authenticate_block(uid, trailer_block, MIFARE_CMD_AUTH_A, key)
                    for key in MIFARE_DEFAULT_KEYS
                )
                if not authed:
                    all_blocks.extend(b"\x00" * 16 * 4)
                    continue
                sectors_read += 1
                for block_offset in range(4):
                    block_number = sector * 4 + block_offset
                    data = self._pn532.mifare_classic_read_block(block_number)
                    all_blocks.extend(data if data else b"\x00" * 16)

            if sectors_read == 0:
                return False, "Could not authenticate any sector with the common default keys tried", None
            return True, f"Dumped {sectors_read}/16 sectors using default keys", all_blocks.hex()
        finally:
            self._running = was_running

    def clone_uid_to_magic(self, uid_hex: str) -> Tuple[bool, str]:
        """Best-effort Gen1a magic-card UID write -- see the module-level
        comment on _MAGIC_UNLOCK_1/_MAGIC_UNLOCK_2 for how unverified this
        path is. Only 4-byte UIDs are supported (Gen1a block-0 layout)."""
        if not self._pn532:
            return False, "Reader not started"
        clean = uid_hex.replace(":", "").replace(" ", "")
        try:
            uid_bytes = bytes.fromhex(clean)
        except ValueError:
            return False, "UID must be hex bytes, e.g. 04A1B2C3"
        if len(uid_bytes) != 4:
            return False, "Only 4-byte UIDs are supported for Gen1a block-0 write"

        was_running = self._running
        self._running = False
        try:
            target = self._pn532.read_passive_target(timeout=2.0)
            if target is None:
                return False, "No tag present -- hold the magic card to the reader and try again"

            unlock1 = self._pn532.call_function(
                _COMMAND_INDATAEXCHANGE, params=[0x01, _MAGIC_UNLOCK_1], response_length=1
            )
            if not unlock1 or unlock1[0] != 0x00:
                return False, "Backdoor unlock step 1 (0x40) failed or was refused -- likely not a Gen1a magic card"
            unlock2 = self._pn532.call_function(
                _COMMAND_INDATAEXCHANGE, params=[0x01, _MAGIC_UNLOCK_2], response_length=1
            )
            if not unlock2 or unlock2[0] != 0x00:
                return False, "Backdoor unlock step 2 (0x43) failed"

            bcc = uid_bytes[0] ^ uid_bytes[1] ^ uid_bytes[2] ^ uid_bytes[3]
            sak = 0x08  # common default SAK for MIFARE Classic 1K
            atqa = b"\x00\x04"
            manufacturer = b"\x00" * 8
            block0 = uid_bytes + bytes([bcc, sak]) + atqa + manufacturer

            if not self._pn532.mifare_classic_write_block(0, block0):
                return False, "Block 0 write rejected -- card may not actually be a Gen1a magic card"
            return True, f"Wrote UID {clean.upper()} to block 0 (best-effort, unverified against real hardware)"
        finally:
            self._running = was_running
