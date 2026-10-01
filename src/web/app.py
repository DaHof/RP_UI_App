"""PIP-UI web dashboard.

Run with:  python src/web/app.py

Binds 127.0.0.1 only. The Tkinter app is untouched and can run alongside this,
though both will contend for the I2C bus if the real PN532 reader is selected.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path bootstrap -- must run before any sibling or engine import.
#
# The engine uses flat imports (`from data_model import CardProfile`) and there
# is no src/__init__.py. Adding one would break every existing import, so `src`
# and `src/web` are put on the path instead. This is also why uvicorn must not
# use reload=True: the reloader re-execs and loses these entries.
# ---------------------------------------------------------------------------
_WEB_DIR = Path(__file__).resolve().parent
_SRC_DIR = _WEB_DIR.parent
for _entry in (str(_SRC_DIR), str(_WEB_DIR)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

import json  # noqa: E402
import os  # noqa: E402
import threading  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402

import hardware  # noqa: E402
import irweb  # noqa: E402
import paths  # noqa: E402
import pins as pins_module  # noqa: E402
import probes  # noqa: E402
import shell  # noqa: E402
import sim  # noqa: E402
from health import monitor  # noqa: E402
from launcher import launcher  # noqa: E402
from library_store import LibraryStore  # noqa: E402

store = LibraryStore(paths.LIBRARY_JSON)
_store_lock = threading.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pins_module.ensure_example()
    with _store_lock:
        store.load()
    hardware.service.start()
    monitor.start()
    yield
    monitor.stop()
    hardware.service.stop()
    launcher.stop_all()


app = FastAPI(title="PIP-UI", docs_url=None, redoc_url=None, lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/api/health")
async def get_health():
    return monitor.snapshot()


@app.post("/api/health/refresh")
async def refresh_health():
    await run_in_threadpool(monitor.refresh_all)
    return monitor.snapshot()


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

@app.get("/api/diagnostics")
async def get_diagnostics():
    def collect() -> dict:
        i2c = shell.run(["i2cdetect", "-y", "1"], timeout=3.0)
        usb = shell.run(["lsusb"], timeout=3.0)
        temp = shell.run(["vcgencmd", "measure_temp"], timeout=2.0)
        throttled = shell.run(["vcgencmd", "get_throttled"], timeout=2.0)

        services = {}
        for unit in ("lircd", "bluetooth"):
            result = shell.run(["systemctl", "is-active", unit], timeout=2.0)
            services[unit] = {
                "state": (result.stdout or result.stderr or "unknown").strip(),
                "available": not (result.unsupported or result.missing),
            }

        raw, flags = probes.decode_throttled(throttled.stdout)
        return {
            "simulated": sim.active(),
            "sim_mode": sim.mode(),
            "i2c": {
                "available": i2c.ok,
                "detail": i2c.detail,
                "addresses": probes.parse_i2c_addresses(i2c.stdout) if i2c.ok else [],
                "raw": i2c.stdout,
            },
            "usb": {
                "available": usb.ok,
                "detail": usb.detail,
                "devices": probes.filter_usb(usb.stdout) if usb.ok else [],
            },
            "thermal": {
                "available": temp.ok,
                "detail": temp.detail,
                "temp_c": probes.parse_temp_c(temp.stdout),
                "throttled_raw": f"0x{raw:x}",
                "flags": flags,
            },
            "services": services,
            "reader": hardware.service.status.as_dict() | {"polling": hardware.service.polling},
        }

    return await run_in_threadpool(collect)


@app.post("/api/diagnostics/ir")
async def run_ir_diagnostic():
    """Runs the Tkinter app's IR boot diagnostic. Slow (~12s) and single-slot."""
    result = await run_in_threadpool(monitor.run_ir_diagnostic)
    if result is None:
        raise HTTPException(status_code=409, detail="An IR diagnostic is already running")
    return result


@app.get("/api/diagnostics/ir")
async def last_ir_diagnostic():
    return monitor.ir_result or {"status": "UNKNOWN", "summary": "Not run yet", "steps": []}


