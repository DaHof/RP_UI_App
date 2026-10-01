"""Bluetooth for the web dashboard, via guarded bluetoothctl calls.

Does not use ``BlueZClient`` (src/bluetooth/bluez_client.py). Its ``_run``
passes ``check=True`` and no ``timeout`` to ``subprocess.run``, so a device that
needs on-screen confirmation to pair would hang that call -- and by extension a
request worker -- forever. The commands it issues are simple and worth
re-deriving directly against the guarded ``shell.run`` instead of reusing a
client built without this constraint in mind.

Of the six tabs the Tkinter Bluetooth screen has, only part of it is backed by
real bluetoothctl calls: Discovery, Pairing, Connection, and Audio's
"auto pair + play" composite. "Test Audio", Library's "Save Device", and all of
Shortcuts just set a status label with no action behind them (verified by
reading app.py directly) -- there is no saved-device store to port. This module
implements only the real part, as one consolidated service rather than
Tkinter's six-tab split.
"""

from __future__ import annotations

from dataclasses import dataclass

import shell

SCAN_SECONDS = 6
SCAN_TIMEOUT = SCAN_SECONDS + 4.0   # headroom over bluetoothctl's own --timeout
ACTION_TIMEOUT = 15.0               # pair/connect can wait on the remote device


@dataclass(frozen=True)
class BluetoothDevice:
    name: str
    address: str

    def as_dict(self) -> dict:
        return {"name": self.name, "address": self.address}


def _parse_devices(stdout: str) -> list[BluetoothDevice]:
    devices: list[BluetoothDevice] = []
    for line in stdout.splitlines():
        if not line.startswith("Device "):
            continue
        parts = line.split(" ", 2)
        if len(parts) < 3:
            continue
        devices.append(BluetoothDevice(name=parts[2].strip(), address=parts[1].strip()))
    return devices


def _device_type(address: str) -> str:
    result = shell.run(["bluetoothctl", "info", address], timeout=4.0)
    if not result.ok:
        return "Unknown"
    for line in result.stdout.splitlines():
        if line.strip().startswith("Icon:"):
            return line.split(":", 1)[1].strip()
    return "Unknown"


def _with_types(devices: list[BluetoothDevice]) -> list[dict]:
    return [{**d.as_dict(), "type": _device_type(d.address)} for d in devices]


def scan() -> tuple[bool, str, list[dict]]:
    """Blocks for ~6s -- bluetoothctl's own --timeout makes this synchronous.

    Callers must run this in a threadpool, same as the IR universal scan.
    """
    started = shell.run(
        ["bluetoothctl", "--timeout", str(SCAN_SECONDS), "scan", "on"], timeout=SCAN_TIMEOUT
    )
    if started.unsupported or started.missing:
        return False, started.detail, []
    listed = shell.run(["bluetoothctl", "devices"], timeout=4.0)
    devices = _parse_devices(listed.stdout) if listed.ok else []
    return True, f"Found {len(devices)} device(s)", _with_types(devices)


def paired() -> list[dict]:
    result = shell.run(["bluetoothctl", "paired-devices"], timeout=4.0)
    return _with_types(_parse_devices(result.stdout)) if result.ok else []


def power(on: bool) -> tuple[bool, str]:
    result = shell.run(["bluetoothctl", "power", "on" if on else "off"], timeout=6.0)
    return (True, f"Powered {'on' if on else 'off'}") if result.ok else (False, result.detail)


_PAST_TENSE = {
    "pair": "Paired", "trust": "Trusted", "connect": "Connected",
    "disconnect": "Disconnected", "remove": "Removed",
}


def _address_action(verb: str, address: str, timeout: float = ACTION_TIMEOUT) -> tuple[bool, str]:
    result = shell.run(["bluetoothctl", verb, address], timeout=timeout)
    if result.ok:
        return True, f"{_PAST_TENSE[verb]} {address}"
    if result.timed_out:
        return False, f"{verb.capitalize()} timed out -- device may need confirmation on its own screen"
    return False, result.detail


def pair(address: str) -> tuple[bool, str]:
    return _address_action("pair", address)


def trust(address: str) -> tuple[bool, str]:
    return _address_action("trust", address)


def connect(address: str) -> tuple[bool, str]:
    return _address_action("connect", address)


def disconnect(address: str) -> tuple[bool, str]:
    return _address_action("disconnect", address, timeout=6.0)


def remove(address: str) -> tuple[bool, str]:
    return _address_action("remove", address, timeout=6.0)


def auto_pair_and_connect(address: str) -> tuple[bool, str]:
    """Pair, trust, connect -- the Tkinter Audio tab's "Auto Pair + Play"."""
    for step, fn in (("pair", pair), ("trust", trust), ("connect", connect)):
        ok, message = fn(address)
        if not ok:
            return False, f"Failed at {step}: {message}"
    return True, f"Paired, trusted and connected {address}"
