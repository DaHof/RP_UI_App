from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class IRRemote:
    name: str
    buttons: List[str]


class LircClient:
    """Minimal LIRC wrapper (stub) for future IR capture/send integration."""

    def list_remotes(self) -> Iterable[IRRemote]:
        raise NotImplementedError("LIRC integration not wired yet.")

    def send_once(self, remote: str, button: str) -> None:
        raise NotImplementedError("LIRC integration not wired yet.")

    def start_capture(self) -> None:
        raise NotImplementedError("LIRC integration not wired yet.")
