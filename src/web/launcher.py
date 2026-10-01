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

import paths
import sim

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


@dataclass(frozen=True)
class Tool:
    id: str
    name: str
    icon: str = "antenna"
    category: str = "Tools"
    kind: str = "launch"            # "launch" | "builtin" | "link"
    view: str = ""                  # for builtin tiles
    argv: tuple[str, ...] = ()
    url: str = ""                   # for link tiles
    note: str = ""
    desc: str = ""                   # one-line "what does this do" for the UI's info popover
    root: bool = False

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
        if kind == "launch" and not argv:
            continue                                  # unlaunchable: skip rather than half-show
        if kind == "link" and not url:
            continue                                  # no destination: skip rather than half-show
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
                note=str(entry.get("note", "")),
                desc=str(entry.get("desc", "")),
                root=bool(entry.get("root", False)),
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
        return shutil.which(tool.binary) is not None

    def as_dicts(self) -> list[dict]:
        self._reap()
        out = []
        for tool in self._tools:
            running = self._running.get(tool.id)
            uptime = int(time.monotonic() - running.started_at) if running else 0
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
                    "note": tool.note,
                    "desc": tool.desc,
                    "root": tool.root,
                    "available": self.available(tool),
                    "running": bool(running),
                    "uptime": uptime,
                }
            )
        return out

    # -- control -----------------------------------------------------------

    def launch(self, tool_id: str) -> tuple[bool, str]:
        tool = self.get(tool_id)
        if tool is None:
            return False, "Unknown tool"
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
