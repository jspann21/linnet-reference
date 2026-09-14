"""Browse device content and review reversible removals."""
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from tools.content import media_library
from tools.content import media_trash
from datetime import datetime


class LibraryWindow:
    def __init__(self, parent, identity, on_change):
        self.identity, self.on_change = identity, on_change
        self.rows, self.events, self.busy = {}, queue.Queue(), False
        self.operation_kind = None
        self.search_timer = None
        self.window = tk.Toplevel(parent)
        self.window.title("Linnet · Manage libraries & Trash")
        self.window.geometry("1100x660")
        self.window.minsize(850, 500)
        self.window.transient(parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Library on {identity['root']}", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(body, text="Manage entire prepared libraries here. Browse individual media in the main workspace.").pack(anchor="w", pady=5)
        filters = ttk.Frame(body)
        filters.pack(fill="x", pady=8)
        self.kind = tk.StringVar(value="Prepared libraries")
        picker = ttk.Combobox(filters, textvariable=self.kind, values=("Prepared libraries", "Trash"), state="readonly", width=22)
        picker.pack(side="left")
        picker.bind("<<ComboboxSelected>>", lambda _: self.render())
        ttk.Label(filters, text="Search").pack(side="left", padx=(16, 6))
        self.search = tk.StringVar()
        ttk.Entry(filters, textvariable=self.search).pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", self.schedule_search)
        self.refresh_button = ttk.Button(filters, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="left", padx=(8, 0))
        grid = ttk.Frame(body)
        grid.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(grid, columns=("kind", "title", "status", "size"), show="headings", selectmode="extended")
        for key, title, width in (("kind", "Folder", 75), ("title", "Item", 410), ("status", "Status", 270), ("size", "Size", 90)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=60)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(grid, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.selection)
        self.details = tk.StringVar(value="Loading…")
        ttk.Label(body, textvariable=self.details, wraplength=1000).pack(anchor="w", pady=8)
        actions = ttk.Frame(body)
        actions.pack(fill="x")
        self.open_button = ttk.Button(actions, text="Open containing folder", command=self.open_folder, state="disabled")
        self.open_button.pack(side="left")
        self.remove_button = ttk.Button(actions, text="Remove selected from iPod…", command=self.remove, state="disabled")
        self.remove_button.pack(side="left", padx=8)
        self.restore_button = ttk.Button(actions, text="Restore removal", command=self.restore, state="disabled")
        self.restore_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Close", command=self.close).pack(side="right")
        self.status = tk.StringVar()
        ttk.Label(body, textvariable=self.status, wraplength=1000).pack(anchor="w", pady=(8, 0))
        self.window.after(100, self.drain)
        self.refresh()

    def work(self, operation, kind):
        if self.busy:
            return
        self.busy = True
        self.operation_kind = kind
        self.refresh_button.configure(state="disabled")
        self.remove_button.configure(state="disabled")
        def worker():
            try:
                self.events.put((kind, operation()))
            except Exception as error:
                self.events.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def refresh(self):
        self.status.set("Reading the library…")
        def load():
            rows = [r for r in media_library.list_items(self.identity) if r['category'] == 'library']
            for removal in media_trash.removals(self.identity):
                rows.append(dict(removal, category='trash', kind='Trash', status='Recoverable · ' + datetime.fromtimestamp(removal['started']).strftime('%b %d, %H:%M'), removable=True))
            return rows
        self.work(load, "loaded")

    def schedule_search(self, *_):
        if self.search_timer is not None:
            self.window.after_cancel(self.search_timer)
        self.search_timer = self.window.after(150, self.render)

    def render(self):
        if self.search_timer is not None:
            self.window.after_cancel(self.search_timer)
            self.search_timer = None
        self.tree.delete(*self.tree.get_children())
        query = self.search.get().casefold()
        kind = self.kind.get()
        for key, row in self.rows.items():
            if (kind == 'Trash') != (row['category'] == 'trash'):
                continue
            if query and query not in " ".join(str(row.get(field, "")) for field in ("title", "path", "source", "status")).casefold():
                continue
            size = row.get("bytes", 0)
            label = f"{size / 1048576:,.1f} MB" if size >= 1048576 else f"{size / 1024:,.1f} KB"
            self.tree.insert("", "end", iid=key, values=(row["kind"], row["title"], row["status"], label))
        self.selection()

    def selection(self, _=None):
        rows = [self.rows[key] for key in self.tree.selection()]
        self.remove_button.configure(state="normal" if rows and not self.busy and all(row.get("removable", False) for row in rows) else "disabled")
        trash = bool(rows) and all(r['category'] == 'trash' for r in rows)
        self.remove_button.configure(text='Permanently delete removal…' if self.kind.get() == 'Trash' else 'Remove prepared library…', state='normal' if rows and not self.busy and (not trash or len(rows) == 1) else 'disabled')
        self.restore_button.configure(state='normal' if trash and len(rows) == 1 and not self.busy else 'disabled')
        self.open_button.configure(state="normal" if len(rows) == 1 else "disabled")
        if len(rows) == 1:
            row = rows[0]
            self.details.set(f"{row['status']}\nLocation: {row['path']}" +
                (f"\nSource: {row['source']}" if row.get("source") and row['source'] != row['path'] else "") +
                (f"\n{row['description']}" if row.get("description") else ""))
        else:
            self.details.set(f"{len(rows):,} selected · {len(self.tree.get_children()):,} items shown")

    def open_folder(self):
        rows = self.tree.selection()
        if len(rows) == 1:
            try:
                os.startfile(str(Path(self.rows[rows[0]]["path"]).parent))
            except OSError as error:
                messagebox.showerror("Could not open folder", str(error), parent=self.window)

    def remove(self):
        rows = [self.rows[key] for key in self.tree.selection()]
        if self.busy or not rows or not all(row.get("removable", False) for row in rows):
            return
        if rows[0]['category'] == 'trash':
            if len(rows) == 1 and messagebox.askokcancel('Permanently delete removal', f"Permanently delete {rows[0]['title']}?\n\nThis frees {rows[0]['bytes'] / 1048576:,.1f} MB on the iPod. These files cannot be restored afterward.", parent=self.window):
                self.work(lambda: media_trash.recover(self.identity, rows[0]['id'], erase=True), 'removed')
            return
        names = "\n".join(row['title'] for row in rows[:8])
        if len(rows) > 8:
            names += f"\n… and {len(rows) - 8} more"
        libraries = [row['kind'] for row in rows if row.get('category') == 'library']
        if libraries:
            names += "\n\nThis removes the ENTIRE published library for: " + ", ".join(libraries)
        if not messagebox.askokcancel("Remove selected content", f"Remove these {len(rows)} item(s)?\n\n{names}\n\nFiles are moved to LINNET\\TRASH on the iPod for recovery; this does not free disk space. Video catalog entries are removed immediately. After removing Music, Notes or Photos source files, run Prepare & update for those folders to refresh their libraries.", parent=self.window):
            return
        self.status.set("Removing selected items… Leave this window open.")
        self.work(lambda: media_library.remove_items(self.identity, rows), "removed")

    def restore(self):
        rows = [self.rows[key] for key in self.tree.selection()]
        if len(rows) == 1 and rows[0]['category'] == 'trash' and not self.busy:
            self.status.set('Restoring files and playback entries…')
            self.work(lambda: media_trash.recover(self.identity, rows[0]['id']), 'removed')

    def drain(self):
        try:
            kind, result = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.refresh_button.configure(state="normal")
            if kind == "loaded":
                self.rows = {str(index): row for index, row in enumerate(result)}
                self.render()
                self.status.set('Removing a prepared library retains originals. Trash remains on the iPod until permanently deleted.')
            elif kind == "removed":
                self.on_change(result)
                messagebox.showinfo("Removal complete", result['summary'] + f"\n\nReport: {result['receipt']}", parent=self.window)
                self.refresh()
            else:
                if self.operation_kind == "removed":
                    self.on_change(dict(summary=result))
                    self.rows = {}
                    self.render()
                self.status.set(result)
                messagebox.showerror("Library needs attention", result, parent=self.window)
                self.selection()
        if self.window.winfo_exists():
            self.window.after(100, self.drain)

    def close(self):
        if self.busy:
            self.status.set("Wait for the current library operation to finish before closing.")
            return
        if self.search_timer is not None:
            self.window.after_cancel(self.search_timer)
            self.search_timer = None
        self.window.grab_release()
        self.window.destroy()
