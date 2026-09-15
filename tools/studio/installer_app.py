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
        self.window.title("Linnet · Choose default boot")
        self.window.geometry("740x690")
        self.window.minsize(700, 650)
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
        ttk.Label(body, text="Choose default boot", style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text="Choose Linnet or another detected installation to start by default.",
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
        choices = ttk.LabelFrame(body, text="Boot software", padding=(12, 8))
        choices.pack(fill="x", pady=(10, 0))
        choices.columnconfigure(1, weight=1)
        self.boot_choice = tk.StringVar(value="linnet:user")
        self.boot_choices = choices
        self.boot_buttons = []
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
        self.apply_button = ttk.Button(self.actions, text="Set as default boot", style="Accent.TButton",
                                       command=self.apply_selection, state="disabled")
        self.apply_button.pack(side="right")

    def _set_status(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(style="InstallerError.TLabel" if error else "Muted.TLabel")

    def _selected_option(self):
        if not self.review:
            return None
        return next((item for item in self.review.get("boot_options", [])
                     if item["id"] == self.boot_choice.get()), None)

    def _update_action(self):
        option = self._selected_option()
        if not option:
            self.apply_button.configure(text="Set as default boot", state="disabled")
            return
        if option.get("active") and not option.get("selectable"):
            text = "Already the default boot"
        elif option["kind"] == "linnet":
            action = self.review["action"]
            current = self.review.get("linnet", {}).get("build")
            if action == "resume":
                text = "Resume Linnet installation"
            elif action == "replace" and current == option.get("build"):
                text = "Reinstall selected build"
            elif action == "replace":
                text = f"Switch to {option['label']}"
            elif action == "adopt":
                text = f"Switch to {option['label']}"
            else:
                text = f"Install {option['label']}"
        elif option.get("active"):
            text = "Already the default boot"
        else:
            text = f"Set {option['label']} as default"
        enabled = option.get("selectable", False) and (not option.get("active") or option["kind"] == "linnet")
        self.apply_button.configure(text=text, state="normal" if enabled and not self.busy else "disabled")

    def _render_boot_options(self):
        for child in self.boot_choices.winfo_children():
            child.destroy()
        self.boot_buttons = []
        options = self.review.get("boot_options", []) if self.review else []
        selected = next((item for item in options if item.get("active")), None)
        if not selected:
            selected = next((item for item in options if item.get("selectable")), None)
        if selected:
            self.boot_choice.set(selected["id"])
        for row, option in enumerate(options):
            title = option["label"] + (" · current default" if option.get("active") else "")
            button = ttk.Radiobutton(
                self.boot_choices, text=title, value=option["id"], variable=self.boot_choice,
                command=self._update_action,
                state="normal" if option.get("selectable") or option.get("active") else "disabled")
            button.grid(row=row, column=0, sticky="nw", pady=2)
            detail = option["detail"]
            if not option.get("selectable") and not option.get("active"):
                detail += " Unavailable."
            ttk.Label(self.boot_choices, text=detail, style="Muted.TLabel", wraplength=400).grid(
                row=row, column=1, sticky="w", padx=(12, 0), pady=2)
            self.boot_buttons.append(button)
        self._update_action()

    def _set_busy(self, value):
        self.busy = value
        state = "disabled" if value else "normal"
        self.refresh_button.configure(state=state)
        for button, option in zip(self.boot_buttons, self.review.get("boot_options", []) if self.review else []):
            enabled = option.get("selectable") or option.get("active")
            button.configure(state="disabled" if value or not enabled else "normal")
        self._update_action()
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
        self._render_boot_options()
        self._set_status(review["summary"])
        self._set_busy(False)

    def apply_selection(self):
        option = self._selected_option()
        if self.busy or not option or not option.get("selectable"):
            return
        identity = self.review["identity"]
        if option["kind"] == "linnet":
            action = self.review["action"]
            verb = ("Resume the matching interrupted Linnet installation" if action == "resume" else
                    "Reinstall the selected Linnet build" if action == "replace" and option.get("active") else
                    f"Make {option['label']} the default boot")
            if not messagebox.askyesno("Choose default boot", verb + " on this iPod?\n\n"
                                      "Existing media and other detected software will be preserved. "
                                      "Keep the iPod connected until completion.", parent=self.window):
                return
            self._set_status(f"Preparing {option['label']}…")
            self._work(lambda: installer.install(
                identity, progress=lambda value: self.events.put(("progress", value)),
                build=option["build"]), "installed")
            return
        if option["kind"] != "previous" or option.get("active"):
            return
        if not messagebox.askyesno("Choose default boot", f"Make {option['label']} the default boot?\n\n"
                                  "Media and Linnet’s data folder will remain on the iPod. "
                                  "Keep the iPod connected until completion.", parent=self.window):
            return
        self._set_status(f"Making {option['label']} the default boot…")
        self._work(lambda: installer.restore(self.review["identity"], expected=option["id"]), "restored")

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
                    messagebox.showinfo("Default boot updated", "Linnet is now the default boot. Safely eject the iPod, then restart it.", parent=self.window)
                    self.refresh()
                    if self.on_changed:
                        self.on_changed()
                elif kind == "restored":
                    self._set_busy(False)
                    messagebox.showinfo("Default boot updated", "The selected software is now the default boot. Safely eject the iPod before restarting it.", parent=self.window)
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
