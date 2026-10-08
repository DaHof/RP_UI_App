"""MSR605X magstripe reader/writer for the web dashboard.

Mirrors pmweb.py's shape: module-level functions, only the parts that are
real, opening the device fresh for each call rather than holding it open
across requests (see MSR605X.__enter__/__exit__ for why).

``msr.msr605x_client`` imports the ``hid`` (hidapi) package at module level,
which isn't installed on every dev machine this project runs on (see
hardware.py's PN532 fallback for the same shape of problem) -- so that import
is deferred and guarded here rather than done at module scope, and every
function below degrades to "not available" instead of taking the whole
dashboard down at startup.
"""

from __future__ import annotations

try:
    from msr.msr605x_client import MSR605X, MSR605XError, is_present

    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised on hidapi-less dev machines
    _IMPORT_ERROR = exc


def _unavailable_detail() -> str:
    return f"MSR605X support not available: {_IMPORT_ERROR}"


# Per-track BPI, remembered across calls so a card that needed 210 bpi last
# time doesn't need re-discovering on every read. In-memory only (resets on
# backend restart) -- there's no "get current BPI" device command to read
# this back from hardware, so it's tracked here instead. _bpi_failed_at[n]
# records the bpi value that JUST failed on track n, so a second consecutive
# failure after flipping to the alternate is recognized as "tried both, this
# isn't a BPI mismatch" instead of flip-flopping forever.
_BPI_DEFAULT = 75
_track_bpi = {1: _BPI_DEFAULT, 2: _BPI_DEFAULT, 3: _BPI_DEFAULT}
_bpi_failed_at: dict[int, int | None] = {1: None, 2: None, 3: None}


def device_info() -> dict:
    if _IMPORT_ERROR is not None:
        return {"connected": False, "detail": _unavailable_detail(), "model": None, "firmware": None, "coercivity": None}
    if not is_present():
        return {"connected": False, "detail": "No MSR605X detected", "model": None, "firmware": None, "coercivity": None}
    try:
        with MSR605X() as dev:
            if not dev.communication_test():
                return {"connected": False, "detail": "Found the device but it didn't answer", "model": None, "firmware": None, "coercivity": None}
            return {
                "connected": True,
                "detail": "Connected",
                "model": dev.get_device_model(),
                "firmware": dev.get_firmware_version(),
                "coercivity": dev.get_coercivity(),
            }
    except MSR605XError as exc:
        return {"connected": False, "detail": str(exc), "model": None, "firmware": None, "coercivity": None}


_EMPTY_TRACKS = {"track1": None, "track2": None, "track3": None}


def read() -> tuple[bool, str, dict, bool]:
    """Returns (ok, message, tracks, retry). `tracks` always has track1/2/3
    keys: "" means that track was blank, None means it read but failed to
    parse (bad swipe), a string is the actual decoded track data.

    `retry=True` means a track just had its BPI auto-switched (see
    _adapt_bpi) and is worth swiping again right away. This function makes
    exactly one attempt and does NOT itself wait through a second swipe --
    it can't update what's on screen while blocked inside one HTTP request,
    so the caller (the web UI) is the one that shows "swipe again" and
    calls this a second time. If that second swipe still fails on the same
    track, _adapt_bpi recognizes "both encodings ruled out" and stops
    flipping instead of going back and forth forever.
    """
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail(), _EMPTY_TRACKS, False
    if not is_present():
        return False, "No MSR605X detected", _EMPTY_TRACKS, False

    try:
        with MSR605X() as dev:
            result = dev.read_iso()
            if not result.responded:
                return False, "No card swiped, or the swipe couldn't be read -- try again", _EMPTY_TRACKS, False
            tracks = {"track1": result.track1, "track2": result.track2, "track3": result.track3}
            switched, gave_up = _adapt_bpi(dev, tracks)
    except MSR605XError as exc:
        return False, str(exc), _EMPTY_TRACKS, False

    # A string (even "") means that track decoded; None means the device
    # flagged it as a parity/framing error -- usually an uneven swipe, not a
    # wiring/protocol problem. Track 2 is the densest and the first to drop
    # out on a slightly fast or crooked swipe, so a real card can easily come
    # back with good data on tracks 1/3 and a bad track 2 -- worth surfacing
    # as a partial read instead of throwing the good tracks away.
    has_data = any(v for v in tracks.values())
    bad_tracks = [name for name, value in tracks.items() if value is None]
    if not result.ok and not has_data:
        return False, "No card swiped, or the swipe couldn't be read -- try again", tracks, False
    if not has_data:
        return False, "Swipe read OK but every track came back blank", tracks, False

    messages = []
    if switched:
        parts = " and ".join(f"track {n} (now {_track_bpi[n]} bpi)" for n in switched)
        messages.append(f"{parts} didn't decode -- switched automatically, swipe the same card again")
    if gave_up:
        parts = " and ".join(f"track {n}" for n in gave_up)
        messages.append(f"{parts} still won't decode at either 75 or 210 bpi -- likely a worn/damaged stripe, not an encoding mismatch")
    # Anything left over (e.g. the BPI switch command itself failed) falls
    # back to the plain partial-read message rather than being dropped.
    unexplained = [n for n in bad_tracks if int(n[-1]) not in switched and int(n[-1]) not in gave_up]
    if unexplained:
        parts = " and ".join(f"track {name[-1]}" for name in unexplained)
        messages.append(f"{parts} couldn't be decoded (try swiping again for a full read)")
    if messages:
        return True, "; ".join(messages), tracks, bool(switched)
    return True, "Card read", tracks, False


