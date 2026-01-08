from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional


@dataclass
class TagDetection:
    uid: str
    tag_type: str
    technologies: List[str]


tag_callback = Callable[[TagDetection], None]


class BasePN532Reader:
    def __init__(self) -> None:
        self._callback: Optional[tag_callback] = None

    def set_callback(self, callback: tag_callback) -> None:
        self._callback = callback

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def _emit(self, detection: TagDetection) -> None:
        if self._callback:
            self._callback(detection)
