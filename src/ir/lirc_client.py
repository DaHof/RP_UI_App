from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
import threading
from typing import Iterable, Iterator, List


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

    def iter_keytable_events(
        self, stop_event: threading.Event
    ) -> Iterator[dict[str, str]]:
        process = subprocess.Popen(
            ["ir-keytable", "-t"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if process.stdout is None:
            return
        for line in process.stdout:
            if stop_event.is_set():
                break
            event = self._parse_keytable_line(line)
            if event:
                yield event
        process.terminate()

    def _parse_keytable_line(self, line: str) -> dict[str, str] | None:
        if "scancode" not in line:
            return None
        protocol_match = re.search(r"protocol\s+(\w+)", line)
        scancode_match = re.search(r"scancode\s+(\w+)", line)
        key_match = re.search(r"key\s+(\w+)", line)
        protocol = protocol_match.group(1) if protocol_match else "unknown"
        scancode = scancode_match.group(1) if scancode_match else "unknown"
        key = key_match.group(1) if key_match else "unknown"
        return {
            "protocol": protocol,
            "data": scancode,
            "source": "ir-keytable",
            "name": key,
        }
