"""Launch and supervise the external tools listed in ``tools.yaml``.

Security model -- the important part of this file:

* ``tools.yaml`` is a strict **allowlist**. A tool can only be launched if it is
  declared there.
* Each entry's ``argv`` is a **list**, never a string, and is passed to
  ``Popen`` verbatim. There is no shell anywhere in this module, so nothing can
  be interpreted as shell syntax.
* The API accepts only a tool **id**. No part of any request -- no argument, no
  path, no flag -- ever reaches the command line. Adding a tool is a config
  edit, which is a deliberate privilege boundary.
* ``stdin`` is ``DEVNULL``, so a ``sudo`` entry without passwordless sudo fails
  immediately instead of hanging forever on a password prompt.

Processes are started in their own session so stopping one cannot signal the
dashboard itself, and so the whole process group can be cleaned up.

A ``kind: link`` entry is not a process at all -- it is a tile that opens
``url`` in a new tab, for a tool that lives on another machine (e.g. a WiFi
sensing app running on a separate Kali box). It never reaches ``launch()`` or
``Popen``; the frontend navigates to it directly, so it carries none of the
argv/allowlist machinery above.

A ``kind: service`` entry is neither of those -- it is a tool installed as its
own systemd unit, meant to keep running independently of this dashboard (a
reboot, or a restart of ``pipui-web`` itself, must not make it look stopped).
So instead of a tracked ``Popen`` handle, "running" is always a fresh
``systemctl is-active`` -- there is nothing in ``self._running`` to lose.
Start/stop go through ``systemctl start|stop``, same privilege model as a
``root: true`` ``launch`` entry: passwordless sudo must be configured for the
specific unit, or the attempt fails immediately rather than hanging.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import health
import paths
import shell
import sim

# Builtin tiles always navigate (the screen is reachable even if its hardware
# isn't), so they don't use `available` for this -- but a handful have a real
# health-monitor channel behind them, and showing nothing on the home grid
# until you open the screen hides a FAIL a user would want to see up front.
# Not every builtin has a probe (Bluetooth, Diagnostics, GPIO Pins, Settings
# don't), so this stays a lookup, not a blanket rule.
BUILTIN_HEALTH_CHANNEL = {
    "nfc": "pn532", "proxmark": "proxmark", "mmwave": "mmwave", "ir": "ir",
    "msr605x": "msr605x", "bluetooth": "bluetooth",
}

# How long a link tile's reachability result is trusted before re-probing, and
# how long the probe itself is allowed to block -- short, since /api/tools is
# polled on a timer and a slow/unreachable host must not stall the dashboard.
_LINK_CACHE_TTL = 15.0
_LINK_CONNECT_TIMEOUT = 0.5

try:
    import yaml

    YAML_OK = True
except Exception:                                    # pragma: no cover
    yaml = None                                      # type: ignore[assignment]
    YAML_OK = False

IS_POSIX = os.name == "posix"

# Tools that report as running in simulation, so the "active" tile state and the
# Stop button can be exercised and screenshotted off-device.
_SIM_RUNNING = {"gnuradio"}


def _service_loaded(unit: str) -> bool:
    """True if systemd knows this unit at all -- read-only, no sudo needed."""
    result = shell.run(["systemctl", "show", unit, "--property=LoadState", "--value"], timeout=3.0)
    return result.ok and result.stdout.strip() == "loaded"


def _service_active(unit: str) -> bool:
    """Read-only, no sudo needed -- systemd will report this for anyone."""
    result = shell.run(["systemctl", "is-active", unit], timeout=3.0)
    return result.stdout.strip() == "active"


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    icon: str = "antenna"
    category: str = "Tools"
    kind: str = "launch"            # "launch" | "builtin" | "link" | "service"
    view: str = ""                  # for builtin tiles
    argv: tuple[str, ...] = ()
    url: str = ""                   # for link tiles, and optionally for service tiles
    unit: str = ""                  # for service tiles -- the systemd unit name
    note: str = ""
    short: str = ""                  # always-visible one-liner on the tile itself
    desc: str = ""                   # longer explanation, shown in the UI's info popover
    root: bool = False
    simple: bool = False             # shown on the simplified home screen (see Settings)

    @property
    def binary(self) -> str:
        """The executable whose presence decides availability.

        For a ``sudo`` entry that is the argument after sudo and its flags, not
        sudo itself -- otherwise every root tool looks installed.
        """
        if not self.argv:
            return ""
        if self.argv[0] != "sudo":
            return self.argv[0]
        for part in self.argv[1:]:
            if not part.startswith("-"):
                return part
        return "sudo"


@dataclass
class Running:
    process: subprocess.Popen
    started_at: float = field(default_factory=time.monotonic)


def _coerce_argv(raw) -> tuple[str, ...]:
    """Accept a list; reject a bare string so nobody can sneak in shell syntax."""
    if isinstance(raw, (list, tuple)):
        return tuple(str(part) for part in raw)
    return ()


def load_tools() -> tuple[list[Tool], str]:
    """Read ``tools.yaml``. Returns (tools, error) -- never raises."""
    if not YAML_OK:
        return [], "PyYAML is not installed; tool list unavailable"
    if not paths.TOOLS_YAML.exists():
        return [], f"{paths.TOOLS_YAML.name} not found"

    try:
        raw = yaml.safe_load(paths.TOOLS_YAML.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [], f"Could not parse {paths.TOOLS_YAML.name}: {exc}"

    tools: list[Tool] = []
    for entry in raw.get("tools") or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        argv = _coerce_argv(entry.get("argv"))
        kind = entry.get("kind", "launch")
        url = str(entry.get("url", ""))
        unit = str(entry.get("unit", ""))
        if kind == "launch" and not argv:
            continue                                  # unlaunchable: skip rather than half-show
        if kind == "link" and not url:
            continue                                  # no destination: skip rather than half-show
        if kind == "service" and not unit:
            continue                                  # nothing to control: skip rather than half-show
        tools.append(
            Tool(
                id=str(entry["id"]),
                name=str(entry.get("name", entry["id"])),
                icon=str(entry.get("icon", "antenna")),
                category=str(entry.get("category", "Tools")),
                kind=kind,
                view=str(entry.get("view", "")),
                argv=argv,
                url=url,
                unit=unit,
                note=str(entry.get("note", "")),
                short=str(entry.get("short", "")),
                desc=str(entry.get("desc", "")),
                root=bool(entry.get("root", False)),
                simple=bool(entry.get("simple", False)),
            )
        )
    return tools, ""


class Launcher:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._running: dict[str, Running] = {}
        self._tools: list[Tool] = []
        self._error = ""
        self._link_cache: dict[str, tuple[float, bool]] = {}
        self.reload()

    def reload(self) -> None:
        self._tools, self._error = load_tools()

    @property
    def error(self) -> str:
        return self._error

    def get(self, tool_id: str) -> Tool | None:
        return next((t for t in self._tools if t.id == tool_id), None)

    # -- state -------------------------------------------------------------

    def _reap(self) -> None:
        """Drop finished processes so uptime and tile state stay truthful."""
        with self._lock:
            for tool_id in [k for k, v in self._running.items() if v.process.poll() is not None]:
                self._running.pop(tool_id, None)

    def _link_reachable(self, tool: Tool) -> bool:
        """TCP-probe a link tile's host, cached -- a dead remote app should grey
        the tile out instead of always showing available and failing on click.
        """
        now = time.monotonic()
        cached = self._link_cache.get(tool.id)
        if cached is not None and now - cached[0] < _LINK_CACHE_TTL:
            return cached[1]

        parsed = urlparse(tool.url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        reachable = False
        if host:
            try:
                with socket.create_connection((host, port), timeout=_LINK_CONNECT_TIMEOUT):
                    reachable = True
            except OSError:
                reachable = False

        self._link_cache[tool.id] = (now, reachable)
        return reachable

    def available(self, tool: Tool) -> bool:
        if tool.kind == "builtin":
            return True
        if sim.active():
            return sim.mode() != "fail"
        if tool.kind == "link":
            return self._link_reachable(tool)
        if tool.kind == "service":
            return _service_loaded(tool.unit)
        return shutil.which(tool.binary) is not None

    def _service_running(self, tool: Tool) -> bool:
        if sim.active():
            return tool.id in _SIM_RUNNING and sim.mode() != "fail"
        return _service_active(tool.unit)

    def as_dicts(self) -> list[dict]:
        self._reap()
        # One snapshot reused for every builtin tile this call, not one per tile.
        health_channels = {c["name"]: c["status"] for c in health.monitor.snapshot()["channels"]}
        out = []
        for tool in self._tools:
            if tool.kind == "service":
                # Asked fresh from systemd every time, not tracked locally --
                # the whole point is surviving a pipui-web restart.
                running, uptime = self._service_running(tool), 0
            else:
                proc = self._running.get(tool.id)
                running = bool(proc)
                uptime = int(time.monotonic() - proc.started_at) if proc else 0
                if sim.active() and tool.id in _SIM_RUNNING and sim.mode() != "fail":
                    running, uptime = True, 247
            out.append(
                {
                    "id": tool.id,
                    "name": tool.name,
                    "icon": tool.icon,
                    "category": tool.category,
                    "kind": tool.kind,
                    "view": tool.view,
                    "cmd": " ".join(tool.argv),
                    "url": tool.url,
                    "unit": tool.unit,
                    "note": tool.note,
                    "short": tool.short,
                    "desc": tool.desc,
                    "root": tool.root,
                    "simple": tool.simple,
                    "hw_status": health_channels.get(BUILTIN_HEALTH_CHANNEL.get(tool.id)),
                    "available": self.available(tool),
                    "running": bool(running),
                    "uptime": uptime,
                }
            )
        return out

    # -- control -----------------------------------------------------------

    def _service_control(self, tool: Tool, action: str) -> tuple[bool, str]:
        verb = "Started" if action == "start" else "Stopped"
        if sim.active():
            return True, f"{verb} {tool.name} (simulated)"
        if action == "start" and not self.available(tool):
            return False, f"{tool.unit} is not installed"
        result = shell.run(["sudo", "systemctl", action, tool.unit], timeout=10.0)
        if not result.ok:
            return False, result.detail
        return True, f"{verb} {tool.name}"

    def launch(self, tool_id: str) -> tuple[bool, str]:
        tool = self.get(tool_id)
        if tool is None:
            return False, "Unknown tool"
        if tool.kind == "service":
            return self._service_control(tool, "start")
        if tool.kind != "launch":
            return False, "This tile is built in, not a launchable process"
        if not self.available(tool):
            return False, f"{tool.binary} is not installed"

        self._reap()
        with self._lock:
            if tool_id in self._running:
                return False, f"{tool.name} is already running"

        if sim.active():
            return True, f"{tool.name} launched (simulated)"

        env = os.environ.copy()
        # GUI tools launched from a service have no display of their own.
        env.setdefault("DISPLAY", ":0")

        try:
            process = subprocess.Popen(
                list(tool.argv),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                start_new_session=IS_POSIX,
            )
        except FileNotFoundError:
            return False, f"{tool.binary} is not installed"
        except PermissionError:
            return False, f"Not permitted to run {tool.binary}"
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"

        with self._lock:
            self._running[tool_id] = Running(process)
        return True, f"Launched {tool.name}"

    def stop(self, tool_id: str) -> tuple[bool, str]:
        tool = self.get(tool_id)
        if tool is None:
            return False, "Unknown tool"
        if tool.kind == "service":
            return self._service_control(tool, "stop")

        if sim.active():
            return True, f"Stopped {tool.name} (simulated)"

        with self._lock:
            running = self._running.pop(tool_id, None)
        if running is None:
            return False, f"{tool.name} is not running"

        process = running.process
        try:
            if IS_POSIX:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if IS_POSIX:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
        except ProcessLookupError:
            pass
        except Exception as exc:
            return False, f"Could not stop {tool.name}: {exc}"
        return True, f"Stopped {tool.name}"

    def stop_all(self) -> None:
        for tool_id in list(self._running):
            self.stop(tool_id)


launcher = Launcher()
