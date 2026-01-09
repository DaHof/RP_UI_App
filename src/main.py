from __future__ import annotations

import os
from pathlib import Path

from library_store import LibraryStore
from pn532.mock_reader import MockPN532Reader
from ui.app import App


def build_reader(mode: str):
    if mode == "adafruit":
        from pn532.adafruit_reader import AdafruitPN532Reader

        return AdafruitPN532Reader()
    return MockPN532Reader()


def main() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    store = LibraryStore(base_dir / "data" / "library.json")
    store.load()

    mode = os.environ.get("PN532_READER", "mock").lower()
    reader = build_reader(mode)

    def shutdown() -> None:
        reader.stop()

    app = App(store, shutdown)
    app.reader = reader
    reader.set_callback(app.on_tag_detected)
    reader.start()
    app.mainloop()


if __name__ == "__main__":
    main()
