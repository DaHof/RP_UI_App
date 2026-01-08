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
        self._add_screen("Hardware", ToolsScreen(self._screen_host, self))
        self._add_screen("Settings", SettingsScreen(self._screen_host, self))
        self._add_screen("IR", IRScreen(self._screen_host, self))
        self._add_screen("WiFi", WiFiScreen(self._screen_host, self))
        self._add_screen("System", SystemScreen(self._screen_host, self))

        self.show_section("Scan")

    def _build_left_nav(self) -> None:
        ttk.Label(self._nav, text="PIP-UI", style="NavTitle.TLabel").pack(pady=(16, 12))
        for label in ["Scan", "IR", "WiFi", "System"]:
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
            for label in ["Scan", "Library", "Emulate", "Hardware", "Settings"]:
                ttk.Button(
                    self._subnav,
                    text=label,
                    style="Nav.TButton",
                    command=lambda screen_name=label: self.show_screen(screen_name),
                ).pack(side=tk.LEFT, padx=6, pady=6)
            self.show_screen("Scan")
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
        self._app.show_screen("Library")

    def _go_emulate(self) -> None:
        self._app.show_screen("Emulate")


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
        self._app.show_screen("Hardware")

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


class ToolsScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="Hardware", style="Title.TLabel").pack(pady=10)
        self._status = tk.StringVar(value="Scan hardware tools.")
        ttk.Label(self, textvariable=self._status, style="Muted.TLabel").pack(pady=4)

        grid = ttk.Frame(self, style="App.TFrame")
        grid.pack(fill=tk.X, padx=16, pady=8)
        grid.columnconfigure(0, weight=1)

        self._build_tool_group(
            grid,
            row=0,
            column=0,
            title="Scan",
            buttons=[
                ("Scan (Low)", lambda: self._set_status("Low-power scan pending.")),
                ("Scan (High)", lambda: self._set_status("High-power scan pending.")),
            ],
        )

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

    def _simulate(self) -> None:
        uid = self._uid_entry.get().strip()
        tag_type = self._type_entry.get().strip() or "Unknown"
        reader = getattr(self._app, "reader", None)
        if reader and hasattr(reader, "simulate_tag"):
            reader.simulate_tag(uid, tag_type)


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


class IRScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="IR", style="Title.TLabel").pack(pady=10)
        ttk.Label(
            self,
            text="IR sender/receiver features will appear here.",
            style="Body.TLabel",
        ).pack(pady=6)


class WiFiScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="WiFi", style="Title.TLabel").pack(pady=10)
        ttk.Label(
            self,
            text="WiFi scan/connect tools will appear here.",
            style="Body.TLabel",
        ).pack(pady=6)


class SystemScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="System", style="Title.TLabel").pack(pady=10)
        ttk.Label(
            self,
            text="System actions will appear here.",
            style="Body.TLabel",
        ).pack(pady=6)


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
