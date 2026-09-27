"""Linnet's native media library and device workspace."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from PySide6.QtCore import (QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, QObject, QRectF, QSize, QPointF, QUrl,
                           Qt, QTimer, Signal, Slot, QSettings, QBuffer, QIODevice, QLoggingCategory, QSignalBlocker)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QIcon, QImage, QImageReader, QKeySequence, QPalette,
                          QLinearGradient, QPainter, QPainterPath, QPixmap, QShortcut, QPen)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QProgressBar, QPushButton, QScrollArea,
    QStackedWidget, QStyledItemDelegate, QStyle,
    QTableView, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QStyleOptionButton, QSizePolicy)

from tools.content import apple_os, games, media_manager as media, media_library, media_status, media_trash
from tools.content.media_manager import format_size as size
from tools.content.music import COVER_NAMES, EXTENSIONS as MUSIC_EXTENSIONS
from tools.studio import installer, screen_settings


ACCENT = '#66d9ef'
UI_FONT = 'Century Gothic'
ICONS = {
    'music': '<path d="M9 18V5l12-2v13M9 9l12-2"/><ellipse cx="6" cy="18" rx="3" ry="3"/><ellipse cx="18" cy="16" rx="3" ry="3"/>',
    'photos': '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 5-5 4 4 4-6 5 7"/>',
    'videos': '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="m10 8 6 4-6 4Z"/>',
    'notes': '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z M14 3v6h6M8 13h8M8 17h5"/>',
    'prepare': '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
    'setup': '<rect x="6" y="2" width="12" height="20" rx="3"/><rect x="8.5" y="5" width="7" height="6" rx="1"/><circle cx="12" cy="16" r="2.5"/>',
    'trash': '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    'settings': '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="10" cy="18" r="2"/>',
    'search': '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    'refresh': '<path d="M20 10a8 8 0 1 0-2 8M20 4v6h-6"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'folder': '<path d="M3 7V5h6l2 2h10v13H3Z"/>',
    'back': '<path d="m14 5-7 7 7 7"/>',
    'eject': '<path d="m5 14 7-10 7 10ZM5 19h14"/>',
    'check': '<path d="m5 12 4 4L19 6"/>',
}


@lru_cache(maxsize=1)
def _boot_artwork_source():
    return QPixmap(str(Path(__file__).resolve().parents[2] / 'assets' / 'boot-screen.png'))


def boot_artwork(rect, width, height):
    artwork = _boot_artwork_source()
    image = artwork.copy(*rect).scaled(width * 2, height * 2, Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation).toImage().convertToFormat(QImage.Format_ARGB32)
    # The boot artwork has a near-black matte. Render it as transparency while
    # preserving the silver and cyan lettering and antialiased edges.
    pixels = image.bits()
    stride = image.bytesPerLine()
    red, green, blue, alpha_byte = ((2, 1, 0, 3) if sys.byteorder == 'little' else
                                    (1, 2, 3, 0))
    for y in range(image.height()):
        for x in range(image.width()):
            offset = y * stride + x * 4
            peak = max(pixels[offset + red], pixels[offset + green], pixels[offset + blue])
            alpha = max(0, (peak - 24) * 255 // 231)
            if alpha:
                for channel in (red, green, blue):
                    index = offset + channel
                    pixels[index] = min(255, pixels[index] * 255 // peak)
                pixels[offset + alpha_byte] = alpha
            else:
                pixels[offset:offset + 4] = b'\0\0\0\0'
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(2)
    return pixmap


@lru_cache(maxsize=128)
def icon(name, color='#63757b', size=20):
    data = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(data.encode()).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def label(text='', name=None, wrap=False):
    item = QLabel(text)
    item.setTextFormat(Qt.PlainText)
    item.setWordWrap(wrap)
    if name:
        item.setObjectName(name)
    return item


def button(text, callback, name=None, glyph=None):
    item = QPushButton(text)
    item.setCursor(Qt.PointingHandCursor)
    if name:
        item.setObjectName(name)
    if glyph:
        item.setIcon(icon(glyph, '#102b32' if name == 'primary' else '#63757b'))
    item.clicked.connect(callback)
    return item


def box(parent=None, horizontal=False, margins=(0, 0, 0, 0), spacing=12):
    layout = QHBoxLayout(parent) if horizontal else QVBoxLayout(parent)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    return layout


def music_group_key(row, field):
    title = row.get(field) or f'Unknown {field}'
    return (title, row.get('album_artist') or row.get('artist', '')) if field == 'album' else title


class StatusLabel(QLabel):
    def __init__(self, text):
        super().__init__()
        self.setObjectName('muted'); self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.message = text

    def set_message(self, text, tooltip=None):
        self.message = text
        self.setToolTip(tooltip or text)
        self.render_message()

    def render_message(self):
        self.setText(self.fontMetrics().elidedText(self.message, Qt.ElideRight, max(0, self.contentsRect().width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_message()


class ComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        view = QListView(self)
        view.setUniformItemSizes(True)
        self.setView(view)

    def showPopup(self):
        # Qt's popup container and scroll gutters otherwise inherit the OS dark
        # palette, even when the list itself has a light stylesheet.
        popup = self.view().window()
        palette = popup.palette()
        for role in (QPalette.Window, QPalette.Base, QPalette.Button):
            palette.setColor(role, QColor('white'))
        palette.setColor(QPalette.WindowText, QColor('#202629'))
        popup.setPalette(palette)
        popup.setAutoFillBackground(True)
        super().showPopup()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#63757b'), 1.5))
        x, y = self.width() - 18, self.height() / 2
        painter.drawLine(QPointF(x - 3, y - 2), QPointF(x, y + 1))
        painter.drawLine(QPointF(x, y + 1), QPointF(x + 3, y - 2))
        painter.end()


class CheckBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            option = QStyleOptionButton(); self.initStyleOption(option)
            rect = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, self)
            painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor('white'), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            path = QPainterPath(QPointF(rect.x() + rect.width() * .27, rect.y() + rect.height() * .5))
            path.lineTo(rect.x() + rect.width() * .45, rect.y() + rect.height() * .68)
            path.lineTo(rect.x() + rect.width() * .76, rect.y() + rect.height() * .34)
            painter.drawPath(path); painter.end()


@dataclass(frozen=True)
class OperationContext:
    id: int
    tag: str
    identity: dict | None
    cancel_event: threading.Event | None

    @property
    def can_cancel(self):
        return self.cancel_event is not None


@dataclass(frozen=True)
class OperationOutcome:
    context: OperationContext
    value: object = None
    status: str = 'succeeded'
    error: str = ''
    error_type: str = ''
    cancel_requested: bool = False


def operation_status(value):
    if isinstance(value, dict):
        if value.get('stopped'):
            return 'cancelled'
        if value.get('complete') is False or value.get('needs_preparation'):
            return 'partial'
    return 'succeeded'


class Events(QObject):
    done = Signal(object)
    progress = Signal(str)
    stage = Signal(object)
    conversion = Signal(object)
    artwork = Signal(int, str, object)
    tools_checked = Signal(int, object)


class Covers(QObject):
    """Load only visible artwork; keep device IO off the GUI thread."""
    MAX_CACHE_BYTES = 64 * 1024 * 1024

    def __init__(self, parent):
        super().__init__(parent)
        self.cache, self.pending = OrderedDict(), {}
        self.cache_costs, self.cache_bytes = {}, 0
        self.sidecars = OrderedDict()
        self.sidecar_lock = threading.Lock()
        self.generation = 0
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='linnet-art')
        self.events = Events(self)
        self.events.artwork.connect(self.receive)
        self.views = []
        self.repaint_queued = False

    def get(self, path, source=None):
        if not path or self.closed:
            return None
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        # Completions repaint the views, which request any still-visible covers
        # again. Keep rapid scrolling from queuing an entire library of reads.
        if path not in self.pending and len(self.pending) < 6:
            self.pending[path] = self.pool.submit(self.read, path, source, self.generation)
        return None

    def invalidate(self, paths=None):
        with self.sidecar_lock:
            self.generation += 1
            self.sidecars.clear()
        for future in self.pending.values():
            future.cancel()
        self.pending.clear()
        if paths is None:
            self.cache.clear()
            self.cache_costs.clear()
            self.cache_bytes = 0
        else:
            for path in paths:
                self.cache.pop(path, None)
                self.cache_bytes -= self.cache_costs.pop(path, 0)

    def read(self, path, source_path, generation):
        if self.closed or generation != self.generation:
            return
        image = QImage()
        try:
            source = Path(path)
            if source.suffix.lower() == '.rgb' or source.suffix.lower() in MUSIC_EXTENSIONS:
                source_path = source_path or (path if source.suffix.lower() in MUSIC_EXTENSIONS else None)
                if source_path:
                    folder = Path(source_path).parent
                    original = self.sidecar(folder, generation)
                    if original and original.stat().st_size <= 32 * 1024 * 1024:
                        image = self.read_image(str(original))
                    if image.isNull():
                        from tools.content.music import _embedded_cover
                        embedded = _embedded_cover(Path(source_path))
                        if embedded:
                            buffer = QBuffer(); buffer.setData(embedded); buffer.open(QIODevice.ReadOnly)
                            image = self.read_image(buffer)
                if image.isNull() and source.suffix.lower() == '.rgb':
                    with source.open('rb') as reader:
                        pixels = reader.read(32769)
                    # Prepared artwork is RGB565: 64 pixels on older targets,
                    # 128 on the Classic. Reject truncated or oversized files.
                    side = {8192: 64, 32768: 128}.get(len(pixels))
                    if side:
                        image = QImage(pixels, side, side, side * 2, QImage.Format_RGB16).copy()
            else:
                image = self.read_image(path)
        except (OSError, ValueError):
            pass
        if not self.closed:
            self.events.artwork.emit(generation, path, image)

    def sidecar(self, folder, generation):
        """Share positive folder lookups within one artwork generation."""
        with self.sidecar_lock:
            if self.closed or generation != self.generation:
                return None
            original = self.sidecars.pop(folder, None)
            if original is not None and original.is_file():
                self.sidecars[folder] = original
                return original
            original = next((folder / name for name in COVER_NAMES if (folder / name).is_file()), None)
            if original is not None:
                self.sidecars[folder] = original
                if len(self.sidecars) > 256:
                    self.sidecars.popitem(last=False)
            return original

    @staticmethod
    def read_image(source):
        reader = QImageReader(source); reader.setAutoTransform(True)
        dimensions = reader.size()
        if dimensions.isValid() and dimensions.width() * dimensions.height() <= 32_000_000:
            if dimensions.width() > 320 or dimensions.height() > 320:
                reader.setScaledSize(dimensions.scaled(320, 320, Qt.KeepAspectRatio))
            return reader.read()
        return QImage()

    @Slot(int, str, object)
    def receive(self, generation, path, image):
        if generation != self.generation:
            return
        self.pending.pop(path, None)
        self.cache_bytes -= self.cache_costs.pop(path, 0)
        picture = QPixmap.fromImage(image) if not image.isNull() else None
        cost = picture.width() * picture.height() * 4 if picture else 0
        self.cache[path] = picture
        self.cache_costs[path] = cost
        self.cache_bytes += cost
        self.cache.move_to_end(path)
        while len(self.cache) > 600 or self.cache_bytes > self.MAX_CACHE_BYTES:
            oldest, _ = self.cache.popitem(last=False)
            self.cache_bytes -= self.cache_costs.pop(oldest)
        if not self.repaint_queued:
            self.repaint_queued = True
            QTimer.singleShot(0, self.repaint_views)

    def repaint_views(self):
        self.repaint_queued = False
        for view in self.views:
            if view.isVisible():
                view.viewport().update()


def paint_cover(painter, rect, row, covers, rounded=9):
    if rect.isEmpty():
        return
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(rect), rounded, rounded)
    painter.setClipPath(clip)
    picture = covers.get(row.get('artwork', ''), row.get('cover_source') or row.get('path'))
    if picture:
        scale = max(rect.width() / picture.width(), rect.height() / picture.height())
        source = QRectF(0, 0, rect.width() / scale, rect.height() / scale)
        source.moveCenter(QPointF(picture.width() / 2, picture.height() / 2))
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(QRectF(rect), picture, source)
    else:
        colors = [('#9c8cce', '#615285'), ('#8fbdba', '#457676'), ('#d4ac9a', '#926769'), ('#a1afce', '#546884')]
        a, b = colors[hashlib.sha256(row['title'].encode()).digest()[0] % len(colors)]
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(a)); gradient.setColorAt(1, QColor(b))
        painter.fillRect(rect, gradient)
        glyph = row.get('kind', 'Music').lower()
        if glyph not in ICONS:
            glyph = 'music'
        extent = min(42, int(rect.width() * .34))
        icon(glyph, '#ffffff', extent).paint(painter, int(rect.center().x() - extent / 2), int(rect.center().y() - extent / 2), extent, extent)
    painter.restore()


class MediaModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows, self.columns = [], [('title', 'TITLE')]

    def reset(self, rows, columns=None):
        self.beginResetModel()
        self.rows = rows
        if columns is not None:
            self.columns = columns
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows) or not 0 <= index.column() < len(self.columns):
            return None
        row = self.rows[index.row()]
        if role == Qt.UserRole:
            return row
        if role == Qt.ToolTipRole:
            return str(row.get(self.columns[index.column()][0], ''))
        if role == Qt.DisplayRole:
            key = self.columns[index.column()][0]
            value = row.get(key, '')
            if key == 'bytes':
                return size(value or 0)
            if key == 'duration':
                return f'{int(value) // 60}:{int(value) % 60:02}' if value else '—'
            return str(value or '—')
        if role == Qt.ForegroundRole and index.column():
            return QColor('#63757b')

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole and 0 <= section < len(self.columns):
            return self.columns[section][1]

    def sort(self, column, order=Qt.AscendingOrder):
        if not 0 <= column < len(self.columns):
            return
        key = self.columns[column][0]
        self.layoutAboutToBeChanged.emit()
        previous = self.persistentIndexList()
        if key == 'status' and all(row.get('kind') == 'Trash' for row in self.rows):
            key = 'started'
        if key in ('bytes', 'duration', 'started'):
            sort_key = lambda row: row.get(key, 0) or 0
        else:
            sort_key = lambda row: str(row.get(key, '')).casefold()
        if previous:
            positions = sorted(range(len(self.rows)), key=lambda at: sort_key(self.rows[at]), reverse=order == Qt.DescendingOrder)
            self.rows[:] = [self.rows[at] for at in positions]
            relocated = {old: new for new, old in enumerate(positions)}
            self.changePersistentIndexList(previous, [self.index(relocated[index.row()], index.column()) for index in previous])
        else:
            self.rows.sort(key=sort_key, reverse=order == Qt.DescendingOrder)
        self.layoutChanged.emit()


class Artwork(QWidget):
    def __init__(self, row, covers, parent=None):
        super().__init__(parent)
        self.row, self.covers = row, covers
        self.setFixedSize(180, 180)
        covers.events.artwork.connect(self.art_ready)

    @Slot(int, str, object)
    def art_ready(self, generation, path, _image):
        artwork = self.row.get('artwork')
        if generation == self.covers.generation and (path == artwork or artwork not in self.covers.cache):
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        paint_cover(painter, QRectF(self.rect()), self.row, self.covers)
        painter.end()


class TrackDelegate(QStyledItemDelegate):
    def __init__(self, covers, parent=None):
        super().__init__(parent)
        self.covers = covers

    def paint(self, painter, option, index):
        if index.column():
            return super().paint(painter, option, index)
        row = index.data(Qt.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor('#ddf4f8'))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor('#edf7f9'))
        painter.setPen(QColor('#e9eef0'))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        x, y = option.rect.x(), option.rect.y()
        paint_cover(painter, QRectF(x + 12, y + 9, 38, 38), row, self.covers, 5)
        painter.setPen(QColor('#202c31'))
        painter.setFont(QFont(UI_FONT, 10, QFont.DemiBold))
        width = option.rect.width() - 76
        painter.drawText(x + 64, y + 25, painter.fontMetrics().elidedText(row['title'], Qt.ElideRight, width))
        painter.setPen(QColor('#617176'))
        painter.setFont(QFont(UI_FONT, 9))
        subtitle = row.get('artist') or row.get('status') or row.get('subtitle', '')
        painter.drawText(x + 64, y + 43, painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, width))
        painter.restore()


class CardDelegate(QStyledItemDelegate):
    def __init__(self, covers, parent=None):
        super().__init__(parent)
        self.covers = covers

    def sizeHint(self, option, index):
        return QSize(186, 234)

    def paint(self, painter, option, index):
        row = index.data(Qt.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 4, -8, -5)
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor('#d9f2f7' if option.state & QStyle.State_Selected else '#ecf4f6'))
            painter.drawRoundedRect(rect, 13, 13)
        art = QRectF(rect.x() + 7, rect.y() + 7, rect.width() - 14, rect.width() - 14)
        paint_cover(painter, art, row, self.covers, art.width() / 2 if row.get('group_kind') == 'Artists' else 9)
        painter.setPen(QColor('#202c31'))
        painter.setFont(QFont(UI_FONT, 10, QFont.DemiBold))
        painter.drawText(int(art.x()), int(art.bottom() + 24), painter.fontMetrics().elidedText(row['title'], Qt.ElideRight, int(art.width())))
        painter.setFont(QFont(UI_FONT, 9))
        painter.setPen(QColor('#617176'))
        subtitle = row.get('subtitle') or row.get('status', '')
        painter.drawText(int(art.x()), int(art.bottom() + 44), painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, int(art.width())))
        painter.restore()


class LibraryPage:
    def __init__(self, window):
        self.window = window

    def build(self):
        window = self.window
        page = QWidget(); outer = box(page, margins=(30, 28, 26, 20), spacing=16)
        top = box(horizontal=True)
        titles = box(spacing=5); window.heading_label = label('Music', 'title', True); window.subtitle = label('', 'subtitle', True)
        titles.addWidget(window.heading_label); titles.addWidget(window.subtitle); top.addLayout(titles, 1)
        window.playlists_button = button('Playlists', window.open_playlists, None, 'music'); top.addWidget(window.playlists_button)
        window.add_button = button('Add media', window.add_media, 'primary', 'plus'); top.addWidget(window.add_button)
        outer.addLayout(top)
        toolbar = box(horizontal=True)
        window.segments = QFrame(); window.segments.setObjectName('segments'); segments = box(window.segments, horizontal=True, margins=(4, 4, 4, 4), spacing=2)
        window.view_buttons = {}
        for name in ('Songs', 'Albums', 'Artists', 'Genres'):
            item = button(name, lambda _=False, n=name: window.change_view(n), 'segment'); item.setCheckable(True)
            window.view_buttons[name] = item; segments.addWidget(item)
        toolbar.addWidget(window.segments)
        window.back_button = button('Back', window.back_to_groups, 'quiet', 'back'); toolbar.addWidget(window.back_button)
        outer.addLayout(toolbar)
        toolbar = box(horizontal=True)
        window.search = QLineEdit(); window.search.setPlaceholderText('Search your collection'); window.search.setClearButtonEnabled(True); window.search.setMinimumWidth(220)
        window.search.addAction(icon('search'), QLineEdit.LeadingPosition)
        window.search.setAccessibleName('Search collection')
        window.search.setToolTip('Search this collection (Ctrl+F). All search words must match.')
        window.search_timer = QTimer(window); window.search_timer.setSingleShot(True); window.search_timer.setInterval(160); window.search_timer.timeout.connect(window.render_library)
        window.search.textChanged.connect(lambda: window.search_timer.start()); toolbar.addWidget(window.search)
        outer.addLayout(toolbar)
        filters = box(horizontal=True)
        window.genre_filter = ComboBox(); window.genre_filter.addItem('All genres', ''); window.genre_filter.currentIndexChanged.connect(window.render_library)
        window.artist_filter = ComboBox(); window.artist_filter.addItem('All artists', ''); window.artist_filter.currentIndexChanged.connect(window.render_library)
        window.genre_filter.setAccessibleName('Filter by genre')
        window.artist_filter.setAccessibleName('Filter by artist')
        filters.addWidget(window.genre_filter); filters.addWidget(window.artist_filter)
        window.clear_button = button('Clear filters', window.clear_filters, 'quiet'); filters.addWidget(window.clear_button)
        filters.addStretch(); window.result_count = label('', 'muted'); filters.addWidget(window.result_count)
        window.sync_button = button('Sync video folder', window.sync_videos, None, 'refresh'); filters.addWidget(window.sync_button)
        window.folder_button = button('Open iPod folder', window.open_media_folder, None, 'folder'); filters.addWidget(window.folder_button)
        outer.addLayout(filters)
        window.notice = label('', 'notice', True); window.notice.hide(); outer.addWidget(window.notice)
        window.model = MediaModel(window)
        window.table = QTableView(); window.table.setModel(window.model); window.table.setShowGrid(False); window.table.setAlternatingRowColors(False)
        window.table.setSelectionBehavior(QAbstractItemView.SelectRows); window.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        window.table.setEditTriggers(QAbstractItemView.NoEditTriggers); window.table.setSortingEnabled(True)
        window.table.sortByColumn(0, Qt.AscendingOrder)
        window.table.setWordWrap(False)
        window.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel); window.table.verticalHeader().hide(); window.table.verticalHeader().setDefaultSectionSize(57)
        window.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        window.table.setItemDelegate(TrackDelegate(window.covers, window.table)); window.table.setMouseTracking(True)
        window.grid = QListView(); window.grid.setModel(window.model); window.grid.setViewMode(QListView.IconMode)
        window.grid.setResizeMode(QListView.Adjust); window.grid.setMovement(QListView.Static); window.grid.setUniformItemSizes(True)
        window.grid.setLayoutMode(QListView.Batched); window.grid.setBatchSize(50); window.grid.setSpacing(4)
        window.grid.setSelectionMode(QAbstractItemView.ExtendedSelection); window.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        window.grid.setItemDelegate(CardDelegate(window.covers, window.grid)); window.grid.setMouseTracking(True)
        window.covers.views = [window.table, window.grid]
        window.views = QStackedWidget(); window.views.addWidget(window.table); window.views.addWidget(window.grid)
        window.empty = QWidget(); empty = box(window.empty, margins=(30, 60, 30, 60)); empty.addStretch()
        window.empty_title = label('Your collection starts here', 'section'); window.empty_title.setAlignment(Qt.AlignCenter)
        window.empty_detail = label('Connect an iPod in Disk Mode to browse its media.', 'muted', True); window.empty_detail.setAlignment(Qt.AlignCenter)
        empty.addWidget(window.empty_title); empty.addWidget(window.empty_detail)
        window.empty_action = button('Find iPod', window.activate_empty, 'primary')
        empty.addWidget(window.empty_action, 0, Qt.AlignHCenter)
        empty.addStretch(); window.views.addWidget(window.empty)
        outer.addWidget(window.views, 1)
        window.table.selectionModel().selectionChanged.connect(window.selection_changed)
        window.grid.selectionModel().selectionChanged.connect(window.selection_changed)
        window.grid.activated.connect(window.open_group)
        window.table.activated.connect(window.inspect_selection)
        window.selection_bar = QFrame(); window.selection_bar.setObjectName('selectionBar'); selection = box(window.selection_bar, horizontal=True, margins=(16, 9, 12, 9))
        window.selection_text = label(); selection.addWidget(window.selection_text, 1)
        selection.addWidget(button('Clear', window.clear_selection, 'quiet'))
        window.info_button = button('Details', window.inspect_selection); selection.addWidget(window.info_button)
        window.restore_button = button('Restore', window.restore_selected, None, 'back'); selection.addWidget(window.restore_button)
        window.remove_button = button('Move to Trash', window.remove_selected, 'danger', 'trash'); selection.addWidget(window.remove_button)
        outer.addWidget(window.selection_bar); window.selection_bar.hide()
        window.hint = label('Double-click an item for details. Ctrl+click or Shift+click to select multiple files.', 'muted', True); outer.addWidget(window.hint)
        return page

class PreparationPage:
    def __init__(self, window):
        self.window = window

    def build(self):
        window = self.window
        page = QWidget(); page.setObjectName('workspace')
        outer = box(page, spacing=0)
        scroll, layout = window.scroll_page()
        scroll.setObjectName('preparationScroll')
        window.preparation_scroll = scroll
        outer.addWidget(scroll, 1)
        window.heading(layout, 'Prepare your media', 'Turn your files into an iPod-ready collection. Your originals stay on the device.')
        window.prep_checks, window.prep_labels = {}, {}
        descriptions = {'Music': 'Build the song library and album artwork', 'Photos': 'Create thumbnails and zoomable photos', 'Videos': 'Validate existing videos and prepare them for this iPod', 'Notes': 'Prepare text and Markdown for the reader'}
        for kind in ('Music', 'Photos', 'Videos', 'Notes'):
            card = QFrame(); card.setObjectName('card'); row = box(card, horizontal=True, margins=(20, 18, 20, 18), spacing=15)
            check = CheckBox(kind); check.setChecked(True); check.setMinimumWidth(110); window.prep_checks[kind] = check; row.addWidget(check)
            text = box(spacing=5); text.addWidget(label(descriptions[kind], 'cardTitle'))
            state = label('Connect an iPod to check this library.', 'muted'); window.prep_labels[kind] = state; text.addWidget(state); row.addLayout(text, 1)
            if kind == 'Videos':
                window.choose_videos_button = button('Choose videos', window.choose_videos); row.addWidget(window.choose_videos_button)
            layout.addWidget(card)
        window.online_artwork = CheckBox('Find missing iTunes album covers online (MusicBrainz / Cover Art Archive)')
        window.online_artwork.setChecked(window.settings.value('onlineArtwork', True, type=bool))
        window.online_artwork.toggled.connect(lambda enabled: window.settings.setValue('onlineArtwork', enabled))
        layout.addWidget(window.online_artwork)
        layout.addSpacing(10); layout.addWidget(label('Up next', 'section'))
        window.queue_model = MediaModel(window)
        window.queue_table = QTableView(); window.queue_table.setModel(window.queue_model); window.queue_table.verticalHeader().hide(); window.queue_table.setShowGrid(False)
        window.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows); window.queue_table.setSelectionMode(QAbstractItemView.ExtendedSelection); window.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        window.queue_table.setMinimumHeight(125); window.queue_table.setMaximumHeight(200)
        layout.addWidget(window.queue_table)
        queue_actions = box(horizontal=True)
        window.queue_add = button('Add files or folder', window.add_media, None, 'plus'); queue_actions.addWidget(window.queue_add)
        window.queue_open = button('Show source', window.open_queued, None, 'folder'); queue_actions.addWidget(window.queue_open)
        window.queue_remove = button('Remove from queue', window.remove_queued, 'quiet'); queue_actions.addWidget(window.queue_remove); queue_actions.addStretch()
        window.queue_remove.setToolTip('Remove selected entries from this queue. Source files stay on your computer.')
        window.queue_table.selectionModel().selectionChanged.connect(window.update_queue_controls)
        window.queue_table.activated.connect(window.open_queued)
        shortcut = QShortcut(QKeySequence('Delete'), window.queue_table, activated=window.remove_queued)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        layout.addLayout(queue_actions)
        window.prep_results = QTextEdit(); window.prep_results.setReadOnly(True); window.prep_results.setMinimumHeight(130); window.prep_results.hide(); layout.addWidget(window.prep_results)
        window.prep_details = button('View preparation details', window.show_preparation_details, 'quiet')
        window.prep_details.hide(); layout.addWidget(window.prep_details, 0, Qt.AlignLeft)
        window.retry_button = button('Review skipped files', window.review_skipped, 'quiet'); layout.addWidget(window.retry_button, 0, Qt.AlignLeft)
        layout.addSpacing(12)
        apple_card = QFrame(); apple_card.setObjectName('card')
        apple_layout = box(apple_card, margins=(20, 18, 20, 18), spacing=9)
        apple_layout.addWidget(label('Available in Apple OS', 'cardTitle'))
        apple_layout.addWidget(label('Choose folders already on your iPod. Update Apple OS after their files change.', 'muted', True))
        window.apple_status = label('Connect an iPod to check Apple OS availability.', 'muted', True)
        apple_layout.addWidget(window.apple_status)
        apple_actions = box(horizontal=True)
        window.apple_choose = button('Choose folders…', window.choose_apple_folders, None, 'folder')
        window.apple_update = button('Update Apple OS', window.update_apple_os, None, 'refresh')
        apple_actions.addWidget(window.apple_choose); apple_actions.addWidget(window.apple_update); apple_actions.addStretch()
        apple_layout.addLayout(apple_actions); layout.addWidget(apple_card)
        layout.addStretch()
        footer = QFrame(); footer.setObjectName('preparationFooter')
        actions = box(footer, horizontal=True, margins=(34, 16, 34, 16), spacing=18)
        window.prep_summary = label('Unchanged media is reused. Choose which videos to convert.', 'muted', True)
        actions.addWidget(window.prep_summary, 1)
        window.prepare_button = button('Prepare selected media', window.prepare, 'primary', 'prepare')
        actions.addWidget(window.prepare_button)
        outer.addWidget(footer)
        return page

class ScreensPage:
    def __init__(self, window):
        self.window = window

    def build(self):
        window = self.window
        page, layout = window.scroll_page()
        window.heading(layout, 'Screens', 'Choose what appears on your iPod and arrange it in your preferred order.')
        window.screen_state = screen_settings.defaults()
        window.screen_loaded_for = None
        window.screen_picker = ComboBox(); window.screen_picker.addItems(['Home', 'Music', 'Settings'])
        window.screen_picker.currentTextChanged.connect(window.screens_controller.render_screen_items)
        layout.addWidget(window.screen_picker)
        layout.addWidget(label('Check items to include them. Drag to reorder, or use the move buttons.', 'muted', True))
        window.screen_items = QListWidget(); window.screen_items.setObjectName('screenItems'); window.screen_items.setMinimumHeight(350)
        window.screen_items.setDragDropMode(QAbstractItemView.InternalMove)
        window.screen_items.setDefaultDropAction(Qt.MoveAction)
        window.screen_items.itemChanged.connect(window.screens_controller.screen_items_changed)
        window.screen_items.model().rowsMoved.connect(window.screens_controller.screen_items_changed)
        layout.addWidget(window.screen_items)
        window.screen_unavailable = label('', 'muted', True); layout.addWidget(window.screen_unavailable)
        window.screen_hint = label('', 'muted', True); layout.addWidget(window.screen_hint)
        window.screen_items.currentItemChanged.connect(window.screens_controller.screen_item_hint)
        controls = box(horizontal=True)
        controls.addWidget(button('Move up', lambda: window.screens_controller.move_screen_item(-1)))
        controls.addWidget(button('Move down', lambda: window.screens_controller.move_screen_item(1)))
        controls.addStretch()
        controls.addWidget(button('Reset this screen', window.screens_controller.reset_screen))
        layout.addLayout(controls)
        window.screen_status = label('Connect an iPod in Disk Mode to save screen settings.', 'muted', True)
        layout.addWidget(window.screen_status)
        window.screen_save = button('Save to iPod', window.screens_controller.save_screens, 'primary')
        layout.addWidget(window.screen_save)
        window.screens_controller.render_screen_items()
        return page

class GamesPage:
    def __init__(self, window):
        self.window = window

    def build(self):
        window = self.window
        page, layout = window.scroll_page()
        window.heading(layout, 'Games', 'Choose the games that appear on your iPod.')
        window.games_loaded_for = None
        window.game_checks = []
        for index, (title, description) in enumerate(games.GAMES):
            card = QFrame(); card.setObjectName('card')
            row = box(card, horizontal=True, margins=(20, 18, 20, 18), spacing=15)
            check = CheckBox(title); check.setChecked(True); check.setMinimumWidth(145)
            check.toggled.connect(window.games_controller.games_changed)
            window.game_checks.append(check); row.addWidget(check)
            row.addWidget(label(description, 'muted', True), 1)
            layout.addWidget(card)
        window.games_status = label('Connect an iPod with games to check installed games.', 'muted', True)
        layout.addWidget(window.games_status)
        window.games_save = button('Update games on iPod', window.games_controller.save_games, 'primary')
        layout.addWidget(window.games_save, 0, Qt.AlignLeft)
        layout.addStretch()
        return page

class SetupPage:
    def __init__(self, window):
        self.window = window

    def build(self):
        window = self.window
        page, layout = window.scroll_page()
        window.heading(layout, 'iPod setup', 'Choose your startup software and how your iPod starts.')
        card = QFrame(); card.setObjectName('card'); details = box(card, margins=(24, 24, 24, 24), spacing=12)
        details.addWidget(label('Connected device', 'section'))
        window.setup_device = label('Connect an iPod in Disk Mode.', 'muted', True); details.addWidget(window.setup_device)
        window.setup_software = label('', 'muted', True); details.addWidget(window.setup_software)
        window.install_detail = label('', 'notice', True); window.install_detail.hide(); details.addWidget(window.install_detail)
        window.setup_progress = QProgressBar(); window.setup_progress.setRange(0, 0)
        window.setup_progress.setTextVisible(False); window.setup_progress.hide(); details.addWidget(window.setup_progress)
        layout.addWidget(card)
        layout.addSpacing(12); layout.addWidget(label('Startup software', 'section'))
        layout.addWidget(label('Choose a default or see options available by holding Menu at startup.', 'muted'))
        window.boot_choice = ComboBox(); window.boot_choice.currentIndexChanged.connect(window.update_install_action); layout.addWidget(window.boot_choice)
        window.boot_detail = label('', 'muted', True); layout.addWidget(window.boot_detail)
        window.method_title = label('Startup behavior', 'section'); layout.addWidget(window.method_title)
        window.method_choice = ComboBox(); window.method_choice.currentIndexChanged.connect(window.update_install_action); layout.addWidget(window.method_choice)
        window.method_detail = label('', 'muted', True); layout.addWidget(window.method_detail)
        window.selector_note = label('A startup selector can offer a choice at boot when compatible software is installed.', 'muted', True); layout.addWidget(window.selector_note)
        layout.addSpacing(10)
        window.install_button = button('Install Linnet', window.install_selected, 'primary'); layout.addWidget(window.install_button, 0, Qt.AlignLeft)
        layout.addWidget(label('Your media is kept. Previous startup files are saved for recovery.', 'muted', True))
        layout.addStretch()
        return page

class SettingsPage:
    def __init__(self, window):
        self.window = window

    def build(self):
        window = self.window
        page, layout = window.scroll_page()
        window.heading(layout, 'Settings', 'Preparation quality and tools, in one place.')
        layout.addWidget(label('Photo detail', 'section'))
        window.photo_detail = ComboBox(); window.photo_detail.addItems(['Standard · 640 px', 'High detail · 2048 px']); window.photo_detail.setCurrentIndex(int(window.settings.value('photo_detail', 0)))
        window.photo_detail.currentIndexChanged.connect(lambda value: window.settings.setValue('photo_detail', value)); layout.addWidget(window.photo_detail)
        layout.addWidget(label('High detail uses more storage and takes longer to prepare.', 'muted'))
        layout.addSpacing(20); layout.addWidget(label('Conversion tools', 'section'))
        window.tools_label = label('', 'muted', True); layout.addWidget(window.tools_label)
        layout.addWidget(button('Choose FFmpeg folder', window.locate_tools, None, 'folder'), 0, Qt.AlignLeft)
        layout.addSpacing(20); layout.addWidget(label('Advanced preparation', 'section'))
        window.verify_audio = CheckBox('Read entire audio files when verifying (slower)'); layout.addWidget(window.verify_audio)
        window.rebuild = CheckBox('Rebuild content that is already prepared'); layout.addWidget(window.rebuild)
        layout.addStretch(); window.update_tools()
        return page


class GamesController:
    def __init__(self, window):
        self.window = window

    def games_changed(self, *_):
        window = self.window
        if window.games_loaded_for:
            window.games_status.setText('Selection changed. Update games on iPod, then eject safely.')

    def load_games(self):
        window = self.window
        if (window.identity and games.available(window.identity) and not window.busy
                and window.games_loaded_for != window.identity['root']):
            identity = window.identity
            window.work('games', lambda: games.read(identity), 'Reading installed games…')

    def save_games(self):
        window = self.window
        if not window.identity or window.busy or not games.available(window.identity):
            return
        selected = {index for index, check in enumerate(window.game_checks) if check.isChecked()}
        identity = window.identity
        window.work('save_games', lambda: games.save(identity, selected), 'Updating games on iPod…')

class ScreensController:
    def __init__(self, window):
        self.window = window

    def render_screen_items(self, *_):
        window = self.window
        name = window.screen_picker.currentText()
        labels = screen_settings.SCREENS[name]
        selected = window.screen_state[name]
        available, unavailable = screen_settings.item_availability(name, window.identity)
        locked = screen_settings.locked_items(name, window.identity, selected)
        window.screen_unavailable.setText('Not available on this device: ' + ', '.join(labels[i] for i in unavailable))
        window.screen_unavailable.setVisible(bool(unavailable))
        order = [i for i in selected if i in available] + [i for i in available if i not in selected]
        with QSignalBlocker(window.screen_items):
            window.screen_items.clear()
            for i in order:
                shown = 'Games' if name == 'Home' and i == 7 and window.identity and games.available(window.identity) else labels[i]
                item = QListWidgetItem(shown); item.setData(Qt.UserRole, i)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
                item.setCheckState(Qt.Checked if i in selected else Qt.Unchecked)
                if i in locked:
                    item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                    item.setText(labels[i] + ' (always included)')
                    item.setToolTip('This item is always included by the device.')
                elif labels[i] in screen_settings.HINTS:
                    item.setToolTip(screen_settings.HINTS[labels[i]])
                window.screen_items.addItem(item)
        window.screen_items.setCurrentRow(0)

    def screen_items_changed(self, *_):
        window = self.window
        name = window.screen_picker.currentText()
        selected = [window.screen_items.item(i).data(Qt.UserRole) for i in range(window.screen_items.count())
                    if window.screen_items.item(i).checkState() == Qt.Checked]
        if name == 'Settings':
            video_settings = next((window.screen_items.item(i) for i in range(window.screen_items.count())
                                   if window.screen_items.item(i).data(Qt.UserRole) == 10), None)
            if video_settings is not None:
                forced = 0 in selected
                with QSignalBlocker(window.screen_items):
                    if forced and 10 not in selected:
                        video_settings.setCheckState(Qt.Checked)
                        position = sum(window.screen_items.item(i).checkState() == Qt.Checked
                                       for i in range(window.screen_items.row(video_settings)))
                        selected.insert(position, 10)
                    flags = video_settings.flags()
                    video_settings.setFlags(flags & ~Qt.ItemIsUserCheckable if forced else
                                            flags | Qt.ItemIsUserCheckable)
                    video_settings.setText('Video Settings (always included)' if forced else 'Video Settings')
                    video_settings.setToolTip('This item is always included with Display.' if forced else '')
        window.screen_state[name] = selected
        window.screen_status.setText('Unsaved changes. Save to iPod, then eject safely to apply on startup.'
                                   if all(window.screen_state.values()) else 'Select at least one item on each screen before saving.')
        window.update_controls()

    def screen_item_hint(self, item, *_):
        window = self.window
        window.screen_hint.setText(item.toolTip() if item else '')

    def move_screen_item(self, direction):
        window = self.window
        row = window.screen_items.currentRow(); target = row + direction
        if row < 0 or not 0 <= target < window.screen_items.count():
            return
        item = window.screen_items.takeItem(row); window.screen_items.insertItem(target, item)
        window.screen_items.setCurrentRow(target); self.screen_items_changed()

    def reset_screen(self):
        window = self.window
        name = window.screen_picker.currentText()
        window.screen_state[name] = screen_settings.defaults(window.identity)[name]
        self.render_screen_items(); self.screen_items_changed()

    def load_screens(self):
        window = self.window
        if window.identity and not window.busy and window.screen_loaded_for != window.identity['root']:
            identity = window.identity
            window.work('screens', lambda: screen_settings.read(identity), 'Reading screen settings…')

    def save_screens(self):
        window = self.window
        if not window.identity or window.busy:
            return
        state = {name: list(rows) for name, rows in window.screen_state.items()}
        try:
            screen_settings.encode(state)
        except ValueError as error:
            window.show_error(str(error)); return
        identity = window.identity
        window.work('save_screens', lambda: screen_settings.save(identity, state), 'Saving screen settings…')


class MediaWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Linnet · Media Manager')
        self.resize(1280, 860)
        self.setMinimumSize(1050, 700)
        self.setWindowIcon(QIcon(boot_artwork((594, 180, 310, 445), 32, 32)))
        self.settings = QSettings('Linnet', 'MediaManager')
        self.identity, self.inventory, self.review = None, None, None
        self.last_preparation = None
        self.rows, self.readiness, self.pending, self.trash_rows = [], {}, [], []
        self.pending_keys = set()
        self.pending_for = None
        self.queue_outcomes = {}
        self.draft_issues = {}
        self.stale_videos = 0
        self.queue_context = None
        self.discovery_errors = []
        self.apple_info = None
        self._library_source, self._library_cache, self._library_stats = None, {}, {}
        self.video_selection, self.video_mode, self.stop_event = set(), 'all', threading.Event()
        self.page, self.view, self.group = 'Music', self.settings.value('music_view', 'Albums'), None
        if self.view not in ('Songs', 'Albums', 'Artists', 'Genres'):
            self.view = 'Albums'
        self.busy = False
        self.closed = False
        self.operation_id = 0
        self.active_operation = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='linnet-media')
        self.tool_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='linnet-tools')
        self.tool_check_id = 0
        self.tools_ready = False
        self.events = Events(self)
        self.events.done.connect(self.completed)
        self.events.progress.connect(self.show_progress)
        self.events.stage.connect(self.show_operation_stage)
        self.events.conversion.connect(self.show_conversion_progress)
        self.events.tools_checked.connect(self.tools_checked)
        self.covers = Covers(self)
        self.ffmpeg = self.settings.value('ffmpeg', shutil.which('ffmpeg') or '')
        self.ffprobe = self.settings.value('ffprobe', shutil.which('ffprobe') or '')
        self.screens_controller = ScreensController(self)
        self.games_controller = GamesController(self)
        self.build()
        self.setStyleSheet(Path(__file__).with_suffix('.qss').read_text(encoding='utf-8'))
        self.update_preparation()
        self.navigate('Music')
        QTimer.singleShot(100, self.discover)

    def build(self):
        shell = QWidget(); self.setCentralWidget(shell)
        main = box(shell, horizontal=True, spacing=0)
        sidebar = QWidget(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(224)
        side = box(sidebar, margins=(18, 20, 18, 16), spacing=6)
        brand = box(horizontal=True, spacing=11)
        mark = label(); mark.setPixmap(boot_artwork((594, 180, 310, 445), 38, 56))
        wordmark = label(); wordmark.setPixmap(boot_artwork((548, 648, 442, 64), 132, 20))
        brand.addWidget(mark); brand.addWidget(wordmark); brand.addStretch()
        side.addLayout(brand); side.addSpacing(18)
        side.addWidget(label('LIBRARY', 'eyebrow')); side.addSpacing(7)
        self.navigation = {}
        for name, glyph in [('Music', 'music'), ('Photos', 'photos'), ('Videos', 'videos'), ('Notes', 'notes'),
                            ('Preparation', 'prepare'), ('Games', 'setup'), ('Screens', 'settings'), ('iPod setup', 'setup'), ('Trash', 'trash'), ('Settings', 'settings')]:
            if name == 'Preparation':
                side.addSpacing(18); side.addWidget(label('DEVICE', 'eyebrow')); side.addSpacing(7)
            item = button(name, lambda _=False, n=name: self.navigate(n), 'nav')
            item.setIcon(icon(glyph, '#a8bbc1')); item.setIconSize(QSize(19, 19)); item.setCheckable(True)
            item.toggled.connect(lambda checked, glyph=glyph, item=item:
                                 item.setIcon(icon(glyph, '#102b32' if checked else '#a8bbc1')))
            self.navigation[name] = item; side.addWidget(item)
        side.addStretch()
        device = QFrame(); device.setObjectName('deviceCard')
        layout = box(device, margins=(15, 17, 15, 15), spacing=9)
        self.device_name = label('Connect your iPod', 'deviceName', True)
        self.device_info = label('USB · Disk Mode', 'deviceInfo', True)
        self.capacity = QProgressBar(); self.capacity.setTextVisible(False); self.capacity.setRange(0, 100); self.capacity.setValue(0)
        layout.addWidget(self.device_name); layout.addWidget(self.device_info); layout.addWidget(self.capacity)
        self.eject_button = button('Eject safely', self.eject, 'sidebarAction', 'eject'); layout.addWidget(self.eject_button)
        side.addWidget(device)
        main.addWidget(sidebar)
        right = QWidget(); right.setObjectName('workspace'); body = box(right, spacing=0)
        self.stack = QStackedWidget(); body.addWidget(self.stack, 1)
        self.library = LibraryPage(self).build(); self.stack.addWidget(self.library)
        self.preparation = PreparationPage(self).build(); self.stack.addWidget(self.preparation)
        self.setup = SetupPage(self).build(); self.stack.addWidget(self.setup)
        self.screens = ScreensPage(self).build(); self.stack.addWidget(self.screens)
        self.games_page = GamesPage(self).build(); self.stack.addWidget(self.games_page)
        self.preferences = SettingsPage(self).build(); self.stack.addWidget(self.preferences)
        activity = QFrame(); activity.setObjectName('activity'); foot = box(activity, margins=(28, 10, 28, 12), spacing=7)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.hide(); foot.addWidget(self.progress)
        status_row = box(horizontal=True, spacing=12)
        self.status = StatusLabel('Looking for your iPod…'); status_row.addWidget(self.status, 1)
        self.cancel_button = button('Stop', self.stop, 'quiet'); self.cancel_button.setToolTip('Stop after the current step finishes'); self.cancel_button.hide(); status_row.addWidget(self.cancel_button)
        self.refresh_button = button('Refresh', self.refresh, 'quiet', 'refresh'); status_row.addWidget(self.refresh_button)
        foot.addLayout(status_row); body.addWidget(activity)
        main.addWidget(right, 1)
        QShortcut(QKeySequence.Find, self, activated=self.focus_search)
        QShortcut(QKeySequence.Refresh, self, activated=self.refresh)
        for view in (self.table, self.grid):
            shortcut = QShortcut(QKeySequence('Delete'), view, activated=self.remove_selected)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)

    def heading(self, layout, title, subtitle):
        layout.addWidget(label(title, 'title'))
        layout.addWidget(label(subtitle, 'subtitle', True))
        layout.addSpacing(16)

    def scroll_page(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); content.setObjectName('pageContent')
        layout = box(content, margins=(34, 32, 34, 28), spacing=14)
        scroll.setWidget(content)
        return scroll, layout

    def navigate(self, page):
        changed = self.page != page
        self.page = page
        for name, item in self.navigation.items():
            item.setChecked(name == page)
        if page in media.KINDS or page == 'Trash':
            if changed:
                self.group = None; self.clear_filters(render=False)
            self.stack.setCurrentWidget(self.library)
            self.render_library()
            if page == 'Trash' and self.identity and not self.busy:
                identity = self.identity
                self.work('trash', lambda: media_trash.removals(identity), 'Reading Trash…')
        elif page == 'Preparation':
            self.stack.setCurrentWidget(self.preparation)
        elif page == 'Screens':
            self.stack.setCurrentWidget(self.screens); self.screens_controller.load_screens()
        elif page == 'Games':
            self.stack.setCurrentWidget(self.games_page); self.games_controller.load_games()
        elif page == 'iPod setup':
            self.stack.setCurrentWidget(self.setup)
            if self.identity and self.review is not None:
                self.render_setup()
            elif self.identity and not self.busy:
                identity = self.identity
                self.work('setup', lambda: installer.assess(identity), 'Checking installed software…')
        else:
            self.stack.setCurrentWidget(self.preferences)
        self.update_controls()

    def change_view(self, view):
        self.view, self.group = view, None
        self.settings.setValue('music_view', view)
        self.clear_selection(); self.render_library()

    def back_to_groups(self):
        self.group = None; self.render_library()

    def focus_search(self):
        if self.stack.currentWidget() == self.library:
            self.search.setFocus(); self.search.selectAll()

    def activate_empty(self):
        if self.busy:
            return
        if not self.identity:
            self.refresh()
        elif self.library_rows():
            self.clear_filters()
        elif self.page != 'Trash':
            self.add_media()

    def clear_filters(self, *, render=True):
        self.search_timer.stop()
        with QSignalBlocker(self.search), QSignalBlocker(self.genre_filter), QSignalBlocker(self.artist_filter):
            self.search.clear(); self.genre_filter.setCurrentIndex(0); self.artist_filter.setCurrentIndex(0)
        if render:
            self.render_library()

    def library_rows(self):
        if self.page == 'Trash':
            return [dict(r, kind='Trash', title=r['title'] or 'Removed files', status=datetime.fromtimestamp(r['started']).strftime('%b %d, %Y · %H:%M')) for r in self.trash_rows]
        # Completed scans replace self.rows. Reuse page rows between searches
        # and view changes, returning a new list so model sorting stays local.
        if self._library_source is not self.rows:
            self._library_source, self._library_cache, self._library_stats = self.rows, {}, {}
            self._group_cards_cache = {}
        if self.page in self._library_cache:
            return list(self._library_cache[self.page])
        unique = {}
        for row in self.rows:
            if row['kind'] == self.page and row['category'] in ('original', 'published'):
                copy = dict(row)
                if row['kind'] == 'Photos':
                    copy['artwork'] = row.get('artwork') or row['path']
                unique[str(Path(row['path'])).casefold()] = copy
        page_rows = list(unique.values())
        albums = len({(r.get('album'), r.get('album_artist') or r.get('artist')) for r in page_rows}) if self.page == 'Music' else 0
        self._library_stats[self.page] = (len(page_rows), sum(r['bytes'] for r in page_rows), albums)
        self._library_cache[self.page] = page_rows
        return list(self._library_cache[self.page])

    def render_library(self):
        if self.page not in (*media.KINDS, 'Trash'):
            return
        context = (self.page, self.view, (self.group['group_kind'], self.group['group_key']) if self.group else None)
        selected_keys = set()
        active = self.views.currentWidget()
        if getattr(self, '_selection_context', None) == context and active in (self.table, self.grid):
            indices = active.selectionModel().selectedRows() if active is self.table else active.selectionModel().selectedIndexes()
            for index in indices:
                if 0 <= index.row() < len(self.model.rows):
                    row = self.model.rows[index.row()]
                    selected_keys.add(('group', row['group_kind'], row['group_key']) if 'group_key' in row else ('row', row['id']))
        self._selection_context = context
        rows = self.library_rows()
        all_rows = rows
        music = self.page == 'Music'
        self.heading_label.setText(self.group['title'] if self.group else self.page)
        self.segments.setVisible(music and self.group is None)
        for name, item in self.view_buttons.items():
            item.setChecked(name == self.view)
        self.back_button.setVisible(self.group is not None)
        self.genre_filter.setVisible(music); self.artist_filter.setVisible(music)
        self.sync_button.setVisible(self.page == 'Videos')
        self.folder_button.setVisible(self.page != 'Trash')
        self.add_button.setVisible(self.page != 'Trash')
        self.search.setPlaceholderText('Search songs, artists, albums…' if music else f'Search {self.page.lower()}…')
        words = self.search.text().casefold().split()
        artist, genre = self.artist_filter.currentData(), self.genre_filter.currentData()
        if self.group:
            rows = list(self.group['members'])
        scope_count = len(rows)
        if music and (artist or genre):
            rows = [r for r in rows if (not artist or (r.get('artist') or 'Unknown artist') == artist)
                    and (not genre or (r.get('genre') or 'Unknown genre') == genre)]
        if words:
            matches = []
            first, *remaining = words
            for row in rows:
                text = row.get('_linnet_search_text')
                if text is None:
                    text = ' '.join(str(row.get(field, '')) for field in ('title', 'artist', 'album', 'genre', 'path')).casefold()
                    row['_linnet_search_text'] = text
                if first in text and (not remaining or all(word in text for word in remaining)):
                    matches.append(row)
            rows = matches
        matched_count = len(rows)
        filtered = bool(words or (music and (artist or genre)))
        grouped = music and self.view != 'Songs' and self.group is None
        if grouped:
            cards = self._group_cards_cache.get(self.view) if not filtered else None
            if cards is None:
                groups = {}
                field = {'Albums': 'album', 'Artists': 'artist', 'Genres': 'genre'}[self.view]
                for row in rows:
                    key = music_group_key(row, field)
                    groups.setdefault(key, []).append(row)
                cards = []
                for key, members in groups.items():
                    artists = {r.get('artist') for r in members if r.get('artist')}
                    subtitle = (members[0].get('album_artist') or (next(iter(artists)) if len(artists) == 1 else 'Various artists')) if self.view == 'Albums' else f'{len(members):,} songs'
                    art_row = next((r for r in members if r.get('artwork')), members[0])
                    cards.append(dict(title=members[0].get(field) or f'Unknown {field}', subtitle=subtitle,
                        kind='Music', group_kind=self.view, group_key=key, members=members, artwork=art_row.get('artwork', '') if self.view != 'Genres' else '', cover_source=art_row['path'], bytes=sum(r['bytes'] for r in members)))
                if not filtered:
                    self._group_cards_cache[self.view] = cards
            rows = list(cards)
        # The table applies its own title sort after reset. Keep this first
        # sort for grids and as a stable title tie-break for other columns.
        if grouped or self.group is not None or self.table.horizontalHeader().sortIndicatorSection() > 0:
            rows.sort(key=lambda r: (r.get('disc', 0), r.get('track', 0), r['title'].casefold()) if self.group and self.view == 'Albums' else (r['title'].casefold(),))
        columns = ([('title', 'TITLE'), ('album', 'ALBUM'), ('genre', 'GENRE'), ('duration', 'TIME'), ('bytes', 'SIZE')]
                   if music and not grouped else [('title', 'NAME'), ('status', 'STATUS'), ('bytes', 'SIZE')])
        self.model.reset(rows, columns)
        if not grouped and self.group is None:
            header = self.table.horizontalHeader()
            self.model.sort(max(0, min(header.sortIndicatorSection(), self.model.columnCount() - 1)), header.sortIndicatorOrder())
        layout = tuple(columns)
        if getattr(self, '_table_layout', None) != layout:
            self._table_layout = layout
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            for col in range(1, self.model.columnCount()):
                self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
                self.table.setColumnWidth(col, 220 if col == 1 and music else 130 if col < 3 else 80)
        grid = grouped or self.page in ('Photos', 'Videos')
        self.views.setCurrentWidget(self.grid if grid else self.table)
        if not rows:
            self.views.setCurrentWidget(self.empty)
            self.empty_title.setText('Reading your collection…' if self.busy else 'Connect your iPod' if not self.identity else 'No matches' if all_rows else 'Trash is empty' if self.page == 'Trash' else f'No {self.page.lower()} yet')
            self.empty_detail.setText('Your collection will appear here when reading finishes.' if self.busy else 'Connect an iPod in Disk Mode, then find it to browse and add media.' if not self.identity else 'Try another search or clear your filters.' if all_rows else 'Removed files appear here until you restore or permanently delete them.' if self.page == 'Trash' else 'Add files from your computer to get started.')
        self.empty_action.setText('Find iPod' if not self.identity else 'Clear filters' if all_rows else 'Add media')
        self.empty_action.setVisible(not self.busy and (not self.identity or bool(all_rows) or self.page != 'Trash'))
        count, total_bytes, albums = ((len(all_rows), sum(r['bytes'] for r in all_rows), 0)
                                      if self.page == 'Trash' else self._library_stats[self.page])
        self.subtitle.setText(f'{count:,} songs  ·  {albums:,} albums  ·  {size(total_bytes)}' if music else
                              'Restore removed files or delete them permanently to free space.' if self.page == 'Trash' else
                              f'{count:,} files on your iPod  ·  {size(total_bytes)}')
        if self.group:
            members = self.group['members']
            self.subtitle.setText((self.group['subtitle'] + '  ·  ' if self.view == 'Albums' else '') + f'{len(members):,} songs  ·  {size(sum(r["bytes"] for r in members))}')
        unit = 'songs' if music else 'items'
        self.result_count.setText(f'{matched_count:,} of {scope_count:,} {unit}' + (f' · {len(rows):,} {self.view.lower()}' if grouped else '') if filtered else
                                  f'{len(rows):,} {self.view.lower() if grouped else unit}')
        self.clear_button.setVisible(filtered)
        self.hint.setText('Select videos to move them to Trash. Sync video folder reconciles files changed in Explorer.' if self.page == 'Videos' else
                          'Double-click to explore. Select one or more groups to manage their songs.' if grouped else
                          'Select a removal to restore it, or permanently delete it to free storage.' if self.page == 'Trash' else
                          'Ctrl+click or Shift+click to select multiple files. Double-click for details.')
        self.selection_bar.hide()
        active = self.views.currentWidget()
        if selected_keys and active in (self.table, self.grid):
            selection = QItemSelection()
            start = None
            for index in range(len(self.model.rows) + 1):
                if index < len(self.model.rows):
                    row = self.model.rows[index]
                    key = ('group', row['group_kind'], row['group_key']) if 'group_key' in row else ('row', row['id'])
                    chosen = key in selected_keys
                else:
                    chosen = False
                if chosen and start is None:
                    start = index
                elif not chosen and start is not None:
                    selection.select(self.model.index(start, 0), self.model.index(index - 1, 0))
                    start = None
            if not selection.isEmpty():
                flags = QItemSelectionModel.Select | (QItemSelectionModel.Rows if active is self.table else QItemSelectionModel.NoUpdate)
                active.selectionModel().select(selection, flags)
                self.selection_changed()

    def selected(self):
        view = self.views.currentWidget()
        if view not in (self.grid, self.table):
            return []
        indices = view.selectionModel().selectedRows() if view is self.table else view.selectionModel().selectedIndexes()
        rows = [self.model.rows[index.row()] for index in indices]
        unique = {}
        for row in rows:
            for member in row.get('members', [row]):
                unique[member['id']] = member
        return list(unique.values())

    def selection_changed(self, *_):
        rows = self.selected()
        self.selection_bar.setVisible(bool(rows))
        self.selection_text.setText(f'{len(rows):,} selected  ·  {size(sum(r["bytes"] for r in rows))}')
        self.restore_button.setVisible(self.page == 'Trash')
        self.restore_button.setEnabled(not self.busy)
        retail_photos = bool(rows) and all(r.get('retail_photo') for r in rows)
        self.remove_button.setText('Exclude from preparation' if retail_photos else
                                   'Delete permanently' if self.page == 'Trash' else 'Move to Trash')
        self.remove_button.setEnabled(not self.busy and (retail_photos or all(r.get('removable', True) for r in rows)))
        self.info_button.setEnabled(len(rows) == 1 and not self.busy)

    def clear_selection(self):
        self.table.clearSelection(); self.grid.clearSelection(); self.selection_bar.hide()

    def open_group(self, index):
        row = self.model.rows[index.row()]
        if 'members' in row:
            self.group = row; self.render_library()
        else:
            self.inspect_selection()

    def dialog(self, title, message, action='Continue', danger=False, cancel=True):
        dialog = QDialog(self); dialog.setWindowTitle(title); dialog.setMinimumWidth(460)
        layout = box(dialog, margins=(28, 28, 28, 24), spacing=18)
        layout.addWidget(label(title, 'section')); layout.addWidget(label(message, None, True))
        actions = box(horizontal=True); actions.addStretch()
        if cancel:
            actions.addWidget(button('Cancel', dialog.reject))
        actions.addWidget(button(action, dialog.accept, 'danger' if danger else 'primary')); layout.addLayout(actions)
        return dialog.exec() == QDialog.Accepted

    def confirm_trash(self, rows):
        dialog = QDialog(self); dialog.setObjectName('trashDialog')
        dialog.setWindowTitle('Move to iPod Trash'); dialog.resize(720, min(550, 340 + len(rows) * 42))
        dialog.setMinimumSize(580, 380)
        layout = box(dialog, margins=(28, 26, 28, 24), spacing=16)
        heading = box(horizontal=True, spacing=14)
        symbol = label(); symbol.setPixmap(icon('trash', '#167489', 30).pixmap(30, 30))
        heading.addWidget(symbol); heading.addWidget(label('Move to iPod Trash?', 'dialogTitle')); heading.addStretch()
        layout.addLayout(heading)
        noun = 'file' if len(rows) == 1 else 'files'
        layout.addWidget(label(f'{len(rows):,} {noun} selected · {size(sum(row["bytes"] for row in rows))}', 'trashSummary'))
        preview = QTableView(); preview.setObjectName('trashPreview')
        model = MediaModel(preview)
        model.reset([dict(row, filename=Path(row['path']).name) for row in rows],
                    [('title', 'TITLE'), ('filename', 'FILE'), ('bytes', 'SIZE')])
        preview.setModel(model); preview.setSortingEnabled(True)
        preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        preview.setSelectionBehavior(QAbstractItemView.SelectRows)
        preview.setShowGrid(False); preview.setWordWrap(False)
        preview.verticalHeader().hide(); preview.verticalHeader().setDefaultSectionSize(42)
        preview.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        preview.setColumnWidth(2, 95); preview.sortByColumn(0, Qt.AscendingOrder)
        layout.addWidget(preview, 1)
        note = QFrame(); note.setObjectName('recoveryNote')
        note_layout = box(note, margins=(16, 13, 16, 13), spacing=5)
        note_layout.addWidget(label('You can restore these files', 'cardTitle'))
        note_layout.addWidget(label('Find them in Trash on this iPod. Playback libraries update automatically. Storage is freed when you empty Trash.', None, True))
        layout.addWidget(note)
        actions = box(horizontal=True, spacing=10); actions.addStretch()
        cancel = button('Keep files', dialog.reject); cancel.setDefault(True)
        move = button('Move to Trash', dialog.accept, 'danger', 'trash'); move.setAutoDefault(False)
        actions.addWidget(cancel); actions.addWidget(move); layout.addLayout(actions)
        cancel.setFocus()
        return dialog.exec() == QDialog.Accepted

    def inspect_selection(self, *_):
        rows = self.selected()
        if len(rows) != 1:
            return
        row = rows[0]
        dialog = QDialog(self); dialog.setWindowTitle('Media details'); dialog.resize(550, 330)
        layout = box(dialog, margins=(28, 28, 28, 28), spacing=15)
        if row.get('artwork'):
            layout.addWidget(Artwork(row, self.covers, dialog), 0, Qt.AlignHCenter)
        layout.addWidget(label(row['title'], 'section', True))
        for field in ('artist', 'album', 'genre', 'status'):
            if row.get(field):
                layout.addWidget(label(f'{field.title()}   {row[field]}', 'muted', True))
        layout.addWidget(label(size(row['bytes']), 'muted'))
        location = label(row['path'], 'muted', True); location.setTextInteractionFlags(Qt.TextSelectableByMouse); layout.addWidget(location)
        actions = box(horizontal=True); actions.addWidget(button('Show in folder', lambda: self.open_folder(row['path']), None, 'folder')); actions.addStretch(); actions.addWidget(button('Done', dialog.accept, 'primary')); layout.addLayout(actions)
        dialog.exec()

    def open_folder(self, path):
        try:
            source = Path(path).resolve(strict=True)
            if source.is_dir():
                os.startfile(str(source))
            else:
                subprocess.Popen(['explorer.exe', '/select,', str(source)])
        except OSError as error:
            self.dialog('Cannot open location', f'The file or folder may have moved or the device may be disconnected.\n\n{error}', 'OK', cancel=False)

    def open_media_folder(self):
        if self.busy or not self.identity or self.page not in media.KINDS:
            return
        root = Path(self.identity['root'])
        folder = root / self.page
        self.open_folder(folder if folder.is_dir() else root)

    def open_queued(self, *_):
        indices = self.queue_table.selectionModel().selectedRows()
        if not self.busy and len(indices) == 1:
            self.open_folder(self.queue_model.rows[indices[0].row()]['path'])

    def update_queue_controls(self, *_):
        count = len(self.queue_table.selectionModel().selectedRows())
        self.queue_remove.setEnabled(not self.busy and count > 0)
        self.queue_open.setEnabled(not self.busy and count == 1)

    def work(self, tag, operation, message):
        if self.busy or self.closed:
            return
        self.operation_id += 1
        context = OperationContext(self.operation_id, tag,
            dict(self.identity) if self.identity and tag != 'devices' else None,
            self.stop_event if tag in ('prepare', 'remove', 'restore') else None)
        self.active_operation = context
        self.busy = True
        self.stop_event.clear()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText('Stop')
        self.cancel_button.setToolTip('Stop after the current step finishes')
        self.cancel_button.setVisible(context.can_cancel)
        self.show_progress(message)
        self.update_controls()
        def run():
            try:
                value = operation()
                outcome = OperationOutcome(context, value, status=operation_status(value),
                    cancel_requested=bool(context.cancel_event and context.cancel_event.is_set()))
            except Exception as error:
                outcome = OperationOutcome(context,
                    status='cancelled' if type(error).__name__ == 'Cancelled' else 'failed',
                    error=str(error) or type(error).__name__,
                    error_type=type(error).__name__,
                    cancel_requested=bool(context.cancel_event and context.cancel_event.is_set()))
            self.events.done.emit(outcome)
        self.pool.submit(run)

    @Slot(str)
    def show_progress(self, text):
        self.status.set_message(text)

    @Slot(object)
    def show_operation_stage(self, event):
        if not self.busy:
            return
        fraction = min(1.0, max(0.0, event.get('fraction', 0)))
        value = min(999, round(1000 * (event['completed'] + fraction) / event['total']))
        self.progress.setRange(0, 1000)
        self.progress.setValue(value)
        context = self.active_operation
        can_stop = bool(context and context.cancel_event and event['can_stop']
                        and not context.cancel_event.is_set())
        self.cancel_button.setEnabled(can_stop)
        self.cancel_button.setText('Stop' if can_stop else 'Finishing current step')
        self.cancel_button.setToolTip('Stop after the current step finishes' if can_stop else
                                      'The current guarded write or cleanup must finish.')
        self.status.set_message(event['name'])

    @Slot(object)
    def show_conversion_progress(self, event):
        def duration(seconds):
            minutes, seconds = divmod(max(0, round(seconds)), 60)
            return f'{minutes}:{seconds:02}'
        stage = 'Converting' if event['stage'] == 'convert' else 'Checking'
        parts = []
        if event.get('percent') is not None:
            parts.append(f"{event['percent']:.0f}%")
        eta = event.get('eta_seconds')
        parts.append(f'~{duration(eta)} left' if eta is not None else 'Estimating time')
        parts.append(f"{duration(event['elapsed_seconds'])} elapsed")
        parts.append(stage)
        if event.get('video_total', 1) > 1:
            parts.append(f"Video {event['video_index']}/{event['video_total']}")
        if event.get('name'):
            parts.append(event['name'])
        self.status.set_message(' · '.join(parts), event['message'])

    @Slot(object)
    def completed(self, outcome):
        context = outcome.context
        if self.active_operation is None or context.id != self.active_operation.id:
            return
        self.active_operation = None
        tag, result, error = context.tag, outcome.value, outcome.error
        self.busy = False
        self.progress.hide()
        self.cancel_button.hide()
        self.update_controls()
        if outcome.status not in ('succeeded', 'partial', 'cancelled', 'failed'):
            self.show_error(f'Unknown background outcome: {outcome.status}')
            return
        if context.identity and not self.same_device(self.identity, context.identity):
            self.show_error('The selected iPod changed while this operation was running. Refresh and try again.')
            return
        if tag == 'queue':
            self._complete_queue(result, error)
            return
        if error:
            self._complete_error(tag, error)
            return
        handlers = {
            'screens': self._complete_screens, 'plan': self._complete_plan,
            'save_screens': self._complete_save_screens, 'games': self._complete_games,
            'save_games': self._complete_save_games, 'review_skipped': self._complete_review_skipped,
            'playlists': self._complete_playlists, 'save_playlists': self._complete_save_playlists,
            'apple_selection': self._complete_apple_selection, 'apple_update': self._complete_apple_update,
            'devices': self._complete_devices, 'scan': self._complete_scan,
            'trash': self._complete_trash, 'setup': self._complete_setup,
            'prepare': self._complete_prepare, 'eject': self._complete_eject,
        }
        for change in ('remove', 'restore', 'erase', 'sync', 'install', 'skipped'):
            handlers[change] = self._complete_change
        handler = handlers.get(tag)
        if handler is None:
            self.show_error(f'Unknown background operation: {tag}')
            return
        handler(result)
        if tag not in ('screens', 'plan', 'save_screens', 'games', 'save_games',
                       'review_skipped', 'playlists', 'save_playlists',
                       'apple_selection', 'apple_update'):
            self.update_controls()

    def _complete_queue(self, result, error):
        context = self.queue_context
        self.queue_context = None
        if context is None or not context['dialog'].isVisible():
            return
        if not self.same_device(self.identity, context['identity']):
            context['error'].setText('The selected iPod changed while checking these sources. Choose them again.')
            context['error'].show()
            return
        if error:
            context['error'].setText(error)
            context['error'].show()
            return
        additions = result
        self.pending.extend(additions)
        self.pending_keys.update((kind, os.path.normcase(path)) for kind, path in additions)
        for kind, path in additions:
            self.queue_outcomes.pop((kind, os.path.normcase(path)), None)
        if self.pending:
            self.pending_for = dict(context['identity'])
        self.validate_draft()
        self.save_draft()
        kind, source = context['kind'], Path(context['paths'][0])
        self.settings.setValue(f'import_folder/{kind}', str(source if context['folder'] else source.parent))
        self.prep_checks[kind].setChecked(True)
        context['dialog'].accept()
        self.update_preparation()
        self.navigate('Preparation')
        QTimer.singleShot(0, lambda: self.preparation_scroll.ensureWidgetVisible(self.queue_table))
        self.show_progress(f'{len(additions):,} new queue entries added.' if additions else
                           'These sources are already queued. Review them in Preparation.')
        return

    def _complete_error(self, tag, error):
        if tag == 'plan':
            self.plan_context = None
        if tag == 'screens':
            self.screen_state = screen_settings.defaults(self.identity)
            self.screens_controller.render_screen_items()
            self.screen_status.setText('Could not read settings. Showing defaults for this iPod; saving will replace its screen settings.')
        if tag in ('setup', 'devices', 'scan'):
            self.setup_progress.hide()
            self.setup_software.setText('Could not check iPod setup. Choose Refresh to try again.')
        self.show_error(error)
        if tag == 'save_playlists':
            self.edit_playlists(self.playlist_draft)
        return

    def _complete_screens(self, result):
        self.screen_state = result; self.screen_loaded_for = self.identity['root']; self.screens_controller.render_screen_items()
        self.screen_status.setText('Loaded from iPod. Changes apply after saving and restarting Linnet.'); self.update_controls(); return

    def _complete_plan(self, result):
        context = self.plan_context
        self.plan_context = None
        if context is None or not self.same_device(self.identity, context['identity']):
            self.show_error('The selected iPod changed while preparing the plan. Review it again.')
            return
        copies = ', '.join(f'{kind}: {count}' for kind, count in result['copy_kinds'].items() if count)
        preview = [f"Prepare: {', '.join(result['selected'])}",
                   f"Copy originals: {result['copies']:,} files ({size(result['bytes'])})" +
                   (f' · {copies}' if copies else ''),
                   f"iPod free before copying: {size(result['free'])}",
                   f"Computer free for preparation: {size(result['computer_free'])}",
                   f"Video jobs: {result['videos']:,}" +
                   (' · conversion output size is unknown' if result['conversion'] else '')]
        if result['reusable']:
            preview.append('Likely reusable prepared libraries: ' + ', '.join(result['reusable']))
        if result['excluded']:
            preview.append(f"Queue entries outside this selection: {result['excluded']:,}")
        for source, description in list(result['previews'].items())[:5]:
            preview.append(f'{Path(source).name}: {description}')
        if len(result['previews']) > 5:
            preview.append(f"…and {len(result['previews']) - 5:,} more queued sources")
        preview.append('Sources, available space, and prepared outputs are checked again during preparation.')
        if self.dialog('Review preparation plan', '\n'.join(preview), 'Start preparation'):
            self.submitted, self.submitted_videos = context['pending'], context['submitted_videos']
            self.prep_results.hide()
            self.work('prepare', context['run'], 'Preparing your selected media…')
        return

    def _complete_save_screens(self, result):
        self.screen_status.setText('Saved to iPod. Eject safely to apply on startup.'); return

    def _complete_games(self, result):
        for index, check in enumerate(self.game_checks):
            with QSignalBlocker(check):
                check.setChecked(index in result)
        self.games_loaded_for = self.identity['root']
        self.games_status.setText('Loaded from iPod. Uncheck a game to remove it from the Games menu.')
        self.update_controls(); return

    def _complete_save_games(self, result):
        self.games_status.setText('Games updated. Eject safely and restart Linnet to apply.')
        self.update_controls(); return

    def _complete_review_skipped(self, result):
        identity, rows = result
        if not self.identity or any(self.identity.get(key) != identity.get(key)
                                    for key in ('root', 'disk_serial', 'volume_serial', 'target_id')):
            self.show_error('The selected iPod changed while skipped files were loading. Try again.')
        elif rows:
            self.show_skipped_dialog(identity, rows)
        else:
            self.show_progress('No skipped files on this iPod.')
        return

    def _complete_playlists(self, result):
        self.show_progress('Playlists loaded.'); self.edit_playlists(result); return

    def _complete_save_playlists(self, result):
        self.show_progress('Playlists saved to iPod. Eject safely when finished.'); return

    def _complete_apple_selection(self, result):
        self.show_progress('Apple OS folder choices saved. Checking availability…')
        self.refresh(); return

    def _complete_apple_update(self, result):
        self.prep_results.setPlainText(result['summary']); self.prep_results.show()
        self.show_progress(result['summary']); self.refresh(); return

    def _complete_devices(self, result):
        devices, errors = result['devices'], result['errors']
        self.discovery_errors = errors
        if not devices:
            self.transition_device(None)
            self.device_name.setText('No iPod connected'); self.device_info.setText('Connect in Disk Mode')
            if errors:
                self.show_error('Could not read a connected iPod: ' + '; '.join(errors))
            else:
                self.show_progress('Connect your iPod, then choose Refresh.')
            return
        if len(devices) > 1:
            dialog = QDialog(self); dialog.setWindowTitle('Choose an iPod'); layout = box(dialog, margins=(24, 24, 24, 24))
            picker = ComboBox()
            for device in devices:
                picker.addItem(f"{device['drive']} · {device['target_name']}", device)
            layout.addWidget(picker); layout.addWidget(button('Use this iPod', dialog.accept, 'primary'))
            if dialog.exec() != QDialog.Accepted:
                return
            identity = picker.currentData()
        else:
            identity = devices[0]
        if errors:
            self.notice.setText('Other connected iPods could not be read: ' + '; '.join(errors))
            self.notice.show()
        self.transition_device(identity)
        self.refresh()

    def _complete_scan(self, result):
        cached_photos = {row['path']: (row['bytes'], row['mtime_ns'], row.get('artwork')) for row in self.rows
                         if row['kind'] in ('Photos', 'Music') and
                         (row.get('artwork') in self.covers.cache or row.get('artwork') in self.covers.pending)}
        self.identity, self.inventory, self.rows, self.readiness, self.apple_info, self.review = result
        if cached_photos:
            current_photos = {row['path']: (row['bytes'], row['mtime_ns'], row.get('artwork')) for row in self.rows
                              if row['path'] in cached_photos}
            changed = [stamp[2] for path, stamp in cached_photos.items() if current_photos.get(path) != stamp]
            if changed:
                self.covers.invalidate(changed)
        if self.group:
            field = {'Albums': 'album', 'Artists': 'artist', 'Genres': 'genre'}[self.group['group_kind']]
            members = [row for row in self.library_rows()
                       if music_group_key(row, field) == self.group['group_key']]
            if members:
                self.group['members'] = members
            else:
                self.group = None
        previous_videos = len(self.video_selection)
        self.video_selection.intersection_update(self.inventory['Videos']['files'])
        self.stale_videos = previous_videos - len(self.video_selection)
        self.validate_draft()
        self.save_draft()
        if self.discovery_errors:
            self.notice.setText('Other connected iPods could not be read: ' + '; '.join(self.discovery_errors))
            self.notice.show()
        else:
            self.notice.hide()
        self.update_device(); self.update_filters(); self.update_preparation(); self.render_library()
        self.show_progress('Ready. Eject safely when you’re finished.')
        if self.page == 'Screens':
            self.screens_controller.load_screens()
        if self.page == 'Games':
            self.games_controller.load_games()
        if self.page == 'iPod setup':
            self.render_setup()
        elif self.page == 'Trash':
            identity = self.identity
            self.work('trash', lambda: media_trash.removals(identity), 'Reading Trash…')

    def _complete_trash(self, result):
        self.trash_rows = result; self.render_library(); self.show_progress('Trash uses storage until files are permanently deleted.')

    def _complete_setup(self, result):
        self.review = result; self.render_setup(); self.show_progress('Device setup is ready.')

    def _complete_prepare(self, result):
        self.last_preparation = (result['identity'], result)
        self.update_controls()
        lines = [result.get('summary') or ('Preparation complete.' if result['complete'] else 'Preparation needs attention.')]
        lines.extend(e['message'] for e in result.get('errors', []))
        self.prep_results.setPlainText('\n'.join(lines)); self.prep_results.show()
        outcomes = {(row['kind'], os.path.normcase(row['source'])): row
                    for row in result.get('source_outcomes', [])}
        submitted_keys = {(kind, os.path.normcase(path)) for kind, path in self.submitted}
        finished = {key for key, row in outcomes.items() if row['status'] == 'completed'}
        self.pending = [item for item in self.pending
                        if (item[0], os.path.normcase(item[1])) not in submitted_keys or
                        (item[0], os.path.normcase(item[1])) not in finished]
        self.pending_keys = {(kind, os.path.normcase(path)) for kind, path in self.pending}
        self.queue_outcomes = {key: row for key, row in outcomes.items()
                               if key in self.pending_keys and row['status'] != 'completed'}
        if not self.pending:
            self.pending_for = None
        if result['complete']:
            self.video_selection.difference_update(self.submitted_videos)
        self.validate_draft()
        self.save_draft()
        self.update_preparation(); self.refresh()

    def _complete_change(self, result):
        self.show_progress(result.get('summary', 'Changes saved.'))
        if result.get('needs_preparation'):
            self.prep_results.setPlainText(result['summary']); self.prep_results.show(); self.navigate('Preparation')
        self.refresh()

    def _complete_eject(self, result):
        self.transition_device(None)
        self.device_name.setText('Safely ejected'); self.device_info.setText('You can disconnect your iPod.'); self.capacity.setValue(0)
        self.show_progress('Your iPod is safe to disconnect.')


    def discover(self):
        self.work('devices', lambda: media.discover(detailed=True), 'Looking for your iPod…')

    def open_playlists(self):
        if self.identity and not self.busy:
            from tools.content import playlists
            identity = self.identity
            self.work('playlists', lambda: playlists.read(identity), 'Reading iPod playlists…')

    def edit_playlists(self, state):
        from tools.content import playlists
        from tools.studio.playlist_editor import PlaylistEditor
        editor = PlaylistEditor(self, state)
        if editor.exec() == QDialog.Accepted:
            self.playlist_draft = state
            self.work('save_playlists', lambda: playlists.save(state), 'Saving playlists to iPod…')

    def refresh(self):
        if self.busy:
            return
        if not self.identity:
            self.discover(); return
        identity = self.identity
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        verification = 'full' if self.verify_audio.isChecked() else 'metadata'
        self.work('scan', lambda: media_status.inspect(identity, dimension, verification),
                  'Reading your collection and checking prepared media…')

    @staticmethod
    def same_device(first, second):
        return bool(first and second) and all(first.get(key) == second.get(key)
            for key in ('root', 'disk_serial', 'volume_serial', 'target_id'))

    @staticmethod
    def draft_key(identity):
        fields = (identity['target_id'], identity['disk_serial'], identity['volume_serial'])
        digest = hashlib.sha256('\0'.join(fields).encode('utf-8')).hexdigest()
        return f'preparation_draft/v2/{digest}'

    def save_draft(self):
        if not self.identity:
            return
        root = Path(self.identity['root'])
        videos = []
        for path in sorted(self.video_selection):
            try:
                videos.append(Path(path).relative_to(root).as_posix())
            except ValueError:
                continue
        draft = dict(version=2, target_id=self.identity['target_id'],
                     disk_serial=self.identity['disk_serial'],
                     volume_serial=self.identity['volume_serial'],
                     pending=[list(item) for item in self.pending],
                     video_mode=self.video_mode, videos=videos,
                     outcomes=[dict(row) for key, row in self.queue_outcomes.items()
                               if key in self.pending_keys])
        self.settings.setValue(self.draft_key(self.identity), json.dumps(draft))
        self.settings.sync()

    def validate_draft(self):
        self.draft_issues = {}
        if not self.identity:
            return
        allowed = media.supported_kinds(self.identity)
        for kind, name in self.pending:
            reason = None
            if kind not in allowed:
                reason = f'{kind} is unavailable on this iPod'
            else:
                try:
                    path = Path(name)
                    if not path.exists():
                        reason = 'Source is missing from this computer'
                    elif path.is_symlink():
                        reason = 'Linked sources must be selected again'
                except (OSError, ValueError):
                    reason = 'Saved source path is invalid'
            if reason:
                self.draft_issues[(kind, os.path.normcase(name))] = reason

    def load_draft(self, identity):
        self.pending, self.pending_keys, self.pending_for = [], set(), None
        self.video_selection, self.video_mode = set(), 'all'
        self.draft_issues, self.stale_videos, self.queue_outcomes = {}, 0, {}
        raw = self.settings.value(self.draft_key(identity), '')
        try:
            draft = json.loads(raw)
            if (not isinstance(draft, dict) or draft.get('version') != 2 or
                    any(draft.get(key) != identity[key] for key in
                        ('target_id', 'disk_serial', 'volume_serial')) or
                    not isinstance(draft.get('pending'), list) or
                    not isinstance(draft.get('videos'), list) or
                    not isinstance(draft.get('outcomes', []), list) or
                    draft.get('video_mode') not in ('all', 'selected', 'none')):
                return
            for item in draft['pending']:
                if (not isinstance(item, list) or len(item) != 2 or
                        not all(isinstance(value, str) for value in item) or
                        item[0] not in media.KINDS or not item[1]):
                    continue
                key = (item[0], os.path.normcase(item[1]))
                if key not in self.pending_keys:
                    self.pending.append(tuple(item))
                    self.pending_keys.add(key)
            for value in draft['videos']:
                if not isinstance(value, str) or '\\' in value:
                    continue
                relative = Path(value)
                if (relative.is_absolute() or relative.drive or '..' in relative.parts or
                        not relative.parts or relative.parts[0].casefold() != 'videos'):
                    continue
                self.video_selection.add(str(Path(identity['root']) / relative))
            for row in draft.get('outcomes', []):
                if (not isinstance(row, dict) or
                        not all(isinstance(row.get(key), str) for key in
                                ('kind', 'source', 'status', 'reason')) or
                        row['status'] not in ('skipped', 'unfinished')):
                    continue
                key = (row['kind'], os.path.normcase(row['source']))
                if key in self.pending_keys:
                    self.queue_outcomes[key] = row
            self.video_mode = draft['video_mode']
            if self.pending:
                self.pending_for = dict(identity)
            self.validate_draft()
        except (TypeError, ValueError):
            return

    def transition_device(self, identity):
        """Clear device-derived state while retaining a draft for its own iPod."""
        if self.same_device(self.identity, identity):
            self.identity = identity
            return
        self.save_draft()
        if identity and self.last_preparation and not self.same_device(self.last_preparation[0], identity):
            self.last_preparation = None
            self.prep_results.clear()
            self.prep_results.hide()
        self.covers.invalidate()
        self.identity = identity
        self._selection_context = None
        self.inventory = self.review = self.apple_info = None
        self.rows = []
        self.trash_rows = []
        self.readiness = {}
        self.group = None
        self.video_selection.clear()
        self.video_mode = 'all'
        if identity:
            self.load_draft(identity)
        else:
            self.pending, self.pending_keys, self.pending_for = [], set(), None
            self.draft_issues, self.stale_videos, self.queue_outcomes = {}, 0, {}
        self.screen_loaded_for = self.games_loaded_for = None
        self.screen_state = screen_settings.defaults(identity)
        self.screens_controller.render_screen_items()
        self.screen_status.setText('Loading screen settings…' if identity else
                                   'Connect an iPod in Disk Mode to save screen settings.')
        for check in self.game_checks:
            with QSignalBlocker(check):
                check.setChecked(False)
        self.games_status.setText('Loading games…' if identity else 'Connect an iPod in Disk Mode.')
        self.playlist_draft = None
        self._library_source, self._library_cache, self._library_stats = None, {}, {}
        self._group_cards_cache = {}
        self._group_cards_cache = {}
        self.capacity.setValue(0)
        self.update_filters()
        self.update_preparation()
        self.render_library()
        self.update_controls()

    def update_device(self):
        identity = self.identity
        self.device_name.setText(identity['target_name'].replace('Linnet for ', ''))
        self.device_info.setText(f"Connected · {identity['drive']}\n{size(identity['free_bytes'])} available")
        total = identity.get('total_bytes') or shutil.disk_usage(identity['root']).total
        self.capacity.setValue(int(100 * (1 - identity['free_bytes'] / total)))

    def update_filters(self):
        for picker, field, title in ((self.genre_filter, 'genre', 'All genres'), (self.artist_filter, 'artist', 'All artists')):
            old = picker.currentData()
            with QSignalBlocker(picker):
                picker.clear(); picker.addItem(title, '')
                for value in sorted({row.get(field) or f'Unknown {field}' for row in self.rows if row['kind'] == 'Music' and row['category'] == 'original'}, key=str.casefold):
                    picker.addItem(value, value)
                picker.setCurrentIndex(max(0, picker.findData(old)))

    def update_controls(self):
        ready = self.identity is not None and not self.busy
        self.retry_button.setEnabled(ready)
        self.prep_details.setVisible(self.last_preparation is not None)
        self.prep_details.setEnabled(ready and self.last_preparation is not None and
                                     all(self.identity.get(key) == self.last_preparation[0].get(key)
                                         for key in ('root', 'disk_serial', 'volume_serial', 'target_id')))
        games_ready = ready and games.available(self.identity)
        self.games_save.setEnabled(games_ready and self.games_loaded_for == self.identity['root'])
        for check in self.game_checks:
            check.setEnabled(games_ready and self.games_loaded_for == self.identity['root'])
        if ready and not games_ready:
            self.games_status.setText('Games are unavailable on this iPod.')
        supported = media.supported_kinds(self.identity) if ready else ()
        self.screens.setEnabled(not self.busy)
        self.screen_save.setEnabled(ready and all(self.screen_state.values()))
        self.screen_items.setEnabled(not self.busy)
        self.screen_picker.setEnabled(not self.busy)
        for item in (self.eject_button, self.add_button, self.playlists_button, self.sync_button, self.choose_videos_button, self.queue_add, self.folder_button):
            item.setEnabled(ready)
        self.update_queue_controls()
        self.prepare_button.setEnabled(ready and self.inventory is not None)
        apple_ready = ready and self.apple_info is not None and self.apple_info['supported']
        self.apple_choose.setEnabled(apple_ready)
        self.apple_update.setText('Retry Apple OS' if apple_ready and
                                  self.apple_info.get('can_update') and
                                  self.apple_info['status'] == 'Needs attention' else 'Update Apple OS')
        self.apple_update.setEnabled(apple_ready and self.apple_info.get('can_update', False))
        self.choose_videos_button.setEnabled(ready and self.inventory is not None and self.identity.get('media_profile', {}).get('video_enabled', True))
        self.refresh_button.setEnabled(not self.busy)
        self.empty_action.setEnabled(not self.busy)
        self.refresh_button.setVisible(not self.busy)
        for kind, check in self.prep_checks.items():
            check.setEnabled(kind in supported)
        self.update_setup_status(); self.update_install_action(); self.selection_changed()

    def update_setup_status(self):
        loading = self.busy and self.review is None
        self.setup_progress.setVisible(loading)
        if self.review is not None:
            return
        if self.identity:
            self.setup_device.setText(f"{self.identity['target_name']} · {self.identity['drive']}")
            self.setup_software.setText('Checking iPod setup…' if loading else 'Choose Refresh to check installed software.')
        else:
            self.setup_device.setText('Looking for your iPod…' if loading else 'Connect an iPod in Disk Mode.')
            self.setup_software.setText('Device detection is in progress.' if loading else '')

    def queue_status(self, kind, path):
        key = (kind, os.path.normcase(path))
        if key in self.draft_issues:
            return self.draft_issues[key]
        outcome = self.queue_outcomes.get(key)
        if outcome:
            action = ('Use Review skipped files to retry.' if outcome['status'] == 'skipped' and kind != 'Videos'
                      else 'Retry with Prepare.')
            return f"{outcome['status'].title()}: {outcome['reason']} {action}"
        return 'Ready'

    def update_preparation(self):
        supported = media.supported_kinds(self.identity) if self.identity else ()
        for kind, text in self.prep_labels.items():
            info = (self.inventory or {}).get(kind)
            if self.identity and kind not in supported:
                text.setText(f'{kind} playback is unavailable on this iPod model.')
            elif not info:
                text.setText('Connect an iPod to check this library.')
            elif kind == 'Videos':
                scope = ('All existing videos included' if self.video_mode == 'all' else
                         f'{len(self.video_selection)} selected for conversion' if self.video_mode == 'selected' else
                         'No conversions selected')
                text.setText(f"{info['count']:,} files · {self.readiness.get(kind, 'Not checked')} · " +
                             scope)
            else:
                text.setText(f"{info['count']:,} files · {self.readiness.get(kind, 'Not checked')}")
        self.queue_model.reset([dict(title=Path(path).name, kind=kind, path=path,
                                     status=self.queue_status(kind, path))
                                for kind, path in self.pending],
                               [('title', 'FILE'), ('kind', 'TYPE'), ('status', 'STATUS'),
                                ('path', 'FROM YOUR COMPUTER')])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.queue_table.setVisible(bool(self.pending)); self.queue_remove.setVisible(bool(self.pending))
        self.queue_open.setVisible(bool(self.pending)); self.update_queue_controls()
        self.queue_table.setFixedHeight(min(200, max(75, self.queue_table.horizontalHeader().height() + len(self.pending) * self.queue_table.verticalHeader().defaultSectionSize() + 4)))
        summary = (f'{len(self.pending):,} files or folders queued. Unchanged media is reused.' if self.pending else
                   'Nothing queued. You can prepare existing iPod files or add media from your computer.')
        if self.draft_issues:
            summary += f' {len(self.draft_issues):,} saved source(s) need attention.'
        if self.stale_videos:
            summary += f' {self.stale_videos:,} saved video choice(s) are no longer on this iPod.'
        self.prep_summary.setText(summary)
        if self.apple_info:
            lines = [self.apple_info['status']]
            lines.extend(f"{entry['kind']}: {entry['count']:,} files · {entry['status']}"
                         for entry in self.apple_info['details']
                         if entry['count'] or entry['kind'] == 'Notes')
            if self.apple_info.get('issues'):
                lines.append(self.apple_info['issues'][0])
            self.apple_status.setText('\n'.join(lines))
        else:
            self.apple_status.setText('Connect an iPod to check Apple OS availability.')

    def choose_apple_folders(self):
        if self.busy or not self.apple_info or not self.apple_info['supported']:
            return
        dialog = QDialog(self); dialog.setWindowTitle('Choose folders for Apple OS')
        dialog.resize(620, 640)
        layout = box(dialog, margins=(24, 24, 24, 24), spacing=12)
        layout.addWidget(label('Available in Apple OS', 'section'))
        layout.addWidget(label('Select music, photo and video folders on your iPod. Their original names and locations stay in place. Apple reads compatible text files in Notes automatically.', 'muted', True))
        tree = QTreeWidget(); tree.setHeaderLabels(['FOLDER', 'APPLE OS'])
        tree.setColumnWidth(0, 420)
        items = {}
        selected = self.apple_info['selected']
        for row in self.apple_info['folders']:
            path, kind = row['path'], row['kind']
            parent_path = path.rpartition('/')[0]
            parent = items.get(parent_path)
            item = QTreeWidgetItem(parent or tree, [path.rpartition('/')[2], ''])
            item.setData(0, Qt.UserRole, path)
            items[path] = item
            if kind in ('Music', 'Photos', 'Videos'):
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                checked = any(path.casefold() == name.casefold() or
                              path.casefold().startswith(name.casefold() + '/') for name in selected)
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                item.setText(1, 'Choose for Apple OS')
            else:
                item.setText(1, 'Visible in Apple Notes')
                item.setToolTip(1, 'Apple reads compatible text files in the Notes folder automatically.')
        for path, item in reversed(list(items.items())):
            if path.split('/')[0] not in ('Music', 'Photos', 'Videos') or not item.childCount():
                continue
            states = {item.child(index).checkState(0) for index in range(item.childCount())}
            item.setCheckState(0, states.pop() if len(states) == 1 else Qt.PartiallyChecked)
        tree.expandToDepth(0); layout.addWidget(tree, 1)
        def changed(item, column):
            if column != 0 or item.data(0, Qt.UserRole).split('/')[0] not in ('Music', 'Photos', 'Videos'):
                return
            with QSignalBlocker(tree):
                if item.checkState(0) != Qt.PartiallyChecked:
                    stack = [item.child(index) for index in range(item.childCount())]
                    while stack:
                        child = stack.pop()
                        child.setCheckState(0, item.checkState(0))
                        stack.extend(child.child(index) for index in range(child.childCount()))
                parent = item.parent()
                while parent and parent.data(0, Qt.UserRole):
                    states = {parent.child(index).checkState(0) for index in range(parent.childCount())}
                    parent.setCheckState(0, states.pop() if len(states) == 1 else Qt.PartiallyChecked)
                    parent = parent.parent()
        tree.itemChanged.connect(changed)
        actions = box(horizontal=True)
        actions.addStretch(); actions.addWidget(button('Cancel', dialog.reject, 'quiet'))
        actions.addWidget(button('Save folders', dialog.accept, 'primary'))
        layout.addLayout(actions)
        if dialog.exec() != QDialog.Accepted:
            return
        folders = [path for path, item in items.items()
                   if path.split('/')[0] in ('Music', 'Photos', 'Videos') and item.checkState(0) == Qt.Checked and
                   (not path.rpartition('/')[0] or
                    items[path.rpartition('/')[0]].checkState(0) != Qt.Checked)]
        identity = self.identity
        self.work('apple_selection', lambda: apple_os.save_selection(identity, folders),
                  'Saving Apple OS folder choices…')

    def update_apple_os(self):
        if self.busy or not self.identity or not self.apple_info or not self.apple_info.get('can_update'):
            return
        identity = self.identity
        ffprobe = self.ffprobe
        self.work('apple_update', lambda: apple_os.update(identity, ffprobe=ffprobe,
                                                          progress=self.events.progress.emit),
                  'Updating Apple OS availability…')

    def add_media(self):
        if self.busy or not self.identity:
            return
        dialog = QDialog(self); dialog.setWindowTitle('Add media'); dialog.setMinimumWidth(480)
        layout = box(dialog, margins=(28, 28, 28, 28), spacing=16)
        layout.addWidget(label('Bring something new', 'section'))
        layout.addWidget(label('Choose files from your computer. Review the queue in Preparation before copying them to your iPod.', 'muted', True))
        picker = ComboBox(); picker.addItems(media.supported_kinds(self.identity)); picker.setCurrentText(self.page if self.page in media.KINDS else 'Music'); layout.addWidget(picker)
        picker.setAccessibleName('Media type to add')
        explanation = label('', 'muted', True); layout.addWidget(explanation)
        def explain():
            explanation.setText('Folders include videos in all subfolders. Other file types are ignored. Originals stay on your computer.' if picker.currentText() == 'Videos' else
                                'Folders include all subfolders and their files, including artwork and other supporting files. Choose individual files to copy only selected media. Originals stay on your computer.')
        picker.currentTextChanged.connect(explain); explain()
        error_label = label('', 'notice', True); error_label.hide(); layout.addWidget(error_label)
        def choose(folder=False):
            kind = picker.currentText()
            initial = self.settings.value(f'import_folder/{kind}', str(Path.home()))
            if folder:
                path = QFileDialog.getExistingDirectory(dialog, f'Add {kind.lower()} folder', initial); paths = [path] if path else []
            else:
                allowed = media.video_source_extensions(self.identity) if kind == 'Videos' else media.extensions(kind)
                paths, _ = QFileDialog.getOpenFileNames(dialog, f'Add {kind.lower()}', initial, kind + ' (' + ' '.join('*' + ext for ext in sorted(allowed)) + ')')
            if paths:
                try:
                    self.queue_sources(kind, paths, dialog, error_label, folder)
                except (OSError, ValueError) as error:
                    error_label.setText(str(error)); error_label.show(); return
        actions = box(horizontal=True); actions.addWidget(button('Choose files', lambda: choose(), 'primary', 'plus')); actions.addWidget(button('Choose a folder', lambda: choose(True), None, 'folder')); layout.addLayout(actions)
        layout.addWidget(button('Cancel', dialog.reject, 'quiet'), 0, Qt.AlignRight)
        dialog.exec()

    def queue_sources(self, kind, paths, dialog, error_label, folder):
        if not self.identity or self.busy:
            raise ValueError('Connect an iPod and wait for the current operation to finish before adding media.')
        if kind not in media.supported_kinds(self.identity):
            raise ValueError(f'{kind} is unavailable on this iPod.')
        identity, known = self.identity, set(self.pending_keys)
        def validate():
            root = Path(identity['root']).resolve(strict=True)
            allowed = media.video_source_extensions(identity) if kind == 'Videos' else media.extensions(kind)
            additions = []
            for value in paths:
                source = Path(value).resolve(strict=True)
                if source.is_relative_to(root):
                    raise ValueError('This source is already on your iPod. Use Refresh to find existing media, then prepare it from Preparation.')
                if not source.is_dir() and (not source.is_file() or source.suffix.lower() not in allowed):
                    raise ValueError(f'{source.name} is not a supported {kind.lower()} file. Choose a supported file or a folder.')
                key = (kind, os.path.normcase(str(source)))
                if key not in known:
                    additions.append((kind, str(source)))
                    known.add(key)
            return additions
        self.queue_context = dict(kind=kind, paths=paths, dialog=dialog, error=error_label,
                                  folder=folder, identity=identity)
        self.work('queue', validate, 'Checking selected sources…')

    def remove_queued(self):
        if self.busy:
            return
        chosen = {index.row() for index in self.queue_table.selectionModel().selectedRows()}
        self.pending = [item for index, item in enumerate(self.pending) if index not in chosen]
        self.pending_keys = {(kind, os.path.normcase(path)) for kind, path in self.pending}
        self.queue_outcomes = {key: row for key, row in self.queue_outcomes.items() if key in self.pending_keys}
        if not self.pending:
            self.pending_for = None
        self.validate_draft()
        self.save_draft()
        self.update_preparation()

    def choose_videos(self):
        if not self.inventory or self.busy:
            return
        allowed = media.video_source_extensions(self.identity)
        native = media.native_video_extensions(self.identity)
        sources = [p for p in self.inventory['Videos']['files']
                   if Path(p).suffix.lower() in allowed and Path(p).suffix.lower() not in native]
        search_rows = [(dict(title=Path(path).name, path=path), path.casefold()) for path in sources]
        dialog = QDialog(self); dialog.setWindowTitle('Choose videos to convert'); dialog.resize(700, 520)
        layout = box(dialog, margins=(24, 24, 24, 24)); layout.addWidget(label('Choose video originals', 'section'))
        layout.addWidget(label('Device-format videos are included automatically. Choose all, selected, or no additional conversions.', 'muted', True))
        mode = ComboBox()
        for title, value in (('Convert all existing videos', 'all'),
                             ('Convert selected videos', 'selected'),
                             ('No conversions', 'none')):
            mode.addItem(title, value)
        mode.setCurrentIndex(mode.findData(self.video_mode))
        layout.addWidget(mode)
        search = QLineEdit(); search.setPlaceholderText('Find a video…'); layout.addWidget(search)
        table = QTableView(); model = MediaModel(table); table.setModel(model); table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection); table.setEditTriggers(QAbstractItemView.NoEditTriggers); table.verticalHeader().hide(); layout.addWidget(table)
        selected = set(self.video_selection)
        search_timer = QTimer(dialog)
        search_timer.setSingleShot(True)
        search_timer.setInterval(160)
        def render():
            if model.rows:
                selected.difference_update(r['path'] for r in model.rows)
                selected.update(model.rows[i.row()]['path'] for i in table.selectionModel().selectedRows())
            query = search.text().casefold()
            model.reset([row for row, folded in search_rows if query in folded],
                        [('title', 'VIDEO'), ('path', 'LOCATION')])
            selection = QItemSelection()
            start = None
            for index in range(len(model.rows) + 1):
                chosen = index < len(model.rows) and model.rows[index]['path'] in selected
                if chosen and start is None:
                    start = index
                elif not chosen and start is not None:
                    selection.select(model.index(start, 0), model.index(index - 1, 0))
                    start = None
            if not selection.isEmpty():
                table.selectionModel().select(selection, QItemSelectionModel.Select | QItemSelectionModel.Rows)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        search.textChanged.connect(search_timer.start)
        search_timer.timeout.connect(render)
        render()
        def accept():
            search_timer.stop()
            render(); self.video_selection = selected; self.video_mode = mode.currentData()
            self.stale_videos = 0
            self.save_draft()
            self.update_preparation(); dialog.accept()
        layout.addWidget(button('Apply video choices', accept, 'primary'), 0, Qt.AlignRight); dialog.exec()

    def prepare(self):
        if self.busy or not self.inventory:
            return
        selected = [kind for kind, check in self.prep_checks.items() if check.isChecked() and check.isEnabled()]
        if not selected:
            self.show_error('Choose at least one media type to prepare.'); return
        self.validate_draft()
        stale = [reason for kind, name in self.pending if kind in selected
                 if (reason := self.draft_issues.get((kind, os.path.normcase(name))))]
        if stale:
            self.show_error(f'{len(stale)} queued source(s) need attention: {stale[0]}. Remove or restore them before preparing.')
            self.update_preparation()
            return
        identity = self.identity; pending = [item for item in self.pending if item[0] in selected]
        all_pending = list(self.pending)
        videos = (None if self.video_mode == 'all' else
                  list(self.video_selection) if self.video_mode == 'selected' else [])
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        online_artwork = self.online_artwork.isChecked()
        force, verification = self.rebuild.isChecked(), 'full' if self.verify_audio.isChecked() else 'metadata'
        ffmpeg, ffprobe = (self.ffmpeg, self.ffprobe) if self.tools_ready else (None, None)
        def run():
            return media.run(identity, selected, pending, photo_dimension=dimension, force=force,
                music_verification=verification, ffmpeg=ffmpeg, ffprobe=ffprobe, video_selection=videos,
                online_artwork=online_artwork,
                progress=self.events.progress.emit, progress_detail=self.events.conversion.emit,
                progress_stage=self.events.stage.emit,
                cancelled=self.stop_event.is_set)
        self.plan_context = dict(identity=identity, pending=pending,
                                 submitted_videos=set(videos or ()) if 'Videos' in selected else set(), run=run)
        def inspect_plan():
            result = media_status.plan(identity, all_pending, selected, videos,
                current_inventory=self.inventory, photo_dimension=dimension,
                music_verification=verification, force=force, online_artwork=online_artwork)
            if result['conversion'] and (not ffmpeg or not ffprobe):
                raise ValueError('Video conversion needs FFmpeg and FFprobe. Choose their folder in Settings.')
            return result
        self.work('plan', inspect_plan, 'Checking the preparation plan…')

    def remove_selected(self):
        rows = self.selected()
        if self.busy or not self.identity or not rows:
            return
        identity = self.identity
        if all(row.get('retail_photo') for row in rows):
            def exclude_photos():
                media.skip_files(identity, [('Photos', row['path']) for row in rows])
                return dict(summary='Photos excluded. Run Prepare to update Linnet; Apple originals are retained.')
            self.work('skipped', exclude_photos, 'Excluding selected photos from preparation…')
            return
        if self.page == 'Trash':
            if self.dialog('Delete permanently?', f'Permanently delete {len(rows)} removals and free {size(sum(r["bytes"] for r in rows))}? These files cannot be restored afterward.', 'Delete permanently', True):
                def erase():
                    for row in rows:
                        media_trash.recover(identity, row['id'], erase=True)
                    return dict(summary='Trash deleted. Storage is now available.')
                self.work('erase', erase, 'Freeing iPod storage…')
            return
        if not self.confirm_trash(rows):
            return
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        ffmpeg, ffprobe = self.ffmpeg, self.ffprobe
        def remove():
            result = media_library.remove_items(identity, rows)
            needed = [kind for kind in result['requires_update'] if kind != 'Videos'
                      and kind in media.supported_kinds(identity) and kind not in result['empty_folders']]
            if needed:
                prepared = media.run(identity, needed, photo_dimension=dimension, ffmpeg=ffmpeg, ffprobe=ffprobe,
                    progress=self.events.progress.emit, cancelled=self.stop_event.is_set)
                result['complete'] = prepared['complete']
                result['stopped'] = prepared['stopped']
                result['needs_preparation'] = not prepared['complete']
                result['summary'] = 'Files moved to Trash. Playback libraries updated.' if prepared['complete'] else 'Files moved to Trash. Playback needs preparation: ' + '; '.join(e['message'] for e in prepared['errors'])
            return result
        self.work('remove', remove, 'Moving selected files to Trash…')

    def restore_selected(self):
        rows = self.selected()
        if self.busy or self.page != 'Trash' or not rows:
            return
        identity = self.identity
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        ffmpeg, ffprobe = self.ffmpeg, self.ffprobe
        def restore():
            needed = set()
            for row in rows:
                result = media_trash.recover(identity, row['id'])
                needed.update(result.get('requires_update', []))
            needed.intersection_update(media.supported_kinds(identity))
            if needed:
                prepared = media.run(identity, needed, photo_dimension=dimension, ffmpeg=ffmpeg, ffprobe=ffprobe,
                    progress=self.events.progress.emit, cancelled=self.stop_event.is_set)
                if not prepared['complete']:
                    return dict(complete=False, stopped=prepared['stopped'], needs_preparation=True,
                        summary='Files restored. Playback needs preparation: ' + '; '.join(e['message'] for e in prepared['errors']))
            return dict(complete=True, summary='Files and playback libraries restored.')
        self.work('restore', restore, 'Restoring your files…')

    def sync_videos(self):
        if self.identity and not self.busy:
            identity = self.identity
            self.work('sync', lambda: media_library.organize_videos(identity), 'Syncing the video folder…')

    def render_setup(self):
        review = self.review
        self.setup_device.setText(f"{review['identity']['target_name']} · {review['identity']['drive']}")
        self.setup_software.setText('Linnet: ' + installer.build_description(review['linnet']))
        available_boot = review['boot_options']
        with QSignalBlocker(self.boot_choice):
            self.boot_choice.clear()
            for option in available_boot:
                suffix = (' · Current' if option.get('active') else
                          ' · Hold Menu' if option.get('chooser_available') else
                          ' · Unavailable' if not option.get('selectable') else '')
                self.boot_choice.addItem(option['label'] + suffix, option)
                self.boot_choice.setItemData(self.boot_choice.count() - 1, option.get('detail', ''), Qt.ToolTipRole)
            selected = next((i for i, option in enumerate(available_boot) if option.get('active')),
                            next((i for i, option in enumerate(available_boot) if option.get('selectable')), -1))
            self.boot_choice.setPlaceholderText('No verified startup software')
            self.boot_choice.setCurrentIndex(selected)
        with QSignalBlocker(self.method_choice):
            self.method_choice.clear()
            for method in review['installation_methods']:
                if not method.get('enabled'):
                    continue
                self.method_choice.addItem(method['label'], method)
                self.method_choice.setItemData(self.method_choice.count() - 1, method['detail'], Qt.ToolTipRole)
                if method['id'] == review.get('default_installation_method'):
                    self.method_choice.setCurrentIndex(self.method_choice.count() - 1)
        self.install_detail.setText(review['summary'])
        self.install_detail.setVisible(review['action'] not in ('install', 'replace', 'adopt') or review['linnet']['state'] in ('invalid', 'incomplete'))
        self.update_install_action()

    def update_install_action(self):
        option = self.boot_choice.currentData(); method = self.method_choice.currentData()
        enabled = not self.busy and self.identity is not None and bool(option and option.get('selectable'))
        linnet = option and option['kind'] == 'linnet'
        self.boot_detail.setText(option.get('detail', '') if option else '')
        show_methods = bool(linnet and option.get('selectable') and method)
        for widget in (self.method_title, self.method_choice, self.method_detail, self.selector_note):
            widget.setVisible(show_methods)
        self.method_detail.setText(method.get('detail', '') if method and linnet else '')
        enabled = enabled and bool(method and method.get('enabled')) if linnet else enabled and not bool(option and option.get('active'))
        self.method_choice.setEnabled(bool(linnet and method) and not self.busy)
        self.boot_choice.setEnabled(not self.busy and self.review is not None and self.boot_choice.count() > 0)
        self.install_button.setEnabled(enabled)
        if option and not option.get('selectable'):
            self.install_button.setText('Current startup software' if option.get('active') else
                                        'Choose on iPod at startup' if option.get('chooser_available') else
                                        'Startup change unavailable')
        else:
            self.install_button.setText(('Reinstall ' if option.get('active') else 'Install ') + option['label'] if linnet else 'Set as default boot')

    def install_selected(self):
        if not self.install_button.isEnabled():
            return
        option, method, identity = self.boot_choice.currentData(), self.method_choice.currentData(), self.identity
        description = f"Make {option['label']} the default startup software?" + (f"\n\nMethod: {method['label']}" if option['kind'] == 'linnet' else '')
        if option['kind'] == 'linnet' and self.review.get('action') in ('replace', 'adopt'):
            description += ('\n\nYour settings, selected theme, playback history, and media libraries '
                            'will be preserved. ' + ('The confirmed OS will be retained for rollback.'
                            if method['strategy'] == 'native-volume' else
                            'Superseded Linnet system files will be archived.'))
        if not self.dialog('Update iPod setup', description + '\n\nKeep the iPod connected until the update finishes.', 'Apply to iPod'):
            return
        operation = (lambda: installer.install(identity, progress=self.events.progress.emit, build=option['build'], installation_method=method['id'])) if option['kind'] == 'linnet' else lambda: installer.restore(identity, expected=option['id'])
        self.work('install', operation, 'Updating your iPod setup…')

    def locate_tools(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose the folder containing FFmpeg and FFprobe')
        if folder:
            self.update_tools(candidate=(str(Path(folder) / 'ffmpeg.exe'),
                                         str(Path(folder) / 'ffprobe.exe')))

    def update_tools(self, *, candidate=None):
        self.tool_check_id += 1
        request = self.tool_check_id
        paths = candidate or (self.ffmpeg, self.ffprobe)
        self.tools_label.setText('Checking FFmpeg and FFprobe…')
        def check():
            errors = []
            resolved = []
            for name, value in zip(('FFmpeg', 'FFprobe'), paths):
                if not value:
                    errors.append(f'{name} is not configured.')
                    continue
                try:
                    path = Path(value).resolve(strict=True)
                    if not path.is_file() or path.stem.casefold() != name.casefold():
                        raise OSError(f'expected {name.lower()}.exe')
                    result = subprocess.run([str(path), '-version'], stdin=subprocess.DEVNULL,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                            timeout=5, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    if result.returncode:
                        raise OSError(f'version check exited with status {result.returncode}')
                    resolved.append(str(path))
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    errors.append(f'{name} at {value} could not run: {error}')
            self.events.tools_checked.emit(request, dict(candidate=candidate, paths=resolved, errors=errors))
        self.tool_pool.submit(check)

    @Slot(int, object)
    def tools_checked(self, request, result):
        if self.closed or request != self.tool_check_id:
            return
        if result['errors']:
            self.tools_label.setText(' '.join(result['errors']) + ' Choose a folder containing both tools.')
            self.tools_ready = False
            return
        self.tools_ready = True
        if result['candidate'] is not None:
            self.ffmpeg, self.ffprobe = result['paths']
            self.settings.setValue('ffmpeg', self.ffmpeg)
            self.settings.setValue('ffprobe', self.ffprobe)
        self.tools_label.setText('FFmpeg and FFprobe are ready.')

    def show_preparation_details(self):
        if not self.identity or self.last_preparation is None:
            return
        identity, report = self.last_preparation
        if any(self.identity.get(key) != identity.get(key)
               for key in ('root', 'disk_serial', 'volume_serial', 'target_id')):
            return
        lines = [report.get('summary') or 'Preparation result', '']
        for step in report.get('steps', [])[:500]:
            name = step.get('file') or step.get('added') or step.get('renamed') or step.get('kind') or 'Step'
            status = step.get('status') or ('copied' if 'added' in step else 'renamed' if 'renamed' in step else 'prepared')
            lines.append(f'{status}: {name}')
        if len(report.get('steps', [])) > 500:
            lines.append(f'... {len(report["steps"]) - 500} more steps are in the saved receipt.')
        if report.get('errors'):
            lines.extend(('', 'Skipped or failed:'))
            for error in report['errors'][:500]:
                name = error.get('file') or error.get('source') or error.get('kind') or 'Operation'
                lines.append(f'{error.get("status", "failed")}: {name} — {error.get("message", "Unknown error")}')
            if len(report['errors']) > 500:
                lines.append(f'... {len(report["errors"]) - 500} more entries are in the saved receipt.')
        receipt = Path(report['receipt'])
        lines.extend(('', f'Saved receipt: {receipt}'))
        dialog = QDialog(self); dialog.setWindowTitle('Preparation details'); dialog.resize(780, 500)
        layout = box(dialog, margins=(24, 24, 24, 24))
        details = QTextEdit(); details.setReadOnly(True); details.setPlainText('\n'.join(lines)); layout.addWidget(details)
        open_receipt = button('Open saved receipt', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(receipt))), 'quiet')
        open_receipt.setEnabled(receipt.is_file())
        layout.addWidget(open_receipt, 0, Qt.AlignLeft)
        dialog.exec()

    def review_skipped(self):
        if self.busy or not self.identity:
            return
        identity = self.identity
        self.work('review_skipped', lambda: (identity, media.list_skipped_files(identity)), 'Loading skipped files…')

    def show_skipped_dialog(self, identity, rows):
        dialog = QDialog(self); dialog.setWindowTitle('Skipped files'); dialog.resize(680, 400)
        layout = box(dialog, margins=(24, 24, 24, 24)); layout.addWidget(label('Skipped during preparation', 'section'))
        table = QTableView(); model = MediaModel(table); model.reset([dict(title=row['relative'], kind=row['kind']) for row in rows], [('title', 'FILE'), ('kind', 'TYPE')]); table.setModel(model)
        table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection); table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); layout.addWidget(table)
        def restore():
            if not self.identity or any(self.identity.get(key) != identity.get(key)
                                        for key in ('root', 'disk_serial', 'volume_serial', 'target_id')):
                dialog.reject(); self.show_error('The selected iPod changed. Load skipped files again.'); return
            selected = [rows[i.row()] for i in table.selectionModel().selectedRows()]
            if selected:
                dialog.accept()
                def run():
                    media.restore_skipped_files(identity, [(r['kind'], r['relative']) for r in selected])
                    return dict(summary='Selected files will be included in the next preparation.')
                self.work('skipped', run, 'Including selected files again…')
        layout.addWidget(button('Include selected files again', restore, 'primary'), 0, Qt.AlignRight); dialog.exec()

    def eject(self):
        if not self.identity or self.busy:
            return
        identity = self.identity
        def run():
            return media.eject_device(identity)
        self.work('eject', run, 'Safely ejecting your iPod…')

    def stop(self):
        context = self.active_operation
        if context and context.cancel_event:
            context.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.show_progress('Finishing the current step before stopping…')

    def show_error(self, message):
        self.notice.setText(message); self.notice.show(); self.show_progress(message)
        if self.stack.currentWidget() != self.library:
            self.prep_results.setPlainText(message); self.prep_results.show()
            if self.page != 'Preparation':
                self.dialog('Needs attention', message, 'OK', cancel=False)

    def closeEvent(self, event):
        if self.busy:
            self.show_progress('Wait for the current operation to finish before closing.'); event.ignore(); return
        self.save_draft()
        self.closed = True
        self.covers.closed = True
        self.covers.pool.shutdown(wait=False, cancel_futures=True)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.tool_pool.shutdown(wait=False, cancel_futures=True)
        event.accept()


def launch():
    # Qt still decodes photos with malformed ICC metadata; avoid repeating
    # profile diagnostics as their previews enter and leave the artwork cache.
    QLoggingCategory.setFilterRules('qt.gui.icc.warning=false')
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle('Fusion'); app.setFont(QFont(UI_FONT, 10))
    window = MediaWindow(); window.show()
    app.exec()
