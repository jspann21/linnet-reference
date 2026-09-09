"""Small native Windows UI for Linnet's media preparation workflow."""
from __future__ import annotations

import os
import importlib.util
import math
from pathlib import Path
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from tools.content import media_manager as media


def size(value):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:,.1f} {unit}"
        value /= 1024


class MediaApp:
    def __init__(self, window):
        self.window = window
        window.title("Linnet · iPod Media")
        window.geometry("900x760")
        window.minsize(900, 720)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.devices = []
        self.inventory = None
        self.pending = []
        self.video_selection = set()
        self.video_summary = tk.StringVar(value="No iPod videos selected")
        self.receipt = None
        self.submitted = []
        self.after_scan_message = None
        self.option_controls = []
        self.ffmpeg = shutil.which("ffmpeg")
        self.ffprobe = shutil.which("ffprobe")
        self.selected = {kind: tk.BooleanVar(value=True) for kind in media.KINDS}
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("TButton", padding=(10, 5))
        outer = ttk.Frame(window, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Your iPod, ready to go", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Use the Music, Notes, Photos and Videos folders already on your iPod, or add more below.",
                  style="Sub.TLabel", wraplength=820).pack(anchor="w", pady=(4, 10))
        device_row = ttk.Frame(outer)
        device_row.pack(fill="x")
        ttk.Label(device_row, text="iPod").pack(side="left", padx=(0, 10))
        self.device_choice = ttk.Combobox(device_row, state="readonly", width=58)
        self.device_choice.pack(side="left", fill="x", expand=True)
        self.device_choice.bind("<<ComboboxSelected>>", self.device_changed)
        self.refresh_button = ttk.Button(device_row, text="Find iPod", command=self.find)
        self.refresh_button.pack(side="left", padx=(10, 0))
        self.device_status = tk.StringVar(value="Connect your iPod in Disk Mode to get started.")
        ttk.Label(outer, textvariable=self.device_status, wraplength=820).pack(anchor="w", pady=(5, 8))
        library = ttk.LabelFrame(outer, text="1. Choose what to update", padding=8)
        library.pack(fill="x")
        self.counts = {}
        descriptions = {
            "Music": "Index existing audio in place and prepare cover art.",
            "Notes": "Prepare text and Markdown files for the Notes reader.",
            "Photos": "Prepare thumbnails and zoomable images; keep originals.",
            "Videos": "Convert chosen videos to IPVF; keep originals.",
        }
        for row, kind in enumerate(media.KINDS):
            checkbox = ttk.Checkbutton(library, text=kind, variable=self.selected[kind])
            checkbox.grid(row=row, column=0, sticky="w", pady=2)
            self.option_controls.append(checkbox)
            label = ttk.Label(library, text="Not scanned", width=25)
            label.grid(row=row, column=1, sticky="w", padx=12)
            self.counts[kind] = label
            ttk.Label(library, text=descriptions[kind]).grid(row=row, column=2, sticky="w")
        video_row = ttk.Frame(library)
        video_row.grid(row=len(media.KINDS), column=0, columnspan=3, sticky="ew", pady=(3, 0))
        self.choose_videos_button = ttk.Button(video_row, text="Choose iPod videos…", command=self.choose_videos, state="disabled")
        self.choose_videos_button.pack(side="left")
        self.add_videos_button = ttk.Button(video_row, text="Add videos…", command=self.add_videos)
        self.add_videos_button.pack(side="left", padx=7)
        ttk.Label(video_row, textvariable=self.video_summary).pack(side="left", padx=5)
        add_box = ttk.LabelFrame(outer, text="2. Add content from your computer (optional)", padding=8)
        add_box.pack(fill="x", pady=8)
        add_row = ttk.Frame(add_box)
        add_row.pack(fill="x")
        self.kind_choice = ttk.Combobox(add_row, values=media.KINDS, state="readonly", width=12)
        self.kind_choice.set("Music")
        self.kind_choice.pack(side="left")
        self.add_files_button = ttk.Button(add_row, text="Add files…", command=self.add_files)
        self.add_files_button.pack(side="left", padx=7)
        self.add_folder_button = ttk.Button(add_row, text="Add folder…", command=self.add_folder)
        self.add_folder_button.pack(side="left")
        self.remove_button = ttk.Button(add_row, text="Remove selection", command=self.remove)
        self.remove_button.pack(side="right")
        self.pending_list = tk.Listbox(add_box, height=2, selectmode="extended", activestyle="none")
        self.pending_list.pack(fill="x", pady=(8, 0))
        options = ttk.Frame(outer)
        options.pack(fill="x")
        ttk.Label(options, text="Photo zoom detail:").pack(side="left")
        self.photo_choice = ttk.Combobox(options, state="readonly", values=("Standard (640 px)", "High (2048 px)"), width=19)
        self.photo_choice.current(0)
        self.photo_choice.pack(side="left", padx=8)
        self.force = tk.BooleanVar(value=False)
        rebuild = ttk.Checkbutton(options, text="Rebuild unchanged content", variable=self.force)
        rebuild.pack(side="left", padx=8)
        self.option_controls.append(rebuild)
        self.tools_button = ttk.Button(options, text="Locate FFmpeg…", command=self.locate_tools)
        self.tools_button.pack(side="right")
        self.tools_status = tk.StringVar()
        self.update_tools_status()
        tools_row = ttk.Frame(outer)
        tools_row.pack(fill="x", pady=(5, 5))
        ttk.Label(tools_row, textvariable=self.tools_status, wraplength=490).pack(side="left")
        self.full_music = tk.BooleanVar(value=False)
        full_check = ttk.Checkbutton(tools_row, text="Verify entire audio files (slow)", variable=self.full_music)
        full_check.pack(side="right")
        self.option_controls.append(full_check)
        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="3. Prepare & update iPod", command=self.start)
        self.start_button.pack(side="left")
        self.scan_button = ttk.Button(actions, text="Scan again", command=self.scan)
        self.scan_button.pack(side="left", padx=8)
        self.library_button = ttk.Button(actions, text="Browse & remove…", command=self.browse_library, state="disabled")
        self.library_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="Stop after current step", command=self.stop, state="disabled")
        self.stop_button.pack(side="left")
        self.report_button = ttk.Button(actions, text="Open report", command=self.open_report, state="disabled")
        self.report_button.pack(side="right")
        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(8, 4))
        self.status = tk.StringVar(value="Ready. Scan first to see what is on the iPod.")
        ttk.Label(outer, textvariable=self.status, wraplength=820).pack(anchor="w")
        self.log = tk.Text(outer, height=3, wrap="word", state="disabled", font=("Segoe UI", 9))
        self.log.pack(fill="both", expand=True, pady=(5, 0))
        ttk.Label(outer, text="New folder browsing requires the updated Linnet firmware. Safely eject after the update finishes.",
                  wraplength=820).pack(anchor="w", pady=(5, 0))
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.after(100, self.drain)
        window.after(250, self.find)

    def update_tools_status(self):
        missing = [name for name, value in (("FFmpeg", self.ffmpeg), ("FFprobe", self.ffprobe)) if not value]
        try:
            import PIL  # noqa: F401
        except ImportError:
            missing.append("Pillow (install with: python -m pip install Pillow)")
        ready = "Tools ready · Fast music tags enabled." if importlib.util.find_spec("mutagen") else "Tools ready · Optional Mutagen speeds up music."
        self.tools_status.set(ready if not missing else "Missing: " + ", ".join(missing))

    def log_message(self, message):
        self.status.set(str(message))
        self.log.configure(state="normal")
        self.log.insert("end", str(message) + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 1000:
            self.log.delete("1.0", "201.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def indeterminate_progress(self):
        if str(self.progress.cget("mode")) != "indeterminate":
            self.progress.stop()
            self.progress.configure(mode="indeterminate", value=0)
            if self.busy:
                self.progress.start(12)

    def video_progress(self, event):
        percent = event.get("percent")
        if isinstance(percent, (int, float)) and math.isfinite(percent):
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=100, value=max(0, min(100, percent)))
        else:
            self.indeterminate_progress()
        message = str(event.get("message", "Preparing video…"))
        if event.get("video_index") and event.get("video_total"):
            message = f"Video {event['video_index']}/{event['video_total']} · {message}"
        self.status.set(message)

    def set_busy(self, value):
        self.busy = value
        for button in (self.refresh_button, self.start_button, self.scan_button, self.add_files_button,
                       self.add_folder_button, self.remove_button, self.tools_button, self.add_videos_button):
            button.configure(state="disabled" if value else "normal")
        self.choose_videos_button.configure(state="disabled" if value or self.inventory is None else "normal")
        self.library_button.configure(state="disabled" if value or self.inventory is None else "normal")
        self.start_button.configure(state="disabled" if value or self.inventory is None else "normal")
        for control in self.option_controls:
            control.configure(state="disabled" if value else "normal")
        for control in (self.device_choice, self.kind_choice, self.photo_choice):
            control.configure(state="disabled" if value else "readonly")
        self.stop_button.configure(state="normal" if value else "disabled")
        if value:
            self.stop_event.clear()
            self.progress.stop()
            self.progress.configure(mode="indeterminate", value=0)
            self.progress.start(12)
        else:
            self.progress.stop()

    def worker(self, operation, result_kind):
        if self.busy:
            return
        self.set_busy(True)
        def work():
            try:
                self.events.put((result_kind, operation()))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=work, daemon=True).start()

    def find(self):
        if self.busy:
            return
        self.inventory = None
        self.video_selection.clear()
        self.update_video_summary()
        self.after_scan_message = None
        self.log_message("Looking for an iPod in Disk Mode…")
        self.worker(media.discover, "devices")

    def identity(self):
        index = self.device_choice.current()
        if not 0 <= index < len(self.devices):
            raise ValueError("Connect the iPod in Disk Mode, then choose Find iPod.")
        return self.devices[index]

    def browse_library(self):
        if self.busy or self.inventory is None:
            return
        from tools.studio.media_library_app import LibraryWindow
        def changed(result):
            if result.get("receipt"):
                self.receipt = result["receipt"]
                self.report_button.configure(state="normal")
            self.log_message(result["summary"])
            self.inventory = None
            self.start_button.configure(state="disabled")
            self.choose_videos_button.configure(state="disabled")
            for label in self.counts.values():
                label.configure(text="Scan required")
        dialog = LibraryWindow(self.window, self.identity(), changed)
        self.window.wait_window(dialog.window)
        if self.inventory is None:
            self.scan()

    def update_video_summary(self):
        count = len(self.video_selection)
        self.video_summary.set(f"{count:,} iPod video{'s' if count != 1 else ''} selected" if count else "No iPod videos selected")

    def device_changed(self, event=None):
        self.video_selection.clear()
        self.update_video_summary()
        self.scan()

    def choose_videos(self):
        if self.busy or self.inventory is None:
            return
        sources = self.inventory["Videos"].get("files", [])
        if not sources:
            self.log_message("No existing videos found on this iPod. Use Add videos… to choose files from your computer.")
            return
        root = Path(self.identity()["root"])
        dialog = tk.Toplevel(self.window)
        dialog.title("Choose videos on your iPod")
        dialog.geometry("700x450")
        dialog.minsize(520, 330)
        dialog.transient(self.window)
        body = ttk.Frame(dialog, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Select videos to convert to IPVF. Originals stay on the iPod.", wraplength=660).pack(anchor="w")
        ttk.Label(body, text="Existing IPVF files are added to the playback library as they are.", wraplength=660).pack(anchor="w", pady=(4, 10))
        rows = ttk.Frame(body)
        rows.pack(fill="both", expand=True)
        listing = tk.Listbox(rows, selectmode="multiple", exportselection=False, activestyle="none")
        vertical = ttk.Scrollbar(rows, orient="vertical", command=listing.yview)
        horizontal = ttk.Scrollbar(body, orient="horizontal", command=listing.xview)
        listing.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side="right", fill="y")
        listing.pack(side="left", fill="both", expand=True)
        horizontal.pack(fill="x")
        for index, source in enumerate(sources):
            listing.insert("end", str(Path(source).relative_to(root)))
            if source in self.video_selection:
                listing.selection_set(index)
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(12, 0))
        ttk.Button(actions, text="Select all", command=lambda: listing.selection_set(0, "end")).pack(side="left")
        ttk.Button(actions, text="Clear", command=lambda: listing.selection_clear(0, "end")).pack(side="left", padx=6)
        def accept():
            self.video_selection = {sources[index] for index in listing.curselection()}
            if self.video_selection:
                self.selected["Videos"].set(True)
            self.update_video_summary()
            dialog.destroy()
        ttk.Button(actions, text="Use selected videos", command=accept).pack(side="right")
        ttk.Button(actions, text="Cancel", command=dialog.destroy).pack(side="right", padx=6)
        dialog.grab_set()
        listing.focus_set()

    def scan(self):
        if self.busy:
            return
        self.inventory = None
        self.choose_videos_button.configure(state="disabled")
        for label in self.counts.values():
            label.configure(text="Not scanned")
        self.start_button.configure(state="disabled")
        try:
            identity = self.identity()
        except ValueError as error:
            self.log_message(error)
            return
        self.log_message("Scanning the four folders. Originals are unchanged.")
        def operation():
            current = media.refresh(identity)
            return current, media.scan(Path(current["root"]))
        self.worker(operation, "inventory")

    def add(self, paths):
        kind = self.kind_choice.get()
        for path in paths:
            item = (kind, path)
            if item not in self.pending:
                self.pending.append(item)
                self.pending_list.insert("end", f"{kind}  ←  {path}")
        self.selected[kind].set(True)

    def add_files(self):
        kind = self.kind_choice.get()
        pattern = " ".join("*" + ext for ext in sorted(media.extensions(kind)))
        self.add(filedialog.askopenfilenames(parent=self.window, title=f"Add {kind.lower()}",
                                            filetypes=[(kind, pattern), ("All files", "*.*")]))

    def add_videos(self):
        self.kind_choice.set("Videos")
        self.add_files()

    def add_folder(self):
        path = filedialog.askdirectory(parent=self.window, title=f"Add a folder to {self.kind_choice.get()}")
        if path:
            self.add([path])

    def remove(self):
        for index in reversed(self.pending_list.curselection()):
            self.pending.pop(index)
            self.pending_list.delete(index)

    def locate_tools(self):
        folder = filedialog.askdirectory(parent=self.window, title="Choose the folder containing ffmpeg.exe and ffprobe.exe")
        if folder:
            for name in ("ffmpeg", "ffprobe"):
                candidate = Path(folder) / (name + ".exe")
                if candidate.is_file():
                    setattr(self, name, str(candidate))
            self.update_tools_status()

    def start(self):
        if self.busy:
            return
        try:
            identity = self.identity()
            selected = [kind for kind in media.KINDS if self.selected[kind].get()]
            if not selected:
                raise ValueError("Choose at least one folder to update.")
            if self.inventory is None:
                raise ValueError("Scan the iPod before preparing content.")
            if "Music" in selected and not self.ffprobe and (self.inventory["Music"]["count"] or any(k == "Music" for k, p in self.pending)):
                raise ValueError("Locate FFmpeg and FFprobe before updating music.")
            video_sources = sorted(self.video_selection)
            needs_video_conversion = any(Path(path).suffix.lower() not in {".ipvf", ".ipv"} for path in video_sources)
            needs_video_conversion |= any(k == "Videos" and (Path(path).is_dir() or Path(path).suffix.lower() not in {".ipvf", ".ipv"}) for k, path in self.pending)
            if "Videos" in selected and (not self.ffmpeg or not self.ffprobe) and needs_video_conversion:
                raise ValueError("Locate FFmpeg and FFprobe before converting videos to IPVF.")
        except ValueError as error:
            self.log_message(error)
            return
        dimension = 2048 if self.photo_choice.current() == 1 else 640
        pending = [item for item in self.pending if item[0] in selected]
        self.submitted = list(pending)
        force = self.force.get()
        verification = "full" if self.full_music.get() else "metadata"
        self.worker(lambda: media.run(identity, selected, pending,
                    progress=lambda text: self.events.put(("progress", text)), cancelled=self.stop_event.is_set,
                    progress_detail=lambda event: self.events.put(("video_progress", event)),
                    photo_dimension=dimension, ffmpeg=self.ffmpeg, ffprobe=self.ffprobe, force=force,
                    music_verification=verification, video_selection=video_sources), "finished")

    def stop(self):
        self.stop_event.set()
        self.log_message("Stop requested. Waiting for the current preparation or publication step to finish…")

    def open_report(self):
        if self.receipt:
            try:
                os.startfile(self.receipt)
            except OSError as error:
                self.log_message(f"Could not open report: {error}. Report: {self.receipt}")

    def close(self):
        if self.busy:
            self.stop()
            self.log_message("Leave this window open until the current step finishes, then close it.")
        else:
            self.window.destroy()

    def drain(self):
        try:
            for _ in range(100):
                kind, value = self.events.get_nowait()
                if kind == "video_progress":
                    self.video_progress(value)
                    continue
                if kind == "progress":
                    self.indeterminate_progress()
                    self.log_message(value)
                    continue
                self.set_busy(False)
                if kind == "devices":
                    self.devices = value
                    self.inventory = None
                    self.start_button.configure(state="disabled")
                    for label in self.counts.values():
                        label.configure(text="Not scanned")
                    self.device_choice["values"] = [f"{d['drive']}  Apple iPod · {d['disk_serial']} · {size(d['free_bytes'])} free" for d in value]
                    if value:
                        self.device_choice.current(0)
                        self.scan()
                    else:
                        self.device_choice.set("")
                        self.device_status.set("No mounted iPod found. Connect it in Disk Mode, then choose Find iPod.")
                        self.log_message("Waiting for the iPod.")
                elif kind == "inventory":
                    identity, self.inventory = value
                    self.video_selection.intersection_update(self.inventory["Videos"].get("files", []))
                    self.update_video_summary()
                    self.choose_videos_button.configure(state="normal")
                    self.library_button.configure(state="normal")
                    self.devices[self.device_choice.current()] = identity
                    self.device_status.set(f"{identity['drive']}  •  {size(identity['free_bytes'])} free  •  Originals stay in their folders.")
                    for folder, item in self.inventory.items():
                        self.counts[folder].configure(text=f"{item['count']:,} files · {size(item['bytes'])}")
                        if item["ignored"]:
                            self.log_message(f"{folder}: {item['ignored']:,} supporting or unsupported files will not be imported as media.")
                    self.start_button.configure(state="normal")
                    self.log_message(self.after_scan_message or "Scan complete. Choose folders, add optional content, then Prepare & update iPod.")
                    self.after_scan_message = None
                elif kind == "finished":
                    self.receipt = value["receipt"]
                    self.report_button.configure(state="normal")
                    if value["complete"]:
                        self.pending = [item for item in self.pending if item not in self.submitted]
                        self.pending_list.delete(0, "end")
                        for folder, path in self.pending:
                            self.pending_list.insert("end", f"{folder}  ←  {path}")
                        self.after_scan_message = "Update complete. Safely eject the iPod and restart Linnet."
                        if self.pending:
                            self.after_scan_message += " Unchecked additions are still queued for a later update."
                        self.log_message("Update complete. Refreshing the folder counts…")
                    else:
                        self.after_scan_message = value.get("summary") or ("Update stopped. Completed work is retained." if value.get("stopped")
                                                   else "Some folders could not finish.")
                        if value.get("cleanup", {}).get("retained"):
                            self.after_scan_message += " Leftover files need review; Open report lists their locations."
                        else:
                            self.after_scan_message += " Temporary preparation files cleaned up. Open report for details."
                        self.log_message(self.after_scan_message)
                    self.submitted = []
                    self.scan()
                elif kind == "error":
                    self.inventory = None
                    self.after_scan_message = None
                    self.start_button.configure(state="disabled")
                    self.choose_videos_button.configure(state="disabled")
                    for label in self.counts.values():
                        label.configure(text="Scan required")
                    self.log_message(f"{value} Scan again after resolving this issue.")
        except queue.Empty:
            pass
        self.window.after(100, self.drain)


def launch():
    if os.name != "nt":
        raise RuntimeError("The desktop media manager currently supports Windows Disk Mode.")
    window = tk.Tk()
    MediaApp(window)
    window.mainloop()
