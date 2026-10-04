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
        return {"connected": False, "port": "", "detail": "No Proxmark3 detected", "raw": ""}

    result = shell.run(["proxmark3", "-p", port, "-c", "hw status"], timeout=CONNECT_TIMEOUT)
    if not result.ok:
        return {"connected": False, "port": port, "detail": result.detail, "raw": result.stdout}
    return {"connected": True, "port": port, "detail": "Connected", "raw": result.stdout}


def _search(command: str) -> tuple[bool, str, str]:
    port = find_port()
    if not port:
        return False, "No Proxmark3 detected", ""

    result = shell.run(["proxmark3", "-p", port, "-c", command], timeout=SEARCH_TIMEOUT)
    if not result.ok:
        return False, result.detail, result.stdout
    return True, "ok", result.stdout


def read_lf() -> tuple[bool, str, str]:
    return _search("lf search")


def read_hf() -> tuple[bool, str, str]:
    return _search("hf search")


def read_em410x() -> tuple[bool, str, str, str | None]:
    """Reads a 125kHz EM410x tag and pulls its ID out of the client's text
    output -- there's no machine-readable flag for `lf em 410x reader`, so
    this is regex-on-stdout. Returns (ok, message, raw, tag_id)."""
    port = find_port()
    if not port:
        return False, "No Proxmark3 detected", "", None

    result = shell.run(["proxmark3", "-p", port, "-c", "lf em 410x reader"], timeout=SEARCH_TIMEOUT)
    match = EM410X_ID_RE.search(result.stdout)
    if match:
        tag_id = match.group(1).upper()
        return True, f"Found EM410x ID {tag_id}", result.stdout, tag_id
    if not result.ok:
        return False, result.detail, result.stdout, None
    return False, "No EM410x tag found", result.stdout, None


def clone_em410x(tag_id: str, target: str = "t55x7") -> tuple[bool, str, str]:
    """Writes an EM410x ID onto a blank T55x7/Q5/EM4305 tag held to the
    antenna. `target` picks the blank chip type; unknown values fall back to
    the default T55x7 encoding (no extra flag)."""
    port = find_port()
    if not port:
        return False, "No Proxmark3 detected", ""
    if not re.fullmatch(r"[0-9A-Fa-f]{10}", tag_id):
        return False, "ID must be 10 hex characters (5 bytes), e.g. 0F0368568B", ""

    flag = EM410X_TARGETS.get(target, "")
    command = f"lf em 410x clone --id {tag_id}" + (f" {flag}" if flag else "")
    result = shell.run(["proxmark3", "-p", port, "-c", command], timeout=CLONE_TIMEOUT)
    if not result.ok:
        return False, result.detail, result.stdout
    return True, f"Cloned {tag_id} to {target}", result.stdout
