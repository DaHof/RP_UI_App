"""Proxmark3 for the web dashboard, via guarded ``proxmark3 -c`` calls.

Mirrors ``btweb.py``'s shape: one module, only the parts that are real.

Does not call the ``pm3`` launcher script -- given no ``-p``, it falls back to
a blocking "waiting for Proxmark3 to appear" loop with no timeout of its own,
which would hang a request worker exactly like the thing ``shell.run`` exists
to prevent. Instead the port is found the same way ``pm3`` finds it on Linux
(a ``/dev/ttyACM*`` device whose USB manufacturer string is "proxmark.org"),
and every command runs as ``proxmark3 -p <port> -c "<command>"`` -- a single
shot, through the real client binary, with ``shell.run``'s own timeout as the
backstop.
"""

from __future__ import annotations

import re
from pathlib import Path

import shell

CONNECT_TIMEOUT = 8.0
SEARCH_TIMEOUT = 20.0  # `lf search` / `hf search` sweep several tag types
CLONE_TIMEOUT = 25.0  # writing several T55x7 blocks takes longer than a read

# The client's print format is the literal string "EM 410x ID " (confirmed by
# grepping it out of the stripped /usr/bin/proxmark3 binary -- this project
# has no EM410x tag on hand to capture a real `lf em 410x reader` hit against,
# so the separator between "ID" and the hex value is matched loosely on
# purpose. If a real tag doesn't parse, the full raw output is still shown in
# the UI so the ID can be read manually.
EM410X_ID_RE = re.compile(r"EM\s?410x\s+ID\s*:?\s*([0-9A-Fa-f]{10})", re.IGNORECASE)

EM410X_TARGETS = {
    "t55x7": "",
    "q5": "--q5",
    "em4305": "--em",
}

# `hf search`'s ISO14443-A block looks like:
#   [+]  UID: FD 20 66 FC   ( ONUID, re-used )
#   [+] ATQA: 00 04
#   [+]  SAK: 08 [2]
#   [+] Possible types:
#   [+]    MIFARE Classic 1K
# As with EM410X_ID_RE, this project has no HF card dump captured from every
# tag family (ISO15693, FeliCa, iCLASS, ...) to confirm against, so only the
# ISO14443-A case -- the one actually exercised against real hardware -- is
# parsed; anything else falls back to the raw text with no UID/tag_type.
HF_UID_RE = re.compile(r"UID:\s*([0-9A-Fa-f]{2}(?:\s[0-9A-Fa-f]{2})*)")
HF_TYPE_RE = re.compile(r"Possible types:\s*\n\[\+\]\s*(.+)")


def _manufacturer(tty_name: str) -> str:
    # Same relative path the `pm3` launcher script itself greps:
    # /sys/class/tty/ttyACM0/../../../manufacturer
    try:
        path = (Path(f"/sys/class/tty/{tty_name}") / ".." / ".." / ".." / "manufacturer").resolve()
        return path.read_text().strip()
    except OSError:
        return ""


def find_port() -> str | None:
    for port in sorted(Path("/dev").glob("ttyACM*")):
        if "proxmark.org" in _manufacturer(port.name):
            return str(port)
    return None


def device_info() -> dict:
    port = find_port()
    if not port:
        return {"connected": False, "port": "", "detail": "No card reader detected", "raw": ""}

    result = shell.run(["proxmark3", "-p", port, "-c", "hw status"], timeout=CONNECT_TIMEOUT)
    if not result.ok:
        return {"connected": False, "port": port, "detail": result.detail, "raw": result.stdout}
    return {"connected": True, "port": port, "detail": "Connected", "raw": result.stdout}


def _search(command: str) -> tuple[bool, str, str]:
    port = find_port()
    if not port:
        return False, "No card reader detected", ""

    result = shell.run(["proxmark3", "-p", port, "-c", command], timeout=SEARCH_TIMEOUT)
    if not result.ok:
        return False, result.detail, result.stdout
    return True, "ok", result.stdout


def read_lf() -> tuple[bool, str, str]:
    return _search("lf search")


def _parse_hf(raw: str) -> tuple[str | None, str | None]:
    uid_match = HF_UID_RE.search(raw)
    if not uid_match:
        return None, None
    uid = uid_match.group(1).replace(" ", "").upper()
    type_match = HF_TYPE_RE.search(raw)
    tag_type = type_match.group(1).strip() if type_match else "ISO14443-A"
    return uid, tag_type


