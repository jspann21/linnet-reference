"""Installer window hosted by Linnet Media."""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from tools.content import media_manager as media
from tools.studio import installer


class InstallerWindow:
    def __init__(self, parent, identity=None):
        self.window = tk.Toplevel(parent)
        self.window.title("Linnet · Install or restore")
        self.window.geometry("720x670")
        self.window.minsize(640, 620)
        self.identity = identity
        self.review = None
        self.events = queue.Queue()
        self.busy = False
        self.receipt = None
        self.fields = {}
        self._build()
        self.window.after(100, self._drain)
        self.window.after(150, self.refresh)

    def _build(self):
        body = ttk.Frame(self.window, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Linnet installation", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Install the build made for this exact iPod, or restore its previous boot software.",
                  style="Muted.TLabel", wraplength=660).pack(anchor="w", pady=(4, 16))
        card = ttk.LabelFrame(body, text="Connected iPod", padding=14)
        card.pack(fill="x")
        for name, label in (("model", "Model"), ("identity", "Device identity"),
                            ("software", "Detected software"), ("linnet", "Linnet"),
                            ("method", "Install method")):
            row = ttk.Frame(card)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=18).pack(side="left", anchor="nw")
            value = tk.StringVar(value="Checking…")
            ttk.Label(row, textvariable=value, wraplength=470).pack(side="left", fill="x", expand=True)
            self.fields[name] = value
        safe = ttk.LabelFrame(body, text="What the installer changes", padding=14)
        safe.pack(fill="x", pady=14)
        ttk.Label(safe, text=("Your music, photos, notes, videos, iTunes database, partitions, and filesystem are preserved. "
                              "Linnet adds its own folder, verifies every written file, backs up the current boot path, "
                              "and publishes the new loader only after preparation succeeds."),
                  wraplength=650).pack(anchor="w")
        build = ttk.LabelFrame(body, text="Build to install", padding=14)
        build.pack(fill="x", pady=(0, 14))
        self.build_choice = tk.StringVar(value="user")
        self.build_buttons = []
        for value, title, detail in (
                ("user", "User build", "Normal listening build; developer transport and instrumentation are excluded."),
                ("dev", "Developer build", "Device-bound diagnostics and Linnet Link are included for development.")):
            row = ttk.Frame(build)
            row.pack(fill="x", pady=2)
            button = ttk.Radiobutton(row, text=title, value=value, variable=self.build_choice)
            button.pack(side="left", anchor="n")
            ttk.Label(row, text=detail, style="Muted.TLabel", wraplength=470).pack(side="left", padx=(10, 0))
            self.build_buttons.append(button)
        self.status = tk.StringVar(value="Inspecting the connected iPod…")
        ttk.Label(body, textvariable=self.status, style="Muted.TLabel", wraplength=660).pack(anchor="w", pady=(2, 8))
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x")
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(16, 0))
        self.refresh_button = ttk.Button(actions, text="Check again", command=self.refresh)
        self.refresh_button.pack(side="left")
        self.restore_button = ttk.Button(actions, text="Restore previous boot", command=self.restore, state="disabled")
        self.restore_button.pack(side="left", padx=8)
        self.report_button = ttk.Button(actions, text="Open receipt", command=self.open_receipt, state="disabled")
        self.report_button.pack(side="right")
        self.install_button = ttk.Button(actions, text="Install Linnet", style="Accent.TButton",
                                         command=self.install, state="disabled")
        self.install_button.pack(side="right", padx=8)

    def _set_busy(self, value):
        self.busy = value
        state = "disabled" if value else "normal"
        self.refresh_button.configure(state=state)
        self.install_button.configure(state="disabled" if value or not self.review or self.review["action"] not in ("install", "resume", "replace") else "normal")
        if self.review and self.review["action"] == "replace":
            self.install_button.configure(text="Fresh reinstall")
        else:
            self.install_button.configure(text="Install Linnet")
        build_state = "disabled" if value or (self.review and self.review["action"] == "resume") else "normal"
        for button in self.build_buttons:
            button.configure(state=build_state)
        recoverable = bool(self.review and self.review.get("recovery", {}).get("phase") == "installed")
        self.restore_button.configure(state="disabled" if value or not recoverable else "normal")
        if value:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _work(self, callback, kind):
        self._set_busy(True)
        def run():
            try:
                self.events.put((kind, callback()))
            except BaseException as error:
                self.events.put(("error", f"{type(error).__name__}: {error}"))
        threading.Thread(target=run, daemon=True).start()

    def refresh(self):
        if self.busy:
            return
        self.status.set("Identifying the iPod, its target, and installed software…")
        def inspect():
            identity = self.identity
            if identity is None:
                devices = media.discover()
                if len(devices) != 1:
                    raise ValueError("Connect exactly one supported iPod in Disk Mode, then check again.")
                identity = devices[0]
            return installer.assess(identity)
        self._work(inspect, "review")

    def _show(self, review):
        self.review = review
        if review["action"] == "resume" and review.get("resume", {}).get("build") in ("user", "dev"):
            self.build_choice.set(review["resume"]["build"])
        identity, target = review["identity"], review["target"]
        model = identity.get("regulatory_model") or identity.get("model_number") or target["id"]
        self.fields["model"].set(f"{target['name']} · {model}")
        self.fields["identity"].set(f"{identity['drive']} · disk {identity['disk_number']} · {identity['disk_serial']}")
        software = ["Apple iPod software", *review["other_installations"]]
        self.fields["software"].set(", ".join(dict.fromkeys(software)))
        state = review["linnet"]["state"]
        self.fields["linnet"].set(review["summary"] if state != "absent" else "Not installed")
        methods = {"rockbox-file": "Use existing Rockbox loader; reversible file replacement",
                   "native-directory": "Verified native boot redirect; administrator approval required",
                   "existing": "Existing installation"}
        self.fields["method"].set(methods.get(review["strategy"], "Unavailable until the issue above is resolved"))
        self.status.set(review["summary"])
        self._set_busy(False)

    def install(self):
        if self.busy or not self.review or self.review["action"] not in ("install", "resume", "replace"):
            return
        if self.review["action"] == "resume":
            verb = "Resume the matching interrupted Linnet installation"
        elif self.review["action"] == "replace":
            verb = "Restore the saved previous boot, preserve the old Linnet folder, and freshly install Linnet 0.1.0"
        else:
            verb = "Install the verified target-specific Linnet build"
        build = self.build_choice.get()
        label = "User build" if build == "user" else "Developer build"
        if not messagebox.askyesno("Install Linnet", verb + " on this iPod?\n\n"
                                  + label + " will be installed. Existing media and other software will be preserved. "
                                  "Keep the iPod connected until completion.",
                                  parent=self.window):
            return
        identity = self.review["identity"]
        self.status.set("Preparing the target-specific Linnet build…")
        self._work(lambda: installer.install(
            identity, progress=lambda value: self.events.put(("progress", value)), build=build), "installed")

    def restore(self):
        if self.busy or not self.review:
            return
        if not messagebox.askyesno("Restore previous boot", "Restore the boot software saved before Linnet was installed?\n\n"
                                  "Media and Linnet’s data folder will remain on the iPod.", parent=self.window):
            return
        self.status.set("Restoring the verified previous boot state…")
        self._work(lambda: installer.restore(self.review["identity"]), "restored")

    def open_receipt(self):
        if self.receipt:
            try:
                os.startfile(self.receipt)
            except OSError as error:
                messagebox.showerror("Open receipt", str(error), parent=self.window)

    def _drain(self):
        try:
            for _ in range(50):
                kind, value = self.events.get_nowait()
                if kind == "progress":
                    self.status.set(str(value))
                elif kind == "review":
                    self.identity = value["identity"]
                    self._show(value)
                elif kind == "installed":
                    self.receipt = value.get("receipt")
                    self.report_button.configure(state="normal" if self.receipt else "disabled")
                    self._set_busy(False)
                    messagebox.showinfo("Linnet installed", "Installation completed and was verified. Safely eject the iPod, then restart it.", parent=self.window)
                    self.refresh()
                elif kind == "restored":
                    self._set_busy(False)
                    messagebox.showinfo("Previous boot restored", "The previous boot software was restored. Safely eject the iPod before restarting it.", parent=self.window)
                    self.refresh()
                elif kind == "error":
                    self._set_busy(False)
                    self.status.set("Needs attention · " + str(value))
                    messagebox.showerror("Linnet installer", str(value), parent=self.window)
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(100, self._drain)
