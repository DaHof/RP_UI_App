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
        self.configure(bg="#111827")
        self._store = store
        self._on_shutdown = on_shutdown
        self._current_detection: Optional[TagDetection] = None
        self._current_profile: Optional[CardProfile] = None

        self._content = ttk.Frame(self)
        self._content.pack(fill=tk.BOTH, expand=True)

        self._screens = {}
        self._current_screen = None

        self._build_bottom_nav()

        self._add_screen("Scan", ScanScreen(self._content, self))
        self._add_screen("Library", LibraryScreen(self._content, self))
        self._add_screen("Emulate", EmulateScreen(self._content, self))
        self._add_screen("Tools", ToolsScreen(self._content, self))
        self._add_screen("Settings", SettingsScreen(self._content, self))

        self.show_screen("Scan")

    def _build_bottom_nav(self) -> None:
        nav = ttk.Frame(self)
        nav.pack(side=tk.BOTTOM, fill=tk.X)
        for label in ["Scan", "Library", "Emulate", "Tools", "Settings"]:
            button = ttk.Button(nav, text=label, command=lambda name=label: self.show_screen(name))
            button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=4, pady=4)

    def _add_screen(self, name: str, frame: tk.Frame) -> None:
        self._screens[name] = frame

    def show_screen(self, name: str) -> None:
        if self._current_screen:
            self._current_screen.pack_forget()
        self._current_screen = self._screens[name]
        self._current_screen.pack(fill=tk.BOTH, expand=True)
        if hasattr(self._current_screen, "refresh"):
            self._current_screen.refresh()

    def on_tag_detected(self, detection: TagDetection) -> None:
        self._current_detection = detection
        existing = self._store.get_by_uid(detection.uid)
        if existing:
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
        super().__init__(master)
        self._app = app


class ScanScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._status = tk.StringVar(value="Ready to scan")
        self._tag_summary = tk.StringVar(value="No tag detected")
        self._tag_details = tk.StringVar(value="")

        status_label = ttk.Label(self, textvariable=self._status, font=("Arial", 20))
        status_label.pack(pady=10)

        summary_label = ttk.Label(self, textvariable=self._tag_summary, font=("Arial", 16))
        summary_label.pack(pady=6)

        details_label = ttk.Label(self, textvariable=self._tag_details)
        details_label.pack(pady=4)

        actions = ttk.Frame(self)
        actions.pack(pady=12)
        ttk.Button(actions, text="Save to Library", command=self._app.save_current_tag).grid(
            row=0, column=0, padx=6, pady=6
        )
        ttk.Button(actions, text="Read Details", command=self._show_details).grid(
            row=0, column=1, padx=6, pady=6
        )
        ttk.Button(actions, text="Clone/Write", command=self._go_clone).grid(
            row=1, column=0, padx=6, pady=6
        )
        ttk.Button(actions, text="Emulate", command=self._go_emulate).grid(
            row=1, column=1, padx=6, pady=6
        )

    def on_tag_detected(self, detection: TagDetection, profile: Optional[CardProfile]) -> None:
        self._status.set("Tag detected")
        name = profile.friendly_name if profile else "Unnamed tag"
        self._tag_summary.set(f"{name} ({detection.tag_type})")
        self._tag_details.set(f"UID: {detection.uid}")

    def _show_details(self) -> None:
        self._app.show_screen("Library")

    def _go_clone(self) -> None:
        self._app.show_screen("Library")

    def _go_emulate(self) -> None:
        self._app.show_screen("Emulate")


class LibraryScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        self._listbox = tk.Listbox(self, height=8)
        self._listbox.pack(fill=tk.X, padx=10, pady=10)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        self._detail = tk.StringVar(value="Select a tag to view details")
        ttk.Label(self, textvariable=self._detail).pack(pady=8)

        actions = ttk.Frame(self)
        actions.pack(pady=8)
        ttk.Button(actions, text="Emulate", command=self._emulate).grid(row=0, column=0, padx=6)
        ttk.Button(actions, text="Clone/Write", command=self._clone).grid(row=0, column=1, padx=6)
        ttk.Button(actions, text="Delete", command=self._delete).grid(row=0, column=2, padx=6)

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
        detail = (
            f"Name: {profile.friendly_name}\n"
            f"UID: {profile.uid}\n"
            f"Type: {profile.tag_type}\n"
            f"Last seen: {profile.timestamps.last_seen_at}"
        )
        self._detail.set(detail)

    def _emulate(self) -> None:
        self._app.show_screen("Emulate")

    def _clone(self) -> None:
        self._app.show_screen("Tools")

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
        ttk.Label(self, textvariable=self._status, font=("Arial", 16)).pack(pady=12)

        method_frame = ttk.Frame(self)
        method_frame.pack(pady=8)
        ttk.Label(method_frame, text="Method:").pack(side=tk.LEFT, padx=6)
        self._method = tk.StringVar(value="Auto")
        ttk.OptionMenu(method_frame, self._method, "Auto", "Auto", "NDEF", "Raw").pack(side=tk.LEFT)

        self._capability = tk.StringVar(value="Select a tag to see capabilities")
        ttk.Label(self, textvariable=self._capability).pack(pady=6)

        ttk.Button(self, text="Start Emulation", command=self._start).pack(pady=12)

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
        ttk.Label(self, text="Tools", font=("Arial", 16)).pack(pady=10)

        self._uid_entry = ttk.Entry(self)
        self._uid_entry.insert(0, "04:AB:CD:EF")
        self._uid_entry.pack(pady=6)

        self._type_entry = ttk.Entry(self)
        self._type_entry.insert(0, "NTAG213")
        self._type_entry.pack(pady=6)

        ttk.Button(self, text="Simulate Tag", command=self._simulate).pack(pady=6)
        ttk.Button(self, text="Shutdown", command=self._app.shutdown).pack(pady=6)

    def _simulate(self) -> None:
        uid = self._uid_entry.get().strip()
        tag_type = self._type_entry.get().strip() or "Unknown"
        reader = getattr(self._app, "reader", None)
        if reader and hasattr(reader, "simulate_tag"):
            reader.simulate_tag(uid, tag_type)


class SettingsScreen(BaseScreen):
    def __init__(self, master: tk.Misc, app: App) -> None:
        super().__init__(master, app)
        ttk.Label(self, text="Settings", font=("Arial", 16)).pack(pady=10)

        conn_frame = ttk.Frame(self)
        conn_frame.pack(pady=8)
        ttk.Label(conn_frame, text="Connection mode:").pack(side=tk.LEFT, padx=6)
        self._conn_mode = tk.StringVar(value="I2C")
        ttk.OptionMenu(conn_frame, self._conn_mode, "I2C", "I2C", "SPI", "UART").pack(side=tk.LEFT)


class SaveDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, profile: CardProfile) -> None:
        super().__init__(master)
        self.title("Save Tag")
        self.result: Optional[CardProfile] = None
        self._profile = profile

        self._name_var = tk.StringVar(value=profile.friendly_name)
        self._category_var = tk.StringVar(value=profile.category or "")
        self._notes_var = tk.StringVar(value=profile.notes or "")

        ttk.Label(self, text="Friendly name").pack(pady=4)
        ttk.Entry(self, textvariable=self._name_var).pack(fill=tk.X, padx=10)

        ttk.Label(self, text="Category").pack(pady=4)
        ttk.Entry(self, textvariable=self._category_var).pack(fill=tk.X, padx=10)

        ttk.Label(self, text="Notes").pack(pady=4)
        ttk.Entry(self, textvariable=self._notes_var).pack(fill=tk.X, padx=10)

        actions = ttk.Frame(self)
        actions.pack(pady=10)
        ttk.Button(actions, text="Save", command=self._save).grid(row=0, column=0, padx=6)
        ttk.Button(actions, text="Cancel", command=self.destroy).grid(row=0, column=1, padx=6)

    def _save(self) -> None:
        self._profile.friendly_name = self._name_var.get().strip() or self._profile.friendly_name
        self._profile.category = self._category_var.get().strip() or None
        self._profile.notes = self._notes_var.get().strip() or None
        self.result = self._profile
        self.destroy()
