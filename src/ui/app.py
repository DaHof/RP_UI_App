from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from data_model import CardProfile
from library_store import LibraryStore
from pn532.reader_base import TagDetection


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

        self.show_section("Scan")

    def _build_left_nav(self) -> None:
        ttk.Label(self._nav, text="PIP-UI", style="NavTitle.TLabel").pack(pady=(16, 12))
        for label in ["Scan", "IR", "Bluetooth", "WiFi", "Proxmark", "System"]:
            button = ttk.Button(
                self._nav,
                text=label,
                style="Nav.TButton",
                command=lambda name=label: self.show_section(name),
            )
            button.pack(fill=tk.X, padx=12, pady=6)

    def _configure_theme(self) -> None:
        self._colors = {
            "bg": "#0b120b",
            "panel": "#0f1b0f",
            "panel_alt": "#0b150b",
            "accent": "#69ff5a",
            "accent_alt": "#2fd05a",
            "text": "#d7ffd7",
            "muted": "#57b857",
        }
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("App.TFrame", background=self._colors["bg"])
        style.configure("Nav.TFrame", background=self._colors["panel_alt"])
        style.configure("Card.TFrame", background=self._colors["panel"])

        style.configure(
            "NavTitle.TLabel",
            background=self._colors["panel_alt"],
            foreground=self._colors["accent"],
            font=("Courier", 16, "bold"),
        )
        style.configure(
            "Title.TLabel",
            background=self._colors["bg"],
            foreground=self._colors["accent"],
            font=("Courier", 20, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=self._colors["bg"],
            foreground=self._colors["text"],
            font=("Courier", 16, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=self._colors["bg"],
            foreground=self._colors["text"],
            font=("Courier", 12),
        )
        style.configure(
            "Muted.TLabel",
            background=self._colors["bg"],
            foreground=self._colors["muted"],
            font=("Courier", 10),
        )

        style.configure(
            "Primary.TButton",
            background=self._colors["accent"],
            foreground="#0b120b",
            font=("Courier", 12, "bold"),
            padding=10,
        )
        style.map(
            "Primary.TButton",
            background=[("active", self._colors["accent_alt"])],
            foreground=[("active", "#0b120b")],
        )

        style.configure(
            "Secondary.TButton",
            background=self._colors["panel"],
            foreground=self._colors["text"],
            font=("Courier", 12, "bold"),
            padding=10,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", self._colors["panel_alt"])],
            foreground=[("active", self._colors["accent"])],
        )

        style.configure(
            "Nav.TButton",
            background=self._colors["panel_alt"],
            foreground=self._colors["text"],
            font=("Courier", 12, "bold"),
            padding=10,
        )
        style.map(
            "Nav.TButton",
            background=[("active", self._colors["panel"])],
            foreground=[("active", self._colors["accent"])],
        )

        style.configure(
            "Small.TButton",
            background=self._colors["panel"],
            foreground=self._colors["text"],
            font=("Courier", 10, "bold"),
            padding=6,
        )
        style.map(
            "Small.TButton",
            background=[("active", self._colors["panel_alt"])],
            foreground=[("active", self._colors["accent"])],
        )

        style.configure(
            "App.TEntry",
            fieldbackground=self._colors["panel"],
            background=self._colors["panel"],
            foreground=self._colors["text"],
            insertcolor=self._colors["accent"],
        )
        style.configure(
            "App.TMenubutton",
            background=self._colors["panel"],
            foreground=self._colors["text"],
            font=("Courier", 11, "bold"),
        )

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
        for child in self._subnav.winfo_children():
            child.destroy()
        if name == "Scan":
            for label in ["Scan", "Library", "Emulate", "Clone/Write", "Settings"]:
                ttk.Button(
                    self._subnav,
                    text=label,
                    style="Nav.TButton",
                    command=lambda screen_name=label: self.show_screen(screen_name),
                ).pack(side=tk.LEFT, padx=6, pady=6)
            self.show_screen("Scan")
        elif name == "IR":
            ir_screen = self._screens["IR"]
            for label in ["Capture", "Library", "Remote", "Learn/Pair", "Send", "Settings"]:
                ttk.Button(
                    self._subnav,
                    text=label,
                    style="Nav.TButton",
                    command=lambda screen_name=label: ir_screen.show_subscreen(screen_name),
                ).pack(side=tk.LEFT, padx=6, pady=6)
            self.show_screen("IR")
            ir_screen.show_subscreen("Capture")
        elif name == "Bluetooth":
            bluetooth_screen = self._screens["Bluetooth"]
            for label in ["Discovery", "Pairing", "Connection", "Audio", "Library", "Shortcuts"]:
                ttk.Button(
                    self._subnav,
                    text=label,
                    style="Nav.TButton",
                    command=lambda screen_name=label: bluetooth_screen.show_subscreen(
                        screen_name
                    ),
                ).pack(side=tk.LEFT, padx=6, pady=6)
            self.show_screen("Bluetooth")
            bluetooth_screen.show_subscreen("Discovery")
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


class BaseScreen(ttk.Frame):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, style="App.TFrame")
        self._app = app


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

        conn_frame = ttk.Frame(self, style="Card.TFrame")
        conn_frame.pack(pady=8)
        ttk.Label(conn_frame, text="Connection mode:", style="Body.TLabel").pack(
            side=tk.LEFT, padx=6
        )
        self._conn_mode = tk.StringVar(value="I2C")
        ttk.OptionMenu(
            conn_frame, self._conn_mode, "I2C", "I2C", "SPI", "UART", style="App.TMenubutton"
        ).pack(side=tk.LEFT)

        ir_frame = ttk.Frame(self, style="Card.TFrame")
        ir_frame.pack(pady=8, padx=16, fill=tk.X)
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
        ttk.Button(
            ir_frame,
            text="Save IR Pins",
            style="Secondary.TButton",
            command=self._save_ir_pins,
        ).pack(pady=(0, 8))

    def _save_ir_pins(self) -> None:
        tx_pin = self._ir_tx_entry.get().strip() or self._app.ir_tx_pin()
        rx_pin = self._ir_rx_entry.get().strip() or self._app.ir_rx_pin()
        self._app.set_ir_pins(tx_pin, rx_pin)


class IRScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._status = tk.StringVar(value="Pick an IR tool.")
        self._debug_status = tk.StringVar(value="Debug ready.")
        self._captures: list[dict[str, str]] = []
        self._capture_detail = tk.StringVar(value="No captures yet.")
        status_row = ttk.Frame(self, style="App.TFrame")
        status_row.pack(fill=tk.X, padx=16, pady=(10, 4))
        ttk.Label(status_row, text="IR", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(status_row, textvariable=self._status, style="Muted.TLabel").pack(
            side=tk.LEFT, padx=12
        )

        self._ir_screen_host = ttk.Frame(self, style="App.TFrame")
        self._ir_screen_host.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))

        self._ir_screens: dict[str, tk.Frame] = {}
        self._current_ir_screen: Optional[tk.Frame] = None

        self._add_ir_screen("Capture", self._build_capture_screen())
        self._add_ir_screen("Library", self._build_library_screen())
        self._add_ir_screen("Remote", self._build_remote_screen())
        self._add_ir_screen("Learn/Pair", self._build_learn_screen())
        self._add_ir_screen("Send", self._build_send_screen())
        self._add_ir_screen("Settings", self._build_settings_screen())

        self._show_ir_screen("Capture")

    def _add_ir_screen(self, name: str, frame: tk.Frame) -> None:
        self._ir_screens[name] = frame

    def _show_ir_screen(self, name: str) -> None:
        if self._current_ir_screen:
            self._current_ir_screen.pack_forget()
        self._current_ir_screen = self._ir_screens[name]
        self._current_ir_screen.pack(fill=tk.BOTH, expand=True)

    def show_subscreen(self, name: str) -> None:
        self._show_ir_screen(name)

    def _build_capture_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        self._build_tool_group(
            frame,
            title="Capture",
            buttons=[
                ("Start Capture", self._start_capture),
                ("Recent Captures", self._show_recent_captures),
                ("Save to Library", lambda: self._set_status("Save current capture.")),
            ],
        )

        captures = ttk.Frame(frame, style="Card.TFrame")
        captures.pack(fill=tk.X, pady=6)
        ttk.Label(captures, text="Captures", style="Status.TLabel").pack(pady=(8, 4))
        self._capture_list = tk.Listbox(
            captures,
            height=5,
            bg=self._app._colors["panel"],
            fg=self._app._colors["text"],
            selectbackground=self._app._colors["accent"],
            selectforeground="#0b1020",
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self._capture_list.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._capture_list.bind("<<ListboxSelect>>", self._on_capture_select)
        ttk.Label(captures, textvariable=self._capture_detail, style="Muted.TLabel").pack(
            pady=(0, 8)
        )
        return frame

    def _build_library_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        self._build_tool_group(
            frame,
            title="Library",
            buttons=[
                ("Browse Signals", lambda: self._set_status("Browse saved IR signals.")),
                ("Send Selected", lambda: self._set_status("Send selected IR signal.")),
            ],
        )
        return frame

    def _build_remote_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        self._build_tool_group(
            frame,
            title="Remote",
            buttons=[
                ("Pick Device", lambda: self._set_status("Select a device profile.")),
                ("Favorites", lambda: self._set_status("Open favorite buttons.")),
            ],
        )
        return frame

    def _build_learn_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        self._build_tool_group(
            frame,
            title="Learn / Pair",
            buttons=[
                ("Guided Learn", lambda: self._set_status("Start guided learning.")),
                ("Edit Profile", lambda: self._set_status("Edit device mappings.")),
            ],
        )
        return frame

    def _build_send_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        self._build_tool_group(
            frame,
            title="Send",
            buttons=[
                ("Protocol Send", lambda: self._set_status("Send by protocol.")),
                ("Raw Send", lambda: self._set_status("Send raw timings.")),
            ],
        )
        return frame

    def _build_settings_screen(self) -> tk.Frame:
        frame = ttk.Frame(self._ir_screen_host, style="App.TFrame")
        self._build_tool_group(
            frame,
            title="Settings",
            buttons=[
                ("IR Hardware", lambda: self._set_status("Open IR settings.")),
                ("Import/Export", lambda: self._set_status("Import or export signals.")),
            ],
        )
        debug = ttk.Frame(frame, style="Card.TFrame")
        debug.pack(fill=tk.X, pady=6)
        ttk.Label(debug, text="Debug", style="Status.TLabel").pack(pady=(8, 4))
        ttk.Label(debug, textvariable=self._debug_status, style="Body.TLabel").pack(pady=2)
        debug_buttons = ttk.Frame(debug, style="Card.TFrame")
        debug_buttons.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(
            debug_buttons,
            text="Check Pins",
            style="Secondary.TButton",
            command=self._check_pins,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            debug_buttons,
            text="Mark OK",
            style="Secondary.TButton",
            command=lambda: self._debug_status.set("IR debug status: OK."),
        ).pack(side=tk.LEFT, padx=4)
        return frame

        captures = ttk.Frame(self, style="Card.TFrame")
        captures.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(captures, text="Captures", style="Status.TLabel").pack(pady=(8, 4))
        self._capture_list = tk.Listbox(
            captures,
            height=5,
            bg=self._app._colors["panel"],
            fg=self._app._colors["text"],
            selectbackground=self._app._colors["accent"],
            selectforeground="#0b1020",
            highlightthickness=0,
            relief=tk.FLAT,
        )
        self._capture_list.pack(fill=tk.X, padx=8, pady=(0, 6))
        self._capture_list.bind("<<ListboxSelect>>", self._on_capture_select)
        ttk.Label(captures, textvariable=self._capture_detail, style="Muted.TLabel").pack(
            pady=(0, 8)
        )

        debug = ttk.Frame(self, style="Card.TFrame")
        debug.pack(fill=tk.X, padx=16, pady=6)
        ttk.Label(debug, text="Debug", style="Status.TLabel").pack(pady=(8, 4))
        ttk.Label(debug, textvariable=self._debug_status, style="Body.TLabel").pack(pady=2)
        debug_buttons = ttk.Frame(debug, style="Card.TFrame")
        debug_buttons.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(
            debug_buttons,
            text="Check Pins",
            style="Secondary.TButton",
            command=self._check_pins,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            debug_buttons,
            text="Mark OK",
            style="Secondary.TButton",
            command=lambda: self._debug_status.set("IR debug status: OK."),
        ).pack(side=tk.LEFT, padx=4)

    def _build_tool_group(
        self,
        master: ttk.Frame,
        title: str,
        buttons: list[tuple[str, Callable[[], None]]],
    ) -> None:
        card = ttk.Frame(master, style="Card.TFrame")
        card.pack(fill=tk.X, pady=6)
        ttk.Label(card, text=title, style="Status.TLabel").pack(pady=(8, 4))
        for label, command in buttons:
            ttk.Button(card, text=label, style="Secondary.TButton", command=command).pack(
                pady=4, padx=8, fill=tk.X
            )

    def _set_status(self, message: str) -> None:
        self._status.set(message)

    def _start_capture(self) -> None:
        self._set_status("Listening for IR signals.")
        self._add_capture(
            name="Capture",
            protocol="NEC",
            data="0x20DF10EF",
            source="GPIO23",
        )

    def _show_recent_captures(self) -> None:
        if not self._captures:
            self._add_capture(
                name="Recent",
                protocol="RC5",
                data="0x1FE4",
                source="GPIO23",
            )
        self._set_status("Showing recent captures.")

    def _add_capture(self, name: str, protocol: str, data: str, source: str) -> None:
        capture = {
            "name": name,
            "protocol": protocol,
            "data": data,
            "source": source,
        }
        self._captures.append(capture)
        self._capture_list.insert(tk.END, f"{name} ({protocol}) {data}")
        self._capture_list.selection_clear(0, tk.END)
        self._capture_list.selection_set(tk.END)
        self._capture_list.event_generate("<<ListboxSelect>>")

    def _on_capture_select(self, event: tk.Event) -> None:
        if not self._capture_list.curselection():
            return
        index = self._capture_list.curselection()[0]
        capture = self._captures[index]
        detail = (
            f"Protocol: {capture['protocol']} | Data: {capture['data']} | Source: {capture['source']}"
        )
        self._capture_detail.set(detail)

    def _check_pins(self) -> None:
        tx_pin = self._app.ir_tx_pin()
        rx_pin = self._app.ir_rx_pin()
        self._debug_status.set(f"IR pins set to TX: {tx_pin}, RX: {rx_pin}.")


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
        ttk.Label(self, text="System", style="Title.TLabel").pack(pady=10)
        ttk.Label(
            self,
            text="System actions will appear here.",
            style="Body.TLabel",
        ).pack(pady=6)


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