def read_hf() -> tuple[bool, str, str, str | None, str | None]:
    """Runs `hf search` and, for the ISO14443-A case, also pulls out a UID
    and possible tag type so the UI can offer a Save-to-library button --
    other HF families (ISO15693, FeliCa, iCLASS, ...) still show their raw
    text but with no parsed UID. Returns (ok, message, raw, uid, tag_type)."""
    ok, message, raw = _search("hf search")
    uid, tag_type = _parse_hf(raw)
    return ok, message, raw, uid, tag_type


def scan() -> dict:
    """One combined LF+HF pass for the Simple-mode "Scan card" button --
    tries HF first (the far more common case: Mifare/NTAG/etc.), then falls
    back to LF, so the person doesn't have to know which frequency their
    card uses before pressing anything."""
    port = find_port()
    if not port:
        return {"found": "disconnected", "uid": None, "tag_type": None, "raw": ""}

    _, _, hf_raw = _search("hf search")
    uid, tag_type = _parse_hf(hf_raw)
    if uid:
        return {"found": "hf", "uid": uid, "tag_type": tag_type, "raw": hf_raw}

    _, _, lf_raw = _search("lf search")
    em_match = EM410X_ID_RE.search(lf_raw)
    combined_raw = hf_raw + "\n\n" + lf_raw
    if em_match:
        return {"found": "lf", "uid": em_match.group(1).upper(), "tag_type": "EM410x", "raw": combined_raw}

    return {"found": "none", "uid": None, "tag_type": None, "raw": combined_raw}


def read_em410x() -> tuple[bool, str, str, str | None]:
    """Reads a 125kHz EM410x tag and pulls its ID out of the client's text
    output -- there's no machine-readable flag for `lf em 410x reader`, so
    this is regex-on-stdout. Returns (ok, message, raw, tag_id)."""
    port = find_port()
    if not port:
        return False, "No card reader detected", "", None

    result = shell.run(["proxmark3", "-p", port, "-c", "lf em 410x reader"], timeout=SEARCH_TIMEOUT)
    match = EM410X_ID_RE.search(result.stdout)
    if match:
        tag_id = match.group(1).upper()
        return True, f"Found EM410x ID {tag_id}", result.stdout, tag_id
    if not result.ok:
        return False, result.detail, result.stdout, None
    return False, "No EM410x tag found", result.stdout, None


def clone_mifare_uid(uid_hex: str) -> tuple[bool, str, str]:
    """Writes a new UID onto a Gen1a magic MIFARE Classic card via the
    client's own `hf mf csetuid` -- a documented backdoor command, unlike the
    hand-rolled unlock-byte sequence the PN532 path uses, so this one is a
    real client feature rather than a best-effort guess."""
    port = find_port()
    if not port:
        return False, "No card reader detected", ""
    clean = uid_hex.replace(":", "").replace(" ", "")
    if not re.fullmatch(r"[0-9A-Fa-f]{8}|[0-9A-Fa-f]{14}", clean):
        return False, "UID must be 4 or 7 hex bytes (8 or 14 hex characters)", ""

    result = shell.run(["proxmark3", "-p", port, "-c", f"hf mf csetuid -u {clean}"], timeout=CLONE_TIMEOUT)
    if not result.ok:
        return False, result.detail, result.stdout
    return True, f"Wrote UID {clean.upper()} to magic card", result.stdout


def clone_em410x(tag_id: str, target: str = "t55x7") -> tuple[bool, str, str]:
    """Writes an EM410x ID onto a blank T55x7/Q5/EM4305 tag held to the
    antenna. `target` picks the blank chip type; unknown values fall back to
    the default T55x7 encoding (no extra flag)."""
    port = find_port()
    if not port:
        return False, "No card reader detected", ""
    if not re.fullmatch(r"[0-9A-Fa-f]{10}", tag_id):
        return False, "ID must be 10 hex characters (5 bytes), e.g. 0F0368568B", ""

    flag = EM410X_TARGETS.get(target, "")
    command = f"lf em 410x clone --id {tag_id}" + (f" {flag}" if flag else "")
    result = shell.run(["proxmark3", "-p", port, "-c", command], timeout=CLONE_TIMEOUT)
    if not result.ok:
        return False, result.detail, result.stdout
    return True, f"Cloned {tag_id} to {target}", result.stdout
