from PySide6.QtCore import Qt, QSize, QSignalBlocker
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
    QFrame, QStackedWidget, QStyledItemDelegate, QStyle)


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, parent, compact=False):
        super().__init__(parent)
        self.compact = compact

    def sizeHint(self, option, index):
        return QSize(160, 36 if self.compact else 32)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        if option.state & QStyle.State_Selected:
            painter.fillRect(rect, QColor('#ddf4f8'))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(rect, QColor('#f0f8fa'))
        title, _, detail = index.data().partition(' · ')
        font = QFont(option.font); font.setWeight(QFont.DemiBold)
        painter.setFont(font); painter.setPen(QColor('#202f35'))
        if self.compact:
            area = rect.adjusted(9, 0, -9, 0)
            painter.drawText(area, Qt.AlignVCenter, painter.fontMetrics().elidedText(index.data(), Qt.ElideRight, area.width()))
            painter.restore(); return
        area = rect.adjusted(10, 0, -12, 0)
        title_width = int(area.width() * .56) if detail else area.width()
        area.setWidth(title_width)
        painter.drawText(area, Qt.AlignVCenter, painter.fontMetrics().elidedText(title, Qt.ElideRight, area.width()))
        font.setWeight(QFont.Normal); font.setPixelSize(11)
        painter.setFont(font); painter.setPen(QColor('#617176'))
        area = rect.adjusted(20 + title_width, 0, -12, 0)
        painter.drawText(area, Qt.AlignVCenter, painter.fontMetrics().elidedText(detail, Qt.ElideRight, area.width()))
        painter.setPen(QColor('#edf1f2')); painter.drawLine(rect.bottomLeft(), rect.bottomRight())
        painter.restore()


