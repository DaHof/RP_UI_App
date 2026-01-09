from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class BluetoothDevice:
    name: str
    address: str


class BlueZClient:
    """Minimal BlueZ wrapper (stub) for future Bluetooth menu integration."""

    def scan(self) -> Iterable[BluetoothDevice]:
        raise NotImplementedError("BlueZ integration not wired yet.")

    def pair(self, address: str) -> None:
        raise NotImplementedError("BlueZ integration not wired yet.")

    def trust(self, address: str) -> None:
        raise NotImplementedError("BlueZ integration not wired yet.")

    def connect_a2dp(self, address: str) -> None:
        raise NotImplementedError("BlueZ integration not wired yet.")

    def auto_pair_and_play(self, address: str) -> None:
        raise NotImplementedError("BlueZ integration not wired yet.")