# ---------------------------------------------------------------------------
# Tools / launcher
# ---------------------------------------------------------------------------

@app.get("/api/tools")
async def get_tools():
    return {
        "configured": not launcher.error,
        "error": launcher.error,
        "simulated": sim.active(),
        "tools": launcher.as_dicts(),
    }


@app.post("/api/tools/{tool_id}/launch")
async def launch_tool(tool_id: str):
    ok, message = await run_in_threadpool(launcher.launch, tool_id)
    if not ok:
        return JSONResponse({"ok": False, "message": message}, status_code=400)
    return {"ok": True, "message": message, "tools": launcher.as_dicts()}


@app.post("/api/tools/{tool_id}/stop")
async def stop_tool(tool_id: str):
    ok, message = await run_in_threadpool(launcher.stop, tool_id)
    if not ok:
        return JSONResponse({"ok": False, "message": message}, status_code=400)
    return {"ok": True, "message": message, "tools": launcher.as_dicts()}


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

@app.get("/api/pins")
async def get_pins():
    return pins_module.snapshot()


# ---------------------------------------------------------------------------
# NFC + library
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    uid: str = "04A29B31EE7C80"
    tag_type: str = "MIFARE Classic 1K"


@app.get("/api/nfc/recent")
async def recent_tags():
    return {
        "reader": hardware.service.status.as_dict() | {"polling": hardware.service.polling},
        "recent": hardware.service.recent(),
    }


@app.post("/api/nfc/simulate")
async def simulate_tag(request: SimulateRequest):
    if not hardware.service.simulate(request.uid, request.tag_type):
        raise HTTPException(
            status_code=409,
            detail="Simulation requires the mock reader; hardware reader is active",
        )
    return {"ok": True, "recent": hardware.service.recent()}


@app.get("/api/library")
async def get_library():
    with _store_lock:
        profiles = store.list_profiles()
    return {"count": len(profiles), "profiles": [p.to_dict() for p in profiles]}


