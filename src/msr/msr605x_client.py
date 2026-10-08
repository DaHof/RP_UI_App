"""Direct HID driver for the MSR605X magstripe reader/writer.

The device (USB VID:PID 0801:0003 -- sold under several names including
MagTek-alike clones branded DEFTUN) speaks a simple ESC-prefixed ASCII
command set over 64-byte HID reports, report ID 0xFF. There is no vendor
Linux driver and no virtual serial port -- it's a raw HID device, opened
directly via libhidapi.

This is a from-scratch port of the protocol documented and reverse-engineered
by magnetic-fox/msr605x (https://github.com/magnetic-fox/msr605x), confirmed
against this project's own hardware (comm test, device model, firmware
version, and coercivity all round-tripped correctly) rather than trusted
blind. ISO 7811 read/write/erase, status queries, per-track BPI selection,
and RAW (8-bit) read/write are implemented -- no leading-zero or LED
control, neither of which the dashboard's read/save/clone workflow needs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import hid

VENDOR_ID = 0x0801
PRODUCT_ID = 0x0003
REPORT_ID = b"\xff"

STATUS_TIMEOUT_MS = 100  # quick commands the device always answers immediately
SWIPE_POLL_MS = 500  # poll granularity while waiting for a card
SWIPE_DEADLINE_S = 20.0  # overall cap so a request thread can't hang forever

ESC = b"\x1b"
FS = b"\x1c"

CMD_RESET = ESC + b"a"
CMD_READ = ESC + b"r"
CMD_WRITE = ESC + b"w"
CMD_COMM_TEST = ESC + b"e"
CMD_ERASE_CARD = ESC + b"c"
CMD_BPI_SELECT = ESC + b"b"
CMD_READ_RAW = ESC + b"m"
CMD_WRITE_RAW = ESC + b"n"
CMD_BPC_SET = ESC + b"o"
CMD_GET_MODEL = ESC + b"t"
CMD_GET_FW_VERSION = ESC + b"v"
CMD_SET_HICO = ESC + b"x"
CMD_SET_LOCO = ESC + b"y"
CMD_GET_COERCIVITY = ESC + b"d"

START_SEQUENCE = ESC + b"s"
END_SEQUENCE_W = b"?" + FS
END_SEQUENCE = END_SEQUENCE_W + ESC
ISO1_DATA_START = ESC + b"\x01"
ISO2_DATA_START = ESC + b"\x02"
ISO3_DATA_START = ESC + b"\x03"

NO_DATA = ESC + b"+"
BAD_DATA = ESC + b"*"

CMD_OK = ESC + b"0"
SB_RW_OK = b"0"

COMM_OK = ESC + b"y"
HICO_SET = ESC + b"h"
LOCO_SET = ESC + b"l"

ISO_TRACK1, ISO_TRACK2, ISO_TRACK3 = 1, 2, 4

# Per-track bits-per-inch setting bytes. Bank-standard (ISO 7811/7813) track 2
# is 75 bpi, but plenty of non-bank cards (hotel keys, access badges, some
# loyalty/gift cards) record it at 210 bpi instead -- a track recorded at the
# BPI the reader isn't expecting comes back as a consistent, every-swipe
# decode/parity error, which looks identical to a bad swipe until you try the
# other setting. Track 1 and 3 can mismatch the same way, just less often in
# practice.
BPI_CODES = {
    (1, 75): b"\xa0",
    (1, 210): b"\xa1",
    (2, 75): b"\x4b",
    (2, 210): b"\xd2",
    (3, 75): b"\xc0",
    (3, 210): b"\xc1",
}

START_SENTINEL_1 = "%"
START_SENTINEL_2_3 = ";"
END_SENTINEL = "?"

# % and ? excluded: they are the start/end sentinels, not data.
ISO1_ALPHABET = " #$()-./0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^"
ISO2_ALPHABET = "0123456789="
ISO3_ALPHABET = "0123456789="
ISO1_MAXSIZE = 76
ISO2_MAXSIZE = 37
ISO3_MAXSIZE = 104


class MSR605XError(Exception):
    """Device missing, unopenable, or a command failed outright."""


@dataclass
class IsoReadResult:
    ok: bool
    # Whether the device sent back a structured response at all -- distinct
    # from `ok`, which reflects its status byte. A true "nothing swiped"
    # timeout and "swiped but every track was unreadable" look identical by
    # track1/2/3 alone (all None), but only the latter is worth auto-retrying
    # a BPI switch over; this flag is what callers use to tell them apart.
    responded: bool
    track1: str | None
    track2: str | None
    track3: str | None
    raw: bytes = b""


@dataclass
class RawReadResult:
    """Like IsoReadResult, but tracks are the literal bytes off the stripe --
    no ISO alphabet or parity check, so this is the only thing that returns
    anything for a track that isn't ISO 7811 data at all (e.g. some
    proprietary access-control encoding). None means the device reported no
    data for that track (not: failed to parse -- RAW mode has nothing to
    parse), b"" means a present-but-empty track."""

    ok: bool
    responded: bool
    track1: bytes | None
    track2: bytes | None
    track3: bytes | None
    raw: bytes = b""


def is_present() -> bool:
    """Cheap presence check via HID enumeration -- no open, no permissions
    needed, same role as proxmark_client.find_port()."""
    return any(
        d["vendor_id"] == VENDOR_ID and d["product_id"] == PRODUCT_ID
        for d in hid.enumerate()
    )


def validate_track(value: str, track: int) -> str | None:
    """Returns an error string if `value` can't be written to that track,
    else None. Mirrors the device's own ISO 7811 alphabet/length limits so
    a bad write attempt fails in the UI, not silently on the card."""
    alphabet, maxsize = {
        1: (ISO1_ALPHABET, ISO1_MAXSIZE),
        2: (ISO2_ALPHABET, ISO2_MAXSIZE),
        3: (ISO3_ALPHABET, ISO3_MAXSIZE),
    }[track]
    if len(value) > maxsize:
        return f"Track {track} data is too long (max {maxsize} characters)"
    for char in value:
        if char not in alphabet:
            return f"Track {track} can't contain '{char}'"
    return None


class MSR605X:
    """Opens the device for the duration of a `with` block, then closes it --
    no connection held across requests, so a crashed call can't wedge the
    handle the way a stuck serial port would."""

    def __init__(self, vendor_id: int = VENDOR_ID, product_id: int = PRODUCT_ID) -> None:
        self._vendor_id = vendor_id
        self._product_id = product_id
        self._dev: hid.device | None = None

    def __enter__(self) -> "MSR605X":
        self._dev = hid.device()
        try:
            self._dev.open(self._vendor_id, self._product_id)
        except OSError as exc:
            self._dev = None
            raise MSR605XError(
                "Could not open the MSR605X -- check the USB connection and the "
                "99-msr605x udev rule (see README)"
            ) from exc
        self._dev.set_nonblocking(False)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._dev is not None:
            self._dev.close()
            self._dev = None

    # ---- framing --------------------------------------------------------
    def _send(self, payload: bytes) -> None:
        assert self._dev is not None
        first, rest = payload[:62], payload[62:]
        frames = [b"\x00" + first] + [rest[i : i + 63] for i in range(0, len(rest), 63)]
        for frame in frames:
            padded = frame + b"\x00" * (63 - len(frame))
            self._dev.write(REPORT_ID + padded)

    def _recv(self, wait_for_swipe: bool = False) -> bytes:
        """Quick commands (status queries) use a short idle timeout and
        return as soon as the device goes quiet. Swipe-dependent commands
        (read/write/erase) poll at SWIPE_POLL_MS until data starts arriving,
        then drain at the short timeout -- same two-phase shape as the
        reference driver's readData(), with an added wall-clock deadline so
        a never-swiped card can't hang the request forever."""
        assert self._dev is not None
        buf = b""
        timeout = SWIPE_POLL_MS if wait_for_swipe else STATUS_TIMEOUT_MS
        deadline = time.monotonic() + SWIPE_DEADLINE_S
        while True:
            chunk = bytes(self._dev.read(64, timeout))[1:]
            if chunk:
                buf += chunk
                timeout = STATUS_TIMEOUT_MS
            elif not wait_for_swipe or buf:
                break
            if time.monotonic() > deadline:
                break
        return buf

    # ---- status -----------------------------------------------------------
    def communication_test(self) -> bool:
        self._send(CMD_COMM_TEST)
        return self._recv()[0:2] == COMM_OK

    def get_device_model(self) -> str:
        data = self._recv_after(CMD_GET_MODEL)
        if len(data) >= 3 and data[0:1] == ESC and data[2:3] == b"S":
            return data[1:2].decode(errors="replace")
        return "?"

    def get_firmware_version(self) -> str:
        data = self._recv_after(CMD_GET_FW_VERSION)
        if len(data) >= 9 and data[0:1] == ESC:
            return data[1:9].decode(errors="replace")
        return "?"

    def get_coercivity(self) -> str:
        data = self._recv_after(CMD_GET_COERCIVITY)
        if data[0:2] == HICO_SET:
            return "H"
        if data[0:2] == LOCO_SET:
            return "L"
        return "?"

    def set_hico(self) -> bool:
        return self._recv_after(CMD_SET_HICO)[0:2] == CMD_OK

    def set_loco(self) -> bool:
        return self._recv_after(CMD_SET_LOCO)[0:2] == CMD_OK

    def select_bpi(self, track: int, bpi: int) -> bool:
        code = BPI_CODES.get((track, bpi))
        if code is None:
            raise MSR605XError(f"No such BPI setting: track {track} at {bpi} bpi (valid: 75 or 210)")
        return self._recv_after(CMD_BPI_SELECT + code)[0:2] == CMD_OK

    def _recv_after(self, command: bytes) -> bytes:
        self._send(command)
        return self._recv()

    # ---- ISO 7811 read/write/erase ----------------------------------------
    def read_iso(self) -> IsoReadResult:
        # Explicit, not assumed: a prior RAW operation on this same device
        # leaves BPC at 8/8/8, which would silently corrupt ISO mode's
        # character packing (7/5/5) if read_iso just trusted whatever was
        # last set.
        self.set_bpc(7, 5, 5)
        self._send(CMD_READ)
        raw = self._recv(wait_for_swipe=True)
        return self._parse_iso(raw)

    def write_iso(self, track1: str | None, track2: str | None, track3: str | None) -> tuple[bool, bytes]:
        self.set_bpc(7, 5, 5)
        for value, track in ((track1, 1), (track2, 2), (track3, 3)):
            if value:
                error = validate_track(value, track)
                if error:
                    raise MSR605XError(error)
        payload = START_SEQUENCE
        payload += ISO1_DATA_START + (track1.encode() if track1 else b"")
        payload += ISO2_DATA_START + (track2.encode() if track2 else b"")
        payload += ISO3_DATA_START + (track3.encode() if track3 else b"")
        payload += END_SEQUENCE_W
        self._send(CMD_WRITE + payload)
        raw = self._recv(wait_for_swipe=True)
        ok = len(raw) >= 2 and raw[0:1] == ESC and raw[1:2] == SB_RW_OK
        return ok, raw

    def erase(self, track1: bool, track2: bool, track3: bool) -> bool:
        if not (track1 or track2 or track3):
            return True
        select = (ISO_TRACK1 if track1 else 0) | (ISO_TRACK2 if track2 else 0) | (ISO_TRACK3 if track3 else 0)
        self._send(CMD_ERASE_CARD + select.to_bytes(1, "big"))
        return self._recv(wait_for_swipe=True)[0:2] == CMD_OK

    # ---- RAW (8-bit) read/write -- bypasses ISO alphabet/parity checking,
    # so this is the only mode that returns anything for a track that isn't
    # valid ISO 7811 data at all (e.g. a proprietary access-control scheme),
    # and the right tool for an exact byte-for-byte clone regardless of what
    # format is actually on the stripe. ------------------------------------
    def set_bpc(self, track1: int, track2: int, track3: int) -> tuple[bool, int, int, int]:
        """Bits-per-character, 5-8. RAW mode needs 8/8/8 for byte-transparent
        transfer -- ISO mode's default (7/5/5 packing) would corrupt
        anything that isn't already valid ISO data. Returns (ok, track1,
        track2, track3) -- the device's own echo of what it actually set,
        falling back to the requested values on failure."""
        self._send(CMD_BPC_SET + bytes((track1, track2, track3)))
        data = self._recv()
        if len(data) >= 5 and data[0:2] == CMD_OK:
            return True, data[2], data[3], data[4]
        return False, track1, track2, track3

    def read_raw(self) -> RawReadResult:
        self.set_bpc(8, 8, 8)
        self._send(CMD_READ_RAW)
        raw = self._recv(wait_for_swipe=True)
        return self._parse_raw(raw)

    def write_raw(self, track1: bytes | None, track2: bytes | None, track3: bytes | None) -> tuple[bool, bytes]:
        self.set_bpc(8, 8, 8)
        track1, track2, track3 = track1 or b"", track2 or b"", track3 or b""
        for value, track in ((track1, 1), (track2, 2), (track3, 3)):
            if len(value) > 255:
                raise MSR605XError(f"Track {track} raw data is too long ({len(value)} bytes, max 255)")
        payload = START_SEQUENCE
        payload += ISO1_DATA_START + len(track1).to_bytes(1, "big") + _bytes_to_lsb(track1)
        payload += ISO2_DATA_START + len(track2).to_bytes(1, "big") + _bytes_to_lsb(track2)
        payload += ISO3_DATA_START + len(track3).to_bytes(1, "big") + _bytes_to_lsb(track3)
        payload += END_SEQUENCE_W
        self._send(CMD_WRITE_RAW + payload)
        raw = self._recv(wait_for_swipe=True)
        ok = len(raw) >= 2 and raw[0:1] == ESC and raw[1:2] == SB_RW_OK
        return ok, raw

    @staticmethod
    def _parse_raw(raw: bytes) -> RawReadResult:
        if raw[0:2] != START_SEQUENCE:
            return RawReadResult(False, False, None, None, None, raw)
        try:
            iso1_marker = raw.find(ISO1_DATA_START)
            iso2_marker = raw.find(ISO2_DATA_START)
            iso3_marker = raw.find(ISO3_DATA_START)
            end_pos = raw.find(END_SEQUENCE) + 3
            # The length byte in a RAW read response is (actual length + 1)
            # -- a firmware quirk distinct from the write side, where the
            # length sent is the literal byte count. Kept exactly as the
            # reference implementation documents it.
            iso1_size = raw[iso1_marker + 2] - 1
            iso2_size = raw[iso2_marker + 2] - 1
            iso3_size = raw[iso3_marker + 2] - 1
            iso1_pos, iso2_pos, iso3_pos = iso1_marker + 3, iso2_marker + 3, iso3_marker + 3
            track1 = raw[iso1_pos : iso1_pos + iso1_size] if iso1_size > 0 else b""
            track2 = raw[iso2_pos : iso2_pos + iso2_size] if iso2_size > 0 else b""
            track3 = raw[iso3_pos : iso3_pos + iso3_size] if iso3_size > 0 else b""
            status = raw[end_pos : end_pos + 1]
            return RawReadResult(status == SB_RW_OK, True, track1, track2, track3, raw)
        except (ValueError, IndexError):
            return RawReadResult(False, True, None, None, None, raw)

    @staticmethod
    def _parse_iso(raw: bytes) -> IsoReadResult:
        if raw[0:2] != START_SEQUENCE:
            return IsoReadResult(False, False, None, None, None, raw)
        try:
            iso1_pos = raw.find(ISO1_DATA_START) + 2
            iso2_pos = raw.find(ISO2_DATA_START) + 2
            iso3_pos = raw.find(ISO3_DATA_START) + 2
            end_pos = raw.find(END_SEQUENCE) + 3
            iso1_raw = raw[iso1_pos : iso2_pos - 2]
            iso2_raw = raw[iso2_pos : iso3_pos - 2]
            iso3_raw = raw[iso3_pos : end_pos - 3]
            status = raw[end_pos : end_pos + 1]
            track1 = _strip_sentinels(iso1_raw, START_SENTINEL_1)
            track2 = _strip_sentinels(iso2_raw, START_SENTINEL_2_3)
            track3 = _strip_sentinels(iso3_raw, START_SENTINEL_2_3)
            return IsoReadResult(status == SB_RW_OK, True, track1, track2, track3, raw)
        except (ValueError, IndexError):
            return IsoReadResult(False, True, None, None, None, raw)


def _strip_sentinels(data: bytes, start_sentinel: str) -> str | None:
    """None means "bad read" (parity/framing error on that track), "" means
    "no data" (track genuinely blank) -- same no-data/bad-data distinction
    the device itself reports, kept instead of collapsing both to ""."""
    if data == NO_DATA:
        return ""
    if data == BAD_DATA:
        return None
    if len(data) >= 2 and chr(data[0]) == start_sentinel and chr(data[-1]) == END_SENTINEL:
        return data[1:-1].decode(errors="replace")
    return None


def _bit_reverse_byte(byte: int) -> int:
    """Reverses the bit order within one byte."""
    result = 0
    for _ in range(8):
        result = (result << 1) | (byte & 1)
        byte >>= 1
    return result


def _bytes_to_lsb(data: bytes) -> bytes:
    """RAW mode writes expect track data bit-reversed (LSB-first) rather
    than normal byte order -- a firmware quirk of this device family, not
    something RAW reads do symmetrically (the read path hands back bytes
    as-is; only write needs this)."""
    return bytes(_bit_reverse_byte(b) for b in data)
