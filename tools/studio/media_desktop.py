"""Linnet's native media library and device workspace."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import tomllib

from PySide6.QtCore import (QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, QObject, QRectF, QSize, QPointF, QUrl,
                           Qt, QTimer, Signal, Slot, QSettings, QBuffer, QIODevice, QLoggingCategory, QSignalBlocker)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QIcon, QImage, QImageReader, QKeySequence, QPalette,
                          QLinearGradient, QPainter, QPainterPath, QPixmap, QShortcut, QPen)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QProgressBar, QPushButton, QScrollArea, QGridLayout,
    QStackedWidget, QStyledItemDelegate, QStyle,
    QTableView, QTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QStyleOptionButton, QSizePolicy)

from tools.content import apple_os, games, media_manager as media, media_library, media_status, media_trash
from tools.content import publish, host_cache, apple_font
from tools.content.media_manager import format_size as size
from tools.content.music import COVER_NAMES, EXTENSIONS as MUSIC_EXTENSIONS
from tools.studio import installer, screen_settings, startup_default, boot_upgrade, media_reader
from tools.studio.media_identity import ICON_PATH, configure_taskbar


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
    'camera': '<path d="M3 7h4l2-3h6l2 3h4v14H3Z"/><circle cx="12" cy="13" r="4"/>',
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


def library_search_text(row):
    return ' '.join(str(row.get(field, '')) for field in ('title', 'artist', 'album', 'genre', 'path')).casefold()

def linnet_version():
    try:
        config = Path(__file__).resolve().parents[2] / 'config' / 'system.toml'
        return str(tomllib.loads(config.read_text(encoding='utf-8'))['system']['version'])
    except (OSError, KeyError, ValueError, TypeError):
        return 'unavailable'


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
    setup_instruction = Signal(object)


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
                        pixels = reader.read(108041)
                    # RGB565 covers may append exact Now Playing renditions.
                    # Preview their leading square; reject unknown file sizes.
                    side = {8192: 64, 32768: 128, 51200: 160, 76288: 160, 108040: 160}.get(len(pixels))
                    if side:
                        image = QImage(pixels[:side * side * 2], side, side, side * 2, QImage.Format_RGB16).copy()
            else:
                image = self.read_image(path)
        except (OSError, ValueError):
            pass
        if not self.closed:
            self.events.artwork.emit(generation, path, image)

    def sidecar(self, folder, generation):
        """Share folder lookups within one artwork generation."""
        with self.sidecar_lock:
            if self.closed or generation != self.generation:
                return None
            if folder in self.sidecars:
                original = self.sidecars.pop(folder)
                if original is None or original.is_file():
                    self.sidecars[folder] = original
                    return original
            original = next((folder / name for name in COVER_NAMES if (folder / name).is_file()), None)
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


def build_library_page(window):
    page = QWidget(); outer = box(page, margins=(30, 28, 26, 20), spacing=16)
    titles = box(spacing=5); window.heading_label = label('Music', 'title', True); window.subtitle = label('', 'subtitle', True)
    titles.addWidget(window.heading_label); titles.addWidget(window.subtitle); outer.addLayout(titles)
    top = box(horizontal=True)
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
    filters.addWidget(window.genre_filter, 1); filters.addWidget(window.artist_filter, 1)
    window.clear_button = button('Clear filters', window.clear_filters, 'quiet'); filters.addWidget(window.clear_button)
    outer.addLayout(filters)
    library_actions = box(horizontal=True)
    window.result_count = label('', 'muted'); library_actions.addWidget(window.result_count, 1)
    window.sync_button = button('Sync video folder', window.sync_videos, None, 'refresh')
    window.folder_button = button('Open iPod folder', window.open_media_folder, None, 'folder'); library_actions.addWidget(window.folder_button)
    library_actions.addWidget(window.sync_button)
    outer.addLayout(library_actions)
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
    window.prepare_pcm_button = button('Prepare as PCM', window.queue_selected_pcm)
    selection.addWidget(window.prepare_pcm_button)
    window.restore_button = button('Restore', window.restore_selected, None, 'back'); selection.addWidget(window.restore_button)
    window.remove_button = button('Move to Trash', window.remove_selected, 'danger', 'trash'); selection.addWidget(window.remove_button)
    outer.addWidget(window.selection_bar); window.selection_bar.hide()
    window.hint = label('Double-click an item for details. Ctrl+click or Shift+click to select multiple files.', 'muted', True); outer.addWidget(window.hint)
    return page

def build_preparation_page(window):
    page = QWidget(); page.setObjectName('workspace')
    outer = box(page, spacing=0)
    scroll, layout = window.scroll_page()
    scroll.setObjectName('preparationScroll')
    window.preparation_scroll = scroll
    outer.addWidget(scroll, 1)
    window.heading(layout, 'Prepare your media', 'Turn your files into an iPod-ready collection. Your originals stay on the device.')
    window.prep_connection = QFrame(); window.prep_connection.setObjectName('recoveryNote')
    connection = box(window.prep_connection, margins=(20, 18, 20, 18), spacing=9)
    window.prep_connection_title = label('Disk Mode needed to prepare media', 'cardTitle', True)
    window.prep_connection_detail = label('', 'muted', True)
    connection.addWidget(window.prep_connection_title); connection.addWidget(window.prep_connection_detail)
    window.prep_connection_button = button('Open Disk Mode', window.connect_preparation, 'primary')
    connection.addWidget(window.prep_connection_button, 0, Qt.AlignLeft)
    layout.addWidget(window.prep_connection)
    window.prep_unavailable = label('', 'notice', True)
    window.prep_unavailable.hide(); layout.addWidget(window.prep_unavailable)
    window.prep_checks, window.prep_labels, window.prep_cards = {}, {}, {}
    descriptions = {'Music': 'Build the song library and album artwork', 'Photos': 'Create thumbnails and zoomable photos', 'Videos': 'Validate existing videos and prepare them for this iPod', 'Notes': 'Prepare text and Markdown for the reader'}
    for kind in ('Music', 'Photos', 'Videos', 'Notes'):
        card = QFrame(); card.setObjectName('card'); row = box(card, horizontal=True, margins=(20, 18, 20, 18), spacing=15)
        window.prep_cards[kind] = card
        check = CheckBox(kind); check.setChecked(True); check.setMinimumWidth(110); window.prep_checks[kind] = check; row.addWidget(check)
        text = box(spacing=5); text.addWidget(label(descriptions[kind], 'cardTitle'))
        state = label('Connect an iPod in Disk Mode to check this library.', 'muted', True); window.prep_labels[kind] = state; text.addWidget(state); row.addLayout(text, 1)
        if kind == 'Videos':
            window.choose_videos_button = button('Choose videos', window.choose_videos); row.addWidget(window.choose_videos_button)
            window.video_repair_button = button('Review catalog backups', window.review_video_catalog)
        layout.addWidget(card)
    layout.addWidget(window.video_repair_button, 0, Qt.AlignLeft)
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
    window.queue_incompatible = button('Queue incompatible iPod music', window.queue_existing_audio)
    queue_actions.addWidget(window.queue_incompatible)
    window.queue_open = button('Show source', window.open_queued, None, 'folder'); queue_actions.addWidget(window.queue_open)
    window.queue_remove = button('Remove from queue', window.remove_queued, 'quiet'); queue_actions.addWidget(window.queue_remove); queue_actions.addStretch()
    window.queue_remove.setToolTip('Remove selected entries from this queue. Source files stay in place.')
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
    apple_layout.addWidget(label('Use media from your own iPod folders in Apple OS too. Choose folders outside the Apple-managed library, then update the Apple library whenever their files change.', 'muted', True))
    window.apple_status = label('Connect an iPod in Disk Mode to check Apple OS availability.', 'muted', True)
    apple_layout.addWidget(window.apple_status)
    window.apple_eligibility = label('', 'muted', True)
    apple_layout.addWidget(window.apple_eligibility)
    apple_actions = box(horizontal=True)
    window.apple_choose = button('Choose folders…', window.choose_apple_folders, None, 'folder')
    window.apple_update = button('Update Apple library', window.update_apple_os, None, 'refresh')
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

def build_screens_page(window):
    page, layout = window.scroll_page()
    window.heading(layout, 'Screens', 'Choose what appears on your iPod and arrange it in your preferred order.')
    window.screen_state = screen_settings.defaults()
    window.screen_base = None
    window.screen_loaded_for = None
    window.screen_picker = ComboBox(); window.screen_picker.addItems(['Home', 'Music', 'Settings', 'Extras'])
    window.screen_picker.currentTextChanged.connect(window.screens_controller.render_screen_items)
    layout.addWidget(window.screen_picker)
    layout.addWidget(label('Check items to include them. Drag to reorder, or use the move buttons.', 'muted', True))
    window.screen_fixed = label('Shuffle, Repeat, and Edit Menus are always available in Settings.', 'muted', True)
    layout.addWidget(window.screen_fixed)
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
    layout.addWidget(button('Reload from iPod', window.screens_controller.reload_screens))
    window.screens_controller.render_screen_items()
    return page

def build_games_page(window):
    page, layout = window.scroll_page()
    window.heading(layout, 'Games', 'Game availability depends on your iPod model.')
    window.games_loaded_for = None
    window.games_unavailable = label('Games aren’t available on this iPod.', 'notice', True)
    window.games_unavailable.hide(); layout.addWidget(window.games_unavailable)
    window.game_checks, window.game_cards = [], []
    for index, (title, description) in enumerate(games.GAMES):
        card = QFrame(); card.setObjectName('card')
        row = box(card, horizontal=True, margins=(20, 18, 20, 18), spacing=15)
        check = CheckBox(title); check.setChecked(True); check.setMinimumWidth(145)
        check.toggled.connect(window.games_controller.games_changed)
        window.game_checks.append(check); row.addWidget(check)
        row.addWidget(label(description, 'muted', True), 1)
        window.game_cards.append(card)
        layout.addWidget(card)
    window.games_status = label('Connect an iPod with games to check installed games.', 'muted', True)
    layout.addWidget(window.games_status)
    window.games_recover = button('Replace damaged game settings', window.games_controller.recover_games)
    window.games_recover.setToolTip('Choose a new game selection after a damaged settings file could not be read.')
    layout.addWidget(window.games_recover, 0, Qt.AlignLeft)
    window.games_save = button('Update games on iPod', window.games_controller.save_games, 'primary')
    layout.addWidget(window.games_save, 0, Qt.AlignLeft)
    layout.addWidget(label('Independent game packages', 'section'))
    layout.addWidget(label('Install a prepared game file for this iPod. Removing a game preserves its saved progress.', 'muted', True))
    window.custom_games = QListWidget(); window.custom_games.setMinimumHeight(100)
    window.custom_games.currentItemChanged.connect(lambda *_: window.update_controls())
    layout.addWidget(window.custom_games)
    package_controls=box(horizontal=True)
    window.game_import=button('Install game file…', window.games_controller.import_game)
    window.game_remove=button('Remove selected game', window.games_controller.remove_game)
    package_controls.addWidget(window.game_import);package_controls.addWidget(window.game_remove);package_controls.addStretch()
    layout.addLayout(package_controls)
    window.game_recover_requested=False
    layout.addStretch()
    return page

def build_setup_page(window):
    page, layout = window.scroll_page()
    window.heading(layout, 'iPod setup', 'Startup, Linnet software, and recovery.')
    window.build_editor_open = False

    header = QFrame(); header.setObjectName('card')
    details = box(header, margins=(20, 18, 20, 18), spacing=8)
    window.setup_device = label('Connect your iPod', 'cardTitle', True); details.addWidget(window.setup_device)
    window.setup_software = label('Connect with USB to get started.', 'muted', True); details.addWidget(window.setup_software)
    window.support_status = label('', 'muted', True); details.addWidget(window.support_status)
    window.discovery_issue = label('', 'notice', True); window.discovery_issue.hide(); details.addWidget(window.discovery_issue)
    window.hardware_report_button = button('Save hardware report…', window.collect_hardware_report)
    details.addWidget(window.hardware_report_button, 0, Qt.AlignLeft)
    window.install_detail = label('', 'notice', True); window.install_detail.hide(); details.addWidget(window.install_detail)
    window.setup_progress = QProgressBar(); window.setup_progress.setRange(0, 0)
    window.setup_progress.setTextVisible(False); window.setup_progress.hide(); details.addWidget(window.setup_progress)
    window.link_disk_button = button('Open Disk Mode', window.open_link_disk)
    window.link_disk_button.hide(); details.addWidget(window.link_disk_button, 0, Qt.AlignLeft)
    window.connection_help = label('If your iPod does not appear, enter Apple Disk Mode:\n'
        '1. Turn the Hold switch off.\n'
        '2. Hold Menu + Select (the center button) until the iPod restarts.\n'
        '3. Immediately hold Select + Play/Pause until Disk Mode appears.\n'
        'Keep USB connected, then choose Find iPod.', 'muted', True)
    details.addWidget(window.connection_help)
    window.setup_find_button = button('Find iPod', window.discover, 'primary', 'refresh')
    details.addWidget(window.setup_find_button, 0, Qt.AlignLeft)
    window.resume_classic_button = button('Resume Classic installation', window.resume_classic_setup, 'primary')
    window.resume_classic_button.hide(); details.addWidget(window.resume_classic_button, 0, Qt.AlignLeft)
    layout.addWidget(header)

    def card(parent_layout):
        frame = QFrame(); frame.setObjectName('card'); parent_layout.addWidget(frame)
        return frame, box(frame, margins=(20, 18, 20, 18), spacing=12)

    window.link_setup_panel = QWidget(); linked = box(window.link_setup_panel, spacing=14)
    _, link_startup = card(linked)
    row = box(horizontal=True); row.addWidget(label('Startup', 'cardTitle'), 1)
    window.link_startup_button = button('Read startup settings', lambda: window.open_link_setup('startup'))
    row.addWidget(window.link_startup_button); link_startup.addLayout(row)
    link_startup.addWidget(label('Check the default system and available startup choices.', 'muted', True))
    _, link_build = card(linked)
    row = box(horizontal=True); row.addWidget(label('Linnet', 'cardTitle'), 1)
    window.link_build_button = button('Change build…', lambda: window.open_link_setup('build'))
    row.addWidget(window.link_build_button); link_build.addLayout(row)
    window.link_build_status = label('', 'muted', True); link_build.addWidget(window.link_build_status)
    _, link_removal = card(linked)
    row = box(horizontal=True); row.addWidget(label('Remove Linnet', 'cardTitle'), 1)
    window.link_uninstall_button = button('Remove…', lambda: window.open_link_setup('remove'), 'danger')
    row.addWidget(window.link_uninstall_button); link_removal.addLayout(row)
    window.link_uninstall_detail = label('', 'muted', True); link_removal.addWidget(window.link_uninstall_detail)
    linked.addWidget(label('Media Manager opens Disk Mode automatically for these actions.', 'muted', True))
    window.link_setup_panel.hide(); layout.addWidget(window.link_setup_panel)

    window.startup_panel, startup = card(layout)
    window.default_title = label('Startup', 'cardTitle'); startup.addWidget(window.default_title)
    window.default_row = QWidget(); window.default_row.setMaximumWidth(620); row = box(window.default_row, horizontal=True, spacing=12)
    row.addWidget(label('Start automatically', 'muted'))
    window.default_choice = ComboBox(); window.default_choice.setMaximumWidth(300)
    window.default_choice.currentIndexChanged.connect(window.update_install_action); row.addWidget(window.default_choice, 1)
    window.default_button = button('Save', window.save_default_startup, 'primary'); row.addWidget(window.default_button)
    row.addStretch(); startup.addWidget(window.default_row)
    window.default_detail = label('Hold Menu during startup to choose a system for that start.', 'muted', True)
    startup.addWidget(window.default_detail)
    window.boot_upgrade_button = button('Update startup selector', window.upgrade_startup_selector)
    startup.addWidget(window.boot_upgrade_button, 0, Qt.AlignLeft)
    window.boot_upgrade_detail = label('', 'muted', True); startup.addWidget(window.boot_upgrade_detail)

    window.install_panel, build = card(layout)
    row = box(horizontal=True); window.install_title = label('Linnet', 'cardTitle'); row.addWidget(window.install_title, 1)
    window.build_editor_button = button('Change build or reinstall…', window.toggle_setup_editor)
    row.addWidget(window.build_editor_button); build.addLayout(row)
    window.installed_build = label('', 'muted', True); build.addWidget(window.installed_build)
    window.build_summary = label('', 'muted', True); build.addWidget(window.build_summary)
    window.build_editor = QWidget(); install = box(window.build_editor, spacing=12); build.addWidget(window.build_editor)
    install.addWidget(label('Build', 'section'))
    window.boot_choice = ComboBox(); window.boot_choice.setMaximumWidth(500)
    window.boot_choice.currentIndexChanged.connect(window.update_install_action); install.addWidget(window.boot_choice)
    window.boot_detail = label('', 'muted', True); install.addWidget(window.boot_detail)
    install.addSpacing(4); install.addWidget(label('Firmware', 'section'))
    window.firmware_path = str(window.settings.value('firmware_bundle', ''))
    window.build_from_source = CheckBox('Build from this source checkout')
    window.build_from_source.setChecked(not getattr(sys, 'frozen', False) and
        window.settings.value('build_from_source', False, type=bool))
    window.build_from_source.setVisible(not getattr(sys, 'frozen', False))
    window.build_from_source.toggled.connect(window.firmware_source_changed); install.addWidget(window.build_from_source)
    window.firmware_picker = QWidget(); window.firmware_picker.setMaximumWidth(620); row = box(window.firmware_picker, horizontal=True, spacing=12)
    window.firmware_label = label('', 'muted', True); row.addWidget(window.firmware_label, 1)
    window.firmware_button = button('Choose ZIP…', window.choose_firmware, None, 'folder'); row.addWidget(window.firmware_button)
    install.addWidget(window.firmware_picker)
    window.method_title = label('Startup options', 'section'); install.addWidget(window.method_title)
    window.method_choice = ComboBox(); window.method_choice.setMaximumWidth(500)
    window.method_choice.currentIndexChanged.connect(window.update_install_action); install.addWidget(window.method_choice)
    window.method_detail = label('', 'muted', True); install.addWidget(window.method_detail)
    window.install_hint = label('', 'muted', True); install.addWidget(window.install_hint)
    window.install_button = button('Install Linnet', window.install_selected, 'primary'); install.addWidget(window.install_button, 0, Qt.AlignLeft)

    window.uninstall_panel, removal = card(layout)
    row = box(horizontal=True); row.addWidget(label('Remove Linnet', 'cardTitle'), 1)
    window.uninstall_button = button('Remove…', window.uninstall_selected, 'danger'); row.addWidget(window.uninstall_button)
    removal.addLayout(row)
    window.uninstall_detail = label('', 'muted', True); removal.addWidget(window.uninstall_detail)
    layout.addStretch()
    return page


def build_settings_page(window):
    page, layout = window.scroll_page()
    window.heading(layout, 'Settings', 'Preparation quality and tools, in one place.')
    layout.addWidget(label('Photo detail', 'section'))
    window.photo_detail = ComboBox(); window.photo_detail.addItems(['Standard · 640 px', 'High detail · 2048 px']); window.photo_detail.setCurrentIndex(int(window.settings.value('photo_detail', 0)))
    window.photo_detail.currentIndexChanged.connect(lambda value: window.settings.setValue('photo_detail', value)); layout.addWidget(window.photo_detail)
    layout.addWidget(label('High detail uses more storage and takes longer to prepare.', 'muted'))
    layout.addSpacing(20); layout.addWidget(label('iPod theme font', 'section'))
    layout.addWidget(label('Use Apple Podium Sans in supported color themes. Downloads 3.8 MB directly from Apple and extracts the font on this computer. Apple software license terms apply.', 'muted', True))
    window.apple_font_status = label('Connect a color iPod in Disk Mode to choose its font.', 'muted', True)
    layout.addWidget(window.apple_font_status)
    actions = box(horizontal=True, spacing=8)
    window.apple_font_install = button('Download and use Apple font', window.install_apple_font)
    window.apple_font_remove = button('Use included font', window.remove_apple_font)
    actions.addWidget(window.apple_font_install); actions.addWidget(window.apple_font_remove); actions.addStretch()
    layout.addLayout(actions)
    layout.addWidget(button('Apple software license', lambda: QDesktopServices.openUrl(QUrl(apple_font.LICENSE_URL)), 'quiet'), 0, Qt.AlignLeft)
    layout.addSpacing(20); layout.addWidget(label('Computer storage', 'section'))
    window.cache_size = label('Open Settings to measure reusable cache files.', 'muted', True)
    layout.addWidget(window.cache_size)
    window.cache_location = label('', 'muted', True)
    window.cache_location.setTextInteractionFlags(Qt.TextSelectableByMouse)
    layout.addWidget(window.cache_location)
    window.cache_open = button('Open cache folder', window.open_computer_folder, None, 'folder')
    window.cache_refresh = button('Refresh size', window.refresh_cache)
    window.cache_change = button('Change location…', window.change_cache_location)
    window.cache_clear = button('Clear cache…', window.clear_computer_cache)
    window.cache_buttons = (window.cache_open, window.cache_refresh, window.cache_change, window.cache_clear)
    for pair in (window.cache_buttons[:2], window.cache_buttons[2:]):
        actions = box(horizontal=True, spacing=8)
        for item in pair:
            actions.addWidget(item)
        actions.addStretch(); layout.addLayout(actions)
    window.cache_protected = label('Startup backups, recovery copies and saved selections are protected. Clearing the cache never removes them.', 'muted', True)
    layout.addWidget(window.cache_protected)
    actions = box(horizontal=True, spacing=8)
    window.backups_open = button('Open startup backups', lambda: window.open_computer_folder(host_cache.storage_root() / 'Installer'))
    window.recovery_open = button('Open recovery and saved state', lambda: window.open_computer_folder(host_cache.media_state_root()))
    actions.addWidget(window.backups_open); actions.addWidget(window.recovery_open); actions.addStretch()
    layout.addLayout(actions)
    layout.addSpacing(20); layout.addWidget(label('Conversion tools', 'section'))
    window.tools_label = label('', 'muted', True); layout.addWidget(window.tools_label)
    layout.addWidget(button('Choose FFmpeg folder', window.locate_tools, None, 'folder'), 0, Qt.AlignLeft)
    layout.addWidget(label('Install FFmpeg and FFprobe on your computer, then choose the folder containing both programs. Video conversions need both tools; ordinary media browsing does not.', 'muted', True))
    layout.addWidget(button('Help and About', window.show_help, 'quiet'), 0, Qt.AlignLeft)
    layout.addSpacing(20); layout.addWidget(label('Advanced preparation', 'section'))
    window.convert_audio = CheckBox('Convert incompatible music to PCM WAV on the computer')
    window.convert_audio.setChecked(str(window.settings.value('convert_audio', True)).lower() in ('true', '1'))
    window.convert_audio.toggled.connect(lambda checked: window.settings.setValue('convert_audio', checked))
    layout.addWidget(window.convert_audio)
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
            window.game_dirty = {i for i, check in enumerate(window.game_checks) if check.isChecked()} != window.game_saved
            window.save_choices_draft()
            window.games_status.setText('Unsaved game selection. Update games on iPod, then eject safely.' if window.game_dirty else
                                        'Game selection matches the iPod.')

    def recover_games(self):
        window = self.window
        if not window.identity or window.busy or not games.available(window.identity) or not window.game_read_failed:
            return
        if not window.dialog('Replace damaged game settings',
                             'The game selection could not be read. Select games below, then choose Update games on iPod to replace the damaged settings.',
                             'Choose games'):
            return
        window.games_loaded_for = window.identity['root']
        window.game_saved = None
        window.game_dirty = True
        window.game_read_failed = False
        window.game_recover_requested=True
        for index, check in enumerate(window.game_checks):
            with QSignalBlocker(check):
                check.setChecked(index in games.supported(window.identity))
        window.load_choices_draft('games')
        window.games_status.setText('Choose games, then update the iPod to replace its damaged selection.')
        window.save_choices_draft()
        window.update_controls()

    def load_games(self):
        window = self.window
        if (window.identity and window.device_connected and games.available(window.identity) and not window.busy
                and window.games_loaded_for != window.identity['root']):
            identity = window.identity
            window.work('games', lambda: games.choices(identity), 'Reading installed games…')

    def save_games(self):
        window = self.window
        if not window.identity or not window.device_connected or window.busy or not games.available(window.identity):
            return
        selected = {index for index, check in enumerate(window.game_checks) if check.isChecked()}
        identity = window.identity
        recover=window.game_recover_requested
        window.work('save_games', lambda: games.save(identity, selected, recover=recover), 'Updating games on iPod…')

    def import_game(self):
        window=self.window
        if not window.identity or window.busy:return
        path,_=QFileDialog.getOpenFileName(window,'Install prepared game','','Linnet game (*.LGM *.lgm)')
        if not path:return
        identity=window.identity
        window.work('import_game',lambda:games.import_package(identity,path),'Installing game package…')

    def remove_game(self):
        window=self.window;item=window.custom_games.currentItem()
        if not item or not window.identity or window.busy:return
        identity=window.identity;game_id=item.data(Qt.UserRole)
        window.work('remove_game',lambda:games.remove_package(identity,game_id),'Removing game package…')

class ScreensController:
    def __init__(self, window):
        self.window = window

    def render_screen_items(self, *_):
        window = self.window
        name = window.screen_picker.currentText()
        window.screen_fixed.setVisible(name == 'Settings')
        labels = screen_settings.SCREENS[name]
        selected = window.screen_state[name]
        available, unavailable = screen_settings.item_availability(name, window.identity)
        locked = screen_settings.locked_items(name)
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
        window.screen_state[name] = selected
        window.screen_dirty = window.screen_state != window.screen_saved
        window.save_choices_draft()
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
        if window.identity and window.device_connected and not window.busy and window.screen_loaded_for != window.identity['root']:
            identity = window.identity
            window.work('screens', lambda: screen_settings.read(identity), 'Reading screen settings…')

    def reload_screens(self):
        window = self.window
        if not window.identity or not window.device_connected or window.busy:
            return
        if window.screen_dirty and not window.dialog('Reload screen settings', 'Discard unsaved desktop menu edits and load the current iPod menus?', 'Reload'):
            return
        window.screen_dirty = False
        window.save_choices_draft()
        window.screen_loaded_for = None
        self.load_screens()

    def save_screens(self):
        window = self.window
        if not window.identity or not window.device_connected or window.busy:
            return
        state = {name: list(rows) for name, rows in window.screen_state.items()}
        try:
            screen_settings.encode(state)
        except ValueError as error:
            window.show_error(str(error)); return
        identity = window.identity
        base = {name: list(rows) for name, rows in window.screen_base.items()} if window.screen_base is not None else None
        window.work('save_screens', lambda: screen_settings.save(identity, state, base), 'Saving screen settings…')


class ScreenshotPreview(QLabel):
    def __init__(self, image):
        super().__init__()
        self.original = QPixmap.fromImage(image)
        self.setAlignment(Qt.AlignCenter); self.setMinimumSize(160,128)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setPixmap(self.original.scaled(self.contentsRect().size(), Qt.KeepAspectRatio, Qt.FastTransformation))


class ScreenshotDialog(QDialog):
    """Keep a captured image available even if the iPod disconnects."""
    def __init__(self, result, parent):
        super().__init__(parent)
        self.setWindowTitle('iPod screenshot')
        self.resize(720, 620); self.setMinimumSize(400, 360)
        self.image = QImage.fromData(result['png'], 'PNG')
        if self.image.isNull():
            raise ValueError('The screenshot could not be opened.')
        self.settings = parent.settings
        self.filename = 'linnet-screenshot-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.png'
        layout = box(self, margins=(24,24,24,24), spacing=14)
        layout.addWidget(label('iPod screenshot', 'section'))
        layout.addWidget(label(f'{self.image.width()} × {self.image.height()} pixels · PNG', 'muted'))
        layout.addWidget(ScreenshotPreview(self.image), 1)
        self.message = label('', 'muted', True); layout.addWidget(self.message)
        actions = box(horizontal=True)
        actions.addWidget(button('Copy image', self.copy_image))
        actions.addWidget(button('Save PNG…', self.save_image, 'primary'))
        actions.addStretch(); actions.addWidget(button('Close', self.accept)); layout.addLayout(actions)
        QShortcut(QKeySequence.Copy, self, activated=self.copy_image)
        QShortcut(QKeySequence.Save, self, activated=self.save_image)

    def copy_image(self):
        QApplication.clipboard().setImage(self.image)
        self.message.setText('Screenshot copied to the clipboard.')

    def save_image(self):
        folder = Path(str(self.settings.value('screenshots/folder', str(Path.home() / 'Pictures'))))
        if not folder.is_dir():folder = Path.home()
        picker = QFileDialog(self, 'Save screenshot', str(folder / self.filename), 'PNG image (*.png)')
        picker.setAcceptMode(QFileDialog.AcceptSave); picker.setDefaultSuffix('png')
        if picker.exec() != QDialog.Accepted:return
        path = Path(picker.selectedFiles()[0])
        if not self.image.save(str(path), 'PNG'):
            self.message.setText('Could not save the screenshot. Choose another folder and try again.')
            return
        self.settings.setValue('screenshots/folder', str(path.parent))
        self.message.setText(f'Saved {path.name}.')


class SetupInstructionDialog(QDialog):
    """Keep the live button instructions visible until setup advances."""
    def reject(self):
        # Escape and the window close shortcut must not hide the release cue.
        # The explicit Stop button requests cancellation through the worker.
        pass


class MediaWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Linnet · Media Manager')
        self.resize(1280, 860)
        self.setMinimumSize(780, 540)
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.settings = QSettings('Linnet', 'MediaManager')
        self.identity, self.inventory, self.review = None, None, None
        self.last_preparation = None
        self.rows, self.readiness, self.pending, self.trash_rows = [], {}, [], []
        self.trash_summary = None
        self.pending_keys = set()
        self.queue_outcomes = {}
        self.draft_issues = {}
        self.stale_videos = 0
        self.queue_context = None
        self.discovery_errors = []
        self.hardware_report = None
        self.device_connected = False
        self.publication_recovery_pending = False
        self.publication_recovery_groups = []
        self._recent_private_identifiers = set()
        self.screen_saved = None
        self.screen_dirty = False
        self.game_saved = None
        self.game_dirty = False
        self.game_read_failed = False
        self.apple_info = None
        self.apple_font_result = None
        self._library_source, self._library_cache, self._library_stats = None, {}, {}
        self._library_search = None
        self.video_selection, self.video_mode, self.stop_event = set(), 'all', threading.Event()
        self.page, self.view, self.group = 'Music', self.settings.value('music_view', 'Albums'), None
        if self.view not in ('Songs', 'Albums', 'Artists', 'Genres'):
            self.view = 'Albums'
        self.busy = False
        self.setup_instruction_dialog = None
        self.link_connection = None
        self.closed = False
        self.cache_info = None
        self.cache_library_dirty = False
        self.operation_id = 0
        self.active_operation = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='linnet-media')
        self.tool_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='linnet-tools')
        self.tool_check_id = 0
        self.verified_ffmpeg = None
        self.verified_ffprobe = None
        self.events = Events(self)
        self.events.done.connect(self.completed)
        self.events.progress.connect(self.show_progress)
        self.events.stage.connect(self.show_operation_stage)
        self.events.conversion.connect(self.show_conversion_progress)
        self.events.tools_checked.connect(self.tools_checked)
        self.events.setup_instruction.connect(self.show_setup_instruction)
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
        sidebar = QWidget(); sidebar.setObjectName('sidebar'); sidebar.setMinimumWidth(232)
        side = box(sidebar, margins=(18, 20, 18, 16), spacing=6)
        brand = box(horizontal=True, spacing=11)
        mark = label(); mark.setPixmap(boot_artwork((594, 180, 310, 445), 38, 56))
        wordmark = label(); wordmark.setPixmap(boot_artwork((548, 648, 442, 64), 132, 20))
        brand.addWidget(mark); brand.addWidget(wordmark); brand.addStretch()
        side.addLayout(brand); side.addSpacing(18)
        side.addWidget(label('LIBRARY', 'eyebrow')); side.addSpacing(7)
        self.navigation = {}
        for name, glyph in [('Music', 'music'), ('Photos', 'photos'), ('Videos', 'videos'), ('Notes', 'notes'),
                            ('iPod setup', 'setup'), ('Preparation', 'prepare'), ('Games', 'setup'), ('Screens', 'settings'), ('Trash', 'trash'), ('Settings', 'settings')]:
            if name == 'iPod setup':
                side.addSpacing(18); side.addWidget(label('DEVICE', 'eyebrow')); side.addSpacing(7)
            item = button(name, lambda _=False, n=name: self.navigate(n), 'nav')
            item.setIcon(icon(glyph, '#a8bbc1')); item.setIconSize(QSize(19, 19)); item.setCheckable(True)
            item.toggled.connect(lambda checked, glyph=glyph, item=item:
                                 item.setIcon(icon(glyph, '#102b32' if checked else '#a8bbc1')))
            self.navigation[name] = item; side.addWidget(item)
            if name == 'Trash':
                self.trash_badge = label('', 'trashBadge')
                self.trash_badge.setAlignment(Qt.AlignCenter)
                self.trash_badge.setAttribute(Qt.WA_TransparentForMouseEvents)
                self.trash_badge.setFixedHeight(20); self.trash_badge.setMinimumWidth(22)
                badge_layout = box(item, horizontal=True, margins=(0, 0, 10, 0), spacing=0)
                badge_layout.addStretch(); badge_layout.addWidget(self.trash_badge)
                self.trash_badge.hide()
        side.addStretch()
        device = QFrame(); device.setObjectName('deviceCard')
        layout = box(device, margins=(13, 17, 13, 15), spacing=9)
        self.device_name = label('Connect your iPod', 'deviceName', True)
        self.device_info = label('USB · Disk Mode', 'deviceInfo', True)
        self.capacity = QProgressBar(); self.capacity.setTextVisible(False); self.capacity.setRange(0, 100); self.capacity.setValue(0)
        layout.addWidget(self.device_name); layout.addWidget(self.device_info); layout.addWidget(self.capacity)
        self.device_details_button = button('Device details', self.device_details, 'sidebarAction', 'setup')
        layout.addWidget(self.device_details_button)
        self.screenshot_button = button('Screenshot…', self.capture_screenshot, 'sidebarAction', 'camera')
        self.screenshot_button.setEnabled(False)
        layout.addWidget(self.screenshot_button)
        self.choose_device_button = button('Find or switch iPod', self.discover, 'sidebarAction', 'refresh')
        layout.addWidget(self.choose_device_button)
        self.eject_button = button('Eject safely', self.eject, 'sidebarAction', 'eject'); layout.addWidget(self.eject_button)
        self.publication_recovery_button = button('Recover media indexes', self.recover_publication, 'sidebarAction')
        layout.addWidget(self.publication_recovery_button)
        side.addWidget(device)
        sidebar_scroll = QScrollArea(); sidebar_scroll.setObjectName('sidebarScroll')
        sidebar_scroll.setWidgetResizable(True); sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setFixedWidth(240); sidebar_scroll.setWidget(sidebar)
        main.addWidget(sidebar_scroll)
        right = QWidget(); right.setObjectName('workspace'); body = box(right, spacing=0)
        self.stack = QStackedWidget(); body.addWidget(self.stack, 1)
        self.library = build_library_page(self); self.stack.addWidget(self.library)
        self.preparation = build_preparation_page(self); self.stack.addWidget(self.preparation)
        self.setup = build_setup_page(self); self.stack.addWidget(self.setup)
        self.screens = build_screens_page(self); self.stack.addWidget(self.screens)
        self.games_page = build_games_page(self); self.stack.addWidget(self.games_page)
        self.preferences = build_settings_page(self); self.stack.addWidget(self.preferences)
        activity = QFrame(); activity.setObjectName('activity'); foot = box(activity, margins=(28, 10, 28, 12), spacing=7)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.hide(); foot.addWidget(self.progress)
        status_row = box(horizontal=True, spacing=12)
        self.status = StatusLabel('Looking for your iPod…'); status_row.addWidget(self.status, 1)
        self.cancel_button = button('Stop', self.stop, 'quiet'); self.cancel_button.setToolTip('Stop after the current step finishes'); self.cancel_button.hide(); status_row.addWidget(self.cancel_button)
        self.refresh_button = button('Refresh', self.refresh, 'quiet', 'refresh'); status_row.addWidget(self.refresh_button)
        self.diagnostics_button = button('Diagnostics', self.show_diagnostics, 'quiet'); status_row.addWidget(self.diagnostics_button)
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
            if page == 'Trash' and self.identity and self.device_connected and not self.busy:
                identity = self.identity
                self.work('trash', lambda: media_trash.inventory(identity), 'Reading Trash…')
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
            elif self.identity and self.device_connected and not self.busy:
                identity = self.identity
                self.work('setup', lambda: installer.assess(identity), 'Checking installed software…')
        else:
            self.stack.setCurrentWidget(self.preferences)
            self.refresh_cache()
        self.update_controls()
        if (self.cache_library_dirty and page != 'Settings' and self.identity and
                self.device_connected and not self.busy):
            self.refresh()

    def refresh_cache(self):
        if not self.busy:
            self.work('cache_size', host_cache.overview, 'Measuring computer cache and protected storage…')

    def open_computer_folder(self, path=None):
        if self.busy:
            return
        try:
            path = host_cache._plain(path) if path else host_cache.cache_base()
            path.mkdir(parents=True, exist_ok=True)
            self.open_folder(path)
        except (OSError, ValueError) as error:
            self.show_error(str(error))

    def clear_computer_cache(self):
        if self.busy or not self.cache_info:
            return
        if self.dialog('Clear computer cache',
                       f'Clear reusable media files (last measured: {size(self.cache_info["bytes"])}). '
                       'Thumbnails, metadata and conversions will be recreated when needed. '
                       'The next preparation may take longer.\n\n'
                       'Startup backups, recovery copies, saved selections and iPod files are kept.',
                       'Clear cache', danger=True):
            self.covers.invalidate()
            self.work('cache_clear', host_cache.clear, 'Clearing reusable computer cache files…')

    def change_cache_location(self):
        if self.busy:
            return
        initial = self.cache_info['location'] if self.cache_info else str(host_cache.default_base())
        folder = QFileDialog.getExistingDirectory(self, 'Choose an empty folder for the media cache', str(Path(initial).parent))
        if not folder or Path(folder) == Path(initial):
            return
        if not self.dialog('Move computer cache',
                           f'Move reusable cache files to:\n{folder}\n\n'
                           'Copies are verified before the location changes. Startup backups, recovery copies '
                           'and saved selections keep their existing locations.', 'Move cache'):
            return
        roots = [self.identity['root']] if self.identity else []
        self.covers.invalidate()
        self.work('cache_move', lambda: host_cache.relocate(folder, device_roots=roots,
                  progress=self.events.progress.emit), 'Moving and verifying reusable cache files…')

    def _complete_cache(self, result):
        self.cache_info = result
        self.cache_size.setText(f'{size(result["bytes"])} reusable cache · {result["files"]:,} files')
        self.cache_location.setText(result['location'])
        self.cache_protected.setText(
            f'Protected: {size(result["startup_bytes"])} startup backups · '
            f'{size(result["retained_bytes"])} recovery, saved state and other retained files.\n'
            'Clearing or moving the cache never removes these files.')
        if result['errors']:
            self.cache_size.setText(self.cache_size.text() + '\nSome files could not be measured or changed; they were kept.')
        self.cache_size.setToolTip('\n'.join(result['errors'][:10]))
        if 'freed_bytes' in result:
            self.show_progress(f'Cleared {size(result["freed_bytes"])} of reusable cache. Protected files were kept.')
        else:
            self.show_progress('Computer storage checked. Startup backups and recovery data are protected.')
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
        elif self.page == 'Trash' and self.trash_summary and self.trash_summary.get('unreadable'):
            self.open_folder(Path(self.identity['root']) / '.LINNET' / 'TRASH')
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
            self._library_title_cache = {}
            self._library_unique_ids = {}
            self._group_cards_cache = {}
            self._library_search = None
        if self.page in self._library_cache:
            return list(self._library_cache[self.page])
        unique = {}
        for row in self.rows:
            if row['kind'] == self.page and row['category'] in ('original', 'published', 'error'):
                copy = dict(row)
                if row['kind'] == 'Photos':
                    copy['artwork'] = row.get('artwork') or row['path']
                unique[str(Path(row['path'])).casefold()] = copy
        page_rows = list(unique.values())
        albums = len({(r.get('album'), r.get('album_artist') or r.get('artist')) for r in page_rows}) if self.page == 'Music' else 0
        self._library_stats[self.page] = (len(page_rows), sum(r['bytes'] for r in page_rows), albums)
        self._library_cache[self.page] = page_rows
        self._library_unique_ids[self.page] = len({row['id'] for row in page_rows}) == len(page_rows)
        return list(self._library_cache[self.page])

    def render_library(self):
        if self.page not in (*media.KINDS, 'Trash'):
            return
        trash_attention = self.page == 'Trash' and bool(self.trash_summary and self.trash_summary.get('unreadable'))
        context = (self.page, self.view, (self.group['group_kind'], self.group['group_key']) if self.group else None)
        active = self.views.currentWidget()
        previous_rows, previous_ranges = None, []
        if getattr(self, '_selection_context', None) == context and active in (self.table, self.grid):
            previous_rows, previous_ranges = self.model.rows, self.selected_row_ranges()
        self._selection_context = context
        rows = self.library_rows()
        grouped = self.page == 'Music' and self.view != 'Songs' and self.group is None
        title_order = self.page != 'Trash' and not grouped and self.group is None
        if title_order:
            # Filtering preserves this order. Keep the original page order for
            # grouped views, whose representative artwork comes from members.
            if self.page not in self._library_title_cache:
                self._library_title_cache[self.page] = sorted(rows, key=lambda row: row['title'].casefold())
            rows = list(self._library_title_cache[self.page])
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
        words = tuple(self.search.text().casefold().split())
        artist, genre = self.artist_filter.currentData(), self.genre_filter.currentData()
        if self.group:
            rows = list(self.group['members'])
        scope_count = len(rows)
        source = (self._library_title_cache[self.page] if title_order else
                  self.group['members'] if self.group else self._library_cache.get(self.page))
        filters = (artist, genre) if music else (None, None)
        previous = self._library_search
        narrower = bool(words and source is not None and previous is not None
                        and previous[0] is source and previous[1] == filters
                        and len(words) >= len(previous[2])
                        and all(word.startswith(old) for word, old in zip(words, previous[2])))
        if narrower:
            rows = previous[3]
        elif music and (artist or genre):
            rows = [r for r in rows if (not artist or (r.get('artist') or 'Unknown artist') == artist)
                    and (not genre or (r.get('genre') or 'Unknown genre') == genre)]
        if words:
            matches = []
            first, *remaining = words
            for row in rows:
                text = row.get('_linnet_search_text')
                if text is None:
                    text = library_search_text(row)
                    row['_linnet_search_text'] = text
                if first in text and (not remaining or all(word in text for word in remaining)):
                    matches.append(row)
            rows = matches
            # Preserve source order separately from the model's in-place sort.
            self._library_search = (source, filters, words, tuple(matches)) if source is not None else None
        else:
            self._library_search = None
        matched_count = len(rows)
        filtered = bool(words or (music and (artist or genre)))
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
        # Ordinary pages already have the title tie-break order. Groups keep
        # their own order; Trash rows are rebuilt with formatted timestamps.
        if grouped or self.group is not None or (self.page == 'Trash' and self.table.horizontalHeader().sortIndicatorSection() > 0):
            rows.sort(key=lambda r: (r.get('disc', 0), r.get('track', 0), r['title'].casefold()) if self.group and self.view == 'Albums' else (r['title'].casefold(),))
        columns = ([('title', 'TITLE'), ('album', 'ALBUM'), ('genre', 'GENRE'), ('duration', 'TIME'), ('bytes', 'SIZE')]
                   if music and not grouped else [('title', 'NAME'), ('status', 'STATUS'), ('bytes', 'SIZE')])
        self.model.reset(rows, columns)
        if not grouped and self.group is None:
            header = self.table.horizontalHeader()
            column = max(0, min(header.sortIndicatorSection(), self.model.columnCount() - 1))
            order = header.sortIndicatorOrder()
            if self.page == 'Trash' or column != 0 or order != Qt.AscendingOrder:
                self.model.sort(column, order)
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
            self.empty_title.setText('Reading your collection…' if self.busy else 'Connect your iPod' if not self.identity else 'No matches' if all_rows else 'Trash needs review' if trash_attention else 'Trash is empty' if self.page == 'Trash' else f'No {self.page.lower()} yet')
            self.empty_detail.setText('Your collection will appear here when reading finishes.' if self.busy else 'Connect an iPod in Disk Mode, then find it to browse and add media.' if not self.identity else 'Try another search or clear your filters.' if all_rows else 'Some Trash entries could not be read. Open the folder to review them.' if trash_attention else 'Removed files appear here until you restore or permanently delete them.' if self.page == 'Trash' else 'Add files from your computer to get started.')
        self.empty_action.setText('Find iPod' if not self.identity else 'Clear filters' if all_rows else 'Open Trash folder' if trash_attention else 'Add media')
        self.empty_action.setVisible(not self.busy and (not self.identity or bool(all_rows) or self.page != 'Trash' or trash_attention))
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
        if previous_ranges and active in (self.table, self.grid):
            selection = QItemSelection()
            unique = grouped or (self.page != 'Trash' and self._library_unique_ids[self.page])
            if unique and previous_rows == self.model.rows:
                # Model reset invalidates Qt ranges. Rebuild their endpoints
                # directly when every row retains its position and identity.
                for first, last in previous_ranges:
                    selection.select(self.model.index(first, 0), self.model.index(last, 0))
            else:
                selected_keys = set()
                for first, last in previous_ranges:
                    for row in previous_rows[first:last + 1]:
                        selected_keys.add(('group', row['group_kind'], row['group_key']) if 'group_key' in row else ('row', row['id']))
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

    def selected_row_ranges(self):
        view = self.views.currentWidget()
        if view not in (self.grid, self.table):
            return []
        selection = view.selectionModel().selection()
        # Row selections already contain compact intervals. Avoid expanding a
        # bulk selection into one Python Qt index per song just to read rows.
        if view is self.table and any(part.left() != 0 or part.right() != self.model.columnCount() - 1 for part in selection):
            spans = [(index.row(), index.row()) for index in view.selectionModel().selectedRows()]
        else:
            spans = [(part.top(), part.bottom()) for part in selection]
        return [(max(0, first), min(len(self.model.rows) - 1, last))
                for first, last in spans if last >= 0 and first < len(self.model.rows)]

    def selected(self):
        unique = {}
        for first, last in self.selected_row_ranges():
            for at in range(first, last + 1):
                row = self.model.rows[at]
                for member in row.get('members', (row,)):
                    unique[member['id']] = member
        return list(unique.values())

    def selection_changed(self, *_):
        rows = self.selected()
        self.selection_bar.setVisible(bool(rows) and self.device_connected)
        self.selection_text.setText(f'{len(rows):,} selected  ·  {size(sum(r["bytes"] for r in rows))}')
        self.restore_button.setVisible(self.page == 'Trash')
        self.restore_button.setEnabled(self.device_connected and not self.busy)
        retail_photos = bool(rows) and all(r.get('retail_photo') for r in rows)
        self.remove_button.setText('Exclude from preparation' if retail_photos else
                                   'Delete permanently' if self.page == 'Trash' else 'Move to Trash')
        self.remove_button.setEnabled(self.device_connected and not self.busy and
                                      (retail_photos or all(r.get('removable', True) for r in rows)))
        self.info_button.setEnabled(len(rows) == 1 and not self.busy)
        music_roots = (Path(self.identity['root']) / 'Music',
                       Path(self.identity['root']) / 'iPod_Control' / 'Music') if self.identity else ()
        self.prepare_pcm_button.setVisible(self.page == 'Music' and bool(rows))
        self.prepare_pcm_button.setEnabled(self.device_connected and not self.busy and bool(rows) and
            all(row['kind'] == 'Music' and row['category'] == 'original' and
                not row['path'].casefold().endswith('.linnet.wav') and
                any(Path(row['path']).is_relative_to(root) for root in music_roots) for row in rows))

    def clear_selection(self):
        self.table.clearSelection(); self.grid.clearSelection(); self.selection_bar.hide()

    def open_group(self, index):
        row = self.model.rows[index.row()]
        if 'members' in row:
            self.group = row; self.render_library()
        else:
            self.inspect_selection()

    def dialog(self, title, message, action='Continue', danger=False, cancel=True, secondary=None):
        dialog = QDialog(self); dialog.setWindowTitle(title); dialog.setMinimumWidth(460)
        layout = box(dialog, margins=(28, 28, 28, 24), spacing=18)
        layout.addWidget(label(title, 'section')); layout.addWidget(label(message, None, True))
        actions = box(horizontal=True); actions.addStretch()
        if secondary:
            actions.addWidget(button(secondary[0], lambda: dialog.done(2)))
        if cancel:
            actions.addWidget(button('Cancel', dialog.reject))
        actions.addWidget(button(action, dialog.accept, 'danger' if danger else 'primary')); layout.addLayout(actions)
        result = dialog.exec()
        if result == 2 and secondary:
            secondary[1]()
        return result == QDialog.Accepted

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
        if row.get('category') == 'error' or row.get('apple_only'):
            layout.addWidget(label(row.get('description') or 'This catalog needs repair before preparation.', 'notice', True))
            if row.get('error'):
                layout.addWidget(label(row['error'], 'muted', True))
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
            dict(self.identity) if self.identity and tag not in ('devices','hardware_report') and not tag.startswith('cache_') else None,
            self.stop_event if tag in ('prepare', 'remove', 'restore', 'scan', 'plan', 'devices', 'hardware_report', 'apple_update', 'classic_install', 'apple_font_install') else None)
        self.active_operation = context
        self.busy = True
        self.stop_event.clear()
        self.progress.setRange(0, 0)
        self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText('Stop')
        self.cancel_button.setToolTip('Stop reading the iPod' if tag in ('scan', 'devices', 'hardware_report') else
                                      'Stop checking the preparation plan' if tag == 'plan' else
                                      'Stop after the current step finishes')
        self.cancel_button.setVisible(context.can_cancel)
        self.show_progress(message)
        self.update_controls()
        def run():
            try:
                with host_cache.activity():
                    value = operation()
                outcome = OperationOutcome(context, value, status=operation_status(value),
                    cancel_requested=bool(context.cancel_event and context.cancel_event.is_set()))
            except Exception as error:
                outcome = OperationOutcome(context,
                    status='cancelled' if type(error).__name__ == 'Cancelled' else 'failed',
                    error=str(error) or type(error).__name__,
                    error_type=getattr(error, 'error_type', type(error).__name__),
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
        if tag in ('classic_install', 'uninstall'):
            self.close_setup_instruction()
        self.busy = False
        self.progress.hide()
        self.cancel_button.hide()
        self.update_controls()
        cancel_requested = outcome.cancel_requested or bool(context.cancel_event and context.cancel_event.is_set())
        if cancel_requested and tag == 'hardware_report' and outcome.status != 'failed':
            self.show_progress('Stopped collecting the hardware report.')
            return
        if cancel_requested and tag in ('scan', 'plan', 'devices') and outcome.status != 'failed':
            if tag == 'plan':
                self.plan_context = None
            elif tag == 'scan' and isinstance(result, dict) and result.get('publication_recovery_pending'):
                self._complete_scan(result)
                self.show_progress('An interrupted media update needs review before this iPod can be used.')
                return
            elif tag == 'devices' and self.publication_recovery_pending:
                self.update_controls()
            else:
                self.transition_device(None)
            self.show_progress('Stopped reading the iPod. If iTunes is syncing, let it finish before refreshing.'
                               if tag in ('scan', 'devices') else
                               'Stopped checking the preparation plan. Refresh when ready.')
            return
        if outcome.status not in ('succeeded', 'partial', 'cancelled', 'failed'):
            self.show_error(f'Unknown background outcome: {outcome.status}')
            return
        if context.identity and not self.same_device(self.identity, context.identity):
            self.record_diagnostic(tag, 'DeviceChanged', 'The selected iPod changed during the operation.', 'failed')
            self.show_error('The selected iPod changed while this operation was running. Refresh and try again.')
            return
        if tag == 'apple_update' and outcome.status == 'cancelled':
            message = 'Apple library update stopped. Checking the current library…'
            self.prep_results.setPlainText(message); self.prep_results.show()
            self.show_progress(message); self.refresh()
            return
        if tag == 'classic_install' and outcome.status == 'cancelled':
            self.show_progress(error or 'Classic setup stopped before bootloader installation.')
            return
        if tag == 'apple_font_install' and outcome.status == 'cancelled':
            self.show_progress('Apple font download stopped. The iPod font was not changed.')
            return
        if error:
            self.record_diagnostic(tag, outcome.error_type or 'Error', error, outcome.status,
                                   cancel_requested)
        if tag == 'queue':
            self._complete_queue(result, error)
            return
        if error:
            self._complete_error(tag, error, outcome.error_type)
            return
        handlers = {
            'cache_size': self._complete_cache, 'cache_clear': self._complete_cache, 'cache_move': self._complete_cache,
            'screens': self._complete_screens, 'plan': self._complete_plan,
            'save_screens': self._complete_save_screens, 'games': self._complete_games,
            'save_games': self._complete_save_games, 'review_skipped': self._complete_review_skipped,
            'import_game': self._complete_installed_game, 'remove_game': self._complete_installed_game,
            'playlists': self._complete_playlists, 'save_playlists': self._complete_save_playlists,
            'apple_selection': self._complete_apple_selection, 'apple_update': self._complete_apple_update,
            'devices': self._complete_devices, 'scan': self._complete_scan,
            'hardware_report': self._complete_hardware_report,
            'video_recovery_options': self._complete_video_recovery_options,
            'recover_publication': self._complete_recover_publication,
            'trash': self._complete_trash, 'setup': self._complete_setup,
            'uninstall_trash': self._complete_uninstall_trash,
            'link_setup': self._complete_link_setup,
            'prepare': self._complete_prepare, 'eject': self._complete_eject,
            'device_details': self._complete_device_details,
            'screenshot': self._complete_screenshot,
            'apple_font_install': self._complete_apple_font,
            'apple_font_remove': self._complete_apple_font,
        }
        for change in ('remove', 'restore', 'erase', 'sync', 'install', 'uninstall', 'skipped',
                       'startup_default', 'boot_upgrade', 'restore_video_catalog', 'classic_install', 'link_disk'):
            handlers[change] = self._complete_change
        handler = handlers.get(tag)
        if handler is None:
            self.show_error(f'Unknown background operation: {tag}')
            return
        handler(result)
        if tag in ('cache_clear', 'cache_move'):
            self.covers.invalidate()
            self._library_source, self._library_cache, self._library_stats = None, {}, {}
            self._library_search = None
            self.cache_library_dirty = True
            if self.page != 'Settings' and self.identity and self.device_connected:
                QTimer.singleShot(0, self.refresh)
        elif not tag.startswith('cache_') and self.page == 'Settings' and self.cache_info is None:
            QTimer.singleShot(0, self.refresh_cache)
        if tag == 'scan':
            self.cache_library_dirty = False
        if tag not in ('screens', 'plan', 'save_screens', 'games', 'save_games', 'import_game', 'remove_game',
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

    def _complete_error(self, tag, error, error_type=''):
        if tag == 'uninstall' and error_type == 'AppleStoragePending':
            # The saved identity belongs to the ejected Linnet connection. Do
            # not leave removal enabled against its old disk serial or volume.
            self.transition_device(None)
            self.device_name.setText('Apple restored · cleanup pending')
            self.device_info.setText('Reconnect in Apple Disk Mode, then choose Find iPod')
        if tag == 'classic_install':
            # The disk may have changed mode while setup was running. Keep the
            # host transaction reachable without offering stale install choices.
            self.review=None
            with QSignalBlocker(self.boot_choice),QSignalBlocker(self.method_choice):
                self.boot_choice.clear();self.method_choice.clear()
            self.update_controls()
        if tag == 'plan':
            self.plan_context = None
        if tag == 'screens':
            self.screen_state = screen_settings.defaults(self.identity)
            self.screen_saved = None
            self.screens_controller.render_screen_items()
            self.screen_status.setText('Could not read settings. Showing defaults for this iPod; saving will replace its screen settings.')
        if tag == 'games':
            self.game_read_failed = error_type=='GameCatalogueRecovery' or 'game selection is damaged' in error.casefold()
            self.games_status.setText('Game settings are damaged. Use Replace damaged game settings to choose a new selection.'
                                      if self.game_read_failed else 'Could not read game settings. Refresh or choose the iPod again.')
        if (tag in ('scan', 'devices', 'link_setup', 'link_disk', 'uninstall') and
                error_type != 'AppleStoragePending'):
            self.transition_device(None)
            self.device_name.setText('Connection needs checking')
            self.device_info.setText('Connection needs checking · choose Refresh or Choose iPod')
            self.update_controls()
        if tag in ('setup', 'devices', 'scan'):
            self.setup_progress.hide()
            self.setup_software.setText('Could not check iPod setup. Choose Refresh to try again.')
        self.show_error(error)
        self.update_controls()
        if tag == 'save_playlists':
            self.edit_playlists(self.playlist_draft)
        return

    def _complete_screens(self, result):
        self.screen_state = result; self.screen_saved = {name: list(rows) for name, rows in result.items()}
        self.screen_base = {name: list(rows) for name, rows in result.items()}
        self.screen_loaded_for = self.identity['root']
        self.load_choices_draft('screens')
        self.screens_controller.render_screen_items()
        self.screen_status.setText('Unsaved screen choices restored for this iPod. Save to apply them.' if self.screen_dirty else
                                   'Loaded from iPod. Changes apply after saving and restarting Linnet.')
        self.update_controls(); return

    def _complete_plan(self, result):
        context = self.plan_context
        self.plan_context = None
        if context is None or not self.same_device(self.identity, context['identity']):
            self.show_error('The selected iPod changed while preparing the plan. Review it again.')
            return
        copies = ', '.join(f'{kind}: {count}' for kind, count in result['copy_kinds'].items() if count)
        summary = [f"Prepare: {', '.join(result['selected'])}"]
        if result['videos']:
            noun = 'video' if result['videos'] == 1 else 'videos'
            summary.append(f"Prepare {result['videos']:,} {noun} for playback on this iPod.")
        if result['copies']:
            noun = 'file' if result['copies'] == 1 else 'files'
            summary.append(f"Copy {result['copies']:,} {noun} ({size(result['bytes'])}) · {copies}")
        elif not result['videos']:
            summary.append('Update the selected iPod libraries.')
        preview = [f"File copies: {result['copies']:,} ({size(result['bytes'])})" +
                   (f' · {copies}' if copies else ''),
                   'Videos are prepared separately from these file copies.',
                   f"Videos to prepare: {result['videos']:,}"]
        if result['conversion']:
            preview.append('Video conversion is included. Final output sizes depend on encoding.')
        profile = context['identity'].get('media_profile', {})
        if result['videos'] and profile.get('video_backend') == 'ipvf':
            preview.append(f"This iPod uses Linnet IPVF video ({profile['video_width']} × "
                           f"{profile['video_height']}, {profile['video_fps']} fps).")
        if result.get('audio_conversions'):
            preview.append(f"Convert on computer: {result['audio_conversions']:,} music files; source files stay in place")
        if result.get('audio_unplayable'):
            summary.append(f"Needs conversion: {result['audio_unplayable']:,} music files will be copied but skipped for playback")
        for issue in result.get('audio_issues', []):
            preview.append(f"{Path(issue['source']).name}: {issue['reason']}")
        if 'device_peak_bytes' in result:
            summary.append(f"iPod space budget: {size(result['device_peak_bytes'])} · {size(result['free'])} available")
        if 'computer_peak_bytes' in result:
            summary.append(f"Computer space budget: {size(result['computer_peak_bytes'])} · {size(result['computer_free'])} available")
        preview.append('Space budgets are conservative estimates for prepared media, temporary files, '
                       'and recovery copies. Final media sizes may be smaller.')
        if result['reusable']:
            preview.append('Likely reusable prepared libraries: ' + ', '.join(result['reusable']))
        if result['existing_unverified']:
            preview.append(f"Existing originals checked during preparation: {result['existing_unverified']:,} files")
        if result['excluded']:
            preview.append(f"Queue entries outside this selection: {result['excluded']:,}")
        for source, description in list(result['previews'].items())[:5]:
            preview.append(f'{Path(source).name}: {description}')
        if len(result['previews']) > 5:
            preview.append(f"…and {len(result['previews']) - 5:,} more queued sources")
        preview.append('Sources, available space, and prepared outputs are checked again during preparation.')
        reconciliation = result.get('reconciliation', [])
        changes = []
        if reconciliation:
            changes.append(f'{len(reconciliation)} changes to existing iPod content require approval:')
            root = Path(context['identity']['root'])
            for action in reconciliation:
                destination = Path(action['destination'])
                try:
                    shown = destination.relative_to(root).as_posix()
                except ValueError:
                    shown = destination.name
                if action['action'] == 'replace':
                    changes.append(f"Replace {action['kind']}: {shown} with {Path(action['source']).name} "
                                   f"({size(action['old_bytes'])} → {size(action['new_bytes'])})")
                elif action['action'] == 'retire-library':
                    changes.append(f"Move empty {action['kind']} library to Trash: {shown}")
                elif action['action'] == 'prune-video':
                    changes.append(f"Remove missing video entry: {action.get('title') or shown}")
        title = 'Review preparation changes' if reconciliation else 'Review preparation plan'
        dialog = QDialog(self); dialog.setWindowTitle(title); dialog.setMinimumWidth(580)
        layout = box(dialog, margins=(28, 28, 28, 24), spacing=16)
        layout.addWidget(label(title, 'section'))
        layout.addWidget(label('\n'.join(summary), None, True))
        layout.addWidget(label('Space budgets include temporary files and recovery copies.', 'muted', True))
        if changes:
            layout.addWidget(label('Review changes to existing content', 'section'))
            review = QTextEdit(); review.setReadOnly(True)
            review.setAccessibleName('Changes to existing iPod content')
            review.setPlainText('\n'.join(changes)); review.setMinimumHeight(160)
            layout.addWidget(review)
        details = QTextEdit(); details.setReadOnly(True)
        details.setAccessibleName('Preparation details')
        details.setPlainText('\n'.join(preview)); details.setMinimumHeight(180)
        details.hide()
        toggle = button('Show details', lambda: None); toggle.setCheckable(True)
        def show_details(visible):
            details.setVisible(visible)
            toggle.setText('Hide details' if visible else 'Show details')
            dialog.adjustSize()
        toggle.toggled.connect(show_details)
        layout.addWidget(toggle, 0, Qt.AlignLeft); layout.addWidget(details)
        actions = box(horizontal=True); actions.addStretch()
        actions.addWidget(button('Cancel', dialog.reject))
        actions.addWidget(button('Approve changes and prepare' if reconciliation else 'Start preparation',
                                 dialog.accept, 'primary'))
        layout.addLayout(actions)
        accepted = dialog.exec() == QDialog.Accepted
        if accepted:
            context['approval']['actions'] = reconciliation
            self.submitted, self.submitted_videos = context['pending'], context['submitted_videos']
            self.prep_results.hide()
            self.work('prepare', context['run'], 'Preparing your selected media…')
        return

    def _complete_save_screens(self, result):
        self.screen_state = result
        self.screen_base = {name: list(rows) for name, rows in result.items()}
        self.screens_controller.render_screen_items()
        self.screen_loaded_for = self.identity['root']
        self.screen_saved = {name: list(rows) for name, rows in self.screen_state.items()}
        self.screen_dirty = False; self.save_choices_draft()
        self.screen_status.setText('Saved to iPod. Eject safely to apply on startup.'); return

    def _complete_games(self, result):
        selected=result['selected'] if isinstance(result,dict) else result
        self.custom_games.clear()
        for row in result.get('custom',[]) if isinstance(result,dict) else []:
            item=QListWidgetItem(row['title']);item.setData(Qt.UserRole,row['id'])
            item.setToolTip(row['id']+'\n'+row['description']);self.custom_games.addItem(item)
        for index, check in enumerate(self.game_checks):
            with QSignalBlocker(check):
                check.setChecked(index in selected)
        self.games_loaded_for = self.identity['root']
        self.game_saved = set(selected); self.game_read_failed = False;self.game_recover_requested=False
        self.load_choices_draft('games')
        self.games_status.setText('Unsaved game choices restored for this iPod. Update to apply them.' if self.game_dirty else
                                  'Loaded from iPod. Uncheck a game to remove its installed package. Saved progress is retained.')
        self.update_controls(); return

    def _complete_save_games(self, result):
        self.game_saved = {i for i, check in enumerate(self.game_checks) if check.isChecked()}
        self.game_dirty = False;self.game_recover_requested=False; self.save_choices_draft()
        self.games_status.setText('Games updated. Eject safely and restart Linnet to apply.')
        self.update_controls(); return

    def _complete_installed_game(self, result):
        self.games_loaded_for=None
        self.games_status.setText('Game packages updated. Eject safely to apply them.')
        self.games_controller.load_games()

    def _complete_review_skipped(self, result):
        identity, rows = result
        if not self.same_device(self.identity, identity):
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
        devices, errors = sorted(result['devices'], key=lambda item: item['drive']), result['errors']
        self.discovery_errors = errors
        self.hardware_report = result.get('hardware_report')
        self.link_connection = None
        if devices and result.get('links'):
            dialog = QDialog(self); dialog.setWindowTitle('Choose an iPod')
            layout = box(dialog, margins=(24,24,24,24)); picker = ComboBox()
            layout.addWidget(label('Choose an iPod', 'section'))
            for item in devices:picker.addItem(self.device_title(item),('disk',item))
            for item in result['links']:
                picker.addItem(item['target_name']+' · Linnet Link · '+item['serial'][-6:],('link',item))
            layout.addWidget(picker); layout.addWidget(button('Use this iPod',dialog.accept,'primary'))
            if dialog.exec() != QDialog.Accepted:return
            kind, selected = picker.currentData()
            devices = [selected] if kind=='disk' else []
            result = dict(result,links=[selected] if kind=='link' else [])
        if not devices and result.get('links'):
            links = result['links']
            selected = links[0]
            if len(links) > 1:
                dialog = QDialog(self); dialog.setWindowTitle('Choose an iPod')
                layout = box(dialog, margins=(24,24,24,24)); picker = ComboBox()
                for item in links:
                    picker.addItem(item['target_name'] + ' · ' + item['serial'][-6:], item)
                layout.addWidget(picker); layout.addWidget(button('Use this iPod',dialog.accept,'primary'))
                if dialog.exec() != QDialog.Accepted:return
                selected = picker.currentData()
            self.transition_device(None)
            self.link_connection = selected
            self.device_name.setText(selected['target_name'].replace('Linnet for ',''))
            self.device_info.setText('Connected through Linnet Link')
            self.update_preparation()
            self.show_progress('Your iPod is connected. Manage startup settings and Linnet builds in iPod setup.')
            self.navigate('iPod setup'); self.update_controls()
            if errors:
                self.record_diagnostic('devices', 'DiscoveryError', '; '.join(errors), 'partial')
                self.show_progress('A connected iPod needs attention. See the message in iPod setup.')
            return
        if not devices:
            self.transition_device(None)
            self.device_name.setText('No iPod connected'); self.device_info.setText('Connect in Disk Mode')
            if self.hardware_report:
                self.device_name.setText('Compatibility needs checking' if self.hardware_report['usb'] else 'No iPod connection verified')
                self.device_info.setText('See iPod setup for details')
                self.show_progress(self.hardware_report['summary'])
                if errors:self.record_diagnostic('devices', 'DiscoveryError', '; '.join(errors), 'failed')
            elif errors:
                self.record_diagnostic('devices', 'DiscoveryError', '; '.join(errors), 'failed')
                self.show_progress('The connected iPod’s storage could not be read. Follow the Disk Mode steps in iPod setup, then choose Refresh.')
            else:
                self.show_progress('Connect your iPod, then choose Refresh.')
            self.navigate('iPod setup')
            return
        if len(devices) > 1:
            dialog = QDialog(self); dialog.setWindowTitle('Choose an iPod'); layout = box(dialog, margins=(24, 24, 24, 24))
            layout.addWidget(label('Choose an iPod', 'section'))
            layout.addWidget(label('Select by name, drive, model, and serial suffix.', 'muted'))
            picker = ComboBox()
            for device in devices:
                picker.addItem(self.device_title(device), device)
                if self.same_device(self.identity, device):
                    picker.setCurrentIndex(picker.count() - 1)
            layout.addWidget(picker); layout.addWidget(button('Use this iPod', dialog.accept, 'primary'))
            if dialog.exec() != QDialog.Accepted:
                return
            identity = picker.currentData()
        else:
            identity = devices[0]
        if errors:
            self.record_diagnostic('devices', 'DiscoveryError', '; '.join(errors), 'partial')
            self.notice.setText('Other connected iPods could not be read: ' + '; '.join(errors))
            self.notice.show()
        self.transition_device(identity)
        self.device_connected = True
        self.refresh()

    @staticmethod
    def device_title(identity):
        name = (identity.get('volume_label') or 'Unnamed iPod').strip()
        model = identity['target_name'].replace('Linnet for ', '')
        serial = identity['disk_serial'][-6:]
        return f"{name} · {identity['drive']} · {model} · {serial}"

    def _complete_scan(self, result):
        if isinstance(result, dict) and result.get('publication_recovery_pending'):
            self.identity = result['identity']
            self.device_connected = False
            self.publication_recovery_pending = True
            self.publication_recovery_groups = result['groups']
            self.inventory = self.review = self.apple_info = None
            self.rows = []; self.readiness = {}
            self.trash_rows = []
            self.update_trash_badge(None)
            self.group = None
            self._selection_context = None
            self.clear_selection()
            self._library_source = None
            self.device_name.setText('Media index recovery needed')
            self.device_info.setText('Review recovery before reading or ejecting this iPod')
            self.notice.setText('An interrupted media index update was found. Choose Recover media indexes to review recovery.')
            self.notice.show()
            self.update_preparation(); self.render_library(); self.update_controls()
            return
        self.publication_recovery_pending = False
        self.publication_recovery_groups = []
        with self.covers.sidecar_lock:
            missing_folders = {folder for folder, found in self.covers.sidecars.items() if found is None}
        cached_photos, missing_covers = {}, set()
        for row in self.rows:
            artwork = row.get('artwork')
            if row['kind'] not in ('Photos', 'Music') or (artwork not in self.covers.cache and
                                                       artwork not in self.covers.pending):
                continue
            cached_photos[row['path']] = (row['bytes'], row['mtime_ns'], artwork)
            if row['kind'] == 'Music' and Path(row.get('cover_source') or row['path']).parent in missing_folders:
                missing_covers.add(row['path'])
        self.identity, self.inventory, self.rows, self.readiness, self.apple_info, self.review = result
        self.device_connected = True
        self.update_trash_badge(self.review.get('trash'))
        changed = []
        if cached_photos:
            current_photos = {row['path']: (row['bytes'], row['mtime_ns'], row.get('artwork')) for row in self.rows
                              if row['path'] in cached_photos}
            changed = [stamp[2] for path, stamp in cached_photos.items()
                       if current_photos.get(path) != stamp or path in missing_covers or
                       (stamp[2] in self.covers.cache and self.covers.cache[stamp[2]] is None)]
        # A refresh may discover a new sidecar even when track metadata and
        # previously loaded pixmaps did not change.
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
        category_errors = [(kind, info.get('errors')) for kind, info in self.inventory.items()
                           if isinstance(info, dict) and info.get('errors')]
        if category_errors:
            names = ', '.join(kind for kind, _ in category_errors)
            self.notice.setText(f'{names} catalog needs repair. Open Preparation and choose Review catalog backups; healthy libraries remain available.')
            self.notice.show()
            for kind, errors in category_errors:
                self.record_diagnostic('scan', 'CatalogError', f'{kind}: {errors}', 'partial')
        elif self.discovery_errors:
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
        elif self.review['linnet']['state']=='absent' and not self.settings.value('setup_seen/'+self.identity['linnet_usb_serial'],False,type=bool):
            self.settings.setValue('setup_seen/'+self.identity['linnet_usb_serial'],True)
            self.navigate('iPod setup')
        elif self.page == 'Trash':
            identity = self.identity
            self.work('trash', lambda: media_trash.inventory(identity), 'Reading Trash…')

    def _complete_trash(self, result):
        self.trash_rows = result['rows']; self.update_trash_badge(result['summary'])
        self.render_library(); self.show_progress('Trash uses storage until files are permanently deleted.')

    def update_trash_badge(self, summary):
        self.trash_summary = summary
        count = summary.get('count', 0) if summary else 0
        unreadable = summary.get('unreadable', 0) if summary else 0
        self.trash_badge.setText(('99+' if count > 99 else str(count)) if count else '!')
        self.trash_badge.setVisible(bool(self.identity and self.device_connected and (count or unreadable)))
        noun = 'entry' if count == 1 else 'entries'
        detail = (f'{count:,} recoverable {noun} in Trash. Restore removed files or empty Trash to free space.' if count else
                  'Removed media can be restored from Trash until you empty it.')
        if unreadable:
            detail += ' Some Trash entries need review.'
        self.navigation['Trash'].setToolTip(detail)
        self.navigation['Trash'].setAccessibleName(
            f'Trash, {count:,} {noun}' + (', needs review' if unreadable else '') if summary else 'Trash')

    def _complete_uninstall_trash(self, result):
        self.review = result['review']; self.render_setup()
        if not (self.review['uninstall']['available'] or self.review['uninstall'].get('blocker') == 'trash'):
            self.dialog('Cannot remove Linnet', self.review['uninstall']['detail'], 'Close', cancel=False)
            return
        if result['unrecognized']:
            if self.dialog('Trash needs review',
                    'Some Trash entries could not be read. Review them in the Trash folder before removing Linnet.',
                    'Open Trash folder'):
                self.open_folder(Path(self.identity['root']) / '.LINNET' / 'TRASH')
        else:
            self.confirm_uninstall(result['rows'])

    def _complete_video_recovery_options(self, review):
        options = review.get('options', [])
        if review.get('status') != 'damaged':
            self.show_progress('The video catalog can be read now. Refresh to update the library.')
            return
        if not options:
            self.dialog('Video catalog needs repair',
                'No complete, validated on-device backup is available. Linnet kept the damaged catalog and prepared videos untouched. Recover the catalog from a trusted backup before preparing videos.',
                'Close', cancel=False)
            return
        dialog = QDialog(self); dialog.setWindowTitle('Review video catalog backups'); dialog.resize(640, 460)
        layout = box(dialog, margins=(20, 20, 20, 20))
        layout.addWidget(label('Restore a verified video catalog', 'section'))
        layout.addWidget(label('This replaces the damaged catalog with the selected on-device backup. The damaged bytes are saved for recovery. Videos added after that backup may need preparation again.', 'muted', True))
        picker = ComboBox(); picker.setAccessibleName('Video catalog backup')
        for option in options:
            picker.addItem(f"{option['name']} · {option['entries']} entries", option)
        layout.addWidget(picker)
        details = QTextEdit(); details.setReadOnly(True); details.setAccessibleName('Backup video titles')
        layout.addWidget(details)
        def describe():
            option = picker.currentData()
            titles = option.get('titles', []) if option else []
            details.setPlainText('\n'.join(str(title) for title in titles[:100]) +
                (f'\n… {len(titles) - 100} more titles' if len(titles) > 100 else ''))
        picker.currentIndexChanged.connect(describe); describe()
        actions = box(horizontal=True)
        actions.addWidget(button('Cancel', dialog.reject)); actions.addStretch()
        actions.addWidget(button('Restore selected backup', dialog.accept, 'primary'))
        layout.addLayout(actions)
        if dialog.exec() == QDialog.Accepted:
            option = picker.currentData()
            identity = self.identity
            if not identity or not self.device_connected:
                self.show_error('The iPod changed. Review its video catalog again.')
                return
            self.work('restore_video_catalog', lambda: media_library.restore_video_catalog_backup(
                identity, option['name'], option['sha256'], review['catalog_sha256']),
                'Restoring the reviewed video catalog backup…')

    def _complete_setup(self, result):
        self.review = result; self.update_trash_badge(result.get('trash'))
        self.render_setup(); self.show_progress('Device setup is ready.')

    def _complete_link_setup(self, result):
        self.transition_device(result['reconnected_identity'])
        self.device_name.setText(self.device_title(self.identity))
        self.device_info.setText('Connected in Disk Mode')
        self.cache_library_dirty = False
        if result.get('publication_recovery_pending'):
            self._complete_scan(result)
            self.navigate('Preparation')
            return
        if result.get('setup_error'):
            self.device_connected = False
            self.update_controls()
            self.cache_library_dirty = True
            self.show_error('Disk Mode connected, but setup could not be read: ' + result['setup_error'])
            return
        self.review = result['review']
        self.update_trash_badge(self.review.get('trash'))
        if result['section'] == 'build':
            self.build_editor_open = True
        self.navigate('iPod setup')
        self.cache_library_dirty = True
        section = result['section']
        target = (self.default_title if section == 'startup' else
                  self.uninstall_panel if section == 'remove' else self.boot_choice)
        def reveal():
            if self.closed or self.page != 'iPod setup' or self.review is not result['review']:
                return
            if section == 'build':
                self.boot_choice.setFocus()
            elif section == 'remove':
                self.uninstall_button.setFocus()
            elif self.default_choice.isVisible():
                self.default_choice.setFocus()
            self.setup.ensureWidgetVisible(target)
            if section == 'remove' and self.uninstall_button.isEnabled():
                self.uninstall_selected()
        # New sections change the scroll content height. Reveal only after
        # Qt has laid them out, so the previous hidden geometry is not used.
        QTimer.singleShot(0, reveal)
        self.show_progress('Choose the default system and use Menu at startup for a one-time choice.'
                           if section == 'startup' else
                           'Review removal options below.' if section == 'remove' else
                           'Choose User or Developer build, then apply the update. Your media is kept.')

    def _complete_prepare(self, result):
        failures = result.get('errors', [])
        if failures:
            self.record_diagnostic('prepare', 'PreparationResult',
                f'{len(failures)} preparation step(s) failed or were skipped.', 'partial',
                bool(result.get('stopped')))
            for failure in failures[:10]:
                self.record_diagnostic('prepare', failure.get('status', 'StepError'),
                    failure.get('message', 'Preparation step needs attention.'), 'partial',
                    bool(result.get('stopped')))
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
        if result['complete']:
            self.video_selection.difference_update(self.submitted_videos)
        self.validate_draft()
        self.save_draft()
        self.update_preparation(); self.refresh()

    def _complete_change(self, result):
        if result.get('reconnected_identity'):
            self.transition_device(result['reconnected_identity'])
        self.show_progress(result.get('summary', 'Changes saved.'))
        if result.get('needs_preparation'):
            self.prep_results.setPlainText(result['summary']); self.prep_results.show(); self.navigate('Preparation')
        self.refresh()

    def _complete_recover_publication(self, result):
        self.publication_recovery_pending = False
        self.publication_recovery_groups = []
        self.device_connected = True
        self.show_progress('Media indexes recovered. Checking the collection again…')
        self.refresh()

    def _complete_eject(self, result):
        self.transition_device(None)
        if result.get('disconnected'):
            self.device_name.setText('iPod disconnected')
            self.device_info.setText('Choose Find iPod after reconnecting.')
            self.capacity.setValue(0)
            self.show_progress('The previous iPod connection has closed. Choose Find iPod after reconnecting.')
            return
        self.device_name.setText('Safely ejected'); self.device_info.setText('You can disconnect your iPod.'); self.capacity.setValue(0)
        if result.get('already_ejected'):
            self.show_progress('Your iPod was already ejected in Windows. It is safe to disconnect, even if its screen still shows Disk Mode.')
        elif result.get('about_warning'):
            self.show_progress('Your iPod is safe to disconnect. Device details could not be refreshed: '
                               + result['about_warning'])
        else:
            self.show_progress('Your iPod is safe to disconnect.')

    def _complete_device_details(self, result):
        if result.get('link_connection') is not None and result['link_connection'] != self.link_connection:
            self.show_error('The selected iPod changed. Read device details again.')
            return
        fields = dict(row.split('  ', 1) for row in result['rows'] if '  ' in row)
        linked = result.get('link_connection') is not None
        dialog = QDialog(self); dialog.setWindowTitle('iPod details'); dialog.resize(580, 760)
        layout = box(dialog, margins=(26, 24, 26, 22), spacing=16)

        def value(text, style=None):
            shown = '\n'.join(text[at:at + 32] for at in range(0, len(text), 32)) if len(text) > 40 and not any(c.isspace() for c in text) else text
            item = label(shown, style, True)
            item.setTextFormat(Qt.PlainText)
            item.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            return item

        heading = value(result['name'], 'section')
        if result.get('name_saved'):
            heading.setToolTip('Last saved iPod name')
        layout.addWidget(heading)
        model = fields.get('Model') or fields.get('Model no.') or fields.get('Device', '')
        if fields.get('Device') and fields['Device'] not in (result['name'], model):
            model = fields['Device'] + ' · ' + model
        layout.addWidget(value(model, 'muted'))
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget(); content = box(body, margins=(0, 0, 8, 0), spacing=18)
        scroll.setWidget(body); body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False); layout.addWidget(scroll, 1)

        captions = []

        def section(title, entries):
            if not entries:
                return
            content.addWidget(label(title, 'cardTitle'))
            grid = QGridLayout(); grid.setHorizontalSpacing(22); grid.setVerticalSpacing(10)
            grid.setColumnStretch(1, 1)
            for row, (caption, text) in enumerate(entries):
                caption_label = label(caption, 'muted'); captions.append(caption_label)
                grid.addWidget(caption_label, row, 0, Qt.AlignTop)
                grid.addWidget(value(text), row, 1)
            content.addLayout(grid)

        def entries(pairs):
            return [(caption, fields[key]) for caption, key in pairs if fields.get(key)]

        section('Device', [(caption, text) for caption, text in (
            ('Serial number', result.get('device_serial')),
            ('Connection', 'Linnet Link' if linked else 'Disk Mode')) if text] + entries((
                ('USB serial', 'USB serial'), ('Disk ID', 'Disk ID'), ('USB model', 'USB model'),
                ('USB', 'USB'), ('Volume ID', 'Volume ID'), ('Regulatory model', 'Regulatory'),
                ('Board', 'Board'), ('Family', 'Family'), ('Region', 'Region'))))
        if result['used_percent'] is not None:
            content.addWidget(label('Storage', 'cardTitle'))
            usage = QProgressBar(); usage.setRange(0, 100); usage.setValue(result['used_percent'])
            usage.setFormat(f"{result['used_percent']}% used"); content.addWidget(usage)
            stats = box(horizontal=True, spacing=20)
            for caption, key in (('Used', 'Used'), ('Available', 'Free'), ('Total', 'Capacity')):
                column = box(spacing=4); column.addWidget(label(caption, 'muted'))
                column.addWidget(value(fields.get(key))); stats.addLayout(column, 1)
            content.addLayout(stats)
        section('Storage details', entries((('Drive', 'Drive'), ('Capacity', 'Disk size'),
            ('Drive firmware', 'Drive firmware'), ('Drive serial', 'Drive serial'),
            ('Partition', 'Partition'), ('Sector size', 'Sector'), ('Logical sector', 'Logical sector'),
            ('Physical sector', 'Physical sector'), ('Power state', 'Storage power'),
            ('Audio', 'Audio'), ('Video', 'Video'), ('Photos', 'Photos'), ('Data', 'Data'),
            ('Trash', 'Trash'), ('Other', 'Other'))))
        section('Software and power', entries((('Software', 'Software'), ('Apple software', 'Apple OS'),
            ('Build', 'Build'), ('Health', 'Health'), ('Build ID', 'Build ID'),
            ('Battery', 'Battery'), ('USB charge limit', 'USB charge limit'), ('Read', 'Read'))))
        caption_width = max((item.sizeHint().width() for item in captions), default=0)
        for item in captions:
            item.setFixedWidth(caption_width)
        content.addStretch()
        layout.addWidget(button('Close', dialog.accept, 'primary'), 0, Qt.AlignRight)
        dialog.exec()


    def discover(self):
        self.work('devices', lambda: media_reader.read('devices', cancelled=self.stop_event.is_set),
                  'Looking for your iPod…')

    def review_video_catalog(self):
        if self.busy or not self.identity or not self.device_connected:
            return
        identity = self.identity
        self.work('video_recovery_options', lambda: media_library.video_catalog_recovery_options(identity),
                  'Checking on-device video catalog backups…')

    def recover_publication(self):
        if self.busy or not self.identity or not self.publication_recovery_pending:
            return
        if not self.dialog('Recover interrupted media update',
            'Interrupted index groups: ' + ', '.join(self.publication_recovery_groups) + '\n\n'
            'Recovery checks the saved device record and restores a verified set before the library is read. Keep the iPod connected until it finishes.',
            'Recover media indexes'):
            return
        identity = self.identity
        self.work('recover_publication', lambda: publish.recover_pending_publications(
            **media.target_args(identity)), 'Recovering media indexes…')

    def open_playlists(self):
        if self.identity and self.device_connected and not self.busy:
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
        if not self.identity or not self.device_connected:
            self.discover(); return
        identity = self.identity
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        verification = 'full' if self.verify_audio.isChecked() else 'metadata'
        def inspect():
            result = media_reader.read('scan', identity=identity, photo_dimension=dimension,
                                       verification=verification, cancelled=self.stop_event.is_set)
            if not isinstance(result, dict):
                for row in result[2]:
                    if self.stop_event.is_set():
                        raise media.Cancelled()
                    if row['category'] in ('original', 'published'):
                        row['_linnet_search_text'] = library_search_text(row)
            return result
        self.work('scan', inspect,
                  'Reading your collection and checking prepared media…')

    @staticmethod
    def same_device(first, second):
        return bool(first and second) and all(first.get(key) == second.get(key)
            for key in ('root', 'disk_serial', 'volume_serial', 'target_id'))

    @staticmethod
    def choices_key(identity):
        fields = (identity['target_id'], identity['disk_serial'], identity['volume_serial'])
        return 'device_choices/v1/' + hashlib.sha256('\0'.join(fields).encode('utf-8')).hexdigest()

    def save_choices_draft(self):
        if not self.identity:
            return
        key = self.choices_key(self.identity)
        try:
            draft = json.loads(self.settings.value(key, '{}'))
            if not isinstance(draft, dict) or draft.get('version', 1) != 1:
                draft = {}
        except (TypeError, ValueError):
            draft = {}
        draft['version'] = 1
        if self.screen_dirty:
            draft['screens'] = {name: list(rows) for name, rows in self.screen_state.items()}
            draft['screens_base'] = self.screen_base
        elif self.screen_loaded_for == self.identity['root']:
            draft.pop('screens', None)
            draft.pop('screens_base', None)
        if self.game_dirty:
            draft['games'] = [i for i, check in enumerate(self.game_checks) if check.isChecked()]
        elif self.games_loaded_for == self.identity['root']:
            draft.pop('games', None)
        if len(draft) == 1:
            self.settings.remove(key)
        else:
            self.settings.setValue(key, json.dumps(draft))
        self.settings.sync()

    def load_choices_draft(self, section):
        if not self.identity:
            return
        try:
            draft = json.loads(self.settings.value(self.choices_key(self.identity), '{}'))
            if not isinstance(draft, dict) or draft.get('version') != 1:
                return
            if section == 'screens' and isinstance(draft.get('screens'), dict):
                state = draft['screens']
                if set(state) != set(screen_settings.SCREENS) or any(
                    not isinstance(rows, list) or len(rows) != len(set(rows)) or
                    any(type(item) is not int or not 0 <= item < len(screen_settings.SCREENS[name])
                        for item in rows)
                    for name, rows in state.items()):
                    raise ValueError('Saved screen choices are invalid.')
                base = draft.get('screens_base')
                if base is not None:
                    screen_settings.encode(base)
                self.screen_state = {name: list(rows) for name, rows in state.items()}
                self.screen_base = base
                self.screen_dirty = self.screen_state != self.screen_saved
            elif section == 'games' and isinstance(draft.get('games'), list):
                chosen = draft['games']
                games.encode(chosen)
                for index, check in enumerate(self.game_checks):
                    with QSignalBlocker(check):
                        check.setChecked(index in chosen)
                self.game_dirty = set(chosen) != self.game_saved
        except (TypeError, ValueError, KeyError):
            self.record_diagnostic('choices', 'InvalidDraft', 'Saved device choices could not be restored.', 'partial')

    @staticmethod
    def draft_key(identity):
        fields = (identity['target_id'], identity['disk_serial'], identity['volume_serial'])
        digest = hashlib.sha256('\0'.join(fields).encode('utf-8')).hexdigest()
        return f'preparation_draft/v3/{digest}'

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
        draft = dict(version=3, target_id=self.identity['target_id'],
                     disk_serial=self.identity['disk_serial'],
                     volume_serial=self.identity['volume_serial'],
                     pending=[[kind, '@device/' + Path(name).relative_to(root).as_posix()
                               if Path(name).is_relative_to(root) else name]
                              for kind, name in self.pending],
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
        self.pending, self.pending_keys = [], set()
        self.video_selection, self.video_mode = set(), 'all'
        self.draft_issues, self.stale_videos, self.queue_outcomes = {}, 0, {}
        raw = self.settings.value(self.draft_key(identity), '')
        try:
            draft = json.loads(raw)
            if (not isinstance(draft, dict) or draft.get('version') != 3 or
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
                kind, name = item
                if name.startswith('@device/'):
                    relative = Path(name[8:])
                    if (kind != 'Music' or relative.is_absolute() or relative.drive or
                            '..' in relative.parts or not relative.parts or
                            relative.parts[0].casefold() != 'music'):
                        continue
                    name = str(Path(identity['root']) / relative)
                key = (kind, os.path.normcase(name))
                if key not in self.pending_keys:
                    self.pending.append((kind, name))
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
            self.validate_draft()
        except (TypeError, ValueError):
            return

    def transition_device(self, identity):
        """Clear device-derived state while retaining a draft for its own iPod."""
        self.link_connection = None
        self.apple_font_result = None
        if self.same_device(self.identity, identity):
            self.identity = identity
            return
        self.build_editor_open = False
        self.save_draft()
        self.save_choices_draft()
        if self.identity:
            self._recent_private_identifiers.update(str(self.identity.get(field)) for field in
                ('root', 'drive', 'disk_serial', 'volume_serial', 'volume_unique_id') if self.identity.get(field))
        if identity and self.last_preparation and not self.same_device(self.last_preparation[0], identity):
            self.last_preparation = None
            self.prep_results.clear()
            self.prep_results.hide()
        self.covers.invalidate()
        self.identity = identity
        self.device_connected = bool(identity)
        self.publication_recovery_pending = False
        self.publication_recovery_groups = []
        self._selection_context = None
        self.inventory = self.review = self.apple_info = None
        with QSignalBlocker(self.boot_choice), QSignalBlocker(self.method_choice), QSignalBlocker(self.default_choice):
            self.boot_choice.clear()
            self.method_choice.clear()
            self.default_choice.clear()
        self.uninstall_detail.setText('Checking removal options…' if identity else 'Connect an iPod to check removal options.')
        self.rows = []
        self.trash_rows = []
        self.update_trash_badge(None)
        self.readiness = {}
        self.group = None
        self.video_selection.clear()
        self.video_mode = 'all'
        if identity:
            self.load_draft(identity)
        else:
            self.pending, self.pending_keys = [], set()
            self.draft_issues, self.stale_videos, self.queue_outcomes = {}, 0, {}
        self.screen_loaded_for = self.games_loaded_for = None
        self.screen_saved = self.game_saved = None
        self.screen_base = None
        self.screen_dirty = self.game_dirty = self.game_read_failed = False
        self.game_recover_requested=False
        self.custom_games.clear()
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
        self._library_search = None
        self.capacity.setValue(0)
        self.device_name.setText((identity.get('volume_label') or 'Unnamed iPod').strip() if identity else 'Connect your iPod')
        self.device_info.setText(f"{identity['drive']} · Loading this iPod…" if identity else 'USB · Disk Mode')
        self.update_filters()
        self.update_preparation()
        self.render_library()
        self.update_controls()

    def update_device(self):
        identity = self.identity
        self.device_name.setText((identity.get('volume_label') or 'Unnamed iPod').strip())
        self.device_info.setText(f"{identity['drive']} · {identity['target_name'].replace('Linnet for ', '')} · {identity['disk_serial'][-6:]}\n{size(identity['free_bytes'])} available")
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
        ready = self.identity is not None and self.device_connected and not self.busy
        from tools.studio.media_capture import available
        self.screenshot_button.setEnabled(not self.busy and available(self.link_connection))
        self.screenshot_button.setToolTip('Capture the screen currently shown on your iPod.' if available(self.link_connection) else
            'Requires Linnet running with a Developer or Trace build over Linnet Link. Unavailable in Disk Mode and recovery.')
        self.update_trash_badge(self.trash_summary)
        self.update_preparation_connection()
        font_ready = ready and apple_font.supported(self.identity) and not self.publication_recovery_pending
        self.apple_font_install.setEnabled(font_ready)
        self.apple_font_remove.setEnabled(font_ready)
        if not apple_font.supported(self.identity):
            self.apple_font_status.setText('Connect a color iPod in Disk Mode to choose its font.')
        elif not self.busy:
            self.apple_font_status.setText(self.apple_font_result or 'Safely eject and restart after changing the font.')
        for item in (*self.cache_buttons, self.backups_open, self.recovery_open):
            item.setEnabled(not self.busy)
        self.cache_clear.setEnabled(not self.busy and bool(self.cache_info and self.cache_info['files']))
        self.choose_device_button.setEnabled(not self.busy)
        self.retry_button.setEnabled(ready)
        self.prep_details.setVisible(self.last_preparation is not None)
        self.prep_details.setEnabled(ready and self.last_preparation is not None and
                                    self.same_device(self.identity, self.last_preparation[0]))
        games_available = bool(self.identity and games.available(self.identity))
        games_unavailable = bool(self.identity and not games_available)
        self.games_unavailable.setVisible(games_unavailable)
        self.games_status.setVisible(not games_unavailable)
        self.games_save.setVisible(games_available)
        for card in self.game_cards:
            card.setVisible(games_available)
        games_ready = ready and games.available(self.identity)
        self.games_save.setEnabled(games_ready and self.games_loaded_for == self.identity['root'])
        packages_ready=games_ready and self.games_loaded_for==self.identity['root']
        self.game_import.setEnabled(packages_ready)
        self.game_remove.setEnabled(packages_ready and self.custom_games.currentItem() is not None)
        self.games_recover.setVisible(bool(self.identity and self.game_read_failed and games.available(self.identity)))
        self.games_recover.setEnabled(ready and self.game_read_failed)
        self.publication_recovery_button.setVisible(self.publication_recovery_pending)
        self.publication_recovery_button.setEnabled(self.publication_recovery_pending and not self.busy)
        self.video_repair_button.setVisible(bool((self.inventory or {}).get('Videos', {}).get('errors')))
        self.video_repair_button.setEnabled(ready and bool((self.inventory or {}).get('Videos', {}).get('errors')))
        supported_games = (games.supported(self.identity)
                           if self.identity and games.available(self.identity) else set())
        for index, check in enumerate(self.game_checks):
            if index not in supported_games and check.isChecked():
                with QSignalBlocker(check):
                    check.setChecked(False)
            check.setEnabled(games_ready and self.games_loaded_for == self.identity['root']
                             and index in supported_games)
        if ready and not games_ready:
            self.games_status.setText('Games are unavailable on this iPod.')
        supported = media.supported_kinds(self.identity) if ready else ()
        self.screens.setEnabled(not self.busy)
        self.screen_save.setEnabled(ready and all(self.screen_state.values()))
        self.screen_items.setEnabled(not self.busy)
        self.screen_picker.setEnabled(not self.busy)
        for item in (self.eject_button, self.add_button, self.playlists_button, self.sync_button, self.choose_videos_button, self.queue_add, self.folder_button):
            item.setEnabled(ready)
        self.device_details_button.setEnabled(ready or bool(self.link_connection and not self.busy))
        music_root = Path(self.identity['root']) / 'Music' if ready else None
        convertible = ready and any(row['kind'] == 'Music' and row['category'] == 'original' and
                                    str(row['status']).startswith('Needs conversion:') and
                                    Path(row['path']).is_relative_to(music_root) for row in self.rows)
        self.queue_incompatible.setVisible(convertible)
        self.queue_incompatible.setEnabled(convertible)
        self.update_queue_controls()
        self.prepare_button.setEnabled(ready and self.inventory is not None)
        apple_ready = ready and self.apple_info is not None and self.apple_info['supported']
        self.apple_choose.setEnabled(apple_ready)
        self.apple_update.setText('Retry Apple library update' if apple_ready and
                                  self.apple_info.get('can_update') and
                                  self.apple_info['status'] == 'Needs attention' else 'Update Apple library')
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
        self.discovery_issue.setText('A connected iPod needs attention: ' + '; '.join(self.discovery_errors))
        self.discovery_issue.setVisible(bool(self.discovery_errors))
        from tools.studio.device_support import describe
        support_identity = self.identity or (self.link_connection or {}).get('identity')
        if self.identity is None and self.link_connection:
            support_identity = dict(support_identity, **self.link_connection.get('product', {}))
        support = describe(support_identity, self.review)
        self.support_status.setText(self.hardware_report['summary'] if not support_identity and self.hardware_report else
                                   support['title'] + ' — ' + support['detail'])
        self.hardware_report_button.setEnabled(not self.busy)
        self.setup_progress.setVisible(loading)
        setting_up = bool(self.busy and self.active_operation and self.active_operation.tag=='classic_install')
        link = self.link_connection
        linked_os = bool(link and link['identity']['image_kind'] == 'os' and self.review is None)
        self.connection_help.setVisible(self.identity is None and link is None and not setting_up)
        self.setup_find_button.setVisible(self.identity is None and link is None and not setting_up)
        self.link_disk_button.setVisible(bool(link and link.get('can_open_disk')))
        self.link_disk_button.setEnabled(bool(link and link.get('can_open_disk')) and not self.busy)
        self.setup_find_button.setEnabled(not self.busy)
        if not self.busy:
            from tools.studio.classic_setup import pending
            scope = dict(target_id=link['identity']['target_id'],linnet_usb_serial=link['serial']) if link else self.identity
            resumable = self.review is None and bool(pending(scope))
            self.resume_classic_button.setVisible(resumable)
            if link and resumable:self.link_disk_button.hide()
        show_link_actions = linked_os and self.resume_classic_button.isHidden() and not setting_up
        self.link_setup_panel.setVisible(show_link_actions)
        for action in (self.link_startup_button, self.link_build_button, self.link_uninstall_button):
            action.setEnabled(bool(show_link_actions and link.get('can_open_disk')) and not self.busy)
        self.link_uninstall_detail.setText(
            'Opens Disk Mode automatically, then asks you to confirm removal. Your media folders are kept.'
            if link and link.get('can_open_disk') else
            'Enter Apple Disk Mode, then choose Find iPod to review removal: hold Menu + Select until restart, '
            'then immediately hold Select + Play/Pause until Disk Mode appears.')
        self.resume_classic_button.setEnabled(not self.busy)
        if self.review is not None:
            return
        if link:
            self.setup_device.setText(link['target_name'].replace('Linnet for ', '') + ' · …' + link['serial'][-6:])
            build = installer.BUILD_LABELS[link['identity']['profile']]
            self.setup_software.setText('Connected through Linnet Link' if linked_os else 'Recovery connected')
            self.link_disk_button.setText('Open Disk Mode')
            self.link_build_status.setText(build + ' running')
            self.install_detail.setText('Setup is continuing automatically. Keep USB connected.' if setting_up else
                'Choose Resume Classic installation to continue the saved setup.' if self.resume_classic_button.isVisible() else
                'Choose a setup action below, or open Disk Mode to manage media.' if linked_os and link.get('can_open_disk') else
                'Your iPod is connected. Open Disk Mode to manage files.' if link.get('can_open_disk') else
                'Linnet Link is connected. This iPod’s storage is not available yet.')
            self.install_detail.setVisible(setting_up or not self.resume_classic_button.isHidden() or not link.get('can_open_disk'))
            return
        if self.identity:
            self.setup_device.setText(self.device_title(self.identity))
            self.setup_software.setText('Checking iPod setup…' if loading else 'Choose Refresh to check installed software.')
        else:
            self.setup_device.setText('Looking for your iPod…' if loading else 'Connect your iPod with USB.')
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
        unavailable = [kind for kind in self.prep_cards if self.identity and kind not in supported]
        self.prep_unavailable.setText(f"{' and '.join(unavailable).capitalize()} aren't available on this iPod."
                                      if unavailable else '')
        self.prep_unavailable.setVisible(bool(unavailable))
        for kind, card in self.prep_cards.items():
            card.setVisible(kind not in unavailable)
        for kind, text in self.prep_labels.items():
            info = (self.inventory or {}).get(kind)
            if self.identity and kind not in supported:
                text.setText(f'{kind} playback is unavailable on this iPod model.')
            elif not info:
                text.setText('Open Disk Mode to check this library.' if self.link_connection else
                             'Reading this library…' if self.identity else
                             'Connect an iPod in Disk Mode to check this library.')
            elif kind == 'Videos':
                scope = ('All existing videos included' if self.video_mode == 'all' else
                         f'{len(self.video_selection)} selected for conversion' if self.video_mode == 'selected' else
                         'No conversions selected')
                text.setText(f"{info['count']:,} {'file' if info['count'] == 1 else 'files'} · {self.readiness.get(kind, 'Not checked')} · " +
                             scope)
            else:
                summary = f"{info['count']:,} {'file' if info['count'] == 1 else 'files'} · {self.readiness.get(kind, 'Not checked')}"
                if kind == 'Music':
                    differences = []
                    if info.get('apple_only'):
                        count = info['apple_only']
                        differences.append(f"{count:,} Apple-only {'track' if count == 1 else 'tracks'} excluded")
                    if info.get('not_in_apple'):
                        count = info['not_in_apple']
                        differences.append(f"{count:,} {'file' if count == 1 else 'files'} not listed in Apple OS")
                    if differences:
                        summary += '\n' + ' · '.join(differences)
                text.setText(summary)
        self.queue_model.reset([dict(title=Path(path).name, kind=kind, path=path,
                                     status=self.queue_status(kind, path))
                                for kind, path in self.pending],
                               [('title', 'FILE'), ('kind', 'TYPE'), ('status', 'STATUS'),
                                ('path', 'SOURCE')])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.queue_table.setVisible(bool(self.pending)); self.queue_remove.setVisible(bool(self.pending))
        self.queue_open.setVisible(bool(self.pending)); self.update_queue_controls()
        self.queue_table.setFixedHeight(min(200, max(75, self.queue_table.horizontalHeader().height() + len(self.pending) * self.queue_table.verticalHeader().defaultSectionSize() + 4)))
        summary = (f'{len(self.pending):,} files or folders queued. Unchanged media is reused.' if self.pending else
                   'Open Disk Mode to prepare existing iPod files or add media from your computer.' if self.link_connection else
                   'Nothing queued. You can prepare existing iPod files or add media from your computer.')
        if self.draft_issues:
            summary += f' {len(self.draft_issues):,} saved source(s) need attention.'
        if self.stale_videos:
            summary += f' {self.stale_videos:,} saved video choice(s) are no longer on this iPod.'
        self.prep_summary.setText(summary)
        if self.apple_info:
            eligibility = '' if self.apple_info['supported'] else self.apple_info.get('eligibility', '')
            self.apple_eligibility.setText(eligibility)
            self.apple_eligibility.setVisible(bool(eligibility))
            lines = [self.apple_info['status']]
            for entry in self.apple_info['details']:
                if entry['kind'] == 'Apple library':
                    if entry['status'] != self.apple_info['status']:
                        lines.append(entry['status'])
                    continue
                if entry['count'] or entry['status'] == 'Needs update':
                    lines.append(f"{entry['kind']}: {entry['count']:,} files · {entry['status']}")
            if self.apple_info.get('issues'):
                lines.append(self.apple_info['issues'][0])
            self.apple_status.setText('\n'.join(lines))
        else:
            self.apple_eligibility.setText('')
            self.apple_eligibility.setVisible(False)
            self.apple_status.setText('Open Disk Mode to check Apple OS availability.' if self.link_connection else
                                      'Checking Apple OS availability…' if self.identity else
                                      'Connect an iPod in Disk Mode to check Apple OS availability.')

    def update_preparation_connection(self):
        self.prep_connection.setVisible(self.identity is None)
        link = self.link_connection
        opening = bool(self.busy and self.active_operation and self.active_operation.tag == 'link_disk')
        can_open = bool(link and link.get('can_open_disk'))
        self.prep_connection_title.setText('Opening Disk Mode…' if opening else 'Disk Mode needed to prepare media')
        self.prep_connection_detail.setText(
            'Keep USB connected. Media Manager will read your libraries when the iPod reconnects.' if opening else
            'Your iPod is connected through Linnet Link. Preparation needs Disk Mode to read and write media. '
            'Choose Open Disk Mode and keep USB connected.' if can_open else
            'Your iPod is connected through Linnet Link, but Disk Mode is not available yet. '
            'Open iPod setup to review connection and setup options.' if link else
            'Connect your iPod in Disk Mode to read its libraries and prepare media. '
            'See iPod setup for connection steps.')
        self.prep_connection_button.setText('Opening Disk Mode…' if opening else 'Open Disk Mode' if can_open else
                                            'Open iPod setup' if link else 'View connection steps')
        self.prep_connection_button.setEnabled(not self.busy)

    def connect_preparation(self):
        if self.busy:
            return
        if self.link_connection and self.link_connection.get('can_open_disk'):
            self.open_link_disk()
        else:
            self.navigate('iPod setup')

    def choose_apple_folders(self):
        if self.busy or not self.apple_info or not self.apple_info['supported']:
            return
        dialog = QDialog(self); dialog.setWindowTitle('Choose folders for Apple OS')
        dialog.resize(620, 640)
        layout = box(dialog, margins=(24, 24, 24, 24), spacing=12)
        layout.addWidget(label('Available in Apple OS', 'section'))
        selectable = self.apple_info['selectable_roots']
        names = [{'Music': 'music', 'Photos': 'photo', 'Videos': 'video'}[kind] for kind in selectable]
        kinds = names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]
        description = (f'Select {kinds} folders on this iPod, outside the Apple-managed library. '
                       'Update the Apple library to use their media in Apple OS too. Files stay in their original locations.')
        layout.addWidget(label(description, 'muted', True))
        layout.addWidget(label('Selecting a folder includes its subfolders. Choose individual subfolders for a narrower selection.', 'muted', True))
        tree = QTreeWidget(); tree.setObjectName('appleFolders')
        tree.setHeaderLabels(['FOLDER', 'APPLE OS'])
        tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        items = {}
        selected = self.apple_info['selected']
        for row in self.apple_info['folders']:
            path, kind = row['path'], row['kind']
            parent_path = path.rpartition('/')[0]
            parent = items.get(parent_path)
            item = QTreeWidgetItem(parent or tree, [path.rpartition('/')[2], ''])
            item.setData(0, Qt.UserRole, path)
            items[path] = item
            if kind in selectable:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                checked = any(path.casefold() == name.casefold() or
                              path.casefold().startswith(name.casefold() + '/') for name in selected)
                item.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                item.setText(1, 'Choose for Apple OS')
            else:
                item.setText(1, 'Visible in Apple Notes')
                item.setToolTip(1, 'Apple reads compatible text files in the Notes folder automatically.')
        for path, item in reversed(list(items.items())):
            if path.split('/')[0] not in selectable or not item.childCount():
                continue
            states = {item.child(index).checkState(0) for index in range(item.childCount())}
            # Child choices never imply selecting the parent: it may contain
            # direct media files or acquire additional subfolders later.
            if item.checkState(0) != Qt.Checked:
                item.setCheckState(0, Qt.PartiallyChecked if states != {Qt.Unchecked} else Qt.Unchecked)
        def inherited_choices():
            for path, item in items.items():
                if path.split('/')[0] not in selectable:
                    continue
                parent, ancestor = item.parent(), None
                while parent:
                    if parent.checkState(0) == Qt.Checked:
                        ancestor = parent
                    parent = parent.parent()
                if ancestor:
                    name = ancestor.data(0, Qt.UserRole)
                    item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                    item.setText(1, f'Included by {name}')
                    item.setToolTip(0, f'Clear {name} first to choose individual subfolders.')
                else:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setText(1, 'Choose for Apple OS')
                    item.setToolTip(0, 'Includes this folder and all its subfolders.')
        inherited_choices()
        tree.expandToDepth(0); layout.addWidget(tree, 1)
        def changed(item, column):
            if column != 0 or item.data(0, Qt.UserRole).split('/')[0] not in selectable:
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
                    if parent.checkState(0) != Qt.Checked or states != {Qt.Checked}:
                        parent.setCheckState(0, Qt.PartiallyChecked if states != {Qt.Unchecked} else Qt.Unchecked)
                    parent = parent.parent()
                inherited_choices()
        tree.itemChanged.connect(changed)
        actions = box(horizontal=True)
        actions.addStretch(); actions.addWidget(button('Cancel', dialog.reject, 'quiet'))
        actions.addWidget(button('Save folders', dialog.accept, 'primary'))
        layout.addLayout(actions)
        if dialog.exec() != QDialog.Accepted:
            return
        folders = [path for path, item in items.items()
                   if path.split('/')[0] in selectable and item.checkState(0) == Qt.Checked and
                   (not path.rpartition('/')[0] or
                    items[path.rpartition('/')[0]].checkState(0) != Qt.Checked)]
        identity = self.identity
        self.work('apple_selection', lambda: apple_os.save_selection(identity, folders),
                  'Saving Apple OS folder choices…')

    def update_apple_os(self):
        if self.busy or not self.identity or not self.apple_info or not self.apple_info.get('can_update'):
            return
        identity = self.identity
        ffprobe = self.verified_ffprobe
        self.work('apple_update', lambda: apple_os.update(identity, ffprobe=ffprobe,
                                                          progress=self.events.progress.emit,
                                                          cancelled=self.stop_event.is_set),
                  'Updating the Apple library…')

    def queue_existing_audio(self):
        if self.busy or not self.identity:
            return
        music_roots = (Path(self.identity['root']) / 'Music',
                       Path(self.identity['root']) / 'iPod_Control' / 'Music')
        additions = []
        for row in self.rows:
            if (row['kind'] != 'Music' or row['category'] != 'original' or
                    not str(row['status']).startswith('Needs conversion:')):
                continue
            path = Path(row['path'])
            key = ('Music', os.path.normcase(str(path)))
            if any(path.is_relative_to(root) for root in music_roots) and key not in self.pending_keys:
                additions.append(('Music', str(path)))
                self.pending_keys.add(key)
        self.pending.extend(additions)
        self.convert_audio.setChecked(True)
        self.prep_checks['Music'].setChecked(True)
        self.validate_draft()
        self.save_draft()
        self.update_preparation()
        self.navigate('Preparation')
        self.show_progress(f'{len(additions):,} incompatible iPod tracks queued for host conversion.')

    def queue_selected_pcm(self):
        if self.busy or not self.identity:
            return
        music_roots = (Path(self.identity['root']) / 'Music',
                       Path(self.identity['root']) / 'iPod_Control' / 'Music')
        rows = self.selected()
        if not rows or any(row['kind'] != 'Music' or row['category'] != 'original' or
                           row['path'].casefold().endswith('.linnet.wav') or
                           not any(Path(row['path']).is_relative_to(root) for root in music_roots)
                           for row in rows):
            return
        additions = [('Music', row['path']) for row in rows
                     if ('Music', os.path.normcase(row['path'])) not in self.pending_keys]
        self.pending.extend(additions)
        self.pending_keys.update((kind, os.path.normcase(path)) for kind, path in additions)
        self.convert_audio.setChecked(True)
        self.prep_checks['Music'].setChecked(True)
        self.validate_draft()
        self.save_draft()
        self.update_preparation()
        self.navigate('Preparation')
        self.show_progress(f'{len(additions):,} iPod tracks queued for PCM preparation on the computer.')

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
        if self.busy or not self.device_connected or not self.inventory:
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
        ffmpeg, ffprobe = self.verified_ffmpeg, self.verified_ffprobe
        convert_audio = self.convert_audio.isChecked()
        approval = {'actions': None}
        def run():
            return media.run(identity, selected, pending, photo_dimension=dimension, force=force,
                music_verification=verification, ffmpeg=ffmpeg, ffprobe=ffprobe, video_selection=videos,
                convert_audio=convert_audio,
                online_artwork=online_artwork, approved_reconciliation=approval['actions'],
                progress=self.events.progress.emit, progress_detail=self.events.conversion.emit,
                progress_stage=self.events.stage.emit,
                cancelled=self.stop_event.is_set)
        self.plan_context = dict(identity=identity, pending=pending,
                                 submitted_videos=set(videos or ()) if 'Videos' in selected else set(),
                                 approval=approval, run=run)
        def inspect_plan():
            result = media_status.plan(identity, all_pending, selected, videos,
                current_inventory=self.inventory, photo_dimension=dimension,
                music_verification=verification, force=force, online_artwork=online_artwork,
                ffprobe=ffprobe, ffmpeg=ffmpeg, convert_audio=convert_audio,
                cancelled=self.stop_event.is_set)
            if result['conversion'] and (not ffmpeg or not ffprobe):
                raise ValueError('Video conversion needs FFmpeg and FFprobe. Choose their folder in Settings.')
            return result
        self.work('plan', inspect_plan, 'Checking the preparation plan…')

    def remove_selected(self):
        rows = self.selected()
        if self.busy or not self.identity or not self.device_connected or not rows:
            return
        if any(not row.get('removable', True) for row in rows):
            self.show_error('This item cannot be removed. Review its details for recovery guidance.')
            return
        identity = self.identity
        if all(row.get('retail_photo') for row in rows):
            def exclude_photos():
                media.skip_files(identity, [('Photos', row['path']) for row in rows])
                return dict(summary='Photos excluded. Run Prepare to update Linnet; Apple originals are retained.')
            self.work('skipped', exclude_photos, 'Excluding selected photos from preparation…')
            return
        if self.page == 'Trash':
            self.erase_trash(rows)
            return
        if not self.confirm_trash(rows):
            return
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        ffmpeg, ffprobe = self.verified_ffmpeg, self.verified_ffprobe
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
        if self.busy or not self.device_connected or self.page != 'Trash' or not rows:
            return
        identity = self.identity
        dimension = 2048 if self.photo_detail.currentIndex() else 640
        ffmpeg, ffprobe = self.verified_ffmpeg, self.verified_ffprobe
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

    def review_uninstall_trash(self):
        if self.busy or not self.identity or not self.device_connected or not self.review or self.review['uninstall'].get('blocker') != 'trash':
            return
        identity = self.identity
        def inspect_trash():
            from tools.content.guard import guarded_path
            current = media.refresh(identity)
            rows = media_trash.removals(current)
            trash = Path(current['root']) / '.LINNET' / 'TRASH'
            guarded_path(trash, Path(current['root']))
            known = {row['id'] for row in rows}
            unrecognized = sum(entry.name not in known for entry in trash.iterdir()) if trash.is_dir() else 0
            return dict(rows=rows, unrecognized=unrecognized, review=installer.assess(current))
        self.work('uninstall_trash', inspect_trash, 'Reading Trash before removal…')

    def erase_trash(self, rows):
        if self.busy or not self.identity or not self.device_connected or not rows:
            return
        identity = self.identity
        message = (f'Permanently delete the selected items from Trash and free {size(sum(r["bytes"] for r in rows))}? '
                   'These files cannot be restored afterward.')
        if not self.dialog('Delete permanently?', message, 'Delete permanently', danger=True):
            return
        def erase():
            for row in rows:
                media_trash.recover(identity, row['id'], erase=True)
            return dict(summary='Trash deleted. Storage is now available.')
        self.work('erase', erase, 'Emptying iPod Trash…')

    def sync_videos(self):
        if self.identity and self.device_connected and not self.busy:
            identity = self.identity
            self.work('sync', lambda: media_library.organize_videos(identity), 'Syncing the video folder…')

    def render_setup(self):
        review = self.review
        identity = review['identity']
        self.setup_device.setText((identity.get('volume_label') or 'iPod') + ' · ' +
                                  identity['target_name'].replace('Linnet for ', ''))
        self.setup_software.setText('Connected in Disk Mode · ' + identity['drive'] + ' · …' + identity['disk_serial'][-6:])
        self.setup_software.setToolTip(installer.build_description(review['linnet']))
        native = review['identity'].get('native_target_id') == review['identity']['target_id']
        available_boot = [option for option in review['boot_options'] if option['kind'] == 'linnet']
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
            self.boot_choice.setPlaceholderText('Installation is unavailable')
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
        summary = review['summary']
        if (review['action'] == 'unsupported' and review['target']['boot_layout'] == 's5l-nor' and
                review['linnet']['state'] == 'absent'):
            if (review.get('recovery') or {}).get('strategy') == 'native-nor' and review['recovery'].get('phase') == 'installed':
                summary = ('Linnet Boot is already installed. Start Linnet Boot, enter Linnet Disk Mode, '
                           'then reconnect and refresh to install Linnet OS. Another Boot installation is not needed.')
        elif review['action'] == 'install' and review['linnet']['state'] == 'absent' and review['strategy']!='classic-bootstrap':
            summary = 'Ready to install Linnet. Choose firmware and a build below, then install and eject safely.'
        self.install_detail.setText(summary)
        self.install_detail.setVisible(review['action'] in ('unsupported', 'attention', 'resume', 'adopt', 'installed') or
            review['linnet']['state'] not in ('installed', 'absent'))
        self.uninstall_detail.setText('Remove Linnet’s software and settings. Your media folders are kept.'
            if review['uninstall'].get('blocker') == 'trash' else review['uninstall']['detail'] +
            (' Your media folders are kept.' if review['uninstall']['available'] else ''))
        try:
            startup = startup_default.inspect(review)
        except OSError:
            # The volume can disappear between a completed scan and opening
            # this page, including during Classic's automatic mode changes.
            self.transition_device(None)
            self.update_controls()
            self.show_progress('The iPod disconnected. Reconnect it and choose Find iPod.')
            return
        self.startup_state = startup
        labels = {'linnet': 'Linnet', 'rockbox': 'Rockbox', 'apple': 'Apple iPod software'}
        self.default_detail.setText('Hold Menu during startup to choose a system for that start.')
        with QSignalBlocker(self.default_choice):
            self.default_choice.clear()
            for choice in startup['choices'] if startup['supported'] else []:
                self.default_choice.addItem(labels[choice], choice)
            self.default_choice.setCurrentIndex(self.default_choice.findData(startup['default']))
        self.boot_upgrade_available = native and boot_upgrade.available(review)
        self.boot_upgrade_pending = bool(review['recovery'] and review['recovery'].get('phase') == 'boot-upgrade-pending')
        self.update_install_action()

    def update_install_action(self):
        option = self.boot_choice.currentData(); method = self.method_choice.currentData()
        review = self.review
        can_install = bool(review and any(item.get('selectable') and item['kind'] == 'linnet'
                                         for item in review['boot_options']) and
                           any(item.get('enabled') for item in review['installation_methods']))
        installed = bool(review and review['linnet']['state'] == 'installed')
        upgrade = bool(review and getattr(self, 'boot_upgrade_available', False))
        pending = bool(review and getattr(self, 'boot_upgrade_pending', False))
        self.install_panel.setVisible(installed or can_install or upgrade or pending)
        self.install_title.setText('Linnet' if installed else 'Resume installation' if review and review['action'] == 'resume' else 'Install Linnet')
        self.installed_build.setVisible(installed)
        profile = (review or {}).get('linnet', {}).get('profile')
        self.installed_build.setText(installer.BUILD_LABELS.get(profile, 'Linnet') + ' installed' if installed else '')
        self.installed_build.setToolTip(installer.build_description(review['linnet']) if installed else '')
        candidate = bool(installed and review['linnet'].get('candidate_pending'))
        next_build = installer.BUILD_LABELS.get((review or {}).get('linnet', {}).get('next_profile'), 'Linnet')
        self.build_summary.setText(next_build + ' ready to start. Eject safely to finish the update.' if candidate else
                                  'Includes diagnostics and Linnet Link.' if installed and profile in ('dev', 'trace') else
                                  'For everyday listening.' if installed else 'Your media stays on the iPod.')
        forced_editor = not installed or bool(review and review['action'] == 'resume') or pending
        show_editor = bool(can_install or upgrade or pending) and (self.build_editor_open or forced_editor)
        self.build_editor.setVisible(show_editor)
        self.build_summary.setVisible(not installed or candidate or not show_editor)
        self.build_editor_button.setVisible(installed and (can_install or upgrade) and not forced_editor)
        self.build_editor_button.setEnabled(not self.busy)
        self.build_editor_button.setText('Hide build options' if self.build_editor_open else 'Change build or reinstall…')
        self.uninstall_panel.setVisible(bool(review and (review['linnet']['state'] != 'absent' or
                                                        review['recovery'] or review['uninstall']['available'])))
        if review is None and not self.link_connection and not (self.busy and self.active_operation and self.active_operation.tag=='classic_install'):
            self.install_detail.hide()
        enabled = not self.busy and self.identity is not None and self.review is not None and bool(option and option.get('selectable'))
        linnet = option and option['kind'] == 'linnet'
        from_source = self.build_from_source.isChecked()
        resume = bool(self.review and self.review.get('action') == 'resume')
        self.build_from_source.setEnabled(not self.busy and not resume)
        self.firmware_button.setEnabled(not self.busy and not resume)
        self.firmware_picker.setVisible(not from_source)
        self.firmware_label.setText(Path(self.firmware_path).name if self.firmware_path else 'Choose a matching firmware ZIP.')
        self.firmware_label.setToolTip(self.firmware_path)
        self.boot_detail.setText(option.get('detail', '') if option and not option.get('selectable') else
                                 'For everyday use, without diagnostics or Linnet Link.' if option and option.get('build') == 'user' else
                                 'Includes diagnostics and Linnet Link.' if option and option.get('build') == 'dev' else
                                 option.get('detail', '') if option else '')
        show_methods = bool(linnet and option.get('selectable') and method)
        for widget in (self.method_title, self.method_choice):
            widget.setVisible(show_methods and self.method_choice.count() > 1)
        self.method_detail.setVisible(show_methods and self.method_choice.count() > 1)
        self.method_detail.setText(method.get('detail', '') if method and linnet else '')
        enabled = enabled and bool(method and method.get('enabled')) if linnet else enabled and not bool(option and option.get('active'))
        if linnet and not resume and not from_source:
            enabled = enabled and bool(self.firmware_path) and option['build'] == 'user'
            if option['build'] == 'dev':
                self.boot_detail.setText('Developer builds are available from a source checkout.' if getattr(sys, 'frozen', False) else
                    'Enable Build from source to compile diagnostics and Linnet Link for this iPod.')
        self.method_choice.setEnabled(bool(linnet and method) and not self.busy)
        self.boot_choice.setEnabled(not self.busy and self.review is not None and self.boot_choice.count() > 0)
        self.install_button.setEnabled(enabled)
        self.install_hint.setText('Keep USB connected while installation resumes.' if resume else
            'Your media and settings are kept. Eject safely when the update finishes.' if installed else
            'Keep USB connected until installation finishes.')
        self.uninstall_button.setEnabled(not self.busy and self.device_connected and bool(
            self.identity and self.review and (self.review['uninstall']['available'] or
                                              self.review['uninstall'].get('blocker') == 'trash')))
        show_default = bool(self.review and self.review['linnet']['state'] == 'installed')
        self.startup_panel.setVisible(show_default)
        for widget in (self.default_title, self.default_detail, self.default_choice, self.default_button,
                       self.boot_upgrade_button, self.boot_upgrade_detail):
            widget.setVisible(show_default)
        startup = getattr(self, 'startup_state', dict(supported=False, choices=[], default='linnet'))
        self.default_row.setVisible(show_default and startup['supported'])
        self.default_detail.setVisible(show_default and startup['supported'])
        self.default_choice.setVisible(show_default and startup['supported'])
        self.default_button.setVisible(show_default and startup['supported'])
        self.default_choice.setEnabled(not self.busy and startup['supported'])
        self.default_button.setEnabled(not self.busy and startup['supported'] and
                                       self.default_choice.currentData() != startup['default'])
        upgrade = getattr(self, 'boot_upgrade_available', False)
        pending = getattr(self, 'boot_upgrade_pending', False)
        self.boot_upgrade_button.setVisible(show_default and (upgrade or pending))
        self.boot_upgrade_button.setText('Resume startup selector update' if pending else 'Update startup selector')
        self.boot_upgrade_button.setEnabled(not self.busy and (pending or upgrade))
        self.boot_upgrade_detail.setVisible(show_default and not startup['supported'])
        self.boot_upgrade_detail.setText('Finish the interrupted startup update before changing the default.' if pending else
            'Update Boot to enable the Menu startup selector and default choices.' if upgrade else
            'This Boot version cannot save a default startup choice from Media Manager.')
        if option is None:
            self.install_button.setText('No startup change available')
        elif not option.get('selectable'):
            self.install_button.setText('Current startup software' if option.get('active') else
                                        'Choose on iPod at startup' if option.get('chooser_available') else
                                        'Startup change unavailable')
        else:
            self.install_button.setText('Resume installation' if resume else
                ('Reinstall ' if option.get('active') else 'Switch to ' if installed else 'Install ') +
                ('Developer build' if option.get('build') == 'dev' else 'User build') if linnet else 'Set as default boot')

    def toggle_setup_editor(self):
        if self.busy:
            return
        self.build_editor_open = not self.build_editor_open
        self.update_install_action()
        if self.build_editor_open:
            self.reveal_setup_editor(self.boot_choice)

    def reveal_setup_editor(self, widget):
        review = self.review
        def reveal():
            if not self.closed and self.page == 'iPod setup' and self.review is review and self.build_editor.isVisible():
                self.setup.ensureWidgetVisible(widget)
        QTimer.singleShot(0, reveal)

    def install_selected(self):
        if not self.device_connected or not self.install_button.isEnabled():
            return
        option, method, identity = self.boot_choice.currentData(), self.method_choice.currentData(), self.identity
        description = (f"Install or update {option['label']}?" + f"\n\nMethod: {method['label']}"
                       if option['kind'] == 'linnet' else
                       f"Make {option['label']} the default startup software?")
        if option['kind'] == 'linnet' and self.review.get('action') in ('replace', 'adopt'):
            description += ('\n\nYour settings, selected theme, playback history, and media libraries '
                            'will be preserved. ' + ('The confirmed OS will be retained for rollback.'
                            if method['strategy'] == 'native-volume' else
                            'Superseded Linnet system files will be archived.'))
        if not self.dialog('Update iPod setup', description + '\n\nKeep the iPod connected until the update finishes.', 'Apply to iPod'):
            return
        from_source = self.build_from_source.isChecked()
        firmware = None if from_source or not self.firmware_path else Path(self.firmware_path)
        if option['kind'] == 'linnet' and self.review.get('action') == 'resume':
            from_source, firmware = option['build'] == 'dev', None
        operation = (lambda: installer.install(identity, progress=self.events.progress.emit,
            build=option['build'], installation_method=method['id'], firmware=firmware,
            from_source=from_source,instruction=self.events.setup_instruction.emit,
            cancelled=self.stop_event.is_set)) if option['kind'] == 'linnet' else lambda: installer.restore(identity, expected=option['id'])
        self.work('classic_install' if method and method['strategy']=='classic-bootstrap' else 'install',
                  operation, 'Updating your iPod setup…')

    @Slot(object)
    def show_setup_instruction(self, event):
        if not self.busy or not self.active_operation or self.active_operation.tag not in ('classic_install', 'uninstall'):
            return
        removing = self.active_operation.tag == 'uninstall'
        if event.get('action') in ('hold','release','apple-disk'):
            if self.setup_instruction_dialog is None:
                dialog = SetupInstructionDialog(self)
                dialog.setWindowTitle('Finish removing Linnet' if removing else 'Connect your Classic for installation')
                dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
                dialog.setWindowModality(Qt.WindowModal)
                dialog.setMinimumWidth(480)
                dialog.setMaximumWidth(600)
                layout = box(dialog, margins=(28,28,28,28))
                dialog.heading = label('', 'section', True)
                dialog.message = label('', None, True)
                layout.addWidget(dialog.heading); layout.addWidget(dialog.message)
                layout.addWidget(label('Media Manager detects this automatically. Keep USB connected.', None, True))
                spinner = QProgressBar(); spinner.setRange(0,0); spinner.setTextVisible(False)
                layout.addWidget(spinner)
                dialog.stop_button = button('Stop installation', self.stop)
                layout.addWidget(dialog.stop_button)
                self.setup_instruction_dialog = dialog
            dialog = self.setup_instruction_dialog
            dialog.heading.setText('Connect Apple Disk Mode' if event['action']=='apple-disk' else
                                   'Release Menu + Select now' if event['action']=='release' else
                                   'Hold Menu + Select')
            dialog.message.setText(event['message'])
            dialog.stop_button.setVisible(bool(event['can_stop']))
            dialog.stop_button.setEnabled(bool(event['can_stop']) and not self.stop_event.is_set())
            dialog.show(); dialog.raise_()
            if not removing:
                self.install_detail.hide()
        else:
            self.close_setup_instruction()
            if not removing:
                self.install_detail.setText(event['message']); self.install_detail.show()
        if not removing:
            self.setup_progress.show()
        self.cancel_button.setVisible(bool(event['can_stop']))
        self.cancel_button.setEnabled(bool(event['can_stop']) and not self.stop_event.is_set())
        self.show_progress(event['message'])

    def close_setup_instruction(self):
        if self.setup_instruction_dialog is not None:
            self.setup_instruction_dialog.done(QDialog.Accepted)
            self.setup_instruction_dialog.deleteLater()
            self.setup_instruction_dialog = None

    def resume_classic_setup(self):
        if self.busy:return
        from tools.studio.classic_setup import pending, run
        scope = dict(target_id=self.link_connection['identity']['target_id'],
                     linnet_usb_serial=self.link_connection['serial']) if self.link_connection else self.identity
        choices=pending(scope)
        if not choices:return
        selected=choices[0]
        if len(choices)>1:
            dialog=QDialog(self); dialog.setWindowTitle('Resume Classic installation')
            layout=box(dialog,margins=(24,24,24,24))
            layout.addWidget(label('Choose the Classic installation to resume.',None,True))
            picker=ComboBox()
            for item in choices:picker.addItem('Classic · '+item['serial'][-6:]+' · '+item['phase'],item)
            layout.addWidget(picker); layout.addWidget(button('Resume installation',dialog.accept,'primary'))
            if dialog.exec()!=QDialog.Accepted:return
            selected=picker.currentData()
        self.work('classic_install',lambda:run(selected['path'],progress=self.events.progress.emit,
            instruction=self.events.setup_instruction.emit,cancelled=self.stop_event.is_set),
            'Resuming Classic installation…')

    def open_link_disk(self):
        if self.busy or not self.link_connection:return
        from tools.studio.media_link import open_disk
        connection = self.link_connection
        self.work('link_disk',lambda:open_disk(connection,progress=self.events.progress.emit),
                  'Opening Disk Mode automatically…')

    def open_link_setup(self, section):
        if self.busy or not self.link_connection or not self.link_connection.get('can_open_disk'):
            return
        from tools.studio.media_link import open_setup
        connection = self.link_connection
        self.work('link_setup', lambda: open_setup(connection, section=section, progress=self.events.progress.emit),
                  'Connecting your iPod’s setup settings…')

    def save_default_startup(self):
        if not self.default_button.isEnabled():
            return
        identity, choice = self.identity, self.default_choice.currentData()
        self.work('startup_default', lambda: startup_default.set_default(identity, choice),
                  'Saving default startup…')

    def upgrade_startup_selector(self):
        if not self.boot_upgrade_button.isEnabled():
            return
        identity = self.identity
        pending = self.boot_upgrade_pending
        option = self.boot_choice.currentData()
        build = (option or {}).get('build', self.review['linnet'].get('build', 'dev'))
        from_source = self.build_from_source.isChecked()
        firmware = None if from_source or not self.firmware_path else Path(self.firmware_path)
        if not pending and not (from_source or firmware and build == 'user'):
            self.build_editor_open = True
            self.update_install_action()
            self.reveal_setup_editor(self.build_from_source if not getattr(sys, 'frozen', False) else self.firmware_button)
            self.show_progress('Choose firmware below, then choose Update startup selector again.')
            return
        if not pending and not self.dialog('Update startup selector',
                f'Update startup firmware on {self.device_title(identity)}? Linnet and the saved Apple software will remain available.\n\nKeep the iPod connected until the update finishes.',
                'Update startup selector'):
            return
        self.work('boot_upgrade', lambda: boot_upgrade.upgrade(identity, build=build,
                  firmware=firmware, from_source=from_source, progress=self.events.progress.emit),
                  'Updating startup selector…')

    def uninstall_selected(self):
        if not self.uninstall_button.isEnabled():
            return
        if self.review['uninstall'].get('blocker') == 'trash':
            self.review_uninstall_trash()
        else:
            self.confirm_uninstall()

    def confirm_uninstall(self, trash_rows=()):
        identity = self.identity
        previous = self.review['uninstall']['previous']
        startup = 'rockbox' if previous == 'Rockbox' else 'apple'
        message = (f"Restore {previous} as the default startup software and remove Linnet OS from "
                   f"{self.device_title(identity)}?\n\n"
                   "Linnet settings, prepared libraries, and system files in .LINNET will be deleted. "
                   "Your Music, Photos, Videos, and Notes folders will remain. "
                   "Apple OS may need a library sync to show media that was prepared only for Linnet.\n\n"
                   "Keep the iPod connected until removal finishes, then eject it safely.")
        if trash_rows:
            message = ('Trash isn’t empty. Continuing will permanently empty Trash '
                       f'({size(sum(row["bytes"] for row in trash_rows))}). These files cannot be restored afterward.\n\n' + message)
        if not self.dialog('Remove Linnet OS?', message,
                           'Empty Trash and remove Linnet' if trash_rows else 'Restore and remove Linnet',
                           danger=True, secondary=('Review Trash', lambda: self.navigate('Trash')) if trash_rows else None):
            return
        def remove():
            for row in trash_rows:
                media_trash.recover(identity, row['id'], erase=True)
            return installer.uninstall(identity, progress=self.events.progress.emit,
                                       expected=startup, instruction=self.events.setup_instruction.emit)
        self.work('uninstall', remove, 'Removing Linnet OS…')

    def install_apple_font(self):
        if not self.apple_font_install.isEnabled():
            return
        identity = dict(self.identity)
        self.work('apple_font_install', lambda: apple_font.install(identity,
            progress=self.events.progress.emit, cancelled=self.stop_event.is_set), 'Preparing Apple Podium Sans…')

    def remove_apple_font(self):
        if not self.apple_font_remove.isEnabled():
            return
        identity = dict(self.identity)
        self.work('apple_font_remove', lambda: apple_font.remove(identity), 'Selecting the included theme font…')

    def _complete_apple_font(self, result):
        self.apple_font_result = result['summary']
        self.apple_font_status.setText(result['summary'])
        self.show_progress(result['summary'])

    def choose_firmware(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose Linnet firmware', self.firmware_path,
                                            'Linnet firmware (*.zip)')
        if path:
            self.firmware_path = path
            self.settings.setValue('firmware_bundle', path)
            self.build_from_source.setChecked(False)
            self.update_install_action()

    def firmware_source_changed(self, enabled):
        self.settings.setValue('build_from_source', enabled)
        self.update_install_action()

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
            validated = {}
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
                    validated[name] = str(path)
                except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                    errors.append(f'{name} at {value} could not run: {error}')
            self.events.tools_checked.emit(request, dict(candidate=candidate, validated=validated, errors=errors))
        self.tool_pool.submit(check)

    @Slot(int, object)
    def tools_checked(self, request, result):
        if self.closed or request != self.tool_check_id:
            return
        validated = result['validated']
        if result['candidate'] is not None:
            for name, setting in (('FFmpeg', 'ffmpeg'), ('FFprobe', 'ffprobe')):
                if name in validated:
                    setattr(self, setting, validated[name])
                    setattr(self, 'verified_' + setting, validated[name])
                    self.settings.setValue(setting, validated[name])
            if validated:
                if len(validated) != 2:
                    self.update_tools()
                    return
        else:
            self.verified_ffmpeg = validated.get('FFmpeg')
            self.verified_ffprobe = validated.get('FFprobe')
        if result['errors']:
            self.record_diagnostic('tools', 'ToolCheckError', '; '.join(result['errors']), 'failed')
            available = (('FFprobe is ready. ' if self.verified_ffprobe else '') +
                         ('FFmpeg is ready. ' if self.verified_ffmpeg else ''))
            self.tools_label.setText(available + ' '.join(result['errors']) +
                ' Choose a folder containing the missing tool.')
            return
        self.tools_label.setText('FFmpeg and FFprobe are ready.')

    def show_preparation_details(self):
        if not self.identity or self.last_preparation is None:
            return
        identity, report = self.last_preparation
        if not self.same_device(self.identity, identity):
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
        if self.busy or not self.identity or not self.device_connected:
            return
        identity = self.identity
        self.work('review_skipped', lambda: (identity, media.list_skipped_files(identity)), 'Loading skipped files…')

    def show_skipped_dialog(self, identity, rows):
        dialog = QDialog(self); dialog.setWindowTitle('Skipped files'); dialog.resize(680, 400)
        layout = box(dialog, margins=(24, 24, 24, 24)); layout.addWidget(label('Skipped during preparation', 'section'))
        table = QTableView(); model = MediaModel(table); model.reset([dict(title=row['relative'], kind=row['kind']) for row in rows], [('title', 'FILE'), ('kind', 'TYPE')]); table.setModel(model)
        table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection); table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); layout.addWidget(table)
        def restore():
            if not self.same_device(self.identity, identity):
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
        if not self.identity or not self.device_connected or self.busy:
            return
        self.save_choices_draft()
        identity = self.identity
        def run():
            return media.eject_device(identity)
        self.work('eject', run, 'Safely ejecting your iPod…')

    def capture_screenshot(self):
        from tools.studio.media_capture import available, capture
        if self.busy or not available(self.link_connection):return
        connection = dict(self.link_connection, identity=dict(self.link_connection['identity']))
        self.work('screenshot', lambda: capture(connection), 'Taking an iPod screenshot…')

    def _complete_screenshot(self, result):
        if result['connection'] != self.link_connection:
            self.show_error('The selected iPod changed. Refresh before taking another screenshot.')
            return
        try:
            dialog = ScreenshotDialog(result, self)
        except ValueError as error:
            self.show_error(str(error)); return
        self.show_progress('Screenshot ready. Copy it or save a PNG.')
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def device_details(self):
        if self.busy:
            return
        if self.link_connection:
            from tools.studio.media_link import read_details
            connection = dict(self.link_connection, identity=dict(self.link_connection['identity']))
            self.work('device_details', lambda: read_details(connection), 'Reading iPod details…')
            return
        if not self.identity or not self.device_connected:
            return
        from tools.content import about
        identity = self.identity
        self.work('device_details', lambda: about.read_details(identity, media.refresh),
                  'Reading iPod details…')

    def stop(self):
        context = self.active_operation
        if context and context.cancel_event:
            context.cancel_event.set()
            if self.setup_instruction_dialog is not None:
                self.setup_instruction_dialog.stop_button.setEnabled(False)
            self.cancel_button.setEnabled(False)
            self.show_progress('Stopping iPod reading…' if context.tag in ('scan', 'devices') else
                               'Stopping preparation checks…' if context.tag == 'plan' else
                               'Finishing the current step before stopping…')

    def record_diagnostic(self, operation, error_type, message, status='failed', cancel_requested=False):
        """Keep bounded support context without source paths or device identifiers."""
        cleaned = str(message)
        cleaned = re.sub(r'(?i)\b[\w.+-]+@[\w.-]+\.[A-Z]{2,}\b', '[email]', cleaned)
        cleaned = re.sub(r'(?i)https?://[^\r\n]+', '[url]', cleaned)
        cleaned = re.sub(r'(?i)\b[A-Z]:[\\/][^\r\n]+', '[path]', cleaned)
        cleaned = re.sub(r'\\\\[^\r\n]+', '[path]', cleaned)
        cleaned = re.sub(r'/(?:Users|home)/[^\r\n]+', '[path]', cleaned)
        cleaned = re.sub(r'(?<!\w)(?:\.{1,2}[\\/])?[\w .-]+[\\/][^\r\n]+', '[path]', cleaned)
        cleaned = re.sub(r'(?i)\b[\w][\w .-]*\.[A-Z0-9]{1,6}\b', '[file]', cleaned)
        identifiers = set(self._recent_private_identifiers)
        if self.identity:
            identifiers.update(str(self.identity.get(field)) for field in
                ('root', 'drive', 'disk_serial', 'volume_serial', 'volume_unique_id') if self.identity.get(field))
        for value in sorted(identifiers, key=len, reverse=True):
            cleaned = re.sub(re.escape(value), '[redacted]', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\b[0-9A-F]{16,}\b', '[identifier]', cleaned, flags=re.IGNORECASE)
        entry = dict(time=datetime.now().astimezone().isoformat(timespec='seconds'),
                     operation=str(operation)[:40], type=str(error_type)[:60],
                     status=status, cancel_requested=bool(cancel_requested),
                     target=(self.identity or {}).get('target_id', ''), message=cleaned[:500])
        try:
            history = json.loads(self.settings.value('diagnostics/history/v1', '[]'))
            if not isinstance(history, list):
                history = []
        except (TypeError, ValueError):
            history = []
        history.append(entry)
        self.settings.setValue('diagnostics/history/v1', json.dumps(history[-50:]))
        self.settings.sync()

    def collect_hardware_report(self):
        if self.busy:return
        self.work('hardware_report', lambda: media_reader.read('support', identity=self.identity,
            cancelled=self.stop_event.is_set), 'Collecting hardware report…')

    def _complete_hardware_report(self, report):
        from tools.studio.device_support import sharing, contact_link
        contact=sharing()
        self.hardware_report = report
        dialog = QDialog(self); dialog.setWindowTitle('Hardware support report'); dialog.resize(700, 500)
        layout = box(dialog, margins=(20,20,20,20))
        layout.addWidget(label(report['summary'], 'section', True))
        layout.addWidget(label(report['privacy'], 'muted', True))
        layout.addWidget(label(contact['instructions'], 'muted', True))
        details = QTextEdit(); details.setReadOnly(True)
        details.setPlainText(json.dumps(report, indent=2)); layout.addWidget(details)
        def save():
            path, _ = QFileDialog.getSaveFileName(dialog, 'Save hardware report', 'linnet-hardware-report.json', 'JSON files (*.json)')
            if path:
                try:
                    Path(path).write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
                    self.show_progress('Report saved. Attach it to your support request.')
                except OSError as error:self.show_error(f'Could not save hardware report: {error}')
        actions=box(horizontal=True);actions.addWidget(button('Save report…',save,'primary'))
        actions.addWidget(button('Copy report',lambda: QApplication.clipboard().setText(json.dumps(report,indent=2))))
        if contact_link():
            actions.addWidget(button('Contact Linnet support',lambda: QDesktopServices.openUrl(QUrl(contact_link()))))
        actions.addStretch();actions.addWidget(button('Close',dialog.reject));layout.addLayout(actions)
        dialog.exec()

    def show_diagnostics(self):
        try:
            entries = json.loads(self.settings.value('diagnostics/history/v1', '[]'))
            if not isinstance(entries, list):
                entries = []
        except (TypeError, ValueError):
            entries = []
        dialog = QDialog(self); dialog.setWindowTitle('Diagnostics'); dialog.resize(700, 440)
        layout = box(dialog, margins=(20, 20, 20, 20))
        layout.addWidget(label('Recent operation errors', 'section'))
        layout.addWidget(label('The last 50 errors are saved on this computer. Device serials, paths, and email addresses are removed from this history.', 'muted', True))
        details = QTextEdit(); details.setReadOnly(True)
        details.setAccessibleName('Recent diagnostic events')
        details.setPlainText('\n\n'.join(f"{e.get('time', '')} · {e.get('operation', '')} · {e.get('type', '')}\n{e.get('message', '')}"
                                         for e in entries) if entries else 'No errors recorded in this session history.')
        layout.addWidget(details)
        actions = box(horizontal=True)
        def export():
            path, _ = QFileDialog.getSaveFileName(dialog, 'Export diagnostics', 'linnet-diagnostics.json', 'JSON files (*.json)')
            if path:
                try:
                    Path(path).write_text(json.dumps(dict(version=1, errors=entries), indent=2) + '\n', encoding='utf-8')
                except OSError as error:
                    self.show_error(f'Could not export diagnostics: {error}')
        actions.addWidget(button('Export support file', export)); actions.addStretch()
        actions.addWidget(button('Hardware report…', lambda: (dialog.accept(), self.collect_hardware_report())))
        actions.addWidget(button('Close', dialog.accept, 'primary'))
        layout.addLayout(actions); dialog.exec()

    def show_help(self):
        self.dialog('About Linnet Media Manager',
                    f'Linnet system version: {linnet_version()}\n\n'
                    'Linnet Media Manager helps prepare music, photos, videos, and notes for supported iPods.\n\n'
                    'Connect your iPod in Disk Mode, choose Refresh or Choose iPod, and use Preparation to review changes. '
                    'Use Eject safely when finished.\n\n'
                    'For video conversion, install FFmpeg and FFprobe on this computer, then choose their folder in Settings. '
                    'Diagnostics in the footer shows recent errors and exports a privacy-filtered support file.',
                    'Close', cancel=False)

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
        self.save_choices_draft()
        self.closed = True
        self.covers.closed = True
        self.covers.pool.shutdown(wait=False, cancel_futures=True)
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.tool_pool.shutdown(wait=False, cancel_futures=True)
        event.accept()


def launch():
    configure_taskbar()
    # Qt still decodes photos with malformed ICC metadata; avoid repeating
    # profile diagnostics as their previews enter and leave the artwork cache.
    QLoggingCategory.setFilterRules('qt.gui.icc.warning=false')
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    app.setStyle('Fusion'); app.setFont(QFont(UI_FONT, 10))
    window = MediaWindow(); window.show()
    app.exec()
