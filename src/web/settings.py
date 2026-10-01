"""Feature toggles: the real blocker to using the web dashboard alone.

Mirrors App._load_feature_flags / _save_feature_flags in src/ui/app.py exactly
-- same file, same five keys, same "missing key defaults to True" semantics --
so either front end can flip a switch and the other sees it. This is the one
piece of System > Features that is actually real (unlike Emulate, Clone/Write,
and the IR TX/RX pin fields, which affect nothing).

Tkinter's "Debug Window" toggle is deliberately not exposed here: it controls a
Tk debug console local to that process, with no meaning for a web page.
"""

from __future__ import annotations

import json

import paths

FEATURES = ("Scan", "IR", "Bluetooth", "WiFi", "Proxmark")


def _read() -> dict:
    try:
        payload = json.loads(paths.SYSTEM_SETTINGS_JSON.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def snapshot() -> dict:
    payload = _read()
    return {
        "features": {name: bool(payload.get(name, True)) for name in FEATURES},
        "log_enabled": bool(payload.get("log_enabled", False)),
    }


def save(features: dict[str, bool] | None, log_enabled: bool | None) -> dict:
    """Merge into the existing file rather than overwrite it.

    Tkinter's own save (app.py:157-161) replaces the WHOLE file with just these
    six keys, so anything else written there is lost on its next save. Merging
    here at least means this side doesn't also destroy unrelated keys.
    """
    payload = _read()
    if features:
        for name in FEATURES:
            if name in features:
                payload[name] = bool(features[name])
    if log_enabled is not None:
        payload["log_enabled"] = bool(log_enabled)

    try:
        paths.SYSTEM_SETTINGS_JSON.parent.mkdir(parents=True, exist_ok=True)
        paths.SYSTEM_SETTINGS_JSON.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        return {**snapshot(), "error": str(exc)}
    return snapshot()