class PlaylistEditor(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state, self.slot = state, None
        self.setWindowTitle('Linnet · Playlists'); self.setObjectName('playlistEditor')
        self.resize(1180, 740); self.setMinimumSize(1040, 640)
        layout = QVBoxLayout(self); layout.setContentsMargins(24, 24, 24, 20); layout.setSpacing(18)
        header = QHBoxLayout(); layout.addLayout(header)
        heading = QVBoxLayout(); heading.setSpacing(5); header.addLayout(heading)
        self.label(heading, 'Playlists', 'dialogTitle')
        self.label(heading, 'Your iPod playlists, in your order.', 'muted')
        header.addStretch(); self.count = self.label(header, '', 'badge')
        columns = QHBoxLayout(); columns.setSpacing(14); layout.addLayout(columns, 1)
        left = self.panel(columns, 0, 206)
        self.label(left, 'ON YOUR IPOD', 'eyebrow')
        self.new_button = self.button(left, '+ New playlist', self.create)
        self.playlists = QListWidget(); self.playlists.setObjectName('playlistNames')
        self.playlists.setItemDelegate(TrackDelegate(self.playlists, compact=True))
        self.playlists.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.playlist_stack, _ = self.list_area(left, self.playlists, 'No playlists yet\n\nCreate your first playlist above.')
        self.delete_button = self.button(left, 'Delete playlist', self.delete, 'danger')
        middle = self.panel(columns, 5)
        self.label(middle, 'PLAYLIST', 'eyebrow')
        self.name = QLineEdit(); self.name.setPlaceholderText('Playlist name'); middle.addWidget(self.name)
        self.name.setToolTip('Up to 31 UTF-8 bytes')
        self.track_count = self.label(middle, '', 'muted')
        self.members = self.track_list()
        self.member_stack, self.empty_members = self.list_area(middle, self.members, '')
        actions = QHBoxLayout(); middle.addLayout(actions)
        self.up_button = self.button(actions, '↑ Up', lambda: self.move(-1))
        self.down_button = self.button(actions, '↓ Down', lambda: self.move(1))
        actions.addStretch(); self.remove_button = self.button(actions, 'Remove', self.remove)
        right = self.panel(columns, 5)
        self.label(right, 'SONG LIBRARY', 'eyebrow')
        self.search = QLineEdit(); self.search.setPlaceholderText('Search songs, artists, albums')
        self.search.setClearButtonEnabled(True); right.addWidget(self.search)
        self.library_count = self.label(right, '', 'muted')
        self.songs = self.track_list()
        self.song_stack, self.empty_songs = self.list_area(right, self.songs, '')
        self.add_tracks_button = self.button(right, '← Add to playlist', self.add)
        for identity, title in sorted(state['tracks'].items(), key=lambda item: item[1].casefold()):
            item = QListWidgetItem(title); item.setData(Qt.UserRole, str(identity))
            item.setToolTip(title); self.songs.addItem(item)
        footer = QHBoxLayout(); footer.setSpacing(10); layout.addLayout(footer)
        self.message = self.label(footer, '', 'muted'); self.message.setWordWrap(True)
        footer.setStretch(0, 1)
        self.button(footer, 'Cancel', self.reject)
        self.button(footer, 'Save to iPod', self.accept_checked, 'primary')
        self.playlists.currentRowChanged.connect(self.select)
        self.name.textEdited.connect(self.rename)
        self.search.textChanged.connect(self.filter)
        self.songs.itemDoubleClicked.connect(lambda _: self.add())
        self.members.itemSelectionChanged.connect(self.update_actions)
        self.songs.itemSelectionChanged.connect(self.update_actions)
        self.render(); self.filter('')

    def label(self, layout, text, name):
        item = QLabel(text); item.setObjectName(name); item.setTextFormat(Qt.PlainText)
        layout.addWidget(item); return item

    def panel(self, layout, stretch, width=None):
        frame = QFrame(); frame.setObjectName('playlistPanel')
        if width:
            frame.setFixedWidth(width)
        layout.addWidget(frame, stretch)
        inner = QVBoxLayout(frame); inner.setContentsMargins(14, 16, 14, 14); inner.setSpacing(12)
        return inner

    def track_list(self):
        view = QListWidget(); view.setObjectName('playlistTracks')
        view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        view.setItemDelegate(TrackDelegate(view)); view.setUniformItemSizes(True)
        return view

    def list_area(self, layout, view, text):
        stack = QStackedWidget(); stack.addWidget(view)
        empty = QLabel(text); empty.setObjectName('playlistEmpty'); empty.setWordWrap(True)
        empty.setAlignment(Qt.AlignCenter); empty.setTextFormat(Qt.PlainText)
        stack.addWidget(empty); layout.addWidget(stack, 1)
        return stack, empty

    def button(self, layout, text, action, name=None):
        item = QPushButton(text); item.setCursor(Qt.PointingHandCursor); item.setAutoDefault(False)
        if name:
            item.setObjectName(name)
        item.clicked.connect(action); layout.addWidget(item); return item

    def update_actions(self):
        active = self.slot is not None
        selected = self.members.selectedItems()
        row = self.members.row(selected[0]) if len(selected) == 1 else -1
        self.delete_button.setEnabled(active)
        self.remove_button.setEnabled(active and bool(selected))
        self.up_button.setEnabled(active and len(selected) == 1 and row > 0)
        self.down_button.setEnabled(active and len(selected) == 1 and 0 <= row < self.members.count() - 1)
        self.add_tracks_button.setEnabled(active and any(not item.isHidden() for item in self.songs.selectedItems()))
        self.new_button.setEnabled(self.playlists.count() < 16)

    def render(self, selected=None):
        with QSignalBlocker(self.playlists):
            self.playlists.clear()
            for slot, playlist in enumerate(self.state['lists']):
                if playlist['name']:
                    item = QListWidgetItem(playlist['name']); item.setData(Qt.UserRole, slot)
                    item.setToolTip(playlist['name']); self.playlists.addItem(item)
                    if slot == selected:
                        self.playlists.setCurrentItem(item)
            if self.playlists.currentRow() < 0 and self.playlists.count():
                self.playlists.setCurrentRow(0)
        self.select()
        self.playlist_stack.setCurrentIndex(0 if self.playlists.count() else 1)
        self.count.setText(f'{self.playlists.count()} / 16 playlists')

    def select(self, *_):
        item = self.playlists.currentItem(); self.slot = item.data(Qt.UserRole) if item else None
        self.name.setEnabled(item is not None)
        playlist = self.state['lists'][self.slot] if item else dict(name='', ids=[])
        self.name.setText(playlist['name'])
        # Clearing a selection emits repeatedly; update controls after the
        # complete list is ready instead of rescanning it for each removed row.
        with QSignalBlocker(self.members):
            self.members.clear()
            for identity in playlist['ids']:
                member = QListWidgetItem(self.state['tracks'].get(identity, f'Missing track · {identity:016x}'))
                member.setToolTip(member.text()); self.members.addItem(member)
        self.track_count.setText(f"{len(playlist['ids'])} / 1024 songs" if item else 'No playlist selected')
        self.empty_members.setText('This playlist is empty\n\nSelect songs on the right and choose Add to playlist.' if item else
                                  'Create a playlist to get started\n\nYour songs will appear here in playback order.')
        self.member_stack.setCurrentIndex(0 if playlist['ids'] else 1)
        self.message.setText('Changes are saved when you choose Save to iPod.')
        self.update_actions()

    def create(self):
        for slot, playlist in enumerate(self.state['lists']):
            if not playlist['name']:
                names = {entry['name'] for entry in self.state['lists']}
                name, suffix = 'New playlist', 2
                while name in names:
                    name = f'New playlist {suffix}'; suffix += 1
                playlist.update(name=name, ids=[]); self.render(slot)
                self.name.setFocus(); self.name.selectAll(); return

    def delete(self):
        if self.slot is not None:
            self.state['lists'][self.slot] = dict(name='', ids=[]); self.render()

    def rename(self, text):
        if self.slot is not None:
            if not text.strip() or '\0' in text or len(text.encode('utf-8')) > 31:
                self.message.setText('Each playlist needs a name of 1–31 UTF-8 bytes.'); return
            self.state['lists'][self.slot]['name'] = text
            self.playlists.currentItem().setText(text)
            self.playlists.currentItem().setToolTip(text)
            self.message.setText('Changes are saved when you choose Save to iPod.')

    def add(self):
        if self.slot is None:
            return
        ids = self.state['lists'][self.slot]['ids']
        selected = sorted((item for item in self.songs.selectedItems() if not item.isHidden()), key=self.songs.row)
        if len(ids) + len(selected) > 1024:
            self.message.setText('A playlist can contain at most 1024 songs.'); return
        ids.extend(int(item.data(Qt.UserRole)) for item in selected); self.select()

    def remove(self):
        if self.slot is not None:
            ids = self.state['lists'][self.slot]['ids']
            for row in sorted((self.members.row(item) for item in self.members.selectedItems()), reverse=True):
                ids.pop(row)
            self.select()

    def move(self, direction):
        selected = self.members.selectedItems()
        if self.slot is None or len(selected) != 1:
            return
        row = self.members.row(selected[0])
        ids = self.state['lists'][self.slot]['ids']; target = row + direction
        if 0 <= target < len(ids):
            ids[row], ids[target] = ids[target], ids[row]
            with QSignalBlocker(self.members):
                member = self.members.takeItem(row)
                self.members.insertItem(target, member)
                self.members.setCurrentItem(member)
            self.message.setText('Changes are saved when you choose Save to iPod.')
            self.update_actions()

    def filter(self, text):
        query, count = text.casefold(), 0
        for row in range(self.songs.count()):
            item = self.songs.item(row)
            visible = query in item.text().casefold()
            item.setHidden(not visible)
            count += visible
        self.library_count.setText(f'{count:,} songs' + (' matching your search' if text else ' available'))
        self.song_stack.setCurrentIndex(0 if count else 1)
        self.empty_songs.setText('No matching songs\n\nTry another title, artist, or album.' if text else
                                'No prepared songs\n\nPrepare your music to add songs to playlists.')
        self.update_actions()

    def accept_checked(self):
        if self.slot is not None and self.name.text() != self.state['lists'][self.slot]['name']:
            self.message.setText('Each playlist needs a name of 1–31 UTF-8 bytes.'); return
        self.accept()