def _adapt_bpi(dev: "MSR605X", tracks: dict) -> tuple[list[int], list[int]]:
    """Flips BPI for any track that just failed, unless the alternate
    setting already failed on the previous attempt (in which case it gives
    up on that track rather than flip-flopping forever). Returns
    (switched_track_numbers, gave_up_track_numbers). A failure sending the
    BPI-switch command itself is swallowed -- it must never cost an
    otherwise-good read of the other tracks, it just means this one track
    stays unexplained."""
    switched: list[int] = []
    gave_up: list[int] = []
    for name, value in tracks.items():
        track = int(name[-1])
        if value is not None:
            _bpi_failed_at[track] = None  # a good read confirms the current setting
            continue
        current = _track_bpi[track]
        alternate = 210 if current == 75 else 75
        if _bpi_failed_at[track] == alternate:
            # The alternate setting was just tried (on the previous swipe)
            # and also failed -- both encodings ruled out, so stop flipping
            # and reset to the standard default for whatever card comes next.
            try:
                if current != _BPI_DEFAULT:
                    dev.select_bpi(track, _BPI_DEFAULT)
                _track_bpi[track] = _BPI_DEFAULT
                _bpi_failed_at[track] = None
                gave_up.append(track)
            except MSR605XError:
                pass
        else:
            try:
                dev.select_bpi(track, alternate)
                _track_bpi[track] = alternate
                _bpi_failed_at[track] = current
                switched.append(track)
            except MSR605XError:
                pass
    return switched, gave_up


def write(track1: str | None, track2: str | None, track3: str | None) -> tuple[bool, str]:
    if not any((track1, track2, track3)):
        return False, "Nothing to write -- at least one track needs data"
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail()
    if not is_present():
        return False, "No MSR605X detected"
    try:
        with MSR605X() as dev:
            ok, _raw = dev.write_iso(track1, track2, track3)
    except MSR605XError as exc:
        return False, str(exc)
    return (True, "Wrote card") if ok else (False, "Write failed -- make sure the card is inserted and try again")


def erase(track1: bool, track2: bool, track3: bool) -> tuple[bool, str]:
    if not any((track1, track2, track3)):
        return False, "Nothing selected to erase"
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail()
    if not is_present():
        return False, "No MSR605X detected"
    try:
        with MSR605X() as dev:
            ok = dev.erase(track1, track2, track3)
    except MSR605XError as exc:
        return False, str(exc)
    tracks = ", ".join(str(n) for n, on in ((1, track1), (2, track2), (3, track3)) if on)
    return (True, f"Erased track{'s' if ',' in tracks else ''} {tracks}") if ok else (False, "Erase failed -- make sure the card is inserted and try again")


def set_coercivity(hi: bool) -> tuple[bool, str]:
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail()
    if not is_present():
        return False, "No MSR605X detected"
    try:
        with MSR605X() as dev:
            ok = dev.set_hico() if hi else dev.set_loco()
    except MSR605XError as exc:
        return False, str(exc)
    label = "Hi-Co" if hi else "Lo-Co"
    return (True, f"Set to {label}") if ok else (False, f"Failed to set {label}")


def set_bpi(track: int, bpi: int) -> tuple[bool, str]:
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail()
    if not is_present():
        return False, "No MSR605X detected"
    try:
        with MSR605X() as dev:
            ok = dev.select_bpi(track, bpi)
    except MSR605XError as exc:
        return False, str(exc)
    return (True, f"Track {track} set to {bpi} bpi") if ok else (False, f"Failed to set track {track} to {bpi} bpi")


def read_raw() -> tuple[bool, str, dict]:
    """Returns (ok, message, tracks) where each track value is a hex string
    (e.g. "a28fa8..."), "" for a present-but-empty track, or None if the raw
    response couldn't be parsed at all. No ISO alphabet/parity check -- this
    is the literal byte capture off the stripe, so it's the only read mode
    that returns anything for a track that isn't ISO 7811 data in the first
    place, and the right source for an exact byte-for-byte clone."""
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail(), _EMPTY_TRACKS
    if not is_present():
        return False, "No MSR605X detected", _EMPTY_TRACKS
    try:
        with MSR605X() as dev:
            result = dev.read_raw()
    except MSR605XError as exc:
        return False, str(exc), _EMPTY_TRACKS

    def to_hex(value: bytes | None) -> str | None:
        return value.hex() if value is not None else None

    tracks = {"track1": to_hex(result.track1), "track2": to_hex(result.track2), "track3": to_hex(result.track3)}
    if not result.responded:
        return False, "No card swiped, or the swipe couldn't be read -- try again", tracks
    if not any(tracks.values()):
        return False, "Swipe read OK but every track came back empty", tracks
    return True, "Raw capture complete", tracks


def write_raw(track1: str | None, track2: str | None, track3: str | None) -> tuple[bool, str]:
    """track1/2/3 are hex strings, as returned by read_raw -- None or ""
    leaves that track untouched."""
    if not any((track1, track2, track3)):
        return False, "Nothing to write -- at least one track needs raw data"
    if _IMPORT_ERROR is not None:
        return False, _unavailable_detail()
    if not is_present():
        return False, "No MSR605X detected"
    try:
        t1 = bytes.fromhex(track1) if track1 else None
        t2 = bytes.fromhex(track2) if track2 else None
        t3 = bytes.fromhex(track3) if track3 else None
    except ValueError:
        return False, "Raw track data must be valid hex"
    try:
        with MSR605X() as dev:
            ok, _raw = dev.write_raw(t1, t2, t3)
    except MSR605XError as exc:
        return False, str(exc)
    return (True, "Wrote raw data to card") if ok else (False, "Write failed -- make sure the card is inserted and try again")