@app.get("/api/library/{profile_id}")
async def get_profile(profile_id: str):
    with _store_lock:
        match = next((p for p in store.list_profiles() if p.id == profile_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail="No such profile")
    return match.to_dict()


@app.delete("/api/library/{profile_id}")
async def delete_profile(profile_id: str):
    with _store_lock:
        exists = any(p.id == profile_id for p in store.list_profiles())
        if not exists:
            raise HTTPException(status_code=404, detail="No such profile")
        store.delete(profile_id)
    return {"ok": True, "id": profile_id}


# ---------------------------------------------------------------------------
# IR: library, universal sweep, send, capture
# ---------------------------------------------------------------------------

class IRSettingsRequest(BaseModel):
    universal_delay: float | None = None
    rx_device: str | None = None


class IRSendRequest(BaseModel):
    remote: str | None = None
    index: int | None = None
    signal: dict | None = None


class IRScanRequest(BaseModel):
    device: str
    button: str


class IRSaveRequest(BaseModel):
    name: str


@app.get("/api/ir/settings")
async def ir_settings():
    data = irweb.service.settings()
    return {
        "universal_delay": data.get("universal_delay", 0.2),
        "rx_device": data.get("rx_device", ""),
        "tx_device": irweb.service.tx_device(),
        # The Tkinter app keeps these in Tk variables and never writes them to
        # disk (src/ui/app.py:524), so they reset on every restart. Reported as
        # defaults here rather than pretending they are configured.
        "pins_persisted": False,
    }


@app.put("/api/ir/settings")
async def save_ir_settings(request: IRSettingsRequest):
    return irweb.service.save_settings(
        universal_delay=request.universal_delay, rx_device=request.rx_device
    )


@app.get("/api/ir/categories")
async def ir_categories():
    return {"categories": await run_in_threadpool(irweb.service.categories)}


@app.get("/api/ir/remotes")
async def ir_remotes(category: str = "", q: str = "", limit: int = 300):
    return await run_in_threadpool(irweb.service.remotes, category, q, limit)


@app.post("/api/ir/send")
async def ir_send(request: IRSendRequest):
    if request.signal:
        signal = irweb._signal_from_dict(request.signal)
    elif request.remote is not None and request.index is not None:
        signal = await run_in_threadpool(
            irweb.service.signal_at, request.remote, request.index
        )
        if signal is None:
            raise HTTPException(status_code=404, detail="No such signal in that remote")
    else:
        raise HTTPException(status_code=400, detail="Provide either signal, or remote + index")

    ok, message = await run_in_threadpool(irweb.service.send, signal)
    if not ok:
        return JSONResponse({"ok": False, "message": message}, status_code=400)
    return {"ok": True, "message": message}


@app.get("/api/ir/universal")
async def ir_universal():
    return {"devices": irweb.service.universal_devices()}


@app.get("/api/ir/universal/scan")
async def ir_scan_state():
    return irweb.service.scan_state


@app.post("/api/ir/universal/scan")
async def ir_start_scan(request: IRScanRequest):
    ok, message = await run_in_threadpool(
        irweb.service.start_scan, request.device, request.button
    )
    if not ok:
        return JSONResponse({"ok": False, "message": message}, status_code=409)
    return {"ok": True, "message": message, "state": irweb.service.scan_state}


@app.post("/api/ir/universal/scan/cancel")
async def ir_cancel_scan():
    return {"ok": irweb.service.cancel_scan(), "state": irweb.service.scan_state}


@app.get("/api/ir/universal/{device}")
async def ir_universal_device(device: str):
    return await run_in_threadpool(irweb.service.universal_buttons, device)


@app.get("/api/ir/capture")
async def ir_capture_state():
    return irweb.service.capture_state


@app.post("/api/ir/capture")
async def ir_start_capture():
    ok, message = irweb.service.start_capture()
    if not ok:
        return JSONResponse({"ok": False, "message": message}, status_code=409)
    return {"ok": True, "message": message}


@app.post("/api/ir/capture/cancel")
async def ir_cancel_capture():
    return {"ok": irweb.service.cancel_capture(), "state": irweb.service.capture_state}


@app.post("/api/ir/capture/save")
async def ir_save_capture(request: IRSaveRequest):
    captured = irweb.service.capture_state.get("result")
    if not captured:
        raise HTTPException(status_code=400, detail="Nothing captured to save")
    signal = irweb._signal_from_dict({**captured, "name": captured.get("name") or "signal"})
    name = await run_in_threadpool(irweb.service.save_remote, request.name, [signal])
    return {"ok": True, "name": name}


# Declared last: a {name:path} route would otherwise swallow every /api/ir/* URL.
@app.get("/api/ir/remotes/{name:path}")
async def ir_remote(name: str):
    return await run_in_threadpool(irweb.service.remote, name)


@app.delete("/api/ir/remotes/{name:path}")
async def ir_delete_remote(name: str):
    await run_in_threadpool(irweb.service.delete_remote, name)
    return {"ok": True, "name": name}


# ---------------------------------------------------------------------------
# Settings (read-only view of what the Tkinter app owns)
# ---------------------------------------------------------------------------

@app.get("/api/settings")
async def get_settings():
    try:
        data = json.loads(paths.SYSTEM_SETTINGS_JSON.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except Exception as exc:
        return {"error": str(exc), "settings": {}}
    return {"error": "", "settings": data}


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

@app.get("/")
async def index():
    page = paths.STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="index.html has not been built yet")
    return FileResponse(page)


if paths.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(paths.STATIC_DIR)), name="static")


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PIPUI_PORT", "8080"))
    banner = sim.banner()
    if banner:
        print(f"  *** {banner} ***")
    print(f"  PIP-UI dashboard -> http://127.0.0.1:{port}")
    # No reload=True: the reloader re-execs and loses the sys.path bootstrap.
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
