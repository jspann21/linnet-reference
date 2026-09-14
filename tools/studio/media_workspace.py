"""Library-first desktop workspace for preparing Linnet media."""
import os
import queue
import shutil
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from .media_app import MediaApp, size
from tools.content import media_manager as media, media_library, media_status


class MediaWorkspace(MediaApp):
    def __init__(self, window):
        self.window = window
        window.title('Linnet · Media library')
        window.geometry('1280x960')
        window.minsize(1100, 800)
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.busy = False
        self.devices, self.pending, self.submitted = [], [], []
        self.inventory = self.receipt = self.after_scan_message = None
        self.video_selection = set()
        self.video_enabled = True
        self.rows, self.readiness = [], {}
        self.option_controls = []
        self.ffmpeg, self.ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        self.selected = {k: tk.BooleanVar(value=True) for k in media.KINDS}
        self.update_checks = {}
        self.video_summary = tk.StringVar(value='Select source videos below to make them playable.')
        self.force, self.full_music = tk.BooleanVar(), tk.BooleanVar()
        self.search, self.filter = tk.StringVar(), tk.StringVar(value='All states')
        self.current_kind = 'Music'
        self.sort_key, self.sort_reverse = 'title', False
        self.search_timer = None
        self.plan_generation = 0
        self.plan_timer = None
        self.plan_ready = False
        self.build()
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(100, self.drain)
        window.after(250, self.find)

    def build(self):
        w = self.window
        w.configure(bg='#f3f5f8')
        style = ttk.Style(w)
        style.theme_use('clam')
        style.configure('.', background='#f3f5f8', foreground='#17283b', font=('Segoe UI', 10))
        style.configure('TFrame', background='#f3f5f8')
        style.configure('TLabel', background='#f3f5f8')
        style.configure('Title.TLabel', font=('Segoe UI', 25, 'bold'))
        style.configure('Heading.TLabel', font=('Segoe UI', 15, 'bold'))
        style.configure('Muted.TLabel', foreground='#52677d')
        style.configure('TButton', padding=(12, 7), background='#ffffff', borderwidth=1)
        style.map('TButton', background=[('active', '#e5edf6')], foreground=[('disabled', '#83909e')])
        style.configure('Accent.TButton', background='#245cdb', foreground='white', font=('Segoe UI', 10, 'bold'))
        style.map('Accent.TButton', background=[('disabled', '#dce3ef'), ('active', '#1749b8')], foreground=[('disabled', '#65778d')])
        style.configure('Treeview', background='white', fieldbackground='white', rowheight=33, borderwidth=0)
        style.configure('Treeview.Heading', background='#e9eef5', padding=8, font=('Segoe UI', 9, 'bold'))
        style.map('Treeview', background=[('selected', '#dce8ff')], foreground=[('selected', '#142f62')])
        style.layout('Category.Toolbutton', [('Toolbutton.padding', {'sticky': 'nswe', 'children': [
            ('Toolbutton.focus', {'sticky': 'nswe', 'children': [('Toolbutton.label', {'sticky': 'nswe'})]})]})])
        style.configure('Category.Toolbutton', padding=(18, 10), anchor='center', background='#e9eef5')
        style.map('Category.Toolbutton', background=[('selected', '#f3f5f8'), ('active', '#dce8ff')], foreground=[('selected', '#245cdb'), ('!selected', '#52677d')])
        style.configure('CategoryStrip.TFrame', background='#e9eef5')
        style.configure('Horizontal.TProgressbar', background='#245cdb', troughcolor='#e1e7f0', borderwidth=0)
        shell = ttk.Frame(w)
        shell.pack(fill='both', expand=True)
        canvas = tk.Canvas(shell, background='#f3f5f8', highlightthickness=0)
        scroll = ttk.Scrollbar(shell, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        shell.rowconfigure(0, weight=1)
        shell.columnconfigure(0, weight=1)
        canvas.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        scroll.grid_remove()
        body = ttk.Frame(canvas, padding=(22, 18, 10, 6))
        content = canvas.create_window(0, 0, window=body, anchor='nw')

        def resize_library(_=None):
            canvas.itemconfigure(content, width=canvas.winfo_width())
            bounds = canvas.bbox('all')
            canvas.configure(scrollregion=bounds)
            if bounds and bounds[3] - bounds[1] > canvas.winfo_height():
                scroll.grid()
            else:
                scroll.grid_remove()
                canvas.yview_moveto(0)

        body.bind('<Configure>', resize_library)
        canvas.bind('<Configure>', resize_library)
        self.window.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-int(e.delta / 120), 'units') if e.widget.winfo_class() != 'Treeview' else None, add='+')
        top = ttk.Frame(body)
        top.pack(fill='x')
        ttk.Label(top, text='Your library. Ready to go.', style='Title.TLabel').pack(side='left')
        self.refresh_button = ttk.Button(top, text='Find iPod', command=self.find)
        self.refresh_button.pack(side='right')
        self.installer_button = ttk.Button(top, text='Install / switch build…', command=self.open_installer)
        self.installer_button.pack(side='right', padx=8)
        device = ttk.Frame(body)
        device.pack(fill='x', pady=(12, 3))
        self.device_choice = ttk.Combobox(device, state='readonly', width=54)
        self.device_choice.pack(side='left')
        self.device_choice.bind('<<ComboboxSelected>>', self.device_changed)
        self.scan_button = ttk.Button(device, text='Refresh library', command=self.scan)
        self.scan_button.pack(side='left', padx=8)
        self.device_status = tk.StringVar(value='Connect your iPod in Disk Mode to get started.')
        ttk.Label(body, textvariable=self.device_status, style='Muted.TLabel').pack(anchor='w', pady=(2, 12))
        self.library_panel = tk.Frame(body, background='#f3f5f8', highlightbackground='#c8d2df', highlightthickness=1, borderwidth=0)
        self.library_panel.pack(fill='both', expand=True)
        self.tabs = ttk.Frame(self.library_panel, style='CategoryStrip.TFrame')
        self.tabs.pack(fill='x')
        self.category = tk.StringVar(value='Music')
        self.category_buttons = []
        self.category_indicators = []
        for index, kind in enumerate(media.KINDS):
            button = ttk.Radiobutton(self.tabs, text=kind, value=kind, variable=self.category,
                                     style='Category.Toolbutton', command=self.change_kind, width=9)
            button.grid(row=0, column=index, sticky='nsew')
            indicator = tk.Frame(self.tabs, height=3, background='#c8d2df')
            indicator.grid(row=1, column=index, sticky='ew')
            self.category_indicators.append(indicator)
            button.bind('<Left>', lambda e, i=index: self.select_category((i - 1) % len(media.KINDS)))
            button.bind('<Right>', lambda e, i=index: self.select_category((i + 1) % len(media.KINDS)))
            self.category_buttons.append(button)
        self.tabs.columnconfigure(len(media.KINDS), weight=1)
        tk.Frame(self.tabs, height=3, background='#c8d2df').grid(row=1, column=len(media.KINDS), sticky='ew')
        body = ttk.Frame(self.library_panel, padding=(12, 0, 12, 12))
        body.pack(fill='both', expand=True)
        heading = ttk.Frame(body)
        heading.pack(fill='x', pady=(14, 8))
        self.heading = tk.StringVar(value='Music')
        ttk.Label(heading, textvariable=self.heading, style='Heading.TLabel').pack(side='left')
        self.category_status = tk.StringVar(value='Connect an iPod to browse your library')
        ttk.Label(heading, textvariable=self.category_status, style='Muted.TLabel').pack(side='left', padx=16)
        self.library_button = ttk.Button(heading, text='Manage libraries & Trash', command=self.browse_library, state='disabled')
        self.library_button.pack(side='right')
        bar = ttk.Frame(body)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Label(bar, text='Search').pack(side='left', padx=(0, 8))
        ttk.Entry(bar, textvariable=self.search).pack(side='left', fill='x', expand=True)
        filt = ttk.Combobox(bar, textvariable=self.filter, values=('All states', 'Originals', 'Ready on iPod', 'Computer copies', 'Needs attention'), state='readonly', width=19)
        filt.pack(side='left', padx=8)
        filt.bind('<<ComboboxSelected>>', lambda _: self.render())
        self.search.trace_add('write', self.schedule_search)
        self.add_files_button = ttk.Button(bar, text='Add files…', command=self.add_files)
        self.add_files_button.pack(side='left')
        self.add_folder_button = ttk.Button(bar, text='Add folder…', command=self.add_folder)
        self.add_folder_button.pack(side='left', padx=(8, 0))
        self.tree = self.make_tree(body, ('title', 'status', 'size'), ('Item', 'Availability', 'Size'), (440, 280, 100), height=4)
        self.tree.bind('<<TreeviewSelect>>', self.selection_changed)
        self.tree.bind('<Double-1>', lambda _: self.open_selected())
        row = ttk.Frame(body)
        row.pack(fill='x', pady=7)
        self.details = tk.StringVar(value='No iPod connected. Your library will appear here.')
        ttk.Label(row, textvariable=self.details, style='Muted.TLabel', wraplength=560).pack(side='left', fill='x', expand=True)
        self.open_button = ttk.Button(row, text='Show in folder', command=self.open_selected, state='disabled')
        self.open_button.pack(side='right')
        self.delete_button = ttk.Button(row, text='Move to Trash…', command=self.remove_selected, state='disabled')
        self.delete_button.pack(side='right', padx=8)
        self.choose_videos_button = ttk.Button(row, text='Include selected videos', command=self.include_videos, state='disabled')
        self.choose_videos_button.pack(side='right')
        self.video_label = ttk.Label(body, textvariable=self.video_summary, style='Muted.TLabel', wraplength=850)
        self.video_label.pack(anchor='w', fill='x')
        self.video_label.bind('<Configure>', lambda e: self.video_label.configure(wraplength=max(300, e.width)))
        body = ttk.Frame(w, padding=(22, 10, 22, 16))
        body.pack(fill='x')
        body.bind('<Configure>', lambda e: [child.configure(wraplength=max(300, e.width - 44)) for child in body.winfo_children() if isinstance(child, ttk.Label)])
        ttk.Separator(body).pack(fill='x', pady=(0, 8))
        queuebar = ttk.Frame(body)
        queuebar.pack(fill='x', pady=(10, 6))
        ttk.Label(queuebar, text='Next update', style='Heading.TLabel').pack(side='left')
        self.remove_button = ttk.Button(queuebar, text='Remove from queue', command=self.remove, state='disabled')
        self.remove_button.pack(side='right')
        self.pending_list = self.make_tree(body, ('kind', 'title', 'destination', 'status'), ('Type', 'Addition', 'Destination', 'Review'), (75, 330, 220, 240), height=2, expand=False)
        self.pending_list.bind('<<TreeviewSelect>>', lambda _: self.remove_button.configure(state='normal' if self.pending_list.selection() and not self.busy else 'disabled'))
        opts = ttk.Frame(body)
        opts.pack(fill='x', pady=8)
        self.queue_options = opts
        self.queue_empty = ttk.Label(body, text='No additions queued. Add files above, or update the content already on your iPod.', style='Muted.TLabel')
        self.queue_empty.pack(before=opts, anchor='w', pady=6)
        self.pending_list.master.pack_forget()
        ttk.Label(opts, text='Update:').pack(side='left', padx=(0, 8))
        self.counts = {}
        for kind in media.KINDS:
            cb = ttk.Checkbutton(opts, text=kind, variable=self.selected[kind], command=self.schedule_plan)
            cb.pack(side='left', padx=(0, 10))
            self.option_controls.append(cb)
            self.update_checks[kind] = cb
        self.tools_button = ttk.Button(opts, text='Settings', command=self.settings)
        self.tools_button.pack(side='right')
        self.tools_status = tk.StringVar()
        self.update_tools_status()
        self.plan_text = tk.StringVar(value='Connect an iPod to review an update.')
        ttk.Label(body, textvariable=self.plan_text, wraplength=1080).pack(anchor='w')
        action = ttk.Frame(body)
        action.pack(fill='x', pady=(9, 5))
        self.start_button = ttk.Button(action, text='Update iPod', style='Accent.TButton', command=self.start, state='disabled')
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(action, text='Stop after current step', command=self.stop, state='disabled')
        self.stop_button.pack(side='left', padx=8)
        self.eject_button = ttk.Button(action, text='Eject iPod', command=self.eject, state='disabled')
        self.eject_button.pack(side='left')
        self.report_button = ttk.Button(action, text='Open detailed report', command=self.open_report, state='disabled')
        self.report_button.pack(side='right')
        self.progress = ttk.Progressbar(body, mode='indeterminate')
        self.progress.pack(fill='x', pady=(4, 5))
        self.status = tk.StringVar(value='Looking for your iPod…')
        ttk.Label(body, textvariable=self.status, wraplength=1080, style='Muted.TLabel').pack(anchor='w')
        self.results = tk.StringVar(value='Completed updates and anything needing attention will stay here.')
        result_frame = ttk.Frame(body)
        result_frame.pack(fill='x', pady=(7, 0))
        self.result_view = tk.Text(result_frame, height=3, wrap='word', state='disabled', font=('Segoe UI', 10), background='#e9eef5', foreground='#17283b', relief='flat', padx=10, pady=7)
        result_scroll = ttk.Scrollbar(result_frame, command=self.result_view.yview)
        self.result_view.configure(yscrollcommand=result_scroll.set)
        self.result_view.pack(side='left', fill='x', expand=True)
        result_scroll.pack(side='right', fill='y')
        self.results.trace_add('write', self.render_results)
        self.render_results()
        # Existing preparation methods use these variables as their option adapters.
        self.kind_choice = ttk.Combobox(w, values=media.KINDS)
        self.kind_choice.set('Music')
        self.photo_choice = ttk.Combobox(w, values=('Standard (640 px)', 'High (2048 px)'))
        self.photo_choice.current(0)
        self.add_videos_button = self.add_files_button
        self.change_kind()

    def render_results(self, *_):
        self.result_view.configure(state='normal')
        self.result_view.delete('1.0', 'end')
        self.result_view.insert('end', self.results.get())
        self.result_view.configure(state='disabled')

    def open_installer(self):
        from tools.studio.installer_app import InstallerWindow
        identity = None
        try:
            identity = self.identity()
        except ValueError:
            pass
        InstallerWindow(self.window, identity, on_changed=self.scan)

    def make_tree(self, parent, columns, labels, widths, height, expand=True):
        frame = ttk.Frame(parent)
        frame.pack(fill='both' if expand else 'x', expand=expand)
        tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='extended', height=height)
        for key, label, width in zip(columns, labels, widths):
            tree.heading(key, text=label, command=lambda k=key: self.sort(k) if k in ('title', 'status', 'size') else None)
            tree.column(key, width=width, minwidth=60)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        return tree

    def log_message(self, message):
        self.status.set(str(message))

    def set_busy(self, value):
        super().set_busy(value)
        self.start_button.configure(state='normal' if not value and self.plan_ready and self.inventory else 'disabled')
        self.selection_changed()
        self.remove_button.configure(state='normal' if not value and self.pending_list.selection() else 'disabled')
        self.eject_button.configure(state='normal' if not value and self.inventory else 'disabled')
        if not value:
            self.progress.configure(value=0)

    def change_kind(self, _=None):
        self.current_kind = self.category.get()
        for kind, indicator in zip(media.KINDS, self.category_indicators):
            indicator.configure(background='#245cdb' if kind == self.current_kind else '#c8d2df')
        self.kind_choice.set(self.current_kind)
        self.heading.set(self.current_kind)
        if self.current_kind == 'Videos' and self.video_enabled:
            self.choose_videos_button.pack(side='right')
        else:
            self.choose_videos_button.pack_forget()
        available = self.current_kind != 'Videos' or self.video_enabled
        self.add_files_button.configure(state='normal' if available and not self.busy else 'disabled')
        self.add_folder_button.configure(state='normal' if available and not self.busy else 'disabled')
        self.update_video_summary()
        self.render()

    def select_category(self, index):
        self.category.set(media.KINDS[index])
        self.category_buttons[index].focus_set()
        self.change_kind()
        return 'break'

    def update_video_summary(self):
        self.video_summary.set(('Video playback is unavailable on this iPod model; original files remain visible and untouched.' if not self.video_enabled else
            f'{len(self.video_selection)} device videos included in next update. Select originals above to include them.') if self.current_kind == 'Videos' else {'Music': 'Add files or a folder to queue new songs. To refresh songs or cover art changed in the iPod’s Music folder, choose Refresh library, then Update iPod. Adding a different file with the same name does not overwrite it.', 'Photos': 'Add photos to the queue, then Update iPod to create browsing and zoom copies. Originals are kept.', 'Notes': 'Add text or Markdown files to the queue, then Update iPod to make them readable in Linnet.'}[self.current_kind])

    def schedule_search(self, *_):
        if self.search_timer:
            self.window.after_cancel(self.search_timer)
        self.search_timer = self.window.after(150, self.render)

    def sort(self, key):
        self.sort_reverse = not self.sort_reverse if self.sort_key == key else False
        self.sort_key = key
        self.render()

    def render(self):
        self.search_timer = None
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        kind, query, state = self.current_kind, self.search.get().casefold(), self.filter.get()
        summary = self.readiness.get(kind, 'Not scanned')
        if self.inventory:
            inventory = self.inventory[kind]
            summary += f" · {inventory['count']:,} sources · {size(inventory['bytes'])}"
            if inventory['ignored']:
                summary += f" · {inventory['ignored']} other files not indexed"
        self.category_status.set(summary)
        rows = [(str(i), r) for i, r in enumerate(self.rows) if r['kind'] == kind and r['category'] != 'library']
        rows.sort(key=lambda p: p[1].get('bytes', 0) if self.sort_key == 'size' else str(p[1].get(self.sort_key, '')).casefold(), reverse=self.sort_reverse)
        for key, r in rows:
            if query not in (r['title'] + ' ' + r['path'] + ' ' + r['status']).casefold():
                continue
            category = r['category']
            if state == 'Originals' and category != 'original' or state == 'Computer copies' and category != 'cache' or state == 'Ready on iPod' and not (category == 'published' and r['status'] == 'Ready on iPod' or category == 'original' and self.readiness.get(kind) == 'Ready') or state == 'Needs attention' and not ('Missing' in r['status'] or self.readiness.get(kind) in ('Needs update', 'Not prepared')):
                continue
            status = r['status']
            if category == 'original' and kind != 'Videos':
                status = self.readiness.get(kind, status)
            if category == 'original' and r['path'] in self.video_selection:
                status = 'Included in next update'
            self.tree.insert('', 'end', iid=key, values=(r['title'], status, size(r['bytes'])))
            if key in selected:
                self.tree.selection_add(key)
        self.selection_changed()

    def selected_rows(self):
        return [self.rows[int(i)] for i in self.tree.selection()]

    def selection_changed(self, _=None):
        if not hasattr(self, 'tree'):
            return
        rows = self.selected_rows()
        enabled = bool(rows) and not self.busy
        removable = enabled and all(r['removable'] for r in rows)
        self.delete_button.configure(state='normal' if removable else 'disabled')
        self.open_button.configure(state='normal' if len(rows) == 1 and not self.busy else 'disabled')
        self.choose_videos_button.configure(state='normal' if self.video_enabled and enabled and all(r['kind'] == 'Videos' and r['category'] == 'original' for r in rows) else 'disabled')
        if rows:
            self.details.set(rows[0]['path'] if len(rows) == 1 else f'{len(rows)} selected · {size(sum(r["bytes"] for r in rows))}')
        else:
            count = len(self.tree.get_children())
            self.details.set(f'{count:,} items shown' if count else 'No matching items. Clear filters or add content to this category.' if self.inventory else 'Connect an iPod in Disk Mode to see your library.')

    def open_selected(self):
        rows = self.selected_rows()
        if len(rows) == 1 and not self.busy:
            try:
                os.startfile(str(Path(rows[0]['path']).parent))
            except OSError as error:
                self.status.set(str(error))

    def include_videos(self):
        if self.busy or not self.video_enabled:
            return
        self.video_selection.update(r['path'] for r in self.selected_rows() if r['category'] == 'original' and r['kind'] == 'Videos')
        self.selected['Videos'].set(True)
        self.update_video_summary()
        self.render_queue()
        self.render()
        self.schedule_plan()

    def add(self, paths):
        if not paths:
            return
        kind = self.kind_choice.get()
        if kind == 'Videos' and not self.video_enabled:
            self.status.set('Video playback is unavailable on this iPod model.')
            return
        for path in paths:
            if (kind, path) not in self.pending:
                self.pending.append((kind, path))
        self.selected[kind].set(True)
        self.render_queue()
        self.schedule_plan()
        self.status.set('Added to the queue. Choose Update iPod to copy and prepare these files; nothing has been copied yet.')

    def render_queue(self, review='Checking…', previews=None):
        if self.pending or self.video_selection:
            self.queue_empty.pack_forget()
            self.pending_list.master.pack(fill='x', before=self.queue_options)
        else:
            self.pending_list.master.pack_forget()
            self.queue_empty.pack(before=self.queue_options, anchor='w', pady=6)
        self.pending_list.delete(*self.pending_list.get_children())
        for i, (kind, path) in enumerate(self.pending):
            label = (previews or {}).get(path, review)
            self.pending_list.insert('', 'end', iid=f'p{i}', values=(kind, Path(path).name, 'Playback copy on iPod' if kind == 'Videos' else f'{kind}/{Path(path).name}', label if self.selected[kind].get() else 'Excluded — category unchecked'))
        for i, path in enumerate(sorted(self.video_selection)):
            self.pending_list.insert('', 'end', iid=f'v{i}', values=('Videos', Path(path).name, 'Playback library', review if self.selected['Videos'].get() else 'Excluded — Videos unchecked'))

    def remove(self):
        if self.busy:
            return
        chosen = self.pending_list.selection()
        videos = sorted(self.video_selection)
        for key in chosen:
            if key.startswith('v'):
                self.video_selection.discard(videos[int(key[1:])])
        for index in sorted((int(k[1:]) for k in chosen if k.startswith('p')), reverse=True):
            self.pending.pop(index)
        self.update_video_summary()
        self.render_queue()
        self.render()
        self.schedule_plan()

    def schedule_plan(self):
        self.plan_generation += 1
        self.plan_ready = False
        self.start_button.configure(state='disabled')
        self.render_queue('Waiting for library scan' if self.inventory is None else 'Checking…')
        if self.inventory is None:
            self.plan_text.set('Connect an iPod and refresh the library to review the update. Queued additions stay on your computer until you choose Update iPod.')
        if self.plan_timer:
            self.window.after_cancel(self.plan_timer)
        self.plan_timer = self.window.after(250, self.check_plan)

    def check_plan(self):
        self.plan_timer = None
        if self.busy or self.inventory is None:
            return
        generation = self.plan_generation
        identity = self.identity()
        pending, videos = list(self.pending), sorted(self.video_selection)
        selected = [k for k in media.KINDS if self.selected[k].get()]
        inventory = self.inventory
        ffmpeg, ffprobe = self.ffmpeg, self.ffprobe
        self.plan_text.set('Reviewing additions, available storage, and destinations…')
        self.render_queue()
        def work():
            try:
                result = media_status.plan(identity, pending, selected, videos)
                if 'Music' in selected and not ffprobe and (inventory['Music']['count'] or any(k == 'Music' for k, p in pending)):
                    raise ValueError('Music needs FFprobe. Open Settings to locate FFmpeg and FFprobe.')
                if result['conversion'] and (not ffmpeg or not ffprobe):
                    raise ValueError('Video conversion needs FFmpeg and FFprobe. Locate them in Settings.')
                if 'Photos' in selected and (inventory['Photos']['count'] or any(k == 'Photos' for k, p in pending)):
                    try:
                        import PIL  # noqa: F401
                    except ImportError:
                        raise ValueError('Photo preparation needs Pillow. Install it with: python -m pip install Pillow')
                self.events.put(('plan', (generation, selected, result, None)))
            except Exception as error:
                self.events.put(('plan', (generation, selected, None, str(error))))
        threading.Thread(target=work, daemon=True).start()

    def scan(self):
        if self.busy:
            return
        try:
            identity = self.identity()
        except ValueError as error:
            self.status.set(str(error))
            return
        self.inventory = None
        self.plan_generation += 1
        self.plan_ready = False
        self.status.set('Reading source folders and verifying prepared libraries…')
        dimension = 2048 if self.photo_choice.current() == 1 else 640
        verification = 'full' if self.full_music.get() else 'metadata'
        self.worker(lambda: media_status.inspect(identity, dimension, verification), 'inspected')

    def find(self):
        if self.busy:
            return
        self.inventory = None
        self.rows, self.readiness = [], {}
        self.video_selection.clear()
        self.plan_generation += 1
        self.plan_ready = False
        self.render()
        self.status.set('Looking for an iPod in Disk Mode…')
        self.worker(media.discover, 'devices')

    def start(self):
        if self.plan_ready:
            self.plan_generation += 1
            self.submitted_videos = set(self.video_selection) if self.selected['Videos'].get() else set()
            super().start()
            if self.busy:
                self.plan_text.set('Update in progress. Keep the iPod connected until copying, preparation, and verification finish.')
                self.render_queue('In this update')
                self.results.set('Updating your iPod… Completed work and any errors will appear here.')

    def eject(self):
        if self.busy or self.inventory is None:
            return
        identity = self.identity()
        self.plan_generation += 1
        def operation():
            from tools.content.publish_photos import _exclusive
            from tools.link.eject import eject
            with _exclusive(identity):
                current = media.refresh(identity)
                return eject(current['disk_number'], current['disk_serial'], wait_link=False)
        self.status.set('Asking Windows to safely eject the iPod…')
        self.worker(operation, 'ejected')

    def remove_selected(self):
        rows = self.selected_rows()
        if self.busy or not rows or not all(r['removable'] for r in rows):
            return
        descriptions = '\n'.join(f"• {r['title']}: {r['description']}" for r in rows[:6])
        if messagebox.askokcancel('Move selected content to Trash', f'{len(rows)} selected item(s)\n\n{descriptions}\n\nRecoverable files stay on the iPod and do not free space until Trash is emptied. Sources may need a library update afterward.', parent=self.window):
            identity = self.identity()
            self.worker(lambda: media_library.remove_items(identity, rows), 'removed')

    def browse_library(self):
        if self.busy or self.inventory is None:
            return
        from .media_library_app import LibraryWindow
        def changed(result):
            self.receipt = result.get('receipt', self.receipt)
            self.results.set(result['summary'])
            self.inventory = None
        dialog = LibraryWindow(self.window, self.identity(), changed)
        self.window.wait_window(dialog.window)
        self.scan()

    def settings(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.window)
        dialog.title('Media settings')
        dialog.transient(self.window)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Preparation settings', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(frame, text='Photos · Zoom detail', padding=(0, 15, 0, 6)).pack(anchor='w')
        photo = ttk.Combobox(frame, values=self.photo_choice['values'], state='readonly', width=30)
        photo.current(self.photo_choice.current())
        photo.pack(anchor='w')
        ttk.Label(frame, text='High detail uses more storage and takes longer to prepare.', style='Muted.TLabel').pack(anchor='w', pady=5)
        ttk.Checkbutton(frame, text='Music · Verify entire audio files (slower)', variable=self.full_music).pack(anchor='w', pady=10)
        ttk.Checkbutton(frame, text='Advanced · Rebuild content that is already ready', variable=self.force).pack(anchor='w', pady=5)
        ttk.Label(frame, textvariable=self.tools_status, wraplength=470).pack(anchor='w', pady=10)
        ttk.Button(frame, text='Locate FFmpeg and FFprobe…', command=self.locate_tools).pack(anchor='w')
        def done():
            self.photo_choice.current(photo.current())
            dialog.destroy()
            self.scan()
        ttk.Button(frame, text='Done', style='Accent.TButton', command=done).pack(anchor='e', pady=(20, 0))
        dialog.protocol('WM_DELETE_WINDOW', done)

    def drain(self):
        try:
            for _ in range(100):
                kind, value = self.events.get_nowait()
                if kind == 'plan':
                    generation, selected, plan, error = value
                    if generation != self.plan_generation or self.busy:
                        continue
                    self.plan_ready = bool(selected) and not error
                    if error:
                        self.plan_text.set('Needs attention · ' + error)
                        self.render_queue('Needs review')
                    elif not selected:
                        self.plan_text.set('Choose at least one category to update. Queued additions are retained.')
                        self.render_queue()
                    else:
                        excluded = plan['excluded'] + (len(self.video_selection) if 'Videos' not in selected else 0)
                        self.plan_text.set(f"Update {', '.join(selected)}: copy {plan['copies']} new files, prepare {plan['videos']} selected videos, and refresh the selected libraries. Unchanged content is reused unless rebuilding is enabled."
                            + (f" {excluded} queued selections are excluded and will stay queued." if excluded else '')
                            + f"\nNew originals: {size(plan['bytes'])} · iPod free: {size(plan['free'])} · Computer free: {size(plan['computer_free'])}. Prepared copies need additional space.")
                        self.render_queue('Ready to add', plan['previews'])
                    self.start_button.configure(state='normal' if self.plan_ready else 'disabled')
                    continue
                if kind == 'video_progress':
                    self.video_progress(value)
                    continue
                if kind == 'progress':
                    self.indeterminate_progress()
                    self.log_message(value)
                    continue
                self.set_busy(False)
                if kind == 'devices':
                    self.devices = value
                    self.device_choice['values'] = [
                        f"{d['drive']} · {d['target_name']} · "
                        f"{d.get('regulatory_model') or d.get('model_number')}"
                        for d in value
                    ]
                    if value:
                        self.device_choice.current(0)
                        self.scan()
                    else:
                        self.device_choice.set('')
                        self.device_status.set('No iPod found. Connect in Disk Mode, then choose Find iPod.')
                        self.status.set('Waiting for your iPod.')
                        self.plan_text.set('Connect an iPod to review an update.')
                elif kind == 'inspected':
                    identity, self.inventory, self.rows, self.readiness = value
                    self.devices[self.device_choice.current()] = identity
                    profile = identity['media_profile']
                    self.video_enabled = profile.get('video_enabled', True)
                    self.selected['Videos'].set(self.video_enabled)
                    self.update_checks['Videos'].configure(state='normal' if self.video_enabled else 'disabled')
                    if not self.video_enabled:
                        self.video_selection.clear()
                    self.video_selection.intersection_update(self.inventory['Videos']['files'])
                    video = ('unavailable on this model' if not self.video_enabled else
                             f"{profile['video_fps']} fps, four-level grayscale"
                             if profile['video_color'] == 'gray4'
                             else f"{profile['video_fps']} fps, full color")
                    from tools.studio.installer import build_description
                    firmware = build_description(identity["linnet"])
                    self.device_status.set(
                        f"Linnet: {firmware} · {identity['target_name']} · {size(identity['free_bytes'])} available · "
                        f"Video: {video} · Originals are preserved during preparation"
                    )
                    self.library_button.configure(state='normal')
                    self.eject_button.configure(state='normal')
                    self.change_kind()
                    self.update_video_summary()
                    self.render()
                    self.status.set('Library refreshed. Review your next update below.')
                    self.schedule_plan()
                elif kind == 'ejected':
                    self.inventory = None
                    self.rows, self.readiness = [], {}
                    self.video_selection.clear()
                    self.plan_ready = False
                    self.set_busy(False)
                    self.render()
                    self.render_queue()
                    self.device_status.set('iPod safely ejected. Hold Menu+Select to restart Linnet.')
                    self.results.set('Windows confirmed ejection. Restart the iPod with Menu+Select.')
                    self.plan_text.set('Restart Linnet, or reconnect in Disk Mode for another media update.')
                elif kind in ('finished', 'removed'):
                    self.receipt = value['receipt']
                    self.report_button.configure(state='normal')
                    if kind == 'finished':
                        lines = []
                        for category in media.KINDS:
                            steps = [s for s in value['steps'] if s.get('kind') == category]
                            ready = sum(s.get('status') == 'published' for s in steps if category != 'Videos' or s.get('file'))
                            unchanged = sum(s.get('status') == 'unchanged' for s in steps)
                            errors = [e for e in value['errors'] if e.get('kind') == category]
                            if steps or errors:
                                outcome = f'{ready} prepared · {unchanged} unchanged' if category == 'Videos' else 'Library updated' if ready else 'Already up to date' if unchanged else 'Not completed'
                                lines.append(f'{category}: {outcome}' + (f' · {len(errors)} need attention' if errors else ''))
                        lines.extend(f"{e.get('file', e.get('kind', 'Update'))}: {e['message']}" for e in value['errors'])
                        if value['complete']:
                            self.pending = [p for p in self.pending if p not in self.submitted]
                            self.video_selection.difference_update(getattr(self, 'submitted_videos', set()))
                            lines.append('Update complete. Choose Eject iPod, then hold Menu+Select to restart Linnet.')
                            if self.pending or self.video_selection:
                                lines.append('Excluded selections are still queued; they were not included in this update.')
                        elif value.get('stopped'):
                            lines.append('Stopped. Completed work is retained. Update again to continue.')
                        else:
                            lines.append('Completed work is retained. Resolve the items above and update again.')
                        if value.get('cleanup', {}).get('retained'):
                            lines.append('Leftover preparation files need review — open the detailed report.')
                        self.results.set('\n'.join(lines))
                        self.submitted = []
                    else:
                        self.results.set(value['summary'])
                    self.render_queue()
                    self.scan()
                elif kind == 'error':
                    self.inventory = None
                    self.rows, self.readiness = [], {}
                    self.render()
                    self.plan_ready = False
                    self.set_busy(False)
                    self.start_button.configure(state='disabled')
                    self.library_button.configure(state='disabled')
                    self.results.set('Needs attention · ' + str(value))
                    self.status.set('Resolve this issue, then refresh the library.')
        except queue.Empty:
            pass
        self.window.after(100, self.drain)
