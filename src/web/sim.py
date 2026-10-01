"""Synthetic hardware states, so every visual state is reachable off-device.

Almost every probe this dashboard runs (``i2cdetect``, ``vcgencmd``, ``rtl_test``,
``pm3``, ``iw``, ``systemctl``) only exists on the Pi. On any other machine they
are simply absent, so the UI would never show anything but failures and could
never be checked against a passing or degraded state.

``PIPUI_SIM`` feeds canned data through the *real* code path instead of
branching the UI: the parsers, the probe registry and the rendering all still
run for real, only the subprocess results are fabricated. That keeps the
simulation honest -- a parser bug still shows up.

This module deliberately imports nothing from the rest of the app: ``shell`` and
``probes`` import it, so it must not import them back. It therefore returns
plain tuples and lets the caller build its own dataclasses.

Modes: ``off`` (default), ``pass``, ``fail``, ``mixed``.
"""

from __future__ import annotations

import os

_VALID = ("off", "pass", "fail", "mixed")


def mode() -> str:
    value = os.environ.get("PIPUI_SIM", "off").strip().lower()
    return value if value in _VALID else "off"


def active() -> bool:
    return mode() != "off"


# --------------------------------------------------------------------------
# Canned command output
# --------------------------------------------------------------------------

_I2C_WITH_PN532 = """\
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- 24 -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --"""

_I2C_EMPTY = _I2C_WITH_PN532.replace(" 24 ", " -- ")

# Two fake nearby devices, used wherever bluetoothctl's "pass"/"mixed" output is
# needed: one already paired (so paired-devices and devices both have content
# worth rendering), one discoverable-only.
_BT_SPEAKER = "AA:BB:CC:DD:EE:01"
_BT_KEYBOARD = "AA:BB:CC:DD:EE:02"
_BT_DEVICES = f"Device {_BT_SPEAKER} JBL Flip 5\nDevice {_BT_KEYBOARD} Keyboard K380"
_BT_PAIRED = f"Device {_BT_KEYBOARD} Keyboard K380"
_BT_ICONS = {_BT_SPEAKER: "audio-card", _BT_KEYBOARD: "input-keyboard"}

_LSUSB_FULL = """\
Bus 001 Device 002: ID 1d6b:0002 Linux Foundation 2.0 root hub
Bus 001 Device 004: ID 0bda:2838 Realtek Semiconductor Corp. RTL2838 DVB-T
Bus 001 Device 005: ID 9ac4:4b8f J. Westhues ProxMark-3 RFID Instrument"""

_LSUSB_BARE = "Bus 001 Device 002: ID 1d6b:0002 Linux Foundation 2.0 root hub"

_RTL_TEST_OK = """\
Found 1 device(s):
  0:  Realtek, RTL2838UHIDIR, SN: 00000001
Supported gain values (29)"""

_IW_MONITOR = """\
Wiphy phy0
	Supported interface modes:
		 * managed
		 * monitor"""

_IW_NO_MONITOR = """\
Wiphy phy0
	Supported interface modes:
		 * managed"""


def _table(mode_name: str) -> dict[str, tuple[int, str, str]]:
    """Canned ``(returncode, stdout, stderr)`` keyed by the binary name."""
    if mode_name == "fail":
        return {
            "i2cdetect": (0, _I2C_EMPTY, ""),
            "lsusb": (0, _LSUSB_BARE, ""),
            "vcgencmd": (0, "temp=82.6'C", ""),
            "rtl_test": (1, "", "No supported devices found."),
            "pm3": (127, "", "Command not found."),
            "iw": (0, _IW_NO_MONITOR, ""),
            "systemctl": (3, "inactive", ""),
            "irsend": (127, "", "Command not found."),
            "ir-ctl": (127, "", "Command not found."),
            "bluetoothctl": (127, "", "Command not found."),
        }
    if mode_name == "mixed":
        return {
            "i2cdetect": (0, _I2C_WITH_PN532, ""),
            "lsusb": (0, _LSUSB_BARE + "\nBus 001 Device 004: ID 0bda:2838 "
                         "Realtek Semiconductor Corp. RTL2838 DVB-T", ""),
            "vcgencmd": (0, "temp=71.4'C", ""),
            "rtl_test": (0, _RTL_TEST_OK, "Failed to open rtlsdr device #0"),
            "pm3": (127, "", "Command not found."),
            "iw": (0, _IW_NO_MONITOR, ""),
            "systemctl": (0, "active", ""),
            "irsend": (0, "", ""),
            "ir-ctl": (0, "", ""),
            "bluetoothctl": (0, "", ""),
        }
    # "pass"
    return {
        "i2cdetect": (0, _I2C_WITH_PN532, ""),
        "lsusb": (0, _LSUSB_FULL, ""),
        "vcgencmd": (0, "temp=48.1'C", ""),
        "rtl_test": (0, _RTL_TEST_OK, ""),
        "pm3": (0, "Iceman/master/v4.19552", ""),
        "iw": (0, _IW_MONITOR, ""),
        "systemctl": (0, "active", ""),
        "irsend": (0, "", ""),
        "ir-ctl": (0, "", ""),
        "bluetoothctl": (0, "", ""),
    }


def command(argv: list[str]) -> tuple[int, str, str] | None:
    """Canned result for ``argv``, or ``None`` to let the real command run."""
    if not active() or not argv:
        return None

    binary = argv[0].rsplit("/", 1)[-1]
    result = _table(mode()).get(binary)
    if result is None:
        return None

    # vcgencmd is two different probes behind one binary.
    if binary == "vcgencmd" and "get_throttled" in argv:
        m = mode()
        if m == "fail":
            return 0, "throttled=0x50005", ""       # under-voltage + throttled, now and historically
        if m == "mixed":
            return 0, "throttled=0x60000", ""       # historical only
        return 0, "throttled=0x0", ""

    # bluetoothctl is one binary standing in for a dozen subcommands; "pass" and
    # "mixed" both get a working stack with two fake devices so Discovery,
    # Pairing and Connection can all be exercised off-device. "fail" already
    # reports the binary itself as missing via _table(), so nothing further to
    # special-case there.
    if binary == "bluetoothctl" and mode() != "fail":
        if "devices" in argv and "paired-devices" not in argv:
            return 0, _BT_DEVICES, ""
        if "paired-devices" in argv:
            return 0, _BT_PAIRED, ""
        if "info" in argv:
            address = argv[-1]
            icon = _BT_ICONS.get(address, "unknown")
            return 0, f"Device {address}\n\tIcon: {icon}\n\tPaired: {'yes' if address == _BT_KEYBOARD else 'no'}", ""
        # scan / power / pair / trust / connect / disconnect / remove: a bare
        # success is enough -- callers care about the return code, not stdout.
        return 0, "", ""
    return result


# --------------------------------------------------------------------------
# Canned probe verdicts
# --------------------------------------------------------------------------

_PROBE_STATES: dict[str, dict[str, tuple[str, str]]] = {
    "pass": {},   # empty: let probes derive PASS from the canned command output
    "fail": {},
    "mixed": {
        # Only states the command table cannot express on its own.
        "pn532": ("PASS", "Mock reader active (simulated)"),
        "proxmark": ("FAIL", "pm3 not installed"),
    },
}


def probe(name: str) -> tuple[str, str] | None:
    """Canned ``(status, detail)`` for a probe, or ``None`` to run it for real."""
    if not active():
        return None
    return _PROBE_STATES.get(mode(), {}).get(name)


def banner() -> str:
    return "" if not active() else f"SIMULATION MODE: {mode()}"
