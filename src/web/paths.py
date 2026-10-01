"""Filesystem locations for the web dashboard.

The rest of the repo reaches the project root with
``Path(__file__).resolve().parent.parent`` because its modules sit directly in
``src/``. Web modules are one level deeper, so that same idiom lands on ``src/``
instead. Every path is named here so nothing has to count ``.parent`` hops.
"""

from __future__ import annotations

from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
SRC_DIR = WEB_DIR.parent
ROOT_DIR = SRC_DIR.parent

DATA_DIR = ROOT_DIR / "data"
STATIC_DIR = WEB_DIR / "static"
LOG_DIR = DATA_DIR / "logs"

TOOLS_YAML = WEB_DIR / "tools.yaml"
PINS_YAML = DATA_DIR / "pins.yaml"
PINS_EXAMPLE_YAML = DATA_DIR / "pins.example.yaml"
LIBRARY_JSON = DATA_DIR / "library.json"
SYSTEM_SETTINGS_JSON = DATA_DIR / "system_settings.json"

IR_DIR = DATA_DIR / "ir"
# Note the space: the Tkinter app created this directory and the name is load
# bearing (src/ui/app.py:1042).
IR_SAVED_DIR = IR_DIR / "saved remotes"
IR_UNIVERSAL_DIR = IR_DIR / "universal"
IR_SETTINGS_JSON = DATA_DIR / "ir_settings.json"
