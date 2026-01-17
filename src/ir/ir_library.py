from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import List, Union

from ir.flipper_ir import FlipperIRSignal, parse_signals, serialize_signals


@dataclass(frozen=True)
class IRRemoteSummary:
    name: str
    path: Path
    signal_count: int


class IRLibraryStore:
    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir
        self._root_dir.mkdir(parents=True, exist_ok=True)

    def list_remotes(self) -> List[IRRemoteSummary]:
        remotes: List[IRRemoteSummary] = []
        for path in sorted(self._root_dir.rglob("*.ir")):
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            signals = parse_signals(text)
            remotes.append(
                IRRemoteSummary(
                    name=path.relative_to(self._root_dir).with_suffix("").as_posix(),
                    path=path,
                    signal_count=len(signals),
                )
            )
        return remotes

    def load_remote(self, remote: Union[str, Path]) -> List[FlipperIRSignal]:
        path = self._resolve_path(remote)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return parse_signals(text)

    def save_remote(self, name: str, signals: List[FlipperIRSignal]) -> Path:
        target = self._available_path(_sanitize_path(name))
        target.write_text(serialize_signals(signals), encoding="utf-8")
        return target

    def save_remote_signals(self, remote: Union[str, Path], signals: List[FlipperIRSignal]) -> None:
        path = self._resolve_path(remote)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialize_signals(signals), encoding="utf-8")

    def rename_remote(self, remote: Union[str, Path], new_name: str) -> Path:
        path = self._resolve_path(remote)
        target = self._available_path(_sanitize_path(new_name))
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
        return target

    def delete_remote(self, remote: Union[str, Path]) -> None:
        path = self._resolve_path(remote)
        if path.exists():
            path.unlink()

    def _resolve_path(self, remote: Union[str, Path]) -> Path:
        if isinstance(remote, Path):
            return remote
        raw = remote.strip()
        if raw:
            candidate = self._root_dir / raw
            if candidate.suffix != ".ir":
                candidate = candidate.with_suffix(".ir")
            if candidate.exists():
                return candidate
        safe_name = _sanitize_path(remote)
        return self._root_dir / f"{safe_name}.ir"

    def _available_path(self, base_name: str) -> Path:
        candidate = self._root_dir / f"{base_name}.ir"
        if not candidate.exists():
            return candidate
        index = 2
        while True:
            candidate = self._root_dir / f"{base_name}_{index}.ir"
            if not candidate.exists():
                return candidate
            index += 1


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    return cleaned.strip("_")


def _sanitize_path(name: str) -> str:
    parts = re.split(r"[\\/]+", name.strip())
    safe_parts = [_sanitize_name(part) for part in parts if part.strip()]
    return "/".join([part for part in safe_parts if part]) or "remote"
