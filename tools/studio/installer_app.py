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
    def __init__(self, parent, identity=None, on_changed=None):
        self.window = tk.Toplevel(parent)
        self.window.title("Linnet · Install, switch build or restore")
        self.window.geometry("720x600")
        self.window.minsize(680, 590)
        self.window.transient(parent)
        self.window.grab_set()
        self.on_changed = on_changed
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
        style = ttk.Style(self.window)
        style.configure("InstallerError.TLabel", foreground="#a12622")
        body = ttk.Frame(self.window, padding=(22, 18))
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Install Linnet", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Choose a build for this iPod, or restore its previous boot software.",
                  style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(2, 12))
        card = ttk.LabelFrame(body, text="Connected iPod", padding=(12, 8))
        card.pack(fill="x")
        card.columnconfigure(1, weight=1)
        for row, (name, label) in enumerate((("model", "Model"), ("identity", "Device identity"),
                                             ("software", "Detected software"), ("linnet", "Linnet"),
                                             ("method", "Install method"))):
            ttk.Label(card, text=label, width=17).grid(row=row, column=0, sticky="nw", pady=2)
            value = tk.StringVar(value="Checking…")
            ttk.Label(card, textvariable=value, wraplength=490).grid(
                row=row, column=1, sticky="ew", pady=2)
            self.fields[name] = value
        safe = ttk.LabelFrame(body, text="Your data stays intact", padding=(12, 8))
        safe.pack(fill="x", pady=(10, 0))
        ttk.Label(safe, text=("The installer preserves your music, photos, notes, videos, iTunes database, partitions, "
                              "and filesystem. It backs up the current boot path and verifies every write before "
                              "switching loaders."), wraplength=640).pack(anchor="w")
        build = ttk.LabelFrame(body, text="Choose a build", padding=(12, 8))
        build.pack(fill="x", pady=(10, 0))
        build.columnconfigure(1, weight=1)
        self.build_choice = tk.StringVar(value="user")
        self.build_buttons = []
        for value, title, detail in (
                ("user", "User build (recommended)", "For everyday use. Developer tools are left out."),
                ("dev", "Developer build", "For diagnostics and Linnet Link. Bound to this iPod.")):
            row = len(self.build_buttons)
            button = ttk.Radiobutton(build, text=title, value=value, variable=self.build_choice,
                                     command=self._update_install_label)
            button.grid(row=row, column=0, sticky="nw", pady=2)
            ttk.Label(build, text=detail, style="Muted.TLabel", wraplength=380).grid(
                row=row, column=1, sticky="w", padx=(12, 0), pady=2)
            self.build_buttons.append(button)
        self.status = tk.StringVar(value="Inspecting the connected iPod…")
        self.status_label = ttk.Label(body, textvariable=self.status, style="Muted.TLabel", wraplength=640)
        self.status_label.pack(anchor="w", pady=(12, 0))
        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.actions = ttk.Frame(body)
        self.actions.pack(fill="x", pady=(12, 0))
        self.refresh_button = ttk.Button(self.actions, text="Check again", command=self.refresh)
        self.refresh_button.pack(side="left")
        self.report_button = ttk.Button(self.actions, text="Open receipt", command=self.open_receipt, state="disabled")
        self.report_button.pack(side="left", padx=8)
        self.install_button = ttk.Button(self.actions, text="Install Linnet", style="Accent.TButton",
                                         command=self.install, state="disabled")
        self.install_button.pack(side="right")
        self.restore_button = ttk.Button(
            self.actions, text="Restore previous boot", command=self.restore, state="disabled")
        self.restore_button.pack(side="right", padx=8)

    def _set_status(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(style="InstallerError.TLabel" if error else "Muted.TLabel")

    def _update_install_label(self):
        action = self.review["action"] if self.review else None
        current = self.review.get("linnet", {}).get("build") if self.review else None
        selected = self.build_choice.get()
        if action == "replace" and current and current != selected:
            label = "User" if selected == "user" else "Developer"
            text = f"Switch to {label} build"
        else:
            text = {"replace": "Reinstall selected build", "resume": "Resume installation"}.get(action, "Install Linnet")
        self.install_button.configure(text=text)

    def _set_busy(self, value):
        self.busy = value
        state = "disabled" if value else "normal"
        self.refresh_button.configure(state=state)
        self.install_button.configure(state="disabled" if value or not self.review or self.review["action"] not in ("install", "resume", "replace") else "normal")
        self._update_install_label()
        build_state = "disabled" if value or (self.review and self.review["action"] == "resume") else "normal"
        for button in self.build_buttons:
            button.configure(state=build_state)
        recoverable = bool(self.review and self.review.get("recovery", {}).get("phase") == "installed")
        self.restore_button.configure(state="disabled" if value or not recoverable else "normal")
        self.report_button.configure(state="disabled" if value or not self.receipt else "normal")
        if value:
            self.progress.pack(fill="x", pady=(8, 0), before=self.actions)
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _work(self, callback, kind):
        self._set_busy(True)
        def run():
            try:
                self.events.put((kind, callback()))
            except BaseException as error:
                self.events.put(("error", str(error) or type(error).__name__))
        threading.Thread(target=run, daemon=True).start()

    def refresh(self):
        if self.busy:
            return
        self._set_status("Identifying the iPod, its target, and installed software…")
        def inspect():
            identity = self.identity
            if identity is None:
                devices = media.discover()
                if not devices:
                    raise ValueError("Connect a supported iPod in Disk Mode, then check again.")
                if len(devices) > 1:
                    raise ValueError("More than one supported iPod is connected. Leave one connected, then check again.")
                identity = devices[0]
            return installer.assess(identity)
        self._work(inspect, "review")

    def _show(self, review):
        self.review = review
        if review["action"] == "resume" and review.get("resume", {}).get("build") in ("user", "dev"):
            self.build_choice.set(review["resume"]["build"])
        elif review["linnet"].get("build") in ("user", "dev"):
            self.build_choice.set(review["linnet"]["build"])
        identity, target = review["identity"], review["target"]
        model = identity.get("regulatory_model") or identity.get("model_number") or target["id"]
        self.fields["model"].set(f"{target['name']} · {model}")
        self.fields["identity"].set(f"{identity['drive']} · disk {identity['disk_number']} · {identity['disk_serial']}")
        software = ["Apple iPod software", *review["other_installations"]]
        self.fields["software"].set(", ".join(dict.fromkeys(software)))
        self.fields["linnet"].set(installer.build_description(review["linnet"]))
        methods = {"rockbox-file": "Use existing Rockbox loader; reversible file replacement",
                   "native-directory": "Verified native boot redirect; administrator approval required",
                   "existing": "Existing installation"}
        self.fields["method"].set(methods.get(review["strategy"], "Unavailable until the issue above is resolved"))
        self._set_status(review["summary"])
        self._set_busy(False)

    def install(self):
        if self.busy or not self.review or self.review["action"] not in ("install", "resume", "replace"):
            return
        if self.review["action"] == "resume":
            verb = "Resume the matching interrupted Linnet installation"
        elif self.review["action"] == "replace":
            verb = "Install the selected build, even if it is the same version, after restoring the saved boot and archiving the old Linnet folder"
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
        self._set_status("Preparing the target-specific Linnet build…")
        self._work(lambda: installer.install(
            identity, progress=lambda value: self.events.put(("progress", value)), build=build), "installed")

    def restore(self):
        if self.busy or not self.review:
            return
        if not messagebox.askyesno("Restore previous boot", "Restore the boot software saved before Linnet was installed?\n\n"
                                  "Media and Linnet’s data folder will remain on the iPod.", parent=self.window):
            return
        self._set_status("Restoring the verified previous boot state…")
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
                    self._set_status(str(value))
                elif kind == "review":
                    self.identity = value["identity"]
                    self._show(value)
                elif kind == "installed":
                    self.receipt = value.get("receipt")
                    self.report_button.configure(state="normal" if self.receipt else "disabled")
                    self._set_busy(False)
                    messagebox.showinfo("Linnet installed", "Installation completed and was verified. Safely eject the iPod, then restart it.", parent=self.window)
                    self.refresh()
                    if self.on_changed:
                        self.on_changed()
                elif kind == "restored":
                    self._set_busy(False)
                    messagebox.showinfo("Previous boot restored", "The previous boot software was restored. Safely eject the iPod before restarting it.", parent=self.window)
                    self.refresh()
                    if self.on_changed:
                        self.on_changed()
                elif kind == "error":
                    self._set_busy(False)
                    self._set_status(str(value), error=True)
                    messagebox.showerror("Linnet installer", str(value), parent=self.window)
        except queue.Empty:
            pass
        if self.window.winfo_exists():
            self.window.after(100, self._drain)
