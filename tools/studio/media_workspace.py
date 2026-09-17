"""Preparation overview for preparing Linnet media."""
import os
import queue
import shutil
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .media_app import MediaApp, size
from tools.content import media_manager as media, media_status


class MediaWorkspace(MediaApp):
    def __init__(self, window):
        self.window = window
        window.title('Linnet · Prepare media')
        window.geometry('1060x960')
        window.minsize(1000, 760)
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
        self.force, self.full_music = tk.BooleanVar(), tk.BooleanVar()
        self.plan_generation = 0
        self.plan_timer = None
        self.plan_ready = False
        self.issues = {}
        self.retry_after_plan = False
        self.build()
        window.protocol('WM_DELETE_WINDOW', self.close)
        window.after(100, self.drain)
        window.after(250, self.find)

    def build(self):
        w = self.window
        style = ttk.Style(w)
        style.theme_use('clam')
        style.configure('.', background='#f3f5f8', foreground='#17283b', font=('Segoe UI', 10))
        style.configure('Title.TLabel', font=('Segoe UI', 24, 'bold'))
        style.configure('Heading.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Card.TFrame', background='#ffffff')
        style.configure('Card.TLabel', background='#ffffff')
        style.configure('CardMuted.TLabel', background='#ffffff', foreground='#64748b')
        style.configure('Card.TCheckbutton', background='#ffffff', font=('Segoe UI', 11, 'bold'))
        style.map('Card.TCheckbutton', background=[('active', '#ffffff')])
        style.configure('State.TLabel', background='#ffffff', foreground='#64748b', font=('Segoe UI', 10))
        style.configure('Ready.TLabel', background='#ffffff', foreground='#23704a', font=('Segoe UI', 10, 'bold'))
        style.configure('Attention.TLabel', background='#ffffff', foreground='#916121', font=('Segoe UI', 10, 'bold'))
        style.configure('Horizontal.TProgressbar', background='#245cdb', troughcolor='#e4eaf2', borderwidth=0)
        style.configure('Muted.TLabel', foreground='#52677d')
        style.configure('TButton', padding=(12, 7))
        style.configure('Accent.TButton', background='#245cdb', foreground='white')
        style.map('Accent.TButton', background=[('disabled', '#dce3ef'), ('active', '#1749b8')], foreground=[('disabled', '#65778d')])
        body = ttk.Frame(w, padding=(18, 14))
        body.pack(fill='both', expand=True)
        top = ttk.Frame(body)
        top.pack(fill='x')
        ttk.Label(top, text='Media preparation', style='Title.TLabel').pack(side='left')
        self.installer_button = ttk.Button(top, text='Linnet installation…', command=self.open_installer)
        self.installer_button.pack(side='right')
        self.tools_button = ttk.Button(top, text='Settings…', command=self.settings)
        self.tools_button.pack(side='right', padx=8)
        ttk.Label(body, text='Get your iPod’s media ready for Linnet. Originals stay untouched.', style='Muted.TLabel').pack(anchor='w', pady=(4, 10))
        device = ttk.Frame(body)
        device.pack(fill='x')
        self.device_choice = ttk.Combobox(device, state='readonly', width=48)
        self.device_choice.pack(side='left', fill='x', expand=True)
        self.device_choice.set('Connect an iPod in Disk Mode')
        self.device_choice.bind('<<ComboboxSelected>>', self.device_changed)
        self.refresh_button = ttk.Button(device, text='Find iPod', command=self.find)
        self.refresh_button.pack(side='left', padx=8)
        self.scan_button = ttk.Button(device, text='Check readiness', command=self.scan)
        self.scan_button.pack(side='left')
        self.default_boot = tk.StringVar(value='')
        ttk.Label(body, textvariable=self.default_boot, style='Muted.TLabel').pack(anchor='w', pady=(7, 0))
        self.device_status = tk.StringVar()
        ttk.Label(body, textvariable=self.device_status, style='Muted.TLabel', wraplength=940).pack(anchor='w', pady=(2, 8))
        ttk.Label(body, text='Prepare for Linnet', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(body, text='Select media types to prepare. Uncheck to skip.', style='Muted.TLabel').pack(anchor='w', pady=(3, 6))
        descriptions = {'Music': 'Song index and cover art', 'Notes': 'Text prepared for the reader',
                        'Photos': 'Thumbnails and zoom images',
                        'Videos': 'Convert selected originals; prepared IPVF is added automatically'}
        self.counts, self.preparation_status = {}, {}
        for kind in media.KINDS:
            row = ttk.Frame(body, padding=(16, 6), style='Card.TFrame')
            row.pack(fill='x', pady=(0, 4))
            row.columnconfigure(1, weight=1)
            check = ttk.Checkbutton(row, text=kind, variable=self.selected[kind], command=self.update_scope, width=10, style='Card.TCheckbutton')
            check.grid(row=0, column=0, rowspan=2, sticky='w', padx=(0, 12))
            self.update_checks[kind] = check
            self.option_controls.append(check)
            ttk.Label(row, text=descriptions[kind], style='Card.TLabel').grid(row=0, column=1, sticky='w')
            self.counts[kind] = ttk.Label(row, text='', style='CardMuted.TLabel')
            self.counts[kind].grid(row=1, column=1, sticky='w', pady=(3, 0))
            self.preparation_status[kind] = ttk.Label(row, text='—', style='State.TLabel')
            self.preparation_status[kind].grid(row=0, column=2, sticky='e')
            if kind == 'Music':
                self.choose_music_button = ttk.Button(row, text='Choose music…', command=self.choose_music, state='disabled')
                self.choose_music_button.grid(row=1, column=2, sticky='e', pady=(3, 0))
            elif kind == 'Videos':
                video_actions = ttk.Frame(row, style='Card.TFrame')
                video_actions.grid(row=1, column=2, sticky='e', pady=(3, 0))
                self.choose_videos_button = ttk.Button(video_actions, text='Choose videos…', command=self.choose_videos, state='disabled')
                self.choose_videos_button.pack(side='left')
        footer = ttk.Frame(body)
        footer.pack(fill='x', pady=(8, 0))
        self.tools_status = tk.StringVar()
        self.update_tools_status()
        self.plan_text = tk.StringVar(value='Connect an iPod to begin.')
        ttk.Label(footer, textvariable=self.plan_text, wraplength=940).pack(anchor='w', pady=(5, 8))
        action = ttk.Frame(footer)
        action.pack(fill='x')
        self.start_button = ttk.Button(action, text='Prepare selected media', style='Accent.TButton', command=self.start, state='disabled')
        self.start_button.pack(side='left')
        self.stop_button = ttk.Button(action, text='Stop after this step', command=self.stop, state='disabled')
        self.eject_button = ttk.Button(action, text='Eject iPod', command=self.eject, state='disabled')
        self.eject_button.pack(side='left', padx=8)
        self.report_button = ttk.Button(action, text='View report', command=self.open_report, state='disabled')
        self.report_button.pack(side='right')
        self.progress = ttk.Progressbar(footer, mode='indeterminate')
        self.status = tk.StringVar(value='Looking for your iPod…')
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=940, style='Muted.TLabel')
        self.status_label.pack(anchor='w', pady=(9, 0))
        self.results = tk.StringVar(value='')
        self.result_frame = ttk.Frame(footer)
        self.result_view = tk.Text(self.result_frame, height=6, wrap='word', state='disabled', font=('Segoe UI', 10), relief='flat', background='#eaf0f7', foreground='#263b53', padx=12, pady=8)
        self.result_view.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(self.result_frame, command=self.result_view.yview)
        def result_scroll(first, last):
            scroll.set(first, last)
            if float(first) > 0 or float(last) < 1:
                scroll.pack(side='right', fill='y')
            else:
                scroll.pack_forget()
        self.result_view.configure(yscrollcommand=result_scroll)
        self.results.trace_add('write', self.render_results)
        self.issue_frame = ttk.LabelFrame(footer, text='Files that need attention', padding=8)
        issue_rows = ttk.Frame(self.issue_frame)
        issue_rows.pack(fill='x')
        self.issue_list = ttk.Treeview(issue_rows, columns=('kind', 'file', 'problem'),
                                       show='headings', height=3, selectmode='extended')
        self.issue_list.heading('kind', text='Type')
        self.issue_list.heading('file', text='File')
        self.issue_list.heading('problem', text='Problem')
        self.issue_list.column('kind', width=70, stretch=False)
        self.issue_list.column('file', width=330)
        self.issue_list.column('problem', width=440)
        issue_scroll = ttk.Scrollbar(issue_rows, orient='vertical', command=self.issue_list.yview)
        self.issue_list.configure(yscrollcommand=issue_scroll.set)
        self.issue_list.pack(side='left', fill='x', expand=True)
        issue_scroll.pack(side='right', fill='y')
        issue_actions = ttk.Frame(self.issue_frame)
        issue_actions.pack(fill='x', pady=(7, 0))
        self.show_issue_button = ttk.Button(issue_actions, text='Show selected file',
                                            command=self.show_selected_issue, state='disabled')
        self.show_issue_button.pack(side='left')
        self.skip_issue_button = ttk.Button(issue_actions, text='Retry selected file',
                                            command=self.retry_selected_issues, state='disabled')
        self.skip_issue_button.pack(side='left', padx=6)
        self.retry_button = ttk.Button(issue_actions, text='Retry update', command=self.retry_update)
        self.retry_button.pack(side='right')
        self.issue_list.bind('<<TreeviewSelect>>', self.update_issue_actions)
        self.kind_choice = ttk.Combobox(w, values=media.KINDS)
        self.kind_choice.set('Music')
        self.photo_choice = ttk.Combobox(w, values=('Standard (640 px)', 'High (2048 px)'))
        self.photo_choice.current(0)
        self.render()

    def render_results(self, *_):
        if self.results.get():
            self.result_frame.pack(fill='x', pady=(7, 0))
        else:
            self.result_frame.pack_forget()
        self.result_view.configure(state='normal')
        self.result_view.delete('1.0', 'end')
        self.result_view.insert('end', self.results.get())
        self.result_view.see('end')
        self.result_view.configure(state='disabled')

    def render_issues(self, errors):
        self.issues = {}
        self.issue_list.delete(*self.issue_list.get_children())
        root = Path(self.identity()['root']) if self.devices and self.device_choice.current() >= 0 else None
        for index, error in enumerate(errors):
            source = error.get('source')
            if not source or not error.get('kind'):
                continue
            path = Path(source)
            try:
                display = path.relative_to(root).as_posix() if root and path.is_relative_to(root) else str(path)
            except (OSError, ValueError):
                display = str(path)
            item = f'issue-{index}'
            self.issues[item] = error
            self.issue_list.insert('', 'end', iid=item,
                                   values=(error['kind'], display, error.get('message', 'Could not prepare file')))
        if self.issues:
            self.result_view.configure(height=3)
            if self.result_frame.winfo_manager():
                self.issue_frame.pack(fill='x', pady=(7, 0), before=self.result_frame)
            else:
                self.issue_frame.pack(fill='x', pady=(7, 0))
            first = next(iter(self.issues))
            self.issue_list.selection_set(first)
            self.issue_list.focus(first)
        else:
            self.issue_frame.pack_forget()
            self.result_view.configure(height=6)
        self.update_issue_actions()

    def update_issue_actions(self, _=None):
        selected = [self.issues[item] for item in self.issue_list.selection() if item in self.issues]
        enabled = not self.busy and bool(selected)
        self.show_issue_button.configure(state='normal' if enabled and len(selected) == 1 else 'disabled')
        self.skip_issue_button.configure(state='normal' if enabled else 'disabled')
        self.retry_button.configure(state='normal' if not self.busy else 'disabled')

    def show_selected_issue(self):
        chosen = self.issue_list.selection()
        if self.busy or len(chosen) != 1:
            return
        path = Path(self.issues[chosen[0]]['source'])
        try:
            os.startfile(str(path.parent))
            self.status.set(f'Opened the folder containing {path.name}. Fix or replace it, then choose Retry selected file.')
        except OSError as error:
            self.status.set(f'Could not open the file location: {error}')

    def retry_update(self):
        if self.busy:
            return
        self.retry_after_plan = True
        if self.inventory is None:
            self.scan()
        else:
            self.schedule_plan()

    def retry_selected_issues(self):
        selected = [self.issues[item] for item in self.issue_list.selection() if item in self.issues]
        if self.busy or not selected:
            return
        root = Path(self.identity()['root']).resolve()
        restore = []
        for issue in selected:
            source = Path(issue['source']).resolve()
            self.selected[issue['kind']].set(True)
            if source.is_relative_to(root):
                restore.append((issue['kind'], source.relative_to(root).as_posix()))
                if issue['kind'] == 'Videos':
                    self.video_selection.add(str(source))
            else:
                item = (issue['kind'], str(source))
                if item not in self.pending:
                    self.pending.append(item)
        self.retry_after_plan = True
        if restore:
            self.status.set('Including the selected files again, then retrying the update…')
            identity = self.identity()
            self.worker(lambda: media.restore_skipped_files(identity, restore), 'issues_restored')
        else:
            self.scan()

    def open_installer(self):
        from tools.studio.installer_app import InstallerWindow
        identity = None
        try:
            identity = self.identity()
        except ValueError:
            pass
        InstallerWindow(self.window, identity, on_changed=self.scan)

    def log_message(self, message):
        self.status.set(str(message))

    def set_busy(self, value):
        self.busy = value
        for control in (self.refresh_button, self.scan_button, self.installer_button, self.tools_button, *self.option_controls):
            control.configure(state='disabled' if value else 'normal')
        self.device_choice.configure(state='disabled' if value else 'readonly')
        self.update_checks['Videos'].configure(state='disabled' if value or not self.video_enabled else 'normal')
        self.choose_music_button.configure(state='normal' if not value and self.inventory else 'disabled')
        self.choose_videos_button.configure(state='normal' if not value and self.inventory and self.video_enabled else 'disabled')
        self.start_button.configure(state='normal' if not value and self.plan_ready and self.inventory else 'disabled')
        self.eject_button.configure(state='normal' if not value and self.inventory else 'disabled')
        self.stop_button.configure(state='normal' if value else 'disabled')
        self.progress.stop()
        if value:
            self.stop_button.pack(side='left', padx=8, before=self.eject_button)
            self.progress.pack(fill='x', pady=(10, 0), before=self.status_label)
            self.stop_event.clear()
            self.progress.configure(mode='indeterminate', value=0)
            self.progress.start(12)
        else:
            self.stop_button.pack_forget()
            self.progress.pack_forget()
            self.progress.configure(value=0)
        self.update_issue_actions()

    def update_scope(self):
        self.render()
        self.schedule_plan()

    def update_video_summary(self):
        self.render()

    def render(self):
        for kind in media.KINDS:
            inventory = self.inventory[kind] if self.inventory else None
            detail = ''
            state = self.readiness.get(kind, 'Not checked') if inventory else '—'
            if inventory:
                detail = f"{inventory['count']:,} files · {size(inventory['bytes'])}"
                if inventory.get('skipped'):
                    detail += f" · {inventory['skipped']:,} skipped"
                if kind == 'Music':
                    queued = sum(pending_kind == 'Music' for pending_kind, _ in self.pending)
                    if queued:
                        detail += f' · {queued:,} selected to add'
                elif kind == 'Videos':
                    queued = sum(pending_kind == 'Videos' for pending_kind, _ in self.pending)
                    detail += f' · {len(self.video_selection):,} selected to convert · {queued:,} from computer'
                    playback = sum(row.get('kind') == 'Videos' and row.get('category') == 'published'
                                   and row.get('status') == 'Ready on iPod' for row in self.rows)
                    detail += f' · {playback:,} in playback library'
                    if not self.video_enabled:
                        state = 'Unavailable on this iPod'
                elif not inventory['count'] and state != 'Prepared library retained':
                    state = 'No source files'
                if not self.selected[kind].get() and (kind != 'Videos' or self.video_enabled):
                    state = 'Skipped'
            self.counts[kind].configure(text=detail)
            status_style = 'Ready.TLabel' if state == 'Ready' else 'Attention.TLabel' if state in ('Not prepared', 'Needs update') else 'State.TLabel'
            self.preparation_status[kind].configure(text=state, style=status_style)

    def choose_music(self):
        if self.busy or not self.inventory:
            return
        pattern = ' '.join('*' + extension for extension in sorted(media.extensions('Music')))
        chosen = filedialog.askopenfilenames(
            parent=self.window,
            title='Choose music to add',
            filetypes=[('Music', pattern), ('All files', '*.*')],
        )
        added = 0
        for path in chosen:
            item = ('Music', path)
            if item not in self.pending:
                self.pending.append(item)
                added += 1
        if chosen:
            self.selected['Music'].set(True)
            self.status.set(
                f"{added:,} music file{'s' if added != 1 else ''} selected to add. "
                'Choose Prepare selected media to copy and index them.'
                if added else 'Those music files are already selected to add.'
            )
            self.update_scope()

    def choose_videos(self):
        if self.busy or not self.inventory or not self.video_enabled:
            return
        sources = self.inventory['Videos'].get('files', [])
        native_extensions = {'.ipv', '.ipvf'}
        conversion_sources = [path for path in sources if Path(path).suffix.lower() not in native_extensions]
        native_sources = [path for path in sources if Path(path).suffix.lower() in native_extensions]
        root = Path(self.identity()['root'])
        dialog = tk.Toplevel(self.window)
        dialog.title('Choose videos to prepare')
        dialog.geometry('820x760')
        dialog.minsize(700, 650)
        dialog.transient(self.window)
        dialog.grab_set()
        actions = ttk.Frame(dialog, padding=(16, 10, 16, 18))
        actions.pack(side='bottom', fill='x')
        ttk.Separator(dialog).pack(side='bottom', fill='x')
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Choose source videos to convert. Prepared IPVF videos are recognized and added to the playback library automatically.',
                  wraplength=740).pack(anchor='w')

        ttk.Label(frame, text='Videos on this iPod', style='Heading.TLabel').pack(anchor='w', pady=(16, 0))
        source_box = ttk.Frame(frame)
        source_box.pack(fill='both', expand=bool(conversion_sources), pady=(4, 10))
        ttk.Label(source_box, text='Select only the originals you want converted. Originals remain unchanged.',
                  style='Muted.TLabel').pack(anchor='w')
        query = tk.StringVar()
        query_entry = ttk.Entry(source_box, textvariable=query)
        query_entry.pack(fill='x', pady=(6, 8))
        list_frame = ttk.Frame(source_box)
        list_frame.pack(fill='both', expand=True)
        listing = tk.Listbox(list_frame, selectmode='multiple', exportselection=False,
                             relief='flat', borderwidth=0, highlightthickness=1)
        listing.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(list_frame, command=listing.yview)
        scrollbar.pack(side='right', fill='y')
        listing.configure(yscrollcommand=scrollbar.set)
        source_empty = ttk.Label(source_box, style='Muted.TLabel')
        selected = set(self.video_selection).intersection(conversion_sources)
        visible = []
        rendering = False
        def remember(_=None):
            if rendering:
                return
            selected.difference_update(visible)
            selected.update(visible[i] for i in listing.curselection())
        def render(*_):
            nonlocal rendering
            rendering = True
            visible[:] = [path for path in conversion_sources
                          if query.get().casefold() in str(Path(path).relative_to(root)).casefold()]
            listing.delete(0, 'end')
            for i, path in enumerate(visible):
                listing.insert('end', str(Path(path).relative_to(root)))
                if path in selected:
                    listing.selection_set(i)
            if visible:
                source_empty.pack_forget()
                list_frame.pack(fill='both', expand=True, before=source_actions)
            else:
                list_frame.pack_forget()
                source_empty.configure(text=('No videos on this iPod need conversion.'
                                             if not conversion_sources else 'No videos match this search.'))
                if source_actions.winfo_manager():
                    source_empty.pack(anchor='w', pady=(8, 4), before=source_actions)
                else:
                    source_empty.pack(anchor='w', pady=(8, 4))
            rendering = False
        listing.bind('<<ListboxSelect>>', remember)
        def query_changed(*_):
            remember()
            render()
        query.trace_add('write', query_changed)
        source_actions = ttk.Frame(source_box)
        source_actions.pack(fill='x', pady=(7, 0))
        def select_all():
            selected.update(visible)
            render()
        def clear():
            selected.clear()
            render()
        ttk.Button(source_actions, text='Select matches', command=select_all).pack(side='left')
        ttk.Button(source_actions, text='Clear selection', command=clear).pack(side='left', padx=6)
        if not conversion_sources:
            query_entry.pack_forget()
            source_actions.pack_forget()

        ttk.Separator(frame).pack(fill='x')
        ttk.Label(frame, text='From this computer', style='Heading.TLabel').pack(anchor='w', pady=(12, 0))
        computer_box = ttk.Frame(frame)
        computer_box.pack(fill='x', pady=(4, 10))
        ttk.Label(computer_box, text='These will be converted when needed and added to the playback library.',
                  style='Muted.TLabel').pack(anchor='w')
        queued = [path for kind, path in self.pending if kind == 'Videos']
        queued_list = tk.Listbox(computer_box, height=3, selectmode='extended', exportselection=False,
                                 relief='flat', borderwidth=0, highlightthickness=1)
        queued_list.pack(fill='x', pady=(6, 6))
        queued_empty = ttk.Label(computer_box, text='No videos chosen from this computer.', style='Muted.TLabel')
        def render_queued():
            queued_list.delete(0, 'end')
            for path in queued:
                action = 'prepared IPVF' if Path(path).suffix.lower() in native_extensions else 'convert to IPVF'
                queued_list.insert('end', f'{Path(path).name} — {action}')
            if queued:
                queued_empty.pack_forget()
                queued_list.pack(fill='x', pady=(6, 6), before=computer_actions)
            else:
                queued_list.pack_forget()
                queued_empty.pack(anchor='w', pady=(7, 6), before=computer_actions)
        def add_computer_videos():
            pattern = ' '.join('*' + extension for extension in sorted(media.extensions('Videos')))
            chosen = filedialog.askopenfilenames(
                parent=dialog, title='Choose videos from this computer',
                filetypes=[('Videos', pattern), ('All files', '*.*')])
            for path in chosen:
                if path not in queued:
                    queued.append(path)
            render_queued()
        def remove_computer_videos():
            if queued:
                for index in reversed(queued_list.curselection()):
                    queued.pop(index)
                render_queued()
        computer_actions = ttk.Frame(computer_box)
        computer_actions.pack(fill='x')
        ttk.Button(computer_actions, text='Choose videos from computer…', command=add_computer_videos).pack(side='left')
        ttk.Button(computer_actions, text='Remove selected', command=remove_computer_videos).pack(side='left', padx=6)

        ttk.Separator(frame).pack(fill='x')
        ttk.Label(frame, text='Already prepared', style='Heading.TLabel').pack(anchor='w', pady=(12, 0))
        prepared_box = ttk.Frame(frame)
        prepared_box.pack(fill='x', pady=(4, 0))
        ttk.Label(prepared_box, text='These are not conversion choices. Linnet adds valid IPVF files to the playback library automatically.',
                  style='Muted.TLabel').pack(anchor='w')
        prepared_list = tk.Listbox(prepared_box, height=4, exportselection=False, takefocus=False,
                                   relief='flat', borderwidth=0, highlightthickness=0,
                                   background='#f3f5f8')
        prepared_list.pack(fill='x', pady=(6, 0))
        prepared = {}
        for path in native_sources:
            prepared[str(Path(path).resolve()).casefold()] = (
                f"{Path(path).relative_to(root)} — IPVF on iPod; added automatically"
            )
        for row in self.rows:
            if row.get('kind') == 'Videos' and row.get('category') == 'published':
                prepared[str(Path(row['path']).resolve()).casefold()] = (
                    f"{row['title']} — {row['status']}"
                )
        for label in sorted(prepared.values(), key=str.casefold):
            prepared_list.insert('end', label)
        if not prepared:
            prepared_list.insert('end', 'No prepared videos found on this iPod')
        prepared_list.bind('<Button-1>', lambda _: 'break')

        def accept():
            remember()
            self.video_selection = selected
            self.pending = [item for item in self.pending if item[0] != 'Videos']
            self.pending.extend(('Videos', path) for path in queued)
            if selected or queued or native_sources:
                self.selected['Videos'].set(True)
            dialog.destroy()
            self.update_scope()
        ttk.Button(actions, text='Prepare these videos', style='Accent.TButton', command=accept).pack(side='right')
        ttk.Button(actions, text='Cancel', command=dialog.destroy).pack(side='right', padx=6)
        render_queued()
        render()

    def schedule_plan(self):
        self.plan_generation += 1
        self.plan_ready = False
        self.start_button.configure(state='disabled')
        self.render()
        if self.inventory is None:
            self.plan_text.set('Connect an iPod to review the update. ')
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
        self.plan_text.set('Checking preparation requirements and storage…')
        self.render()
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
                self.render()
                self.results.set('Updating your iPod… Completed work and any errors will appear here.')

    def eject(self):
        if self.busy or self.inventory is None:
            return
        identity = self.identity()
        self.plan_generation += 1
        def operation():
            return media.eject_device(identity)
        self.status.set('Asking Windows to safely eject the iPod…')
        self.worker(operation, 'ejected')

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
        ttk.Button(frame, text='Prepared library recovery…', command=self.browse_library, state='normal' if self.inventory else 'disabled').pack(anchor='w', pady=(10, 0))
        skipped = media.list_skipped_files(self.identity()) if self.inventory else []
        ttk.Label(frame, text='Files skipped during preparation', padding=(0, 15, 0, 5)).pack(anchor='w')
        skipped_list = tk.Listbox(frame, height=min(4, max(1, len(skipped))), selectmode='extended',
                                  exportselection=False, activestyle='none')
        skipped_list.pack(fill='x')
        for item in skipped:
            skipped_list.insert('end', f"{item['kind']} · {item['relative']}")
        if skipped:
            skipped_list.selection_set(0)
        else:
            skipped_list.insert('end', 'No files are skipped')
            skipped_list.configure(state='disabled')
        def restore_skipped():
            chosen = [skipped[index] for index in skipped_list.curselection()]
            if not chosen:
                return
            identity = self.identity()
            dialog.destroy()
            self.worker(lambda: media.restore_skipped_files(
                identity, [(item['kind'], item['relative']) for item in chosen]), 'issues_restored')
        ttk.Button(frame, text='Include selected files again', command=restore_skipped,
                   state='normal' if skipped else 'disabled').pack(anchor='w', pady=(6, 0))
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
                        self.render()
                    elif not selected:
                        self.plan_text.set('Choose at least one media type to prepare.')
                        self.render()
                    else:
                        scope = ', '.join(k for k in selected if k != 'Videos')
                        if 'Videos' in selected:
                            scope += (' · ' if scope else '') + f"{plan['videos']} videos to prepare or index"
                        self.plan_text.set(f"Prepare: {scope}. Unchanged content is reused."
                            + f"\n{size(plan['free'])} free on iPod · Prepared copies need additional space.")
                        self.render()
                    self.start_button.configure(state='normal' if self.plan_ready else 'disabled')
                    if self.retry_after_plan:
                        self.retry_after_plan = False
                        if self.plan_ready:
                            self.window.after_idle(self.start)
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
                        self.device_choice.set('Connect an iPod in Disk Mode')
                        self.default_boot.set('Default boot: No iPod connected')
                        self.device_status.set('No iPod found. Connect in Disk Mode, then choose Find iPod.')
                        self.status.set('Waiting for your iPod.')
                        self.plan_text.set('Connect an iPod to check preparation needs.')
                elif kind == 'inspected':
                    identity, self.inventory, self.rows, self.readiness = value
                    self.devices[self.device_choice.current()] = identity
                    profile = identity['media_profile']
                    self.video_enabled = profile.get('video_enabled', True)
                    if not self.video_enabled:
                        self.selected['Videos'].set(False)
                    self.update_checks['Videos'].configure(state='normal' if self.video_enabled else 'disabled')
                    self.choose_music_button.configure(state='normal')
                    self.choose_videos_button.configure(state='normal' if self.video_enabled else 'disabled')
                    if not self.video_enabled:
                        self.video_selection.clear()
                    self.video_selection.intersection_update(self.inventory['Videos']['files'])
                    video = ('unavailable on this model' if not self.video_enabled else
                             f"{profile['video_fps']} fps, four-level grayscale"
                             if profile['video_color'] == 'gray4'
                             else f"{profile['video_fps']} fps, full color")
                    from tools.studio.installer import build_description
                    firmware = build_description(identity["linnet"])
                    default = identity['default_boot']
                    self.default_boot.set(f"Default boot: {default['label']}")
                    linnet_state = ("" if default['id'].startswith('linnet:') else
                                    f"Linnet files: {firmware} · ")
                    self.device_status.set(
                        f"{linnet_state}{identity['target_name']} · {size(identity['free_bytes'])} available · "
                        f"Video: {video}"
                    )
                    self.eject_button.configure(state='normal')
                    self.update_video_summary()
                    self.render()
                    self.status.set('Readiness checked. Choose what to prepare.')
                    self.schedule_plan()
                elif kind == 'ejected':
                    self.inventory = None
                    self.rows, self.readiness = [], {}
                    self.video_selection.clear()
                    self.plan_ready = False
                    self.set_busy(False)
                    self.render()
                    self.render()
                    self.default_boot.set('Default boot: Device disconnected')
                    self.device_status.set('iPod safely ejected. Hold Menu+Select to restart it.')
                    self.results.set('Windows confirmed ejection. Restart the iPod with Menu+Select.')
                    self.plan_text.set('Restart the iPod, or reconnect in Disk Mode for another media update.')
                elif kind == 'issues_restored':
                    count = len(value)
                    self.results.set(f"Included {count} previously skipped file{'s' if count != 1 else ''} again.")
                    self.status.set('Checking readiness with the restored files…')
                    self.scan()
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
                                skipped = sum(error.get('status') == 'skipped' for error in errors)
                                unresolved = len(errors) - skipped
                                attention = (f" · {skipped} skipped" if skipped else '')
                                attention += (' · 1 needs attention' if unresolved == 1 else
                                              f' · {unresolved} need attention' if unresolved else '')
                                lines.append(f'{category}: {outcome}{attention}')
                        lines.extend(
                            f"{'Skipped' if e.get('status') == 'skipped' else e.get('file', e.get('kind', 'Update'))}: "
                            f"{e.get('file', '') + ': ' if e.get('status') == 'skipped' and e.get('file') else ''}{e['message']}"
                            for e in value['errors']
                        )
                        if value['complete']:
                            self.pending = [p for p in self.pending if p not in self.submitted]
                            self.video_selection.difference_update(getattr(self, 'submitted_videos', set()))
                            if value.get('auto_skipped'):
                                count = len(value['auto_skipped'])
                                lines.append(f"Update complete with {count} problem file{'s' if count != 1 else ''} skipped. Select one below only if you want to retry it.")
                            lines.append('Choose Eject iPod, then hold Menu+Select to restart it.')
                            if self.pending or self.video_selection:
                                lines.append('Skipped videos remain selected for a later preparation.')
                        elif value.get('stopped'):
                            lines.append('Stopped. Completed work is retained. Update again to continue.')
                        else:
                            actionable = any(error.get('kind') and error.get('source') for error in value['errors'])
                            lines.append('Completed work is retained. Select an issue below to show or retry its file.'
                                         if actionable else
                                         'Completed work is retained. Resolve the items above and update again.')
                        if value.get('cleanup', {}).get('retained'):
                            lines.append('Leftover preparation files need review — open the detailed report.')
                        self.results.set('\n'.join(lines))
                        self.render_issues(value['errors'])
                        self.submitted = []
                    else:
                        self.results.set(value['summary'])
                    self.render()
                    self.scan()
                elif kind == 'error':
                    self.inventory = None
                    self.rows, self.readiness = [], {}
                    self.render()
                    self.plan_ready = False
                    self.set_busy(False)
                    self.start_button.configure(state='disabled')
                    self.results.set('Needs attention · ' + str(value))
                    self.render_issues([])
                    self.status.set('Reconnect the iPod in Disk Mode, then choose Find iPod.' if 'identity' in str(value).lower() else 'Resolve the issue below, then choose Check readiness.')
        except queue.Empty:
            pass
        self.window.after(100, self.drain)
