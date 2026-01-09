from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Iterable, List


@dataclass(frozen=True)
class BluetoothDevice:
    name: str
    address: str


class BlueZClient:
    """Minimal BlueZ wrapper for Bluetooth menu integration."""

    def scan(self, timeout_s: int = 6) -> List[BluetoothDevice]:
        self._run(["bluetoothctl", "--timeout", str(timeout_s), "scan", "on"])
        return self._parse_devices(self._run(["bluetoothctl", "devices"]))

    def list_paired(self) -> List[BluetoothDevice]:
        return self._parse_devices(self._run(["bluetoothctl", "paired-devices"]))

    def pair(self, address: str) -> None:
        self._run(["bluetoothctl", "pair", address])

    def trust(self, address: str) -> None:
        self._run(["bluetoothctl", "trust", address])

    def connect_a2dp(self, address: str) -> None:
        self._run(["bluetoothctl", "connect", address])

    def disconnect(self, address: str) -> None:
        self._run(["bluetoothctl", "disconnect", address])

    def remove(self, address: str) -> None:
        self._run(["bluetoothctl", "remove", address])

    def auto_pair_and_play(self, address: str) -> None:
        self.pair(address)
        self.trust(address)
        self.connect_a2dp(address)

    def _run(self, command: List[str]) -> str:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True
        )
        return result.stdout

    def _parse_devices(self, output: str) -> List[BluetoothDevice]:
        devices: List[BluetoothDevice] = []
        for line in output.splitlines():
            if not line.startswith("Device "):
                continue
            _, address, name = line.split(" ", 2)
            devices.append(BluetoothDevice(name=name.strip(), address=address.strip()))
        return devices
