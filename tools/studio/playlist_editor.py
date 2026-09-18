from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)


class PlaylistEditor(QDialog):
    def __init__(self, parent, state):
        super().__init__(parent)
        self.state, self.slot = state, None
        self.setWindowTitle('iPod playlists')
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Edit playlists, then Save to iPod. Up to 16 playlists, 1024 tracks each.'))
        columns = QHBoxLayout(); layout.addLayout(columns, 1)
        left, middle, right = QVBoxLayout(), QVBoxLayout(), QVBoxLayout()
        columns.addLayout(left, 1); columns.addLayout(middle, 2); columns.addLayout(right, 2)
        self.playlists = QListWidget(); left.addWidget(self.playlists)
        self.add_button(left, 'New playlist', self.create)
        self.add_button(left, 'Delete playlist', self.delete)
        self.name = QLineEdit(); self.name.setPlaceholderText('Playlist name'); middle.addWidget(self.name)
        self.members = QListWidget(); self.members.setSelectionMode(QAbstractItemView.ExtendedSelection)
        middle.addWidget(self.members)
        actions = QHBoxLayout(); middle.addLayout(actions)
        self.add_button(actions, 'Move up', lambda: self.move(-1))
        self.add_button(actions, 'Move down', lambda: self.move(1))
        self.add_button(middle, 'Remove selected tracks', self.remove)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search prepared songs'); right.addWidget(self.search)
        self.songs = QListWidget(); self.songs.setSelectionMode(QAbstractItemView.ExtendedSelection); right.addWidget(self.songs)
        self.add_button(right, 'Add selected songs', self.add)
        for identity, title in sorted(state['tracks'].items(), key=lambda item: item[1].casefold()):
            item = QListWidgetItem(title); item.setData(Qt.UserRole, str(identity)); self.songs.addItem(item)
        self.message = QLabel(); self.message.setWordWrap(True); layout.addWidget(self.message)
        footer = QHBoxLayout(); layout.addLayout(footer)
        self.add_button(footer, 'Cancel', self.reject)
        self.add_button(footer, 'Save to iPod', self.accept_checked)
        self.playlists.currentRowChanged.connect(self.select)
        self.name.textEdited.connect(self.rename)
        self.search.textChanged.connect(self.filter)
        self.songs.itemDoubleClicked.connect(lambda _: self.add())
        self.render()

    def add_button(self, layout, text, action):
        item = QPushButton(text); item.clicked.connect(action); layout.addWidget(item)

    def render(self, selected=None):
        self.playlists.blockSignals(True); self.playlists.clear()
        for slot, playlist in enumerate(self.state['lists']):
            if playlist['name']:
                item = QListWidgetItem(playlist['name']); item.setData(Qt.UserRole, slot); self.playlists.addItem(item)
                if slot == selected:
                    self.playlists.setCurrentItem(item)
        self.playlists.blockSignals(False)
        if self.playlists.currentRow() < 0 and self.playlists.count():
            self.playlists.setCurrentRow(0)
        self.select()

    def select(self, *_):
        item = self.playlists.currentItem()
        self.slot = item.data(Qt.UserRole) if item else None
        self.name.setEnabled(item is not None); self.members.clear()
        playlist = self.state['lists'][self.slot] if item else dict(name='', ids=[])
        self.name.setText(playlist['name'])
        for identity in playlist['ids']:
            self.members.addItem(self.state['tracks'].get(identity, f'Missing track · {identity:016x}'))
        self.message.setText(f"{len(playlist['ids'])} tracks · Names can use up to 31 UTF-8 bytes.")

    def create(self):
        for slot, playlist in enumerate(self.state['lists']):
            if not playlist['name']:
                playlist.update(name='New playlist', ids=[]); self.render(slot)
                self.name.setFocus(); self.name.selectAll(); return
        self.message.setText('All 16 playlists are in use.')

    def delete(self):
        if self.slot is not None:
            self.state['lists'][self.slot] = dict(name='', ids=[]); self.render()

    def rename(self, text):
        if self.slot is not None:
            if not text.strip() or '\0' in text or len(text.encode('utf-8')) > 31:
                self.message.setText('Each playlist needs a name of 1–31 UTF-8 bytes.'); return
            self.state['lists'][self.slot]['name'] = text
            self.playlists.currentItem().setText(text)

    def add(self):
        if self.slot is None:
            return
        ids = self.state['lists'][self.slot]['ids']
        selected = sorted((item for item in self.songs.selectedItems() if not item.isHidden()), key=self.songs.row)
        if len(ids) + len(selected) > 1024:
            self.message.setText('A playlist can contain at most 1024 tracks.'); return
        ids.extend(int(item.data(Qt.UserRole)) for item in selected); self.select()

    def remove(self):
        if self.slot is not None:
            ids = self.state['lists'][self.slot]['ids']
            for row in sorted((self.members.row(item) for item in self.members.selectedItems()), reverse=True):
                ids.pop(row)
            self.select()

    def move(self, direction):
        row = self.members.currentRow()
        if self.slot is None or row < 0:
            return
        ids = self.state['lists'][self.slot]['ids']; target = row + direction
        if 0 <= target < len(ids):
            ids[row], ids[target] = ids[target], ids[row]
            self.select(); self.members.setCurrentRow(target)

    def filter(self, text):
        for row in range(self.songs.count()):
            item = self.songs.item(row); item.setHidden(text.casefold() not in item.text().casefold())

    def accept_checked(self):
        if self.slot is not None and self.name.text() != self.state['lists'][self.slot]['name']:
            self.message.setText('Each playlist needs a name of 1–31 UTF-8 bytes.'); return
        # Validate displayed slots too: a blank rename is not a deletion.
        for row in range(self.playlists.count()):
            name = self.state['lists'][self.playlists.item(row).data(Qt.UserRole)]['name']
            if not name.strip() or '\0' in name or len(name.encode('utf-8')) > 31:
                self.message.setText('Each playlist needs a name of 1–31 UTF-8 bytes.'); return
        self.accept()
