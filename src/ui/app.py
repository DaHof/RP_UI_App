from __future__ import annotations

import json
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Callable, Optional

from data_model import CardProfile
from library_store import LibraryStore
from pn532.reader_base import TagDetection
from ir.diagnostics import IRDiagnosticService, DiagnosticResult, DiagnosticStepResult


class App(tk.Tk):
    def __init__(self, store: LibraryStore, on_shutdown: Callable[[], None]) -> None:
        super().__init__()
        self.title("PN532 Touch UI")
        self.geometry("800x480")
        self._configure_theme()
        self.configure(bg=self._colors["bg"])
        self._store = store
        self._on_shutdown = on_shutdown
        self._current_detection: Optional[TagDetection] = None
        self._current_profile: Optional[CardProfile] = None
        self._ir_tx_pin = tk.StringVar(value="GPIO18 (Pin 12)")
        self._ir_rx_pin = tk.StringVar(value="GPIO23 (Pin 16)")
        self._feature_flags = self._load_feature_flags()
        self._ir_detected = {"rx": False, "tx": False}
        self._gif_frames: list[tk.PhotoImage] = []
        self._gif_label: Optional[ttk.Label] = None
        self._gif_frame_index = 0
        self._gif_animation_id: Optional[str] = None
        self._gif_update_image: Optional[Callable[[tk.PhotoImage], None]] = None
        self._gif_target_size = (340, 340)
        self._debug_window: Optional[tk.Toplevel] = None
        self._debug_text: Optional[tk.Text] = None
        self._debug_enabled = tk.BooleanVar(value=False)
        self._log_enabled = tk.BooleanVar(value=self._load_log_setting())
        self._log_dir = Path(__file__).resolve().parents[2] / "data" / "logs"
        self._log_max_bytes = 1024 * 1024
        self._ir_diagnostics = IRDiagnosticService(
            logger=lambda message: self.log_feature("IR", message)
        )
        self._ir_boot_diagnostic: Optional[DiagnosticResult] = None
        self._ir_settings_path = Path(__file__).resolve().parents[2] / "data" / "ir_settings.json"
        self._load_main_gif()

        layout = ttk.Frame(self, style="App.TFrame")
        layout.pack(fill=tk.BOTH, expand=True)
        layout.columnconfigure(1, weight=1)
        layout.rowconfigure(0, weight=1)

        self._nav = ttk.Frame(layout, style="Nav.TFrame")
        self._nav.grid(row=0, column=0, sticky="ns")

        self._content = ttk.Frame(layout, style="App.TFrame")
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.rowconfigure(1, weight=1)
        self._content.columnconfigure(0, weight=1)

        self._subnav = ttk.Frame(self._content, style="Nav.TFrame")
        self._subnav.grid(row=0, column=0, sticky="ew")
        self._screen_host = ttk.Frame(self._content, style="App.TFrame")
        self._screen_host.grid(row=1, column=0, sticky="nsew")

        self._screens = {}
        self._current_screen = None

        self._build_left_nav()

        self._add_screen("Home", HomeScreen(self._screen_host, self))
        self._add_screen("Scan", ScanScreen(self._screen_host, self))
        self._add_screen("Library", LibraryScreen(self._screen_host, self))
        self._add_screen("Emulate", EmulateScreen(self._screen_host, self))
        self._add_screen("Clone/Write", CloneWriteScreen(self._screen_host, self))
        self._add_screen("Settings", SettingsScreen(self._screen_host, self))
        self._add_screen("IR", IRScreen(self._screen_host, self))
        self._add_screen("Bluetooth", BluetoothScreen(self._screen_host, self))
        self._add_screen("WiFi", WiFiScreen(self._screen_host, self))
        self._add_screen("Proxmark", ProxmarkScreen(self._screen_host, self))
        self._add_screen("System", SystemScreen(self._screen_host, self))

        self.show_section("Home")
        self._start_ir_boot_diagnostic()

    def _build_left_nav(self) -> None:
        for child in self._nav.winfo_children():
            child.destroy()
        ttk.Label(self._nav, text="PIP-UI", style="NavTitle.TLabel").pack(pady=(16, 6))
        for label in ["Home", "Scan", "IR", "Bluetooth", "WiFi", "Proxmark", "System"]:
            if label != "System" and not self.feature_enabled(label):
                continue
            button = ttk.Button(
                self._nav,
                text=label,
                style="Nav.TButton",
                command=lambda name=label: self.show_section(name),
            )
            button.pack(fill=tk.X, padx=12, pady=6)



    def _default_section(self) -> str:
        for label in ["Home", "Scan", "IR", "Bluetooth", "WiFi", "Proxmark", "System"]:
            if label == "System" or self.feature_enabled(label):
                return label
        return "System"

    def feature_enabled(self, name: str) -> bool:
        return self._feature_flags.get(name, True)

    def set_feature_flags(self, flags: dict[str, bool]) -> None:
        self._feature_flags.update(flags)
        self._save_feature_flags()
        self._build_left_nav()
        self.show_section(self._default_section())
        self.refresh_home()

    def _load_feature_flags(self) -> dict[str, bool]:
        settings_path = Path(__file__).resolve().parents[2] / "data" / "system_settings.json"
        if not settings_path.exists():
            return {
                "Scan": True,
                "IR": True,
                "Bluetooth": True,
                "WiFi": True,
                "Proxmark": True,
            }
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        return {
            "Scan": bool(payload.get("Scan", True)),
            "IR": bool(payload.get("IR", True)),
            "Bluetooth": bool(payload.get("Bluetooth", True)),
            "WiFi": bool(payload.get("WiFi", True)),
            "Proxmark": bool(payload.get("Proxmark", True)),
        }

    def _load_log_setting(self) -> bool:
        settings_path = Path(__file__).resolve().parents[2] / "data" / "system_settings.json"
        if not settings_path.exists():
            return False
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        return bool(payload.get("log_enabled", False))

    def _save_feature_flags(self) -> None:
        settings_path = Path(__file__).resolve().parents[2] / "data" / "system_settings.json"
        payload = {name: bool(value) for name, value in self._feature_flags.items()}
        payload["log_enabled"] = bool(self._log_enabled.get())
        settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _build_ir_indicators(self) -> None:
        indicator = ttk.Frame(self._nav, style="Nav.TFrame")
        indicator.pack(fill=tk.X, padx=12, pady=(6, 12))
        ttk.Label(indicator, text="IR Status", style="Muted.TLabel").pack(anchor="w")
        row = ttk.Frame(indicator, style="Nav.TFrame")
        row.pack(fill=tk.X, pady=(4, 0))
        self._ir_rx_canvas = tk.Canvas(
            row, width=12, height=12, highlightthickness=0, bg=self._colors["panel_alt"]
        )
        self._ir_rx_canvas.pack(side=tk.LEFT, padx=(0, 6))
        self._ir_tx_canvas = tk.Canvas(
            row, width=12, height=12, highlightthickness=0, bg=self._colors["panel_alt"]
        )
        self._ir_tx_canvas.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(row, text="RX", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Label(row, text="TX", style="Muted.TLabel").pack(side=tk.LEFT)
        self._refresh_ir_detection()

    def _refresh_ir_detection(self) -> None:
        if self._ir_boot_diagnostic:
            self._apply_ir_diagnostic_status(self._ir_boot_diagnostic)
        else:
            self._ir_detected["rx"] = bool(self._ir_rx_pin.get().strip())
            self._ir_detected["tx"] = bool(self._ir_tx_pin.get().strip())
        self._update_ir_indicators()

    def _apply_ir_diagnostic_status(self, result: DiagnosticResult) -> None:
        step_status = {step.name: step.status for step in result.steps}
        rx_ready = step_status.get("Presence Check") == "PASS" and step_status.get(
            "Driver/Binding Check"
        ) == "PASS"
        tx_ready = step_status.get("TX Send Test") == "PASS"
        self._ir_detected["rx"] = rx_ready
        self._ir_detected["tx"] = tx_ready

    def _update_ir_indicators(self) -> None:
        if not hasattr(self, "_ir_rx_canvas"):
            return
        rx_color = self._colors["accent"] if self._ir_detected["rx"] else self._colors["muted"]
        tx_color = self._colors["accent"] if self._ir_detected["tx"] else self._colors["muted"]
        self._ir_rx_canvas.delete("all")
        self._ir_tx_canvas.delete("all")
        self._ir_rx_canvas.create_oval(2, 2, 10, 10, fill=rx_color, outline=rx_color)
        self._ir_tx_canvas.create_oval(2, 2, 10, 10, fill=tx_color, outline=tx_color)

    def _load_main_gif(self) -> None:
        gif_path = Path(__file__).resolve().parents[2] / "data" / "assets" / "main.gif"
        if not gif_path.exists():
            return
        frames: list[tk.PhotoImage] = []
        index = 0
        while True:
            try:
                frame = tk.PhotoImage(file=str(gif_path), format=f"gif -index {index}")
            except tk.TclError:
                break
            frames.append(frame)
            index += 1
        if frames:
            width = frames[0].width()
            height = frames[0].height()
            target_w, target_h = self._gif_target_size
            scale = max(1, math.ceil(width / target_w), math.ceil(height / target_h))
            if scale > 1:
                frames = [frame.subsample(scale, scale) for frame in frames]
            self._gif_frames = frames

    def _start_gif_animation(self, update_image: Callable[[tk.PhotoImage], None]) -> None:
        if self._gif_animation_id:
            self.after_cancel(self._gif_animation_id)
        self._gif_update_image = update_image
        self._gif_frame_index = 0
        self._animate_gif()

    def _animate_gif(self) -> None:
        if not self._gif_update_image or not self._gif_frames:
            return
        self._gif_frame_index = (self._gif_frame_index + 1) % len(self._gif_frames)
        self._gif_update_image(self._gif_frames[self._gif_frame_index])
        self._gif_animation_id = self.after(120, self._animate_gif)

    def system_check_summary(self) -> str:
        enabled = [name for name, value in self._feature_flags.items() if value]
        disabled = [name for name, value in self._feature_flags.items() if not value]
        rx_status = "Detected" if self._ir_detected["rx"] else "Not detected"
        tx_status = "Detected" if self._ir_detected["tx"] else "Not detected"
        lines = [
            "System Check",
            f"Enabled: {', '.join(enabled) if enabled else 'None'}",
        ]
        if disabled:
            lines.append(f"Disabled: {', '.join(disabled)}")
        lines.append(f"IR RX: {rx_status}")
        lines.append(f"IR TX: {tx_status}")
        return "\n".join(lines)

    def refresh_home(self) -> None:
        screen = self._screens.get("Home")
        if screen and hasattr(screen, "refresh"):
            screen.refresh()

    def toggle_debug_window(self) -> None:
        if self._debug_enabled.get():
            self._open_debug_window()
        else:
            self._close_debug_window()

    def set_log_enabled(self, enabled: bool) -> None:
        self._log_enabled.set(enabled)
        self._save_feature_flags()
        if enabled:
            self._emit_placeholder_logs()

    def _open_debug_window(self) -> None:
        if self._debug_window and self._debug_window.winfo_exists():
            self._debug_window.lift()
            return
        window = tk.Toplevel(self)
        window.title("Debug Console")
        window.geometry("420x220")
        theme_bg = ttk.Style().lookup("TFrame", "background") or self._colors["bg"]
        theme_fg = ttk.Style().lookup("TLabel", "foreground") or self._colors["text"]
        entry_bg = ttk.Style().lookup("TEntry", "fieldbackground") or theme_bg
        window.configure(bg=theme_bg)
        window.resizable(True, True)
        self._debug_window = window

        text = tk.Text(
            window,
            height=8,
            bg=entry_bg,
            fg=theme_fg,
            insertbackground=theme_fg,
            wrap=tk.WORD,
        )
        text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        text.configure(state=tk.DISABLED)
        self._debug_text = text

        def on_close() -> None:
            self._debug_enabled.set(False)
            self._close_debug_window()

        window.protocol("WM_DELETE_WINDOW", on_close)

    def _close_debug_window(self) -> None:
        if self._debug_window and self._debug_window.winfo_exists():
            self._debug_window.destroy()
        self._debug_window = None
        self._debug_text = None

    def log_debug(self, message: str) -> None:
        if not self._debug_enabled.get():
            return
        if not self._debug_text or not self._debug_text.winfo_exists():
            return
        stamped = f"{self._timestamp()} {message}"
        self._debug_text.configure(state=tk.NORMAL)
        self._debug_text.insert(tk.END, stamped + "\n")
        self._debug_text.see(tk.END)
        self._debug_text.configure(state=tk.DISABLED)
        if self._log_enabled.get():
            self._log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self._log_dir / "debug.log"
            self._append_log_line(log_path, stamped)

    def log_feature(self, feature: str, message: str) -> None:
        line = f"[{feature}] {message}"
        self.log_debug(line)
        if self._log_enabled.get():
            self._log_dir.mkdir(parents=True, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", feature.strip()).lower() or "system"
            log_path = self._log_dir / f"{safe}.log"
            stamped = f"{self._timestamp()} {line}"
            self._append_log_line(log_path, stamped)

    def _emit_placeholder_logs(self) -> None:
        self.log_feature("IR", "Receiver ready on GPIO RX.")
        self.log_feature("IR", "Transmitter ready on GPIO TX.")
        self.log_feature("Bluetooth", "Adapter detected, scan idle.")
        self.log_feature("WiFi", "Interface up, no active connection.")

    def _start_ir_boot_diagnostic(self) -> None:
        thread = threading.Thread(target=self._run_ir_boot_diagnostic, daemon=True)
        thread.start()

    def _run_ir_boot_diagnostic(self) -> None:
        result = self._ir_diagnostics.run_boot_diagnostic()
        self._ir_boot_diagnostic = result
        self._apply_ir_diagnostic_status(result)
        self.log_feature("IR", f"Boot diagnostic complete: {result.status}")
        self.log_feature("IR", f"Boot diagnostic summary: {result.summary_line()}")
        for step in result.steps:
            self.log_feature("IR", f"Boot {step.name}: {step.status} {step.details}")
        self.after(0, self._notify_boot_diagnostic_ready)

    def _notify_boot_diagnostic_ready(self) -> None:
        screen = self._screens.get("System")
        if screen and hasattr(screen, "refresh"):
            screen.refresh()
        self.refresh_home()

    def ir_diagnostics(self) -> IRDiagnosticService:
        return self._ir_diagnostics

    def ir_boot_diagnostic(self) -> Optional[DiagnosticResult]:
        return self._ir_boot_diagnostic

    def _timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _append_log_line(self, path: Path, line: str) -> None:
        self._rotate_log_if_needed(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _rotate_log_if_needed(self, path: Path) -> None:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return
        if size < self._log_max_bytes:
            return
        backup = path.with_suffix(path.suffix + ".1")
        if backup.exists():
            backup.unlink()
        path.replace(backup)

    def _configure_theme(self) -> None:
        self._colors = {
            "bg": "#000000",
            "panel": "#18222d",
            "panel_alt": "#141c26",
            "accent": "#36d1cc",
            "accent_alt": "#1aa6a0",
            "text": "#e6f0f6",
            "muted": "#8aa4b5",
            "warning": "#f4b400",
            "error": "#ff6b6b",
        }
        style = ttk.Style(self)
        try:
            import sv_ttk  # type: ignore

            sv_ttk.set_theme("dark")
            self._colors["bg"] = "#1c1c1c"
        except Exception:
            style.theme_use("clam")

        # Use Sun-Valley defaults without custom style overrides.

    def _add_screen(self, name: str, frame: tk.Frame) -> None:
        self._screens[name] = frame

    def show_screen(self, name: str) -> None:
        if self._current_screen:
            self._current_screen.pack_forget()
        self._current_screen = self._screens[name]
        self._current_screen.pack(fill=tk.BOTH, expand=True)
        if hasattr(self._current_screen, "refresh"):
            self._current_screen.refresh()

    def show_section(self, name: str) -> None:
        if name != "System" and not self.feature_enabled(name):
            return
        if name in {"Home", "System"}:
            self._subnav.grid_remove()
        else:
            self._subnav.grid()
        for child in self._subnav.winfo_children():
            child.destroy()
        def build_tabs(labels: list[str], on_select: Callable[[str], None], default: str) -> None:
            notebook = ttk.Notebook(self._subnav)
            notebook.pack(fill=tk.X, padx=6, pady=6)
            tab_frames: dict[str, ttk.Frame] = {}
            for label in labels:
                tab = ttk.Frame(notebook)
                notebook.add(tab, text=label)
                tab_frames[str(tab)] = label

            def handle_tab_change(event: tk.Event) -> None:
                selected = event.widget.select()
                label = tab_frames.get(selected)
                if label:
                    on_select(label)

            notebook.bind("<<NotebookTabChanged>>", handle_tab_change)
            if default in labels:
                notebook.select(labels.index(default))
                on_select(default)
        if name == "Home":
            self.show_screen("Home")
            return
        if name == "Scan":
            labels = ["Scan", "Library", "Emulate", "Clone/Write", "Settings"]
            build_tabs(labels, self.show_screen, "Scan")
        elif name == "IR":
            ir_screen = self._screens["IR"]
            labels = [
                "Universal Remotes",
                "Learn New Remote",
                "Saved Remotes",
                "Settings",
            ]
            self.show_screen("IR")
            build_tabs(labels, ir_screen.show_subscreen, "Universal Remotes")
        elif name == "Bluetooth":
            bluetooth_screen = self._screens["Bluetooth"]
            self.show_screen("Bluetooth")
            labels = ["Discovery", "Pairing", "Connection", "Audio", "Library", "Shortcuts"]
            build_tabs(labels, bluetooth_screen.show_subscreen, "Discovery")
        else:
            self.show_screen(name)

    def on_tag_detected(self, detection: TagDetection) -> None:
        self._current_detection = detection
        existing = self._store.get_by_uid(detection.uid)
        if existing:
            if detection.technologies:
                existing.tech_details["technologies"] = detection.technologies
            existing.touch_seen()
            self._store.upsert(existing)
            self._current_profile = existing
        else:
            self._current_profile = None
        for screen in self._screens.values():
            if hasattr(screen, "on_tag_detected"):
                screen.on_tag_detected(detection, self._current_profile)

    def save_current_tag(self) -> None:
        if not self._current_detection:
            return
        profile = self._current_profile or CardProfile.new_from_scan(
            uid=self._current_detection.uid,
            tag_type=self._current_detection.tag_type,
            tech_details={"technologies": self._current_detection.technologies},
        )
        dialog = SaveDialog(self, profile)
        self.wait_window(dialog)
        if dialog.result:
            updated = dialog.result
            self._store.upsert(updated)
            self._current_profile = updated
            self.show_screen("Library")

    def get_store(self) -> LibraryStore:
        return self._store

    def current_profile(self) -> Optional[CardProfile]:
        return self._current_profile

    def shutdown(self) -> None:
        self._on_shutdown()
        self.destroy()

    def ir_tx_pin(self) -> str:
        return self._ir_tx_pin.get()

    def ir_rx_pin(self) -> str:
        return self._ir_rx_pin.get()

    def set_ir_pins(self, tx_pin: str, rx_pin: str) -> None:
        self._ir_tx_pin.set(tx_pin)
        self._ir_rx_pin.set(rx_pin)
        self._refresh_ir_detection()
        self.refresh_home()

    def ir_rx_device(self) -> str:
        payload = self._load_ir_settings()
        value = str(payload.get("rx_device", "")).strip()
        if not value:
            return "/dev/lirc1"
        if not value.startswith("/dev/"):
            return f"/dev/{value}"
        return value

    def set_ir_rx_device(self, device: str) -> None:
        value = device.strip()
        if value and not value.startswith("/dev/"):
            value = f"/dev/{value}"
        payload = self._load_ir_settings()
        payload["rx_device"] = value
        self._save_ir_settings(payload)
        screen = self._screens.get("IR")
        if screen and hasattr(screen, "set_rx_device"):
            screen.set_rx_device(value)

    def _load_ir_settings(self) -> dict[str, object]:
        if not self._ir_settings_path.exists():
            return {}
        try:
            return json.loads(self._ir_settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_ir_settings(self, payload: dict[str, object]) -> None:
        self._ir_settings_path.write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )


class BaseScreen(ttk.Frame):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, style="App.TFrame")
        self._app = app


class HomeScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._status_rows: list[tuple[str, tk.Canvas]] = []

        self._content = ttk.Frame(self, style="App.TFrame")
        self._content.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)

        top_row = ttk.Frame(self._content, style="App.TFrame")
        top_row.pack(fill=tk.X, pady=(6, 8))

        self._status_card = ttk.Frame(top_row, style="Card.TFrame")
        ttk.Label(self._status_card, text="System Check", style="Status.TLabel").pack(
            pady=(8, 4), anchor="w", padx=12
        )
        self._status_host = ttk.Frame(self._status_card, style="Card.TFrame")
        self._status_host.pack(fill=tk.X, expand=True, padx=12, pady=(0, 12), anchor="w")
        self._sync_status_card_visibility()
        self._build_status_rows()

        if self._app._gif_frames:
            gif_w, gif_h = self._app._gif_target_size
            theme_bg = ttk.Style().lookup("TFrame", "background") or self._app._colors["bg"]
            gif_canvas = tk.Canvas(
                top_row,
                width=gif_w,
                height=gif_h,
                highlightthickness=0,
                bg=theme_bg,
            )
            gif_canvas.pack(side=tk.RIGHT, anchor="e")
            image_id = gif_canvas.create_image(
                gif_w // 2,
                gif_h // 2,
                image=self._app._gif_frames[0],
                anchor="center",
            )
            self._app._start_gif_animation(
                lambda img, canvas=gif_canvas, item=image_id: canvas.itemconfigure(
                    item, image=img
                )
            )
        else:
            ttk.Label(
                top_row,
                text="GIF missing: data/assets/main.gif",
                style="Muted.TLabel",
            ).pack(side=tk.RIGHT, anchor="e")

    def refresh(self) -> None:
        self._build_status_rows()

    def _sync_status_card_visibility(self) -> bool:
        if self._app.feature_enabled("IR"):
            if not self._status_card.winfo_manager():
                self._status_card.pack(
                    side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 16)
                )
            return True
        if self._status_card.winfo_manager():
            self._status_card.pack_forget()
        return False

    def _build_status_rows(self) -> None:
        if not self._sync_status_card_visibility():
            for child in self._status_host.winfo_children():
                child.destroy()
            self._status_rows.clear()
            return
        for child in self._status_host.winfo_children():
            child.destroy()
        self._status_rows.clear()

        boot_result = self._app.ir_boot_diagnostic()
        if boot_result:
            ttk.Label(
                self._status_host,
                text="IR System Check",
                style="Status.TLabel",
            ).pack(anchor="w", pady=(0, 6))
            for step in boot_result.steps:
                row = ttk.Frame(self._status_host, style="Card.TFrame")
                row.pack(fill=tk.X, pady=2, anchor="w")
                self._make_status_indicator(row, step.status)
                ttk.Label(row, text=step.name, style="Body.TLabel").pack(
                    side=tk.LEFT, padx=(8, 0)
                )

        enabled_modules = [name for name, enabled in self._app._feature_flags.items() if enabled]
        if not enabled_modules:
            ttk.Label(
                self._status_host,
                text="No modules enabled.",
                style="Muted.TLabel",
            ).pack(anchor="w")
            return

        for name in enabled_modules:
            row = ttk.Frame(self._status_host, style="Card.TFrame")
            row.pack(fill=tk.X, pady=4, anchor="w")
            if name == "IR":
                continue
            ttk.Label(row, text=name, style="Body.TLabel").pack(side=tk.LEFT, padx=(0, 8))
            light = self._make_status_light(row)
            self._status_rows.append((name, light))

        self._update_status_lights()

    def _make_status_light(self, parent: ttk.Frame) -> tk.Canvas:
        canvas = tk.Canvas(
            parent,
            width=12,
            height=12,
            highlightthickness=0,
            bg=self._app._colors["panel"],
        )
        canvas.pack(side=tk.LEFT)
        return canvas

    def _update_status_lights(self) -> None:
        for name, canvas in self._status_rows:
            canvas.delete("all")
            canvas.create_oval(2, 2, 10, 10, fill=self._status_color("PASS"), outline=self._status_color("PASS"))

    def _make_status_indicator(self, parent: ttk.Frame, status: str) -> tk.Canvas:
        canvas = self._make_status_light(parent)
        color = self._status_color(status)
        canvas.create_oval(2, 2, 10, 10, fill=color, outline=color)
        return canvas

    def _status_color(self, status: Optional[str]) -> str:
        if status == "PASS":
            return self._app._colors["accent"]
        if status == "WARN":
            return self._app._colors["warning"]
        if status == "FAIL":
            return self._app._colors["error"]
        return self._app._colors["muted"]

    def _set_ir_statuses(self, result: DiagnosticResult) -> None:
        step_status = {step.name: step.status for step in result.steps}
        rx_statuses = [
            step_status.get("Presence Check"),
            step_status.get("Driver/Binding Check"),
        ]
        tx_statuses = [step_status.get("TX Send Test")]
        self._ir_rx_status = self._combine_statuses(rx_statuses)
        self._ir_tx_status = self._combine_statuses(tx_statuses)

    def _combine_statuses(self, statuses: list[Optional[str]]) -> str:
        filtered = [status for status in statuses if status]
        if not filtered:
            return "PENDING"
        if "FAIL" in filtered:
            return "FAIL"
        if "WARN" in filtered:
            return "WARN"
        return "PASS"

    def _status_color(self, status: Optional[str]) -> str:
        if status == "PASS":
            return self._app._colors["accent"]
        if status == "WARN":
            return self._app._colors["warning"]
        if status == "FAIL":
            return self._app._colors["error"]
        return self._app._colors["muted"]


class ScanScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._status = tk.StringVar(value="Ready to scan")
        self._tag_summary = tk.StringVar(value="No tag detected")
        self._tag_details = tk.StringVar(value="")

        status_label = ttk.Label(self, textvariable=self._status, style="Title.TLabel")
        status_label.pack(pady=10)

        summary_label = ttk.Label(self, textvariable=self._tag_summary, style="Status.TLabel")
        summary_label.pack(pady=6)

        details_label = ttk.Label(self, textvariable=self._tag_details, style="Muted.TLabel")
        details_label.pack(pady=4)

        actions = ttk.Frame(self, style="Card.TFrame")
        actions.pack(pady=12)
        ttk.Button(
            actions,
            text="Save to Library",
            style="Primary.TButton",
            command=self._app.save_current_tag,
        ).grid(row=0, column=0, padx=8, pady=8)
        ttk.Button(
            actions,
            text="Read Details",
            style="Secondary.TButton",
            command=self._show_details,
        ).grid(row=0, column=1, padx=8, pady=8)
        ttk.Button(
            actions,
            text="Clone/Write",
            style="Secondary.TButton",
            command=self._go_clone,
        ).grid(row=1, column=0, padx=8, pady=8)
        ttk.Button(
            actions,
            text="Emulate",
            style="Secondary.TButton",
            command=self._go_emulate,
        ).grid(row=1, column=1, padx=8, pady=8)

        simulate = ttk.Frame(self, style="Card.TFrame")
        simulate.pack(fill=tk.X, padx=16, pady=12)
        ttk.Label(simulate, text="Mock Tag", style="Body.TLabel").pack(pady=6)
        self._uid_entry = ttk.Entry(simulate, style="App.TEntry")
        self._uid_entry.insert(0, "04:AB:CD:EF")
        self._uid_entry.pack(pady=4, padx=8, fill=tk.X)
        self._type_entry = ttk.Entry(simulate, style="App.TEntry")
        self._type_entry.insert(0, "NTAG213")
        self._type_entry.pack(pady=4, padx=8, fill=tk.X)
        ttk.Button(
            simulate, text="Simulate Tag", style="Secondary.TButton", command=self._simulate
        ).pack(pady=8)

    def on_tag_detected(self, detection: TagDetection, profile: Optional[CardProfile]) -> None:
        self._status.set("Tag detected")
        name = profile.friendly_name if profile else "Unnamed tag"
        technologies = ", ".join(detection.technologies) if detection.technologies else "Unknown"
        self._tag_summary.set(f"{name} ({detection.tag_type})")
        self._tag_details.set(
            f"Serial: {detection.uid} | Technologies: {technologies}"
        )

    def _show_details(self) -> None:
        self._app.show_screen("Library")

    def _go_clone(self) -> None:
        self._app.show_screen("Clone/Write")

    def _go_emulate(self) -> None:
        self._app.show_screen("Emulate")

    def _simulate(self) -> None:
        uid = self._uid_entry.get().strip()
        tag_type = self._type_entry.get().strip() or "Unknown"
        reader = getattr(self._app, "reader", None)
        if reader and hasattr(reader, "simulate_tag"):
            reader.simulate_tag(uid, tag_type)


class LibraryScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._listbox = tk.Listbox(
            self,
            height=8,
            bg=self._app._colors["panel"],
            fg=self._app._colors["text"],
            selectbackground=self._app._colors["accent"],
            selectforeground="#0b1020",
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self._listbox.pack(fill=tk.X, padx=10, pady=10)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        self._detail = tk.StringVar(value="Select a tag to view details")
        ttk.Label(self, textvariable=self._detail, style="Body.TLabel").pack(pady=8)

        actions = ttk.Frame(self, style="Card.TFrame")
        actions.pack(pady=8)
        ttk.Button(actions, text="Emulate", style="Primary.TButton", command=self._emulate).grid(
            row=0, column=0, padx=8, pady=6
        )
        ttk.Button(actions, text="Clone/Write", style="Secondary.TButton", command=self._clone).grid(
            row=0, column=1, padx=8, pady=6
        )
        ttk.Button(actions, text="Delete", style="Secondary.TButton", command=self._delete).grid(
            row=0, column=2, padx=8, pady=6
        )

        self._profiles = []

    def refresh(self) -> None:
        self._profiles = self._app.get_store().list_profiles()
        self._listbox.delete(0, tk.END)
        for profile in self._profiles:
            self._listbox.insert(tk.END, f"{profile.friendly_name} ({profile.uid_short})")

    def _on_select(self, event: tk.Event) -> None:
        if not self._listbox.curselection():
            return
        index = self._listbox.curselection()[0]
        profile = self._profiles[index]
        technologies = ", ".join(profile.tech_details.get("technologies", [])) or "Unknown"
        detail = (
            f"Name: {profile.friendly_name}\n"
            f"UID: {profile.uid}\n"
            f"Type: {profile.tag_type}\n"
            f"Technologies: {technologies}\n"
            f"Last seen: {profile.timestamps.last_seen_at}"
        )
        self._detail.set(detail)

    def _emulate(self) -> None:
        self._app.show_screen("Emulate")

    def _clone(self) -> None:
        self._app.show_screen("Clone/Write")

    def _delete(self) -> None:
        if not self._listbox.curselection():
            return
        index = self._listbox.curselection()[0]
        profile = self._profiles[index]
        self._app.get_store().delete(profile.id)
        self.refresh()


class EmulateScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._status = tk.StringVar(value="Pick a tag from the Library")
        ttk.Label(self, textvariable=self._status, style="Status.TLabel").pack(pady=12)

        method_frame = ttk.Frame(self, style="Card.TFrame")
        method_frame.pack(pady=8)
        ttk.Label(method_frame, text="Method:", style="Body.TLabel").pack(side=tk.LEFT, padx=6)
        self._method = tk.StringVar(value="Auto")
        ttk.OptionMenu(
            method_frame, self._method, "Auto", "Auto", "NDEF", "Raw", style="App.TMenubutton"
        ).pack(side=tk.LEFT)

        self._capability = tk.StringVar(value="Select a tag to see capabilities")
        ttk.Label(self, textvariable=self._capability, style="Muted.TLabel").pack(pady=6)

        ttk.Button(self, text="Start Emulation", style="Primary.TButton", command=self._start).pack(
            pady=12
        )

    def refresh(self) -> None:
        profile = self._app.current_profile()
        if profile:
            self._status.set(f"Selected: {profile.friendly_name}")
            self._capability.set("Auto will select the best available method.")

    def _start(self) -> None:
        profile = self._app.current_profile()
        if profile:
            self._status.set(f"Emulating {profile.friendly_name} ({self._method.get()})")


class CloneWriteScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="Clone/Write", style="Title.TLabel").pack(pady=10)
        self._status = tk.StringVar(value="Select a tag from the Library to clone or write.")
        ttk.Label(self, textvariable=self._status, style="Muted.TLabel").pack(pady=4)

        grid = ttk.Frame(self, style="App.TFrame")
        grid.pack(fill=tk.X, padx=16, pady=8)
        grid.columnconfigure(0, weight=1)

        self._build_tool_group(
            grid,
            row=0,
            column=0,
            title="Clone/Write",
            buttons=[
                ("Clone (Auto)", lambda: self._set_status("Clone using best available method.")),
                ("Write NDEF", lambda: self._set_status("Write NDEF to target tag.")),
                ("Write Raw", lambda: self._set_status("Write raw memory to target tag.")),
            ],
        )

    def _build_tool_group(
        self,
        master: ttk.Frame,
        row: int,
        column: int,
        title: str,
        buttons: list[tuple[str, Callable[[], None]]],
    ) -> None:
        card = ttk.Frame(master, style="Card.TFrame")
        card.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        ttk.Label(card, text=title, style="Status.TLabel").pack(pady=(8, 4))
        for label, command in buttons:
            ttk.Button(card, text=label, style="Secondary.TButton", command=command).pack(
                pady=4, padx=8, fill=tk.X
            )

    def _set_status(self, message: str) -> None:
        self._status.set(message)


class SettingsScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="Settings", style="Title.TLabel").pack(pady=10)
        self._ir_test_status = tk.StringVar(value="Run the IR test to verify devices.")

        conn_frame = ttk.Frame(self, style="Card.TFrame")
        conn_frame.pack(pady=8)
        ttk.Label(conn_frame, text="Connection mode:", style="Body.TLabel").pack(
            side=tk.LEFT, padx=6
        )
        self._conn_mode = tk.StringVar(value="I2C")
        ttk.OptionMenu(
            conn_frame, self._conn_mode, "I2C", "I2C", "SPI", "UART", style="App.TMenubutton"
        ).pack(side=tk.LEFT)

        ir_test_card = ttk.Frame(self, style="Card.TFrame")
        ir_test_card.pack(pady=8, padx=16, fill=tk.X)
        ttk.Label(ir_test_card, text="IR Diagnostics", style="Status.TLabel").pack(
            pady=(8, 4)
        )
        ttk.Button(
            ir_test_card,
            text="Run IR Test",
            style="Secondary.TButton",
            command=self._run_ir_test,
        ).pack(pady=4, padx=8, fill=tk.X)
        ttk.Label(
            ir_test_card,
            textvariable=self._ir_test_status,
            style="Muted.TLabel",
        ).pack(pady=(4, 8), padx=8, anchor="w")

        # IR pins moved to System screen.

    def _run_ir_test(self) -> None:
        devices = sorted(Path("/dev").glob("lirc*"))
        if devices:
            device_list = ", ".join(str(device) for device in devices)
            message = f"Detected IR devices: {device_list}."
        else:
            message = "No /dev/lirc* devices found."
        self._ir_test_status.set(message)
        rx_status = "detected" if self._app._ir_detected["rx"] else "not detected"
        tx_status = "detected" if self._app._ir_detected["tx"] else "not detected"
        self._app.log_feature("IR", f"IR test: {message}")
        self._app.log_feature("IR", f"IR test: RX {rx_status}, TX {tx_status}.")



class IRScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        from ir.flipper_ir import FlipperIRSignal, parse_library_signals, serialize_signals
        from ir.ir_decode import decode_raw_timings
        from ir.ir_library import IRLibraryStore
        from ir.lirc_client import LircClient

        self._flipper_signal = FlipperIRSignal
        self._parse_library_signals = parse_library_signals
        self._serialize_signals = serialize_signals
        self._decode_raw_timings = decode_raw_timings

        self._status = tk.StringVar(value="")
        self._captures: list[dict[str, object]] = []
        self._capture_detail = tk.StringVar(value="")
        self._capture_idle = tk.StringVar(value="2.0")
        self._aggregate_mode = tk.StringVar(value="Selected")
        self._last_capture: Optional[dict[str, object]] = None
        self._capture_thread: Optional[threading.Thread] = None
        self._capture_stop = threading.Event()
        self._ir_test_status = tk.StringVar(value="Run the IR test to verify devices.")
        self._client = LircClient()
        self._client.set_rx_device(self._app.ir_rx_device())

        self._data_dir = Path(__file__).resolve().parents[2] / "data"
        self._saved_dir = self._data_dir / "ir" / "saved remotes"
        self._universal_dir = self._data_dir / "universal"
        self._ir_settings_path = self._data_dir / "ir_settings.json"
        self._ir_library = IRLibraryStore(self._saved_dir)

        self._saved_detail = tk.StringVar(value="Select a remote")
        self._saved_button_detail = tk.StringVar(value="Select a button")
        self._saved_remotes: list[str] = []
        self._saved_buttons: list[str] = []
        self._selected_saved_remote_signals: list[FlipperIRSignal] = []
        self._saved_tree_nodes: dict[str, str] = {}
        self._saved_remote_items: dict[str, str] = {}
        self._saved_group = tk.StringVar(value="All")
        self._saved_groups: list[str] = []

        self._universal_device = tk.StringVar(value="TV")
        self._universal_selected_button = tk.StringVar(value="Select a button")
        self._universal_progress_value = tk.DoubleVar(value=0.0)
        self._universal_model = tk.StringVar(value="-")
        self._universal_notice = tk.StringVar(value="")
        self._universal_delay = self._load_universal_delay()
        self._delay_value = tk.DoubleVar(value=self._universal_delay)
        self._universal_scan_thread: Optional[threading.Thread] = None
        self._universal_scan_stop = threading.Event()
        self._universal_buttons: dict[str, ttk.Button] = {}
        self._selected_universal_button: Optional[str] = None
        self._learn_instruction = tk.StringVar(
            value="Point the remote at the IR port and push the button."
        )

        self._universal_layouts = {
            "TV": [
                "Power",
                "Mute",
                "Vol+",
                "Vol-",
                "Ch+",
                "Ch-",
            ],
            "Audio System": [
                "Power",
                "Mute",
                "Vol+",
                "Vol-",
                "Bass+",
                "Bass-",
                "Treble+",
                "Treble-",
            ],
            "Projector": [
                "Power",
                "Source",
                "Menu",
                "Up",
                "Down",
                "Left",
                "Right",
                "OK",
                "Back",
                "Vol+",
                "Vol-",
                "Keystone+",
                "Keystone-",
            ],
            "Air Conditioner": [
                "Power",
                "Mode",
                "Temp+",
                "Temp-",
                "Fan",
                "Swing",
            ],
            "LED": [
                "Power",
                "Bright+",
                "Bright-",
                "Speed+",
                "Speed-",
                "Color+",
                "Color-",
            ],
        }

        self._ir_screen_host = ttk.Frame(self, style="App.TFrame")
        self._ir_screen_host.pack(fill=tk.BOTH, expand=True, padx=16, pady=(10, 10))

        self._ir_screens: dict[str, tk.Frame] = {}
        self._current_ir_screen: Optional[tk.Frame] = None

        self._add_ir_screen("Universal Remotes", self._build_universal_screen())
        self._add_ir_screen("Learn New Remote", self._build_learn_screen())
        self._add_ir_screen("Saved Remotes", self._build_saved_remotes_screen())
        self._add_ir_screen("Settings", self._build_ir_settings_screen())

        self._show_ir_screen("Universal Remotes")

    def _add_ir_screen(self, name: str, frame: tk.Frame) -> None:
        self._ir_screens[name] = frame

    def _show_ir_screen(self, name: str) -> None:
        if self._current_ir_screen:
            self._current_ir_screen.pack_forget()
        self._current_ir_screen = self._ir_screens[name]
        self._current_ir_screen.pack(fill=tk.BOTH, expand=True)

    def show_subscreen(self, name: str) -> None:
        if name != "Learn New Remote" and self._capture_thread:
            self._stop_capture()
        self._show_ir_screen(name)
        if name == "Learn New Remote":
            self._begin_learn_session()
        if name == "Saved Remotes":
            self._refresh_saved_remotes()

    def _run_ir_test(self) -> None:
        self._app.show_section("System")
        system_screen = self._app._screens.get("System")
        if system_screen and hasattr(system_screen, "show_diagnostics_tab"):
            system_screen.show_diagnostics_tab()

    def _build_universal_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        device_card = ttk.Frame(frame, style="Card.TFrame")
        device_card.grid(row=0, column=0, sticky="ns", padx=(0, 10), pady=6)
        ttk.Label(device_card, text="Devices", style="Status.TLabel").pack(pady=(8, 4))
        self._universal_device_list = ttk.Treeview(
            device_card,
            show="tree",
            selectmode="browse",
            height=7,
        )
        self._universal_device_list.pack(fill=tk.BOTH, padx=8, pady=(0, 8))
        self._universal_device_list.bind(
            "<<TreeviewSelect>>", self._on_universal_device_select
        )
        for device in self._universal_layouts.keys():
            self._universal_device_list.insert("", tk.END, text=device)
        first = self._universal_device_list.get_children()
        if first:
            self._universal_device_list.selection_set(first[0])
            self._universal_device_list.see(first[0])

        right = ttk.Frame(frame, style="App.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)

        info = ttk.Frame(right, style="Card.TFrame")
        info.pack(fill=tk.X, pady=6)
        ttk.Label(info, textvariable=self._universal_model, style="Muted.TLabel").pack(pady=2)
        ttk.Label(info, textvariable=self._universal_notice, style="Muted.TLabel").pack(pady=2)
        self._universal_progress_bar = ttk.Progressbar(
            info,
            variable=self._universal_progress_value,
            maximum=1.0,
            mode="determinate",
        )
        self._universal_progress_bar.pack(fill=tk.X, padx=12, pady=(4, 8))

        controls = ttk.Frame(right, style="Card.TFrame")
        controls.pack(fill=tk.X, pady=6)
        button_row = ttk.Frame(controls, style="Card.TFrame")
        button_row.pack(fill=tk.X, padx=8, pady=8)
        ttk.Button(
            button_row, text="Start", style="Small.TButton", command=self._start_universal_scan
        ).grid(row=0, column=0, padx=4, sticky="ew")
        ttk.Button(
            button_row, text="Stop", style="Small.TButton", command=self._stop_universal_scan
        ).grid(row=0, column=1, padx=4, sticky="ew")
        button_row.columnconfigure(0, weight=1)
        button_row.columnconfigure(1, weight=1)

        self._universal_button_host = ttk.Frame(right, style="Card.TFrame")
        self._universal_button_host.pack(fill=tk.BOTH, expand=True, pady=6)
        ttk.Label(
            self._universal_button_host, text="Remote Buttons", style="Status.TLabel"
        ).pack(pady=(8, 4))
        self._universal_button_grid = ttk.Frame(self._universal_button_host, style="Card.TFrame")
        self._universal_button_grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._render_universal_buttons(self._universal_device.get())
        return frame
    def _build_learn_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        frame.columnconfigure(0, weight=1)

        control_card = ttk.Frame(frame, style="Card.TFrame")
        control_card.pack(fill=tk.X, pady=6)
        # Title removed to avoid duplicate "Learn New Remote" text.
        ttk.Label(
            control_card,
            textvariable=self._learn_instruction,
            style="Body.TLabel",
            wraplength=420,
        ).pack(pady=(0, 6))
        options = ttk.Frame(control_card, style="Card.TFrame")
        options.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(options, text="Idle Finish (s)", style="Muted.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self._capture_idle_picker = ttk.Combobox(
            options,
            textvariable=self._capture_idle,
            state="readonly",
            values=["1.0", "1.5", "2.0", "3.0", "5.0"],
            width=6,
        )
        self._capture_idle_picker.grid(row=0, column=1, padx=(8, 16), sticky="w")
        ttk.Label(options, text="Decode Using", style="Muted.TLabel").grid(
            row=0, column=2, sticky="w"
        )
        self._aggregate_mode_picker = ttk.Combobox(
            options,
            textvariable=self._aggregate_mode,
            state="readonly",
            values=["Selected", "Best", "Median", "Mean"],
            width=14,
        )
        self._aggregate_mode_picker.grid(row=0, column=3, padx=(8, 0), sticky="w")
        self._aggregate_mode_picker.bind(
            "<<ComboboxSelected>>", self._on_aggregate_mode_change
        )
        options.columnconfigure(4, weight=1)

        captures = ttk.Frame(frame, style="Card.TFrame")
        captures.pack(fill=tk.BOTH, expand=True, pady=6)
        # Captured Signals header removed to keep layout concise.
        self._learn_capture_list = tk.Listbox(
            captures,
            height=8,
            bg=ttk.Style().lookup("TFrame", "background") or self._app._colors["bg"],
            fg=ttk.Style().lookup("TLabel", "foreground") or self._app._colors["text"],
            selectbackground=ttk.Style().lookup("Treeview", "selectbackground")
            or self._app._colors["accent"],
            selectforeground=ttk.Style().lookup("Treeview", "selectforeground")
            or self._app._colors["text"],
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self._learn_capture_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self._learn_capture_list.bind("<<ListboxSelect>>", self._on_capture_select)
        ttk.Label(captures, textvariable=self._capture_detail, style="Muted.TLabel").pack(
            pady=(0, 8)
        )

        self._learn_button_row = ttk.Frame(frame, style="Card.TFrame")
        self._learn_button_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._learn_retry_btn = ttk.Button(
            self._learn_button_row, text="Retry", style="Small.TButton", command=self._retry_learn
        )
        self._learn_retry_btn.grid(row=0, column=0, padx=4, sticky="ew")
        self._learn_send_btn = ttk.Button(
            self._learn_button_row, text="Send", style="Small.TButton", command=self._send_learned_signal
        )
        self._learn_send_btn.grid(row=0, column=1, padx=4, sticky="ew")
        self._learn_send_decoded_btn = ttk.Button(
            self._learn_button_row,
            text="Send Decoded",
            style="Small.TButton",
            command=self._send_decoded_learned_signal,
        )
        self._learn_send_decoded_btn.grid(row=0, column=2, padx=4, sticky="ew")
        self._learn_send_raw_btn = ttk.Button(
            self._learn_button_row, text="Send Raw", style="Small.TButton", command=self._send_raw_learned_signal
        )
        self._learn_send_raw_btn.grid(row=0, column=3, padx=4, sticky="ew")
        self._learn_save_btn = ttk.Button(
            self._learn_button_row, text="Save", style="Small.TButton", command=self._save_learned_signal
        )
        self._learn_save_btn.grid(row=0, column=4, padx=4, sticky="ew")
        self._learn_save_decoded_btn = ttk.Button(
            self._learn_button_row,
            text="Save Decoded",
            style="Small.TButton",
            command=self._save_decoded_signal,
        )
        self._learn_save_decoded_btn.grid(row=0, column=5, padx=4, sticky="ew")
        for idx in range(6):
            self._learn_button_row.columnconfigure(idx, weight=1)
        return frame

    def _build_saved_remotes_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=2)
        frame.rowconfigure(0, weight=1)

        left = ttk.Frame(frame, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=6)
        group_row = ttk.Frame(left, style="Card.TFrame")
        group_row.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(group_row, text="Group", style="Muted.TLabel").pack(side=tk.LEFT)
        self._saved_group_picker = ttk.Combobox(
            group_row,
            textvariable=self._saved_group,
            state="readonly",
            values=["All"],
        )
        self._saved_group_picker.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(8, 0))
        self._saved_group_picker.bind("<<ComboboxSelected>>", self._on_saved_group_change)
        ttk.Label(left, text="Saved Remotes", style="Status.TLabel").pack(pady=(8, 4))
        self._saved_remote_list = ttk.Treeview(
            left,
            show="tree",
            selectmode="browse",
            height=10,
        )
        self._saved_remote_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))
        self._saved_remote_list.bind(
            "<<TreeviewSelect>>", self._on_saved_remote_select
        )
        ttk.Label(left, textvariable=self._saved_detail, style="Muted.TLabel").pack(
            pady=(0, 8)
        )
        ttk.Button(
            left, text="Edit Remote", style="Small.TButton", command=self._open_saved_editor
        ).pack(pady=(0, 8))

        right = ttk.Frame(frame, style="App.TFrame")
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        button_card = ttk.Frame(right, style="Card.TFrame")
        button_card.pack(fill=tk.BOTH, expand=True, pady=6)
        ttk.Label(button_card, text="Buttons", style="Status.TLabel").pack(pady=(8, 4))
        self._saved_button_list = ttk.Treeview(
            button_card,
            show="tree",
            selectmode="browse",
            height=6,
        )
        self._saved_button_list.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._saved_button_list.bind(
            "<<TreeviewSelect>>", self._on_saved_button_select
        )
        ttk.Label(button_card, textvariable=self._saved_button_detail, style="Muted.TLabel").pack(
            pady=(0, 8)
        )
        self._saved_button_grid = ttk.Frame(button_card, style="Card.TFrame")
        self._saved_button_grid.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        return frame

    def _build_ir_settings_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        delay_card = ttk.Frame(frame, style="Card.TFrame")
        delay_card.pack(fill=tk.X, pady=6)
        ttk.Label(
            delay_card, text="Universal Remote Delay (s)", style="Status.TLabel"
        ).pack(pady=(8, 4))
        self._delay_label = tk.StringVar(value=f"{self._universal_delay:.1f} s")
        ttk.Label(delay_card, textvariable=self._delay_label, style="Body.TLabel").pack(
            pady=(0, 4)
        )
        self._delay_slider = ttk.Scale(
            delay_card,
            from_=0.0,
            to=4.0,
            variable=self._delay_value,
            command=self._update_delay_label,
        )
        self._delay_slider.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(
            delay_card,
            text="Save Delay",
            style="Secondary.TButton",
            command=self._save_universal_delay,
        ).pack(pady=(0, 8))

        pin_status = ttk.Frame(frame, style="Card.TFrame")
        pin_status.pack(fill=tk.X, pady=6)
        ttk.Label(pin_status, text="IR Pins", style="Status.TLabel").pack(pady=(6, 2))
        ttk.Label(
            pin_status,
            text=f"TX: {self._app.ir_tx_pin()} | RX: {self._app.ir_rx_pin()}",
            style="Body.TLabel",
        ).pack(pady=(0, 6))
        ttk.Button(
            pin_status,
            text="Edit Pins in System",
            style="Secondary.TButton",
            command=self._open_ir_pin_settings,
        ).pack(pady=(0, 8))

        ir_test_card = ttk.Frame(frame, style="Card.TFrame")
        ir_test_card.pack(fill=tk.X, pady=6)
        ttk.Label(ir_test_card, text="IR Diagnostics", style="Status.TLabel").pack(
            pady=(8, 4)
        )
        ttk.Button(
            ir_test_card,
            text="Run IR Test",
            style="Secondary.TButton",
            command=self._run_ir_test,
        ).pack(pady=4, padx=8, fill=tk.X)
        ttk.Label(
            ir_test_card,
            textvariable=self._ir_test_status,
            style="Muted.TLabel",
        ).pack(pady=(4, 8), padx=8, anchor="w")
        return frame

    def _set_status(self, message: str) -> None:
        self._status.set(message)

    def _begin_learn_session(self) -> None:
        self._captures.clear()
        self._last_capture = None
        self._capture_detail.set("")
        self._learn_instruction.set(
            "Point the remote at the IR port and push the button."
        )
        self._app.log_feature("IR", "Learn session start")
        if hasattr(self, "_learn_button_row"):
            self._learn_button_row.pack_forget()
        if hasattr(self, "_learn_capture_list"):
            self._learn_capture_list.delete(0, tk.END)
        self._start_capture()

    def _retry_learn(self) -> None:
        self._begin_learn_session()

    def _start_capture(self) -> None:
        if self._capture_thread and self._capture_thread.is_alive():
            return
        self._app.log_feature("IR", "Learn start capture thread")
        self._capture_stop.clear()
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def _stop_capture(self) -> None:
        if not self._capture_thread or not self._capture_thread.is_alive():
            return
        self._app.log_feature("IR", "Learn stop capture thread")
        self._capture_stop.set()

    def _capture_loop(self) -> None:
        self._app.log_feature("IR", "Learn capture loop begin")
        captured = 0
        idle_timeout = self._capture_idle_timeout()
        while not self._capture_stop.is_set():
            capture = self._client.capture_signal(self._capture_stop, timeout_s=idle_timeout)
            if not capture:
                if captured:
                    self._app.log_feature("IR", "Learn capture loop ended (idle)")
                    self._app.after(
                        0,
                        lambda: self._learn_instruction.set(
                            "Capture complete. Review details below."
                        ),
                    )
                else:
                    self._app.log_feature("IR", "Learn capture loop ended (no capture)")
                return
            captured += 1
            self._app.after(0, lambda payload=capture: self._add_capture(payload))
            self._app.after(
                0,
                lambda count=captured: self._update_learn_progress(count),
            )
            self._app.log_feature("IR", "Learn capture received")

    def _add_capture(self, capture: dict[str, object]) -> None:
        self._captures.append(capture)
        self._last_capture = capture
        self._log_ir_capture(capture)
        protocol = capture.get("protocol")
        self._app.log_feature("IR", f"Learn capture added protocol={protocol}")
        self._learn_instruction.set("Signal captured. Review details below.")
        if hasattr(self, "_learn_button_row"):
            self._learn_button_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        if hasattr(self, "_learn_capture_list"):
            detail = self._format_capture_list_entry(capture)
            self._learn_capture_list.insert(tk.END, detail)
            self._learn_capture_list.selection_clear(0, tk.END)
            self._learn_capture_list.selection_set(tk.END)
            self._learn_capture_list.event_generate("<<ListboxSelect>>")
        if self._aggregate_mode.get().strip() != "Selected":
            self._capture_detail.set(self._aggregate_detail_line())

    def _on_capture_select(self, event: tk.Event) -> None:
        listbox = event.widget
        if not listbox.curselection():
            return
        index = listbox.curselection()[0]
        capture = self._captures[index]
        if self._aggregate_mode.get().strip() == "Selected":
            self._capture_detail.set(self._format_capture_detail(capture))
        else:
            self._capture_detail.set(self._aggregate_detail_line())

    def _log_ir_capture(self, capture: dict[str, object]) -> None:
        if not self._app._log_enabled.get():
            return
        signal_type = str(capture.get("signal_type") or "parsed")
        raw_data = capture.get("raw_data")
        raw_burst = capture.get("raw_burst")
        frequency = capture.get("raw_frequency")
        duty_cycle = capture.get("raw_duty_cycle")
        raw_attempted = capture.get("raw_attempted")
        raw_device = capture.get("raw_device")
        raw_lines = capture.get("raw_lines") or []
        raw_command = capture.get("raw_command")
        keytable_command = capture.get("keytable_command")
        raw_error = capture.get("raw_error")
        if signal_type == "raw":
            raw_data = capture.get("data") or raw_data
            frequency = capture.get("frequency") or frequency
            duty_cycle = capture.get("duty_cycle") or duty_cycle
            raw_lines = capture.get("raw_lines") or raw_lines
        self._app._log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self._app._log_dir / "ir_raw_captures.log"
        protocol = str(capture.get("protocol") or "Unknown")
        address = str(capture.get("address") or "")
        command = str(capture.get("command") or "")
        raw_line = ",".join(str(value) for value in raw_data) if raw_data else "missing"
        raw_burst_count = len(raw_burst) if raw_burst else 0
        stamped = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = (
            f"{stamped} protocol={protocol} address={address} command={command} "
            f"frequency={frequency} duty_cycle={duty_cycle} raw={raw_line} "
            f"raw_attempted={raw_attempted} raw_device={raw_device} "
            f"raw_command={raw_command} keytable_command={keytable_command} "
            f"raw_error={raw_error} raw_burst_count={raw_burst_count} "
            f"raw_lines={';'.join(str(item) for item in raw_lines[-10:])}"
        )
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if raw_command or raw_lines:
            output = ";".join(str(item) for item in raw_lines)
            self._app.log_feature(
                "IR",
                f"Learn raw capture command={raw_command} output={output}",
            )

    def _selected_capture(self) -> Optional[dict[str, object]]:
        mode = self._aggregate_mode.get().strip()
        if mode in {"Best", "Median", "Mean"}:
            aggregate = self._aggregate_capture(mode)
            if aggregate:
                return aggregate
        if hasattr(self, "_learn_capture_list") and self._learn_capture_list.curselection():
            index = self._learn_capture_list.curselection()[0]
            return self._captures[index]
        return self._last_capture

    def _on_aggregate_mode_change(self, _event: tk.Event) -> None:
        if self._aggregate_mode.get().strip() == "Selected":
            if hasattr(self, "_learn_capture_list") and self._learn_capture_list.curselection():
                index = self._learn_capture_list.curselection()[0]
                capture = self._captures[index]
                self._capture_detail.set(self._format_capture_detail(capture))
        else:
            self._capture_detail.set(self._aggregate_detail_line())

    def _update_learn_progress(self, count: int) -> None:
        idle = self._capture_idle_timeout()
        self._learn_instruction.set(
            f"Captured {count}. Press again or wait {idle:.1f}s to finish."
        )

    def _capture_idle_timeout(self) -> float:
        try:
            value = float(self._capture_idle.get())
        except (TypeError, ValueError):
            value = 2.0
        return max(0.5, min(value, 10.0))

    def _format_capture_list_entry(self, capture: dict[str, object]) -> str:
        name = str(capture.get("name") or "Unknown")
        signal_type = str(capture.get("signal_type") or "parsed")
        protocol = str(capture.get("protocol") or "Unknown")
        command = capture.get("command")
        if signal_type == "raw":
            data = capture.get("data") or []
            return f"{name} | RAW | {len(data)} samples"
        return f"{name} | {protocol} | {command}"

    def _format_capture_detail(self, capture: dict[str, object]) -> str:
        signal_type = str(capture.get("signal_type") or "parsed")
        if signal_type == "raw":
            data = capture.get("data") or []
            frequency = capture.get("frequency")
            duty_cycle = capture.get("duty_cycle")
            detail = f"Raw signal | Samples: {len(data)}"
            if frequency:
                detail += f" | Carrier: {frequency} Hz"
            if duty_cycle is not None:
                detail += f" | Duty: {duty_cycle:.2f}"
            return detail
        return (
            f"Protocol: {capture.get('protocol')} | "
            f"Address: {capture.get('address')} | "
            f"Command: {capture.get('command')}"
        )

    def _aggregate_capture(self, mode: str) -> Optional[dict[str, object]]:
        if not self._captures:
            return None
        raw_entries = []
        for capture in self._captures:
            raw_data = capture.get("raw_burst") or capture.get("raw_data") or capture.get("data")
            if raw_data:
                raw_entries.append((capture, list(raw_data)))
        if raw_entries:
            trimmed = self._trim_raw_entries(raw_entries)
            baseline = self._aggregate_raw_baseline(trimmed, mode)
            if baseline is None:
                return None
            if mode == "Best":
                best = self._select_best_raw(trimmed, baseline)
                if best:
                    return best
            frequency, duty_cycle = self._select_carrier(raw_entries)
            return {
                "name": f"Aggregate {mode}",
                "signal_type": "raw",
                "protocol": "RAW",
                "address": None,
                "command": None,
                "scancode": None,
                "source": "aggregate",
                "frequency": frequency,
                "duty_cycle": duty_cycle,
                "data": baseline,
                "raw_data": baseline,
                "raw_burst": baseline,
            }
        parsed = self._aggregate_parsed()
        return parsed

    def _aggregate_parsed(self) -> Optional[dict[str, object]]:
        parsed = [capture for capture in self._captures if capture.get("signal_type") != "raw"]
        if not parsed:
            return None
        protocol = self._majority_value([cap.get("protocol") for cap in parsed])
        address = self._majority_value([cap.get("address") for cap in parsed])
        command = self._majority_value([cap.get("command") for cap in parsed])
        return {
            "name": "Aggregate Parsed",
            "signal_type": "parsed",
            "protocol": protocol,
            "address": address,
            "command": command,
            "scancode": None,
            "source": "aggregate",
            "frequency": None,
            "duty_cycle": None,
            "data": None,
        }

    def _majority_value(self, values: list[object]) -> Optional[object]:
        counts: dict[object, int] = {}
        for value in values:
            if value is None:
                continue
            counts[value] = counts.get(value, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    def _trim_raw_entries(
        self, entries: list[tuple[dict[str, object], list[int]]]
    ) -> list[tuple[dict[str, object], list[int]]]:
        lengths = [len(data) for _, data in entries if data]
        if not lengths:
            return []
        min_len = min(lengths)
        trimmed = []
        for capture, data in entries:
            if len(data) >= min_len:
                trimmed.append((capture, data[:min_len]))
        return trimmed

    def _aggregate_raw_baseline(
        self, entries: list[tuple[dict[str, object], list[int]]], mode: str
    ) -> Optional[list[int]]:
        if not entries:
            return None
        samples = [data for _, data in entries]
        if not samples:
            return None
        length = len(samples[0])
        baseline: list[int] = []
        for idx in range(length):
            column = [row[idx] for row in samples]
            if mode == "Mean":
                baseline.append(int(sum(column) / len(column)))
            else:
                baseline.append(self._median_int(column))
        return baseline

    def _select_best_raw(
        self,
        entries: list[tuple[dict[str, object], list[int]]],
        baseline: list[int],
    ) -> Optional[dict[str, object]]:
        if not entries or not baseline:
            return None
        best_capture = None
        best_score = None
        for capture, data in entries:
            score = sum(abs(a - b) for a, b in zip(data, baseline))
            if best_score is None or score < best_score:
                best_score = score
                best_capture = capture
        return best_capture

    def _select_carrier(
        self, entries: list[tuple[dict[str, object], list[int]]]
    ) -> tuple[Optional[int], Optional[float]]:
        frequencies = [cap.get("raw_frequency") or cap.get("frequency") for cap, _ in entries]
        duties = [cap.get("raw_duty_cycle") or cap.get("duty_cycle") for cap, _ in entries]
        frequency = self._majority_value([value for value in frequencies if value])
        duty = self._majority_value([value for value in duties if value is not None])
        return frequency, duty

    def _median_int(self, values: list[int]) -> int:
        if not values:
            return 0
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return int(ordered[mid])
        return int((ordered[mid - 1] + ordered[mid]) / 2)

    def _aggregate_detail_line(self) -> str:
        raw_entries = []
        for capture in self._captures:
            raw_data = capture.get("raw_burst") or capture.get("raw_data") or capture.get("data")
            if raw_data:
                raw_entries.append(list(raw_data))
        if len(raw_entries) < 2:
            return "Aggregate requires at least 2 raw captures."
        min_len = min(len(data) for data in raw_entries)
        trimmed = [data[:min_len] for data in raw_entries]
        if not trimmed:
            return "Aggregate requires raw captures."
        std_values = []
        for idx in range(min_len):
            column = [row[idx] for row in trimmed]
            mean = sum(column) / len(column)
            variance = sum((value - mean) ** 2 for value in column) / len(column)
            std_values.append(math.sqrt(variance))
        avg_std = sum(std_values) / len(std_values) if std_values else 0.0
        accuracy = self._accuracy_from_std(avg_std)
        return f"Aggregate deviation: {avg_std:.1f} us | Likely accuracy: {accuracy:.0f}%"

    def _accuracy_from_std(self, avg_std: float) -> float:
        good = 150.0
        poor = 800.0
        if avg_std <= good:
            return 100.0
        if avg_std >= poor:
            return 0.0
        return 100.0 * (poor - avg_std) / (poor - good)

    def _send_learned_signal(self) -> None:
        capture = self._selected_capture()
        if not capture:
            messagebox.showinfo("Learn Remote", "No captured signal to send.")
            return
        self._app.log_feature("IR", "Learn send captured signal")
        signal_type = str(capture.get("signal_type") or "parsed")
        if signal_type == "raw":
            success, message = self._client.send_raw(
                capture.get("frequency"),
                capture.get("duty_cycle"),
                capture.get("data"),
            )
            if not success:
                messagebox.showerror("Learn Remote", message)
            else:
                self._set_status("Sent raw signal.")
            return
        self._send_parsed_signal(
            str(capture.get("protocol") or ""),
            capture.get("address"),
            capture.get("command"),
            "Learn Remote",
        )

    def _send_raw_learned_signal(self) -> None:
        capture = self._selected_capture()
        if not capture:
            messagebox.showinfo("Learn Remote", "No captured signal to send.")
            return
        raw_full = capture.get("raw_data") or capture.get("data")
        raw_burst = capture.get("raw_burst")
        raw_data = raw_burst or raw_full
        protocol = str(capture.get("protocol") or "")
        frequency = capture.get("raw_frequency") or capture.get("frequency")
        duty_cycle = capture.get("raw_duty_cycle") or capture.get("duty_cycle")
        if not frequency or duty_cycle is None:
            frequency, duty_cycle = self._default_carrier(protocol)
        if not raw_data:
            messagebox.showinfo("Learn Remote", "No raw signal data available.")
            return
        self._app.log_feature("IR", "Learn send raw signal")
        success, message = self._client.send_raw(frequency, duty_cycle, raw_data)
        if not success and raw_full and raw_full is not raw_data:
            self._app.log_feature("IR", "Learn raw fallback to full capture")
            success, message = self._client.send_raw(
                frequency,
                duty_cycle,
                raw_full,
            )
        if not success:
            messagebox.showerror("Learn Remote", message)
        else:
            self._set_status("Sent raw signal.")

    def _send_decoded_learned_signal(self) -> None:
        capture = self._selected_capture()
        if not capture:
            messagebox.showinfo("Learn Remote", "No captured signal to send.")
            return
        parsed = self._decode_capture_for_send(capture)
        if not parsed:
            messagebox.showerror(
                "Learn Remote", "Unable to decode a parsed signal from this capture."
            )
            return
        protocol, address, command = parsed
        self._app.log_feature("IR", "Learn send decoded signal")
        self._send_parsed_signal(protocol, address, command, "Learn Remote")

    def _save_learned_signal(self) -> None:
        capture = self._selected_capture()
        if not capture:
            messagebox.showinfo("Learn Remote", "No captured signal to save.")
            return
        self._app.log_feature("IR", "Learn save captured signal")
        device = simpledialog.askstring("Device Name", "Enter the device name:")
        if not device:
            return
        button_name = simpledialog.askstring("Button Name", "Enter the button name:")
        if not button_name:
            return
        signals = self._ir_library.load_remote(device) or []
        signal_type = str(capture.get("signal_type") or "parsed")
        raw_burst = capture.get("raw_burst") or capture.get("data")
        raw_full = capture.get("raw_data")
        raw_frequency = capture.get("raw_frequency") or capture.get("frequency")
        raw_duty = capture.get("raw_duty_cycle") or capture.get("duty_cycle")
        if not raw_frequency or raw_duty is None:
            raw_frequency, raw_duty = self._default_carrier(str(capture.get("protocol") or ""))
        if signal_type == "raw":
            signal = self._flipper_signal(
                name=button_name,
                signal_type="raw",
                frequency=raw_frequency,
                duty_cycle=raw_duty,
                data=raw_burst,
            )
        else:
            signal = self._flipper_signal(
                name=button_name,
                signal_type="parsed",
                protocol=capture.get("protocol"),
                address=capture.get("address"),
                command=capture.get("command"),
            )
        signals.append(signal)
        if signal_type != "raw" and raw_burst:
            raw_variant = self._flipper_signal(
                name=f"{button_name} (raw)",
                signal_type="raw",
                frequency=raw_frequency,
                duty_cycle=raw_duty,
                data=raw_burst,
            )
            signals.append(raw_variant)
        self._ir_library.save_remote_signals(device, signals)
        self._refresh_saved_remotes()
        self._select_saved_remote(device)
        messagebox.showinfo("Learn Remote", f"Saved {button_name} to {device}.")

    def _save_decoded_signal(self) -> None:
        capture = self._selected_capture()
        if not capture:
            messagebox.showinfo("Learn Remote", "No captured signal to save.")
            return
        parsed = self._decode_capture_for_send(capture)
        if not parsed:
            messagebox.showerror(
                "Learn Remote", "Unable to decode a parsed signal from this capture."
            )
            return
        protocol, address, command = parsed
        device = simpledialog.askstring("Device Name", "Enter the device name:")
        if not device:
            return
        button_name = simpledialog.askstring("Button Name", "Enter the button name:")
        if not button_name:
            return
        signals = self._ir_library.load_remote(device) or []
        raw_burst = capture.get("raw_burst") or capture.get("data")
        raw_frequency = capture.get("raw_frequency") or capture.get("frequency")
        raw_duty = capture.get("raw_duty_cycle") or capture.get("duty_cycle")
        if not raw_frequency or raw_duty is None:
            raw_frequency, raw_duty = self._default_carrier(str(protocol or ""))
        decoded_signal = self._flipper_signal(
            name=button_name,
            signal_type="parsed",
            protocol=protocol,
            address=address,
            command=command,
        )
        signals.append(decoded_signal)
        if raw_burst:
            raw_variant = self._flipper_signal(
                name=f"{button_name} (raw)",
                signal_type="raw",
                frequency=raw_frequency,
                duty_cycle=raw_duty,
                data=raw_burst,
            )
            signals.append(raw_variant)
        self._ir_library.save_remote_signals(device, signals)
        self._refresh_saved_remotes()
        self._select_saved_remote(device)
        messagebox.showinfo("Learn Remote", f"Saved {button_name} to {device}.")

    def _decode_capture_for_send(
        self, capture: dict[str, object]
    ) -> Optional[tuple[str, str, str]]:
        signal_type = str(capture.get("signal_type") or "parsed")
        if signal_type != "raw":
            protocol = str(capture.get("protocol") or "")
            address = str(capture.get("address") or "")
            command = str(capture.get("command") or "")
            if protocol and address and command:
                return protocol, address, command
        raw_data = capture.get("raw_burst") or capture.get("raw_data") or capture.get("data")
        if not raw_data:
            return None
        decoded = self._decode_raw_timings(raw_data)
        if not decoded:
            return None
        return decoded.protocol, decoded.address, decoded.command

    def _refresh_saved_remotes(self) -> None:
        self._saved_remotes = [remote.name for remote in self._ir_library.list_remotes()]
        if hasattr(self, "_saved_remote_list"):
            for item in self._saved_remote_list.get_children():
                self._saved_remote_list.delete(item)
            self._saved_tree_nodes.clear()
            self._saved_remote_items.clear()
            groups = set()
            for remote in self._saved_remotes:
                if "/" in remote:
                    groups.add(remote.split("/", 1)[0])
                else:
                    groups.add("Ungrouped")
            self._saved_groups = ["All", *sorted(groups)]
            if hasattr(self, "_saved_group_picker"):
                self._saved_group_picker.configure(values=self._saved_groups)
                if self._saved_group.get() not in self._saved_groups:
                    self._saved_group.set("All")
            selected_group = self._saved_group.get()
            for remote in self._saved_remotes:
                if "/" in remote:
                    group, name = remote.split("/", 1)
                else:
                    group, name = "Ungrouped", remote
                if selected_group not in {"All", group}:
                    continue
                item_id = self._saved_remote_list.insert("", tk.END, text=name)
                self._saved_remote_items[item_id] = remote
        self._saved_detail.set("Select a remote")
        self._saved_buttons = []
        self._selected_saved_remote_signals = []
        if hasattr(self, "_saved_button_list"):
            for item in self._saved_button_list.get_children():
                self._saved_button_list.delete(item)
        self._saved_button_detail.set("Select a button")
        self._render_saved_button_grid()

    def _select_saved_remote(self, name: str) -> None:
        if name not in self._saved_remotes:
            return
        if hasattr(self, "_saved_remote_list"):
            for item, remote in self._saved_remote_items.items():
                if remote == name:
                    self._saved_remote_list.selection_set(item)
                    self._saved_remote_list.see(item)
                    self._saved_remote_list.event_generate("<<TreeviewSelect>>")
                    break

    def _on_saved_remote_select(self, event: tk.Event) -> None:
        selection = self._saved_remote_list.selection()
        if not selection:
            return
        item = selection[0]
        if item not in self._saved_remote_items:
            return
        name = self._saved_remote_items[item]
        signals = self._ir_library.load_remote(name) or []
        self._selected_saved_remote_signals = signals
        self._saved_buttons = [signal.name for signal in signals]
        self._saved_detail.set(f"{name} ({len(signals)} buttons)")
        for item in self._saved_button_list.get_children():
            self._saved_button_list.delete(item)
        for button in self._saved_buttons:
            self._saved_button_list.insert("", tk.END, text=button)
        self._saved_button_detail.set("Select a button")
        self._render_saved_button_grid()

    def _on_saved_button_select(self, event: tk.Event) -> None:
        selection = self._saved_button_list.selection()
        if not selection:
            return
        index = self._saved_button_list.index(selection[0])
        signal = self._selected_saved_remote_signals[index]
        if signal.signal_type == "raw":
            count = len(signal.data) if signal.data else 0
            self._saved_button_detail.set(f"{signal.name} | RAW | {count} samples")
        else:
            self._saved_button_detail.set(
                f"{signal.name} | {signal.protocol} | {signal.address} | {signal.command}"
            )

    def _render_saved_button_grid(self) -> None:
        for child in self._saved_button_grid.winfo_children():
            child.destroy()
        if not self._selected_saved_remote_signals:
            return
        columns = 3
        for idx, signal in enumerate(self._selected_saved_remote_signals):
            row = idx // columns
            col = idx % columns
            ttk.Button(
                self._saved_button_grid,
                text=signal.name,
                style="Small.TButton",
                command=lambda payload=signal: self._send_saved_button(payload),
            ).grid(row=row, column=col, padx=4, pady=4, sticky="ew")
        for col in range(columns):
            self._saved_button_grid.columnconfigure(col, weight=1)

    def _send_saved_button(self, signal: "FlipperIRSignal") -> None:
        if signal.signal_type == "raw":
            data_count = len(signal.data) if signal.data else 0
            self._app.log_feature(
                "IR",
                (
                    "Send saved raw signal"
                    f" label={signal.name} frequency={signal.frequency}"
                    f" duty_cycle={signal.duty_cycle} data_count={data_count}"
                ),
            )
            if not signal.data:
                messagebox.showerror(
                    "Saved Remotes", "Missing raw signal data to send."
                )
                return
            frequency = signal.frequency
            duty_cycle = signal.duty_cycle
            if not frequency or duty_cycle is None:
                frequency, duty_cycle = self._default_carrier("")
            success, message = self._client.send_raw(
                frequency, duty_cycle, signal.data
            )
            if not success:
                messagebox.showerror("Saved Remotes", message)
            else:
                self._set_status(f"Sent {signal.name}.")
            return
        self._app.log_feature(
            "IR",
            (
                "Send saved parsed signal"
                f" label={signal.name} protocol={signal.protocol}"
                f" address={signal.address} command={signal.command}"
            ),
        )
        self._send_parsed_signal(
            signal.protocol,
            signal.address,
            signal.command,
            "Saved Remotes",
            signal.name,
        )

    def _on_saved_group_change(self, _event: tk.Event) -> None:
        self._refresh_saved_remotes()

    def _default_carrier(self, protocol: str) -> tuple[int, float]:
        key = protocol.strip().upper()
        if key in {"SIRC", "SIRC15", "SIRC20"}:
            return 40000, 0.33
        if key in {"RC5", "RC6"}:
            return 36000, 0.33
        return 38000, 0.33
    def _open_saved_editor(self) -> None:
        selection = self._saved_remote_list.selection()
        if not selection:
            messagebox.showinfo("Saved Remotes", "Select a remote to edit.")
            return
        item = selection[0]
        remote_name = self._saved_remote_list.item(item, "text")

        editor = tk.Toplevel(self)
        editor.title(f"Edit {remote_name}")
        editor.configure(bg=self._app._colors["bg"])

        actions = ttk.Frame(editor, style="Card.TFrame")
        actions.pack(padx=12, pady=12, fill=tk.BOTH, expand=True)

        ttk.Button(
            actions,
            text="Add Button",
            style="Secondary.TButton",
            command=lambda: self._editor_add_button(remote_name),
        ).pack(fill=tk.X, pady=4)
        ttk.Button(
            actions,
            text="Rename Button",
            style="Secondary.TButton",
            command=lambda: self._editor_rename_button(remote_name),
        ).pack(fill=tk.X, pady=4)
        ttk.Button(
            actions,
            text="Delete Button",
            style="Secondary.TButton",
            command=lambda: self._editor_delete_button(remote_name),
        ).pack(fill=tk.X, pady=4)
        ttk.Button(
            actions,
            text="Rename Remote",
            style="Secondary.TButton",
            command=lambda: self._editor_rename_remote(remote_name),
        ).pack(fill=tk.X, pady=4)
        ttk.Button(
            actions,
            text="Delete Remote",
            style="Secondary.TButton",
            command=lambda: self._editor_delete_remote(remote_name),
        ).pack(fill=tk.X, pady=4)

    def _editor_add_button(self, remote_name: str) -> None:
        capture = self._selected_capture()
        if not capture:
            messagebox.showinfo("Add Button", "Capture a signal first.")
            return
        button_name = simpledialog.askstring("Button Name", "Enter the button name:")
        if not button_name:
            return
        signals = self._ir_library.load_remote(remote_name) or []
        signals.append(
            self._flipper_signal(
                name=button_name,
                signal_type="parsed",
                protocol=capture["protocol"],
                address=capture["address"],
                command=capture["command"],
            )
        )
        self._ir_library.save_remote_signals(remote_name, signals)
        self._refresh_saved_remotes()
        self._select_saved_remote(remote_name)

    def _editor_rename_button(self, remote_name: str) -> None:
        selection = self._saved_button_list.selection()
        if not selection:
            messagebox.showinfo("Rename Button", "Select a button to rename.")
            return
        index = self._saved_button_list.index(selection[0])
        signal = self._selected_saved_remote_signals[index]
        new_name = simpledialog.askstring("Rename Button", "Enter new button name:")
        if not new_name:
            return
        signals = list(self._selected_saved_remote_signals)
        signals[index] = self._flipper_signal(
            name=new_name,
            signal_type=signal.signal_type,
            protocol=signal.protocol,
            address=signal.address,
            command=signal.command,
        )
        self._ir_library.save_remote_signals(remote_name, signals)
        self._refresh_saved_remotes()
        self._select_saved_remote(remote_name)

    def _editor_delete_button(self, remote_name: str) -> None:
        selection = self._saved_button_list.selection()
        if not selection:
            messagebox.showinfo("Delete Button", "Select a button to delete.")
            return
        index = self._saved_button_list.index(selection[0])
        signal = self._selected_saved_remote_signals[index]
        if not messagebox.askyesno("Delete Button", f"Delete {signal.name}?"):
            return
        signals = list(self._selected_saved_remote_signals)
        signals.pop(index)
        self._ir_library.save_remote_signals(remote_name, signals)
        self._refresh_saved_remotes()
        self._select_saved_remote(remote_name)

    def _editor_rename_remote(self, remote_name: str) -> None:
        new_name = simpledialog.askstring("Rename Remote", "Enter new remote name:")
        if not new_name:
            return
        self._ir_library.rename_remote(remote_name, new_name)
        self._refresh_saved_remotes()
        self._select_saved_remote(new_name)

    def _editor_delete_remote(self, remote_name: str) -> None:
        if not messagebox.askyesno("Delete Remote", f"Delete {remote_name}?"):
            return
        self._ir_library.delete_remote(remote_name)
        self._refresh_saved_remotes()

    def _on_universal_device_select(self, event: tk.Event) -> None:
        if self._universal_scan_thread and self._universal_scan_thread.is_alive():
            return
        selection = self._universal_device_list.selection()
        if not selection:
            return
        item = selection[0]
        device = self._universal_device_list.item(item, "text")
        self._universal_device.set(device)
        self._render_universal_buttons(device)
        self._universal_selected_button.set("Select a button")
        self._selected_universal_button = None
        self._universal_model.set("-")
        self._universal_notice.set("")
        self._universal_progress_value.set(0.0)
        self._universal_progress_bar.configure(maximum=1.0)

    def _render_universal_buttons(self, device: str) -> None:
        for child in self._universal_button_grid.winfo_children():
            child.destroy()
        self._universal_buttons.clear()
        buttons = self._universal_layouts.get(device, [])
        columns = 3
        for idx, label in enumerate(buttons):
            row = idx // columns
            col = idx % columns
            button = ttk.Button(
                self._universal_button_grid,
                text=label,
                style="Small.TButton",
                command=lambda name=label: self._select_universal_button(name),
            )
            button.grid(row=row, column=col, padx=4, pady=4, sticky="ew")
            self._universal_buttons[label] = button
        for col in range(columns):
            self._universal_button_grid.columnconfigure(col, weight=1)

    def _select_universal_button(self, label: str) -> None:
        if self._universal_scan_thread and self._universal_scan_thread.is_alive():
            return
        self._universal_selected_button.set(label)
        self._universal_notice.set("")
        self._highlight_universal_button(label)
        self._universal_model.set("-")
        self._universal_progress_value.set(0.0)
        self._universal_progress_bar.configure(maximum=1.0)

    def _highlight_universal_button(self, label: str) -> None:
        if self._selected_universal_button and self._selected_universal_button in self._universal_buttons:
            self._universal_buttons[self._selected_universal_button].configure(
                style="Small.TButton"
            )
        self._selected_universal_button = label
        if label in self._universal_buttons:
            self._universal_buttons[label].configure(style="Accent.TButton")

    def _start_universal_scan(self) -> None:
        if self._universal_scan_thread and self._universal_scan_thread.is_alive():
            return
        button_label = self._universal_selected_button.get()
        if not button_label or button_label == "Select a button":
            self._universal_notice.set("Select a button to start.")
            return
        device = self._universal_device.get()
        signals = self._load_universal_signals(device)
        target = self._normalize_button_name(button_label)
        filtered = [
            item
            for item in signals
            if self._normalize_button_name(item.signal.name) == target
        ]
        if not filtered:
            messagebox.showinfo("Universal Remotes", f"No {button_label} signals found.")
            return
        self._universal_scan_stop.clear()
        self._set_universal_controls_enabled(False)
        self._universal_scan_thread = threading.Thread(
            target=self._run_universal_scan,
            args=(filtered, button_label),
            daemon=True,
        )
        self._universal_scan_thread.start()

    def _stop_universal_scan(self) -> None:
        if self._universal_scan_thread and self._universal_scan_thread.is_alive():
            self._universal_scan_stop.set()

    def _run_universal_scan(self, signals: list["FlipperIRLibrarySignal"], label: str) -> None:
        total = len(signals)
        for idx, signal in enumerate(signals, start=1):
            if self._universal_scan_stop.is_set():
                break
            self._app.after(
                0,
                lambda current=signal, count=idx: self._update_universal_progress(
                    label, current, count, total
                ),
            )
            self._send_universal_signal_background(signal.signal, label)
            time.sleep(self._universal_delay)
        self._app.after(0, self._finish_universal_scan)

    def _finish_universal_scan(self) -> None:
        self._universal_progress_value.set(0.0)
        self._universal_progress_bar.configure(maximum=1.0)
        self._set_universal_controls_enabled(True)

    def _set_universal_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        try:
            if enabled:
                self._universal_device_list.state(("!disabled",))
            else:
                self._universal_device_list.state(("disabled",))
        except tk.TclError:
            pass
        for label, button in self._universal_buttons.items():
            target_state = state
            if not enabled and label == self._selected_universal_button:
                target_state = "normal"
            try:
                button.configure(state=target_state)
            except tk.TclError:
                continue

    def _update_universal_progress(
        self, label: str, signal: "FlipperIRLibrarySignal", count: int, total: int
    ) -> None:
        self._universal_selected_button.set(label)
        model = signal.model or "Unknown"
        self._universal_model.set(model)
        self._universal_progress_bar.configure(maximum=total)
        self._universal_progress_value.set(float(count))

    def _send_universal_signal_background(
        self, signal: "FlipperIRSignal", label: str
    ) -> None:
        if signal.signal_type == "parsed":
            self._app.log_feature(
                "IR",
                (
                    "Send parsed signal"
                    f" label={label} protocol={signal.protocol}"
                    f" address={signal.address} command={signal.command}"
                ),
            )
            success, message = self._client.send_parsed(
                signal.protocol or "", signal.address, signal.command
            )
        elif signal.signal_type == "raw":
            data_count = len(signal.data) if signal.data else 0
            self._app.log_feature(
                "IR",
                (
                    "Send raw signal"
                    f" label={label} frequency={signal.frequency}"
                    f" duty_cycle={signal.duty_cycle} data_count={data_count}"
                ),
            )
            success, message = self._client.send_raw(
                signal.frequency, signal.duty_cycle, signal.data
            )
        else:
            success = False
            message = f"Unsupported signal type: {signal.signal_type}."

        def update_status() -> None:
            if success:
                self._set_status(f"Sent {label}.")
                return
            self._universal_notice.set(message)
            self._set_status(message)
        self._app.after(0, update_status)

    def _send_parsed_signal(
        self,
        protocol: Optional[str],
        address: Optional[str],
        command: Optional[str],
        context: str,
        label: Optional[str] = None,
    ) -> None:
        if not protocol or not address or not command:
            messagebox.showerror(context, "Missing signal data to send.")
            return
        self._app.log_feature(
            "IR",
            (
                "Send parsed signal"
                f" label={label or protocol} protocol={protocol}"
                f" address={address} command={command}"
            ),
        )
        success, message = self._client.send_parsed(protocol, address, command)
        if success:
            name = label or protocol
            self._set_status(f"Sent {name}.")
            return
        messagebox.showerror(context, message)
        self._set_status(message)

    def _normalize_button_name(self, name: str) -> str:
        normalized = name.strip().lower().replace(" ", "_")
        normalized = normalized.replace("+", "_up").replace("-", "_dn")
        mapping = {
            "vol_up": "vol_up",
            "vol_dn": "vol_dn",
            "ch_up": "ch_next",
            "ch_dn": "ch_prev",
            "temp_up": "temp_up",
            "temp_dn": "temp_dn",
            "bright_up": "bright_up",
            "bright_dn": "bright_dn",
            "speed_up": "speed_up",
            "speed_dn": "speed_dn",
            "color_up": "color_up",
            "color_dn": "color_dn",
            "bass_up": "bass_up",
            "bass_dn": "bass_dn",
            "treble_up": "treble_up",
            "treble_dn": "treble_dn",
            "keystone_up": "keystone_up",
            "keystone_dn": "keystone_dn",
        }
        return mapping.get(normalized, normalized)

    def _load_universal_signals(self, device: str) -> list["FlipperIRLibrarySignal"]:
        file_map = {
            "TV": "tv.ir",
            "Audio System": "audio.ir",
            "Projector": "projector.ir",
            "Air Conditioner": "ac.ir",
            "LED": "led.ir",
        }
        filename = file_map.get(device, f"{device.lower().replace(' ', '_')}.ir")
        paths = [
            self._data_dir / "ir" / "universal" / filename,
            self._universal_dir / filename,
        ]
        for path in paths:
            if path.exists():
                text = path.read_text(encoding="utf-8")
                return self._parse_library_signals(text)
        return []

    def _save_universal_delay(self) -> None:
        value = float(self._delay_value.get())
        value = max(0.0, min(4.0, value))
        value = round(value, 1)
        self._universal_delay = value
        self._store_universal_delay(value)
        self._delay_value.set(value)
        self._delay_label.set(f"{value:.1f} s")

    def _update_delay_label(self, _value: str) -> None:
        value = round(float(self._delay_value.get()), 1)
        self._delay_label.set(f"{value:.1f} s")

    def _load_universal_delay(self) -> float:
        if not self._ir_settings_path.exists():
            return 0.5
        try:
            payload = json.loads(self._ir_settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0.5
        return float(payload.get("universal_delay", 0.5))

    def _store_universal_delay(self, value: float) -> None:
        payload = self._app._load_ir_settings()
        payload["universal_delay"] = value
        self._app._save_ir_settings(payload)

    def _open_ir_pin_settings(self) -> None:
        self._app.show_section("System")
        system_screen = self._app._screens.get("System")
        if system_screen and hasattr(system_screen, "show_pins_tab"):
            system_screen.show_pins_tab()

    def set_rx_device(self, device: str) -> None:
        self._client.set_rx_device(device)


class WiFiScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="WiFi", style="Title.TLabel").pack(pady=10)
        ttk.Label(
            self,
            text="WiFi scan/connect tools will appear here.",
            style="Body.TLabel",
        ).pack(pady=6)


class BluetoothScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        from bluetooth.bluez_client import BlueZClient

        self._client = BlueZClient()
        self._status = tk.StringVar(value="")
        self._selected_name = tk.StringVar(value="No device selected")
        self._selected_address = tk.StringVar(value="")
        self._selected_type = tk.StringVar(value="")

        self._bt_content = ttk.Frame(self, style="App.TFrame")
        self._bt_content.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        self._target_section = ttk.Frame(self._bt_content, style="Card.TFrame")
        self._target_section.pack(fill=tk.X, pady=6)
        self._build_target_section()

        self._bt_screen_host = ttk.Frame(self._bt_content, style="App.TFrame")
        self._bt_screen_host.pack(fill=tk.BOTH, expand=True)

        self._bt_screens = {}
        self._current_bt_screen: Optional[tk.Frame] = None

        self._add_bt_screen("Discovery", self._build_discovery_screen())
        self._add_bt_screen("Pairing", self._build_pairing_screen())
        self._add_bt_screen("Connection", self._build_connection_screen())
        self._add_bt_screen("Audio", self._build_audio_screen())
        self._add_bt_screen("Library", self._build_library_screen())
        self._add_bt_screen("Shortcuts", self._build_shortcuts_screen())

        self._show_bt_screen("Discovery")

    def _add_bt_screen(self, name: str, frame: tk.Frame) -> None:
        self._bt_screens[name] = frame

    def _show_bt_screen(self, name: str) -> None:
        if self._current_bt_screen:
            self._current_bt_screen.pack_forget()
        self._current_bt_screen = self._bt_screens[name]
        self._current_bt_screen.pack(fill=tk.BOTH, expand=True)

    def show_subscreen(self, name: str) -> None:
        self._show_bt_screen(name)

    def _build_target_section(self) -> None:
        self._device_entry = ttk.Entry(self._target_section, style="App.TEntry")
        self._device_entry.insert(0, "AA:BB:CC:DD:EE:FF")
        self._device_entry.pack(fill=tk.X, padx=8, pady=(8, 8))

        self._device_list = ttk.Treeview(
            self._target_section,
            columns=("name", "address", "type"),
            show="headings",
            height=4,
        )
        self._device_list.heading("name", text="Device Name")
        self._device_list.heading("address", text="Address")
        self._device_list.heading("type", text="Type")
        self._device_list.column("name", width=180, anchor="w")
        self._device_list.column("address", width=120, anchor="w")
        self._device_list.column("type", width=80, anchor="w")
        self._device_list.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._device_list.bind("<<TreeviewSelect>>", self._on_device_select)

    def _build_discovery_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._bt_screen_host, style="App.TFrame")
        self._build_button_card(
            frame,
            title="",
            buttons=[
                ("Scan Devices", self._scan_devices),
                ("Known Devices", self._list_known),
                ("Power On", self._power_on),
                ("Power Off", self._power_off),
            ],
        )
        details = ttk.Frame(frame, style="Card.TFrame")
        details.pack(fill=tk.X, pady=8)
        ttk.Label(details, textvariable=self._selected_name, style="Body.TLabel").pack(pady=2)
        ttk.Label(details, textvariable=self._selected_address, style="Muted.TLabel").pack(
            pady=(0, 6)
        )
        ttk.Label(details, textvariable=self._selected_type, style="Muted.TLabel").pack(pady=(0, 6))
        self._build_button_card(
            details,
            title="",
            buttons=[
                ("Pair", self._pair_device),
                ("Trust", self._trust_device),
                ("Connect", self._connect_audio),
                ("Forget", self._forget_device),
            ],
        )
        return frame

    def _build_pairing_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._bt_screen_host, style="App.TFrame")
        self._build_button_card(
            frame,
            title="",
            buttons=[
                ("Pair", self._pair_device),
                ("Trust", self._trust_device),
                ("Forget", self._forget_device),
            ],
        )
        return frame

    def _build_connection_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._bt_screen_host, style="App.TFrame")
        self._build_button_card(
            frame,
            title="",
            buttons=[
                ("Connect", self._connect_audio),
                ("Disconnect", self._disconnect_audio),
            ],
        )
        return frame

    def _build_audio_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._bt_screen_host, style="App.TFrame")
        self._build_button_card(
            frame,
            title="",
            buttons=[
                ("Auto Pair + Play", self._auto_pair_play),
                ("Test Audio", lambda: self._set_status("Playing test audio.")),
            ],
        )
        return frame

    def _build_library_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._bt_screen_host, style="App.TFrame")
        self._build_button_card(
            frame,
            title="",
            buttons=[
                ("Save Device", lambda: self._set_status("Saving device profile.")),
                ("Paired List", self._list_paired),
            ],
        )
        return frame

    def _build_shortcuts_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._bt_screen_host, style="App.TFrame")
        self._build_button_card(
            frame,
            title="",
            buttons=[
                ("Last Device", lambda: self._set_status("Connecting last device.")),
                ("Clear List", self._clear_devices),
            ],
        )
        return frame

    def _build_button_card(
        self, master: ttk.Frame, title: str, buttons: list[tuple[str, Callable[[], None]]]
    ) -> None:
        card = ttk.Frame(master, style="Card.TFrame")
        card.pack(fill=tk.X, pady=8)
        if title:
            ttk.Label(card, text=title, style="Status.TLabel").pack(pady=(8, 4))
        button_row = ttk.Frame(card, style="Card.TFrame")
        button_row.pack(fill=tk.X, padx=8, pady=8)
        for index, (label, command) in enumerate(buttons):
            button_row.columnconfigure(index, weight=1)
            ttk.Button(
                button_row, text=label, style="Small.TButton", command=command
            ).grid(row=0, column=index, padx=4, sticky="ew")

    def _set_status(self, message: str) -> None:
        self._status.set(message)

    def _device_address(self) -> str:
        return self._device_entry.get().strip()

    def _on_device_select(self, event: tk.Event) -> None:
        selection = self._device_list.selection()
        if not selection:
            return
        item = selection[0]
        name, address, device_type = self._device_list.item(item, "values")
        self._device_entry.delete(0, tk.END)
        self._device_entry.insert(0, address)
        self._selected_name.set(name or "Unknown device")
        self._selected_address.set(address)
        self._selected_type.set(device_type or "Unknown")

    def _scan_devices(self) -> None:
        self._set_status("Scanning for devices...")
        devices = self._client.scan()
        for item in self._device_list.get_children():
            self._device_list.delete(item)
        for device in devices:
            device_type = self._client.device_type(device.address)
            self._device_list.insert(
                "", tk.END, values=(device.name, device.address, device_type)
            )
        self._set_status(f"Found {len(devices)} device(s).")

        if devices:
            primary = devices[0]
            self._set_status(
                f"Found {len(devices)} device(s). Nearest: {primary.name} ({primary.address})."
            )
            self._selected_name.set(primary.name)
            self._selected_address.set(primary.address)
            self._selected_type.set(self._client.device_type(primary.address))

    def _list_known(self) -> None:
        devices = self._client.list_paired()
        for item in self._device_list.get_children():
            self._device_list.delete(item)
        for device in devices:
            device_type = self._client.device_type(device.address)
            self._device_list.insert(
                "", tk.END, values=(device.name, device.address, device_type)
            )
        self._set_status("Showing known devices.")
        if devices:
            primary = devices[0]
            self._selected_name.set(primary.name)
            self._selected_address.set(primary.address)
            self._selected_type.set(self._client.device_type(primary.address))

    def _power_on(self) -> None:
        self._client.power_on()
        self._set_status("Bluetooth powered on.")

    def _power_off(self) -> None:
        self._client.power_off()
        self._set_status("Bluetooth powered off.")

    def _pair_device(self) -> None:
        address = self._device_address()
        if not address:
            self._set_status("Enter a device address.")
            return
        self._client.pair(address)
        self._set_status(f"Paired with {address}.")

    def _trust_device(self) -> None:
        address = self._device_address()
        if not address:
            self._set_status("Enter a device address.")
            return
        self._client.trust(address)
        self._set_status(f"Trusted {address}.")

    def _connect_audio(self) -> None:
        address = self._device_address()
        if not address:
            self._set_status("Enter a device address.")
            return
        self._client.connect_a2dp(address)
        self._set_status(f"Connected audio to {address}.")

    def _disconnect_audio(self) -> None:
        address = self._device_address()
        if not address:
            self._set_status("Enter a device address.")
            return
        self._client.disconnect(address)
        self._set_status(f"Disconnected {address}.")

    def _auto_pair_play(self) -> None:
        address = self._device_address()
        if not address:
            self._set_status("Enter a device address.")
            return
        self._client.auto_pair_and_play(address)
        self._set_status(f"Auto paired and connected {address}.")

    def _list_paired(self) -> None:
        devices = self._client.list_paired()
        for item in self._device_list.get_children():
            self._device_list.delete(item)
        for device in devices:
            device_type = self._client.device_type(device.address)
            self._device_list.insert(
                "", tk.END, values=(device.name, device.address, device_type)
            )
        self._set_status("Showing paired devices.")
        if devices:
            primary = devices[0]
            self._selected_name.set(primary.name)
            self._selected_address.set(primary.address)
            self._selected_type.set(self._client.device_type(primary.address))

    def _forget_device(self) -> None:
        address = self._device_address()
        if not address:
            self._set_status("Enter a device address.")
            return
        self._client.remove(address)
        self._set_status(f"Removed {address}.")

    def _clear_devices(self) -> None:
        for item in self._device_list.get_children():
            self._device_list.delete(item)
        self._set_status("Cleared device list.")


class SystemScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._tabs = ttk.Notebook(self)
        self._tabs.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        features_tab = ttk.Frame(self._tabs)
        pins_tab = ttk.Frame(self._tabs)
        diagnostics_tab = ttk.Frame(self._tabs)
        self._tabs.add(features_tab, text="Features")
        self._tabs.add(pins_tab, text="Pins")
        self._tabs.add(diagnostics_tab, text="Diagnostics")

        feature_card = ttk.Frame(features_tab, style="Card.TFrame")
        feature_card.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        ttk.Label(feature_card, text="Main Menu Features", style="Status.TLabel").pack(
            pady=(8, 4)
        )
        self._feature_vars = {
            "Scan": tk.BooleanVar(value=self._app.feature_enabled("Scan")),
            "IR": tk.BooleanVar(value=self._app.feature_enabled("IR")),
            "Bluetooth": tk.BooleanVar(value=self._app.feature_enabled("Bluetooth")),
            "WiFi": tk.BooleanVar(value=self._app.feature_enabled("WiFi")),
            "Proxmark": tk.BooleanVar(value=self._app.feature_enabled("Proxmark")),
        }
        feature_row = ttk.Frame(feature_card, style="Card.TFrame")
        feature_row.pack(fill=tk.X, padx=8, pady=6)
        for index, (label, var) in enumerate(self._feature_vars.items()):
            ttk.Checkbutton(
                feature_row,
                text=label,
                variable=var,
                style="Switch.TCheckbutton",
            ).grid(row=index // 2, column=index % 2, sticky="w", padx=4, pady=4)
        ttk.Label(feature_card, text="Dev", style="Status.TLabel").pack(pady=(4, 4))
        debug_row = ttk.Frame(feature_card, style="Card.TFrame")
        debug_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Checkbutton(
            debug_row,
            text="Debug Window",
            variable=self._app._debug_enabled,
            style="Switch.TCheckbutton",
            command=self._app.toggle_debug_window,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            debug_row,
            text="Log to Files",
            variable=self._app._log_enabled,
            style="Switch.TCheckbutton",
            command=lambda: self._app.set_log_enabled(self._app._log_enabled.get()),
        ).pack(side=tk.LEFT, padx=12)
        ttk.Button(
            feature_card,
            text="Save Features",
            style="Secondary.TButton",
            command=self._save_features,
        ).pack(pady=(0, 8))

        ir_frame = ttk.Frame(pins_tab, style="Card.TFrame")
        ir_frame.pack(pady=12, padx=12, fill=tk.X)
        ttk.Label(ir_frame, text="IR GPIO Pins", style="Status.TLabel").pack(pady=(8, 4))
        pin_row = ttk.Frame(ir_frame, style="Card.TFrame")
        pin_row.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(pin_row, text="TX:", style="Body.TLabel").grid(row=0, column=0, padx=4)
        self._ir_tx_entry = ttk.Entry(pin_row, style="App.TEntry")
        self._ir_tx_entry.insert(0, self._app.ir_tx_pin())
        self._ir_tx_entry.grid(row=0, column=1, padx=4, sticky="ew")
        ttk.Label(pin_row, text="RX:", style="Body.TLabel").grid(row=0, column=2, padx=4)
        self._ir_rx_entry = ttk.Entry(pin_row, style="App.TEntry")
        self._ir_rx_entry.insert(0, self._app.ir_rx_pin())
        self._ir_rx_entry.grid(row=0, column=3, padx=4, sticky="ew")
        pin_row.columnconfigure(1, weight=1)
        pin_row.columnconfigure(3, weight=1)

        device_row = ttk.Frame(ir_frame, style="Card.TFrame")
        device_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(device_row, text="RX Device:", style="Body.TLabel").grid(
            row=0, column=0, padx=4
        )
        self._ir_rx_device_entry = ttk.Entry(device_row, style="App.TEntry")
        self._ir_rx_device_entry.insert(0, self._app.ir_rx_device())
        self._ir_rx_device_entry.grid(row=0, column=1, padx=4, sticky="ew")
        device_row.columnconfigure(1, weight=1)
        ttk.Button(
            ir_frame,
            text="Save IR Pins",
            style="Secondary.TButton",
            command=self._save_ir_pins,
        ).pack(pady=(0, 8))

        boot_card = ttk.Frame(diagnostics_tab, style="Card.TFrame")
        boot_card.pack(pady=12, padx=12, fill=tk.X)
        ttk.Label(
            boot_card, text="Boot IR Diagnostic", style="Status.TLabel"
        ).pack(pady=(8, 4))
        self._boot_diag_status = tk.StringVar(value="Pending boot diagnostic...")
        self._boot_diag_timestamp = tk.StringVar(value="")
        ttk.Label(
            boot_card, textvariable=self._boot_diag_status, style="Body.TLabel"
        ).pack(pady=(0, 2))
        ttk.Label(
            boot_card, textvariable=self._boot_diag_timestamp, style="Muted.TLabel"
        ).pack(pady=(0, 8))

        settings_card = ttk.Frame(diagnostics_tab, style="Card.TFrame")
        settings_card.pack(pady=(0, 12), padx=12, fill=tk.BOTH, expand=True)
        ttk.Label(
            settings_card, text="IR Test (Diagnostics)", style="Status.TLabel"
        ).pack(pady=(8, 4))
        self._ir_diag_status = tk.StringVar(value="Idle")
        self._ir_diag_progress = tk.DoubleVar(value=0.0)
        ttk.Label(
            settings_card, textvariable=self._ir_diag_status, style="Body.TLabel"
        ).pack(pady=(0, 4))
        self._ir_diag_progress_bar = ttk.Progressbar(
            settings_card,
            variable=self._ir_diag_progress,
            maximum=5.0,
            mode="determinate",
        )
        self._ir_diag_progress_bar.pack(fill=tk.X, padx=12, pady=(0, 8))
        ttk.Button(
            settings_card,
            text="Run IR Test",
            style="Secondary.TButton",
            command=self._run_ir_settings_diagnostic,
        ).pack(pady=(0, 8), padx=12, fill=tk.X)
        self._ir_diag_steps = ttk.Treeview(
            settings_card,
            columns=("status", "details"),
            show="tree headings",
            height=6,
        )
        self._ir_diag_steps.heading("status", text="Status")
        self._ir_diag_steps.heading("details", text="Details")
        self._ir_diag_steps.heading("#0", text="Step")
        self._ir_diag_steps.column("#0", width=160, anchor="w")
        self._ir_diag_steps.column("status", width=80, anchor="center")
        self._ir_diag_steps.column("details", width=360, anchor="w")
        self._ir_diag_steps.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        self._ir_diag_step_nodes: dict[str, str] = {}
        self._ir_diag_fixes = tk.StringVar(value="")
        ttk.Label(
            settings_card,
            textvariable=self._ir_diag_fixes,
            style="Muted.TLabel",
            wraplength=420,
            justify=tk.LEFT,
        ).pack(pady=(0, 8), padx=12, anchor="w")
        self.refresh()

    def _save_features(self) -> None:
        flags = {name: var.get() for name, var in self._feature_vars.items()}
        self._app.set_feature_flags(flags)

    def _save_ir_pins(self) -> None:
        tx_pin = self._ir_tx_entry.get().strip() or self._app.ir_tx_pin()
        rx_pin = self._ir_rx_entry.get().strip() or self._app.ir_rx_pin()
        self._app.set_ir_pins(tx_pin, rx_pin)
        rx_device = self._ir_rx_device_entry.get().strip() or self._app.ir_rx_device()
        self._app.set_ir_rx_device(rx_device)

    def show_pins_tab(self) -> None:
        if hasattr(self, "_tabs"):
            self._tabs.select(1)

    def show_diagnostics_tab(self) -> None:
        if hasattr(self, "_tabs"):
            self._tabs.select(2)

    def refresh(self) -> None:
        self._refresh_boot_diagnostic()

    def _refresh_boot_diagnostic(self) -> None:
        result = self._app.ir_boot_diagnostic()
        if not result:
            self._boot_diag_status.set("Pending boot diagnostic...")
            self._boot_diag_timestamp.set("")
            return
        self._boot_diag_status.set(f"Overall status: {result.status}")
        self._boot_diag_timestamp.set(f"Timestamp: {result.timestamp}")

    def _run_ir_settings_diagnostic(self) -> None:
        if hasattr(self, "_ir_diag_thread") and self._ir_diag_thread.is_alive():
            return
        for item in self._ir_diag_steps.get_children():
            self._ir_diag_steps.delete(item)
        self._ir_diag_step_nodes.clear()
        self._ir_diag_status.set("Running IR diagnostics...")
        self._ir_diag_fixes.set("")
        self._ir_diag_progress_bar.configure(maximum=5.0)
        self._ir_diag_progress.set(0.0)

        def prompt(message: str) -> None:
            self._app.after(
                0, lambda: messagebox.showinfo("IR Diagnostic", message, parent=self)
            )

        def progress(step: DiagnosticStepResult, index: int, total: int) -> None:
            self._app.after(
                0, lambda: self._update_ir_diag_step(step, index, total)
            )

        def run_diag() -> None:
            result = self._app.ir_diagnostics().run_settings_diagnostic(
                prompt=prompt, progress=progress
            )
            self._app.after(0, lambda: self._finish_ir_diag(result))

        self._ir_diag_thread = threading.Thread(target=run_diag, daemon=True)
        self._ir_diag_thread.start()

    def _update_ir_diag_step(
        self, step: DiagnosticStepResult, index: int, total: int
    ) -> None:
        node = self._ir_diag_step_nodes.get(step.name)
        if node:
            self._ir_diag_steps.item(node, values=(step.status, step.details))
        else:
            node = self._ir_diag_steps.insert(
                "", tk.END, text=step.name, values=(step.status, step.details)
            )
            self._ir_diag_step_nodes[step.name] = node
        self._ir_diag_progress_bar.configure(maximum=float(total))
        self._ir_diag_progress.set(float(index))
        self._ir_diag_status.set(f"{step.name}: {step.status}")

    def _finish_ir_diag(self, result: DiagnosticResult) -> None:
        self._app._apply_ir_diagnostic_status(result)
        self._app.refresh_home()
        self._ir_diag_status.set(
            f"Overall status: {result.status} | {result.summary_line()}"
        )
        fixes = result.suggested_fixes
        if fixes:
            self._ir_diag_fixes.set("Suggested fixes: " + " | ".join(fixes))
        else:
            self._ir_diag_fixes.set("Suggested fixes: None.")


class ProxmarkScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="Proxmark", style="Title.TLabel").pack(pady=10)
        self._status = tk.StringVar(value="Pick a Proxmark tool.")
        ttk.Label(self, textvariable=self._status, style="Muted.TLabel").pack(pady=4)

        grid = ttk.Frame(self, style="App.TFrame")
        grid.pack(fill=tk.X, padx=16, pady=8)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        self._build_tool_group(
            grid,
            row=0,
            column=0,
            title="Connection",
            buttons=[
                ("Connect USB", lambda: self._set_status("Connecting to Proxmark...")),
                ("Device Info", lambda: self._set_status("Fetching device info.")),
            ],
        )
        self._build_tool_group(
            grid,
            row=0,
            column=1,
            title="Read",
            buttons=[
                ("Low Frequency", lambda: self._set_status("LF read pending.")),
                ("High Frequency", lambda: self._set_status("HF read pending.")),
            ],
        )
        self._build_tool_group(
            grid,
            row=1,
            column=0,
            title="Write/Clone",
            buttons=[
                ("Clone", lambda: self._set_status("Clone pending.")),
                ("Write", lambda: self._set_status("Write pending.")),
            ],
        )
        self._build_tool_group(
            grid,
            row=1,
            column=1,
            title="Sniff/Tools",
            buttons=[
                ("Sniff", lambda: self._set_status("Sniff mode pending.")),
                ("Script", lambda: self._set_status("Run Proxmark script.")),
            ],
        )

    def _build_tool_group(
        self,
        master: ttk.Frame,
        row: int,
        column: int,
        title: str,
        buttons: list[tuple[str, Callable[[], None]]],
    ) -> None:
        card = ttk.Frame(master, style="Card.TFrame")
        card.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        ttk.Label(card, text=title, style="Status.TLabel").pack(pady=(8, 4))
        for label, command in buttons:
            ttk.Button(card, text=label, style="Secondary.TButton", command=command).pack(
                pady=4, padx=8, fill=tk.X
            )

    def _set_status(self, message: str) -> None:
        self._status.set(message)


class SaveDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, profile: CardProfile) -> None:
        super().__init__(master)
        self.title("Save Tag")
        self.configure(bg="#0b120b")
        self.result: Optional[CardProfile] = None
        self._profile = profile

        self._name_var = tk.StringVar(value=profile.friendly_name)
        self._category_var = tk.StringVar(value=profile.category or "")
        self._notes_var = tk.StringVar(value=profile.notes or "")

        ttk.Label(self, text="Friendly name", style="Body.TLabel").pack(pady=4)
        ttk.Entry(self, textvariable=self._name_var, style="App.TEntry").pack(
            fill=tk.X, padx=10
        )

        ttk.Label(self, text="Category", style="Body.TLabel").pack(pady=4)
        ttk.Entry(self, textvariable=self._category_var, style="App.TEntry").pack(
            fill=tk.X, padx=10
        )

        ttk.Label(self, text="Notes", style="Body.TLabel").pack(pady=4)
        ttk.Entry(self, textvariable=self._notes_var, style="App.TEntry").pack(
            fill=tk.X, padx=10
        )

        actions = ttk.Frame(self, style="Card.TFrame")
        actions.pack(pady=10)
        ttk.Button(actions, text="Save", style="Primary.TButton", command=self._save).grid(
            row=0, column=0, padx=6
        )
        ttk.Button(actions, text="Cancel", style="Secondary.TButton", command=self.destroy).grid(
            row=0, column=1, padx=6
        )

    def _save(self) -> None:
        self._profile.friendly_name = self._name_var.get().strip() or self._profile.friendly_name
        self._profile.category = self._category_var.get().strip() or None
        self._profile.notes = self._notes_var.get().strip() or None
        self.result = self._profile
        self.destroy()
