"""Linnet's native media library and device workspace."""
from concurrent.futures import ThreadPoolExecutor
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QObject, QRectF, QSize, QPointF,
                           Qt, QTimer, Signal, Slot, QSettings, QBuffer, QIODevice, QLoggingCategory, QSignalBlocker)
from PySide6.QtGui import (QColor, QFont, QIcon, QImage, QImageReader, QKeySequence, QPalette,
                          QLinearGradient, QPainter, QPainterPath, QPixmap, QShortcut, QPen)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
    QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QProgressBar, QPushButton, QScrollArea,
    QStackedWidget, QStyledItemDelegate, QStyle,
    QTableView, QTextEdit, QVBoxLayout, QWidget, QStyleOptionButton, QSizePolicy)

from tools.content import media_manager as media, media_library, media_status, media_trash
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


def boot_artwork(rect, width, height):
    artwork = QPixmap(str(Path(__file__).resolve().parents[2] / 'assets' / 'boot-screen.png'))
    image = artwork.copy(*rect).scaled(width * 2, height * 2, Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation).toImage().convertToFormat(QImage.Format_ARGB32)
    # The boot artwork has a near-black matte. Render it as transparency while
    # preserving the silver and cyan lettering and antialiased edges.
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            peak = max(color.red(), color.green(), color.blue())
            alpha = max(0, (peak - 24) * 255 // 231)
            if alpha:
                color = QColor(*(min(255, channel * 255 // peak)
                                 for channel in (color.red(), color.green(), color.blue())), alpha)
            else:
                color = QColor(0, 0, 0, 0)
            image.setPixelColor(x, y, color)
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


class Events(QObject):
    done = Signal(str, object, str)
    progress = Signal(str)
    conversion = Signal(object)
    artwork = Signal(int, str, object)


class Covers(QObject):
    """Load only visible artwork; keep device IO off the GUI thread."""
    def __init__(self, parent):
        super().__init__(parent)
        self.cache, self.pending = OrderedDict(), set()
        self.generation = 0
        self.closed = False
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix='linnet-art')
        self.events = Events(self)
        self.events.artwork.connect(self.receive)
        self.views = []

    def get(self, path, source=None):
        if not path:
            return None
        if path in self.cache:
            self.cache.move_to_end(path)
            return self.cache[path]
        if path not in self.pending:
            self.pending.add(path)
            self.pool.submit(self.read, path, source, self.generation)
        return None

    def invalidate(self, paths=None):
        self.generation += 1
        self.pending.clear()
        if paths is None:
            self.cache.clear()
        else:
            for path in paths:
                self.cache.pop(path, None)

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
                    original = next((folder / name for name in COVER_NAMES if (folder / name).is_file()), None)
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

    @staticmethod
    def read_image(source):
        reader = QImageReader(source); reader.setAutoTransform(True)
        dimensions = reader.size()
        if dimensions.isValid() and dimensions.width() * dimensions.height() <= 32_000_000:
            reader.setScaledSize(dimensions.scaled(320, 320, Qt.KeepAspectRatio))
            return reader.read()
        return QImage()

    @Slot(int, str, object)
    def receive(self, generation, path, image):
        if generation != self.generation:
            return
        self.pending.discard(path)
        self.cache[path] = QPixmap.fromImage(image) if not image.isNull() else None
        self.cache.move_to_end(path)
        if len(self.cache) > 600:
            self.cache.popitem(last=False)
        for view in self.views:
            view.viewport().update()


def paint_cover(painter, rect, row, covers, rounded=9):
    painter.save()
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(rect), rounded, rounded)
    painter.setClipPath(clip)
    picture = covers.get(row.get('artwork', ''), row.get('cover_source') or row.get('path'))
    if picture:
        scaled = picture.scaled(rect.size().toSize(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.drawPixmap(rect.toRect(), scaled, scaled.rect().adjusted(
            max(0, (scaled.width() - int(rect.width())) // 2), max(0, (scaled.height() - int(rect.height())) // 2),
            -max(0, (scaled.width() - int(rect.width())) // 2), -max(0, (scaled.height() - int(rect.height())) // 2)))
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
        if generation == self.covers.generation and path == self.row.get('artwork'):
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


class MediaWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Linnet · Media Manager')
        self.resize(1280, 860)
        self.setMinimumSize(1050, 700)
        self.setWindowIcon(QIcon(boot_artwork((594, 180, 310, 445), 32, 32)))
        self.settings = QSettings('Linnet', 'MediaManager')
        self.identity, self.inventory, self.review = None, None, None
        self.rows, self.readiness, self.pending, self.trash_rows = [], {}, [], []
        self._library_source, self._library_cache = None, {}
        self.video_selection, self.stop_event = set(), threading.Event()
        self.page, self.view, self.group = 'Music', self.settings.value('music_view', 'Albums'), None
        if self.view not in ('Songs', 'Albums', 'Artists', 'Genres'):
            self.view = 'Albums'
        self.busy = False
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='linnet-media')
        self.events = Events(self)
        self.events.done.connect(self.completed)
        self.events.progress.connect(self.show_progress)
        self.events.conversion.connect(self.show_conversion_progress)
        self.covers = Covers(self)
        self.ffmpeg = self.settings.value('ffmpeg', shutil.which('ffmpeg') or '')
        self.ffprobe = self.settings.value('ffprobe', shutil.which('ffprobe') or '')
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
                            ('Preparation', 'prepare'), ('Screens', 'settings'), ('iPod setup', 'setup'), ('Trash', 'trash'), ('Settings', 'settings')]:
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
        self.library = self.build_library(); self.stack.addWidget(self.library)
        self.preparation = self.build_preparation(); self.stack.addWidget(self.preparation)
        self.setup = self.build_setup(); self.stack.addWidget(self.setup)
        self.screens = self.build_screens(); self.stack.addWidget(self.screens)
        self.preferences = self.build_settings(); self.stack.addWidget(self.preferences)
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

    def build_library(self):
        page = QWidget(); outer = box(page, margins=(30, 28, 26, 20), spacing=16)
        top = box(horizontal=True)
        titles = box(spacing=5); self.heading_label = label('Music', 'title', True); self.subtitle = label('', 'subtitle', True)
        titles.addWidget(self.heading_label); titles.addWidget(self.subtitle); top.addLayout(titles, 1)
        self.playlists_button = button('Playlists', self.open_playlists, None, 'music'); top.addWidget(self.playlists_button)
        self.add_button = button('Add media', self.add_media, 'primary', 'plus'); top.addWidget(self.add_button)
        outer.addLayout(top)
        toolbar = box(horizontal=True)
        self.segments = QFrame(); self.segments.setObjectName('segments'); segments = box(self.segments, horizontal=True, margins=(4, 4, 4, 4), spacing=2)
        self.view_buttons = {}
        for name in ('Songs', 'Albums', 'Artists', 'Genres'):
            item = button(name, lambda _=False, n=name: self.change_view(n), 'segment'); item.setCheckable(True)
            self.view_buttons[name] = item; segments.addWidget(item)
        toolbar.addWidget(self.segments)
        self.back_button = button('Back', self.back_to_groups, 'quiet', 'back'); toolbar.addWidget(self.back_button)
        outer.addLayout(toolbar)
        toolbar = box(horizontal=True)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search your collection'); self.search.setClearButtonEnabled(True); self.search.setMinimumWidth(220)
        self.search.addAction(icon('search'), QLineEdit.LeadingPosition)
        self.search.setAccessibleName('Search collection')
        self.search.setToolTip('Search this collection (Ctrl+F). All search words must match.')
        self.search_timer = QTimer(self); self.search_timer.setSingleShot(True); self.search_timer.setInterval(160); self.search_timer.timeout.connect(self.render_library)
        self.search.textChanged.connect(lambda: self.search_timer.start()); toolbar.addWidget(self.search)
        outer.addLayout(toolbar)
        filters = box(horizontal=True)
        self.genre_filter = ComboBox(); self.genre_filter.addItem('All genres', ''); self.genre_filter.currentIndexChanged.connect(self.render_library)
        self.artist_filter = ComboBox(); self.artist_filter.addItem('All artists', ''); self.artist_filter.currentIndexChanged.connect(self.render_library)
        self.genre_filter.setAccessibleName('Filter by genre')
        self.artist_filter.setAccessibleName('Filter by artist')
        filters.addWidget(self.genre_filter); filters.addWidget(self.artist_filter)
        self.clear_button = button('Clear filters', self.clear_filters, 'quiet'); filters.addWidget(self.clear_button)
        filters.addStretch(); self.result_count = label('', 'muted'); filters.addWidget(self.result_count)
        self.sync_button = button('Sync video folder', self.sync_videos, None, 'refresh'); filters.addWidget(self.sync_button)
        self.folder_button = button('Open iPod folder', self.open_media_folder, None, 'folder'); filters.addWidget(self.folder_button)
        outer.addLayout(filters)
        self.notice = label('', 'notice', True); self.notice.hide(); outer.addWidget(self.notice)
        self.model = MediaModel(self)
        self.table = QTableView(); self.table.setModel(self.model); self.table.setShowGrid(False); self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel); self.table.verticalHeader().hide(); self.table.verticalHeader().setDefaultSectionSize(57)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.setItemDelegate(TrackDelegate(self.covers, self.table)); self.table.setMouseTracking(True)
        self.grid = QListView(); self.grid.setModel(self.model); self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust); self.grid.setMovement(QListView.Static); self.grid.setUniformItemSizes(True)
        self.grid.setLayoutMode(QListView.Batched); self.grid.setBatchSize(50); self.grid.setSpacing(4)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection); self.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.setItemDelegate(CardDelegate(self.covers, self.grid)); self.grid.setMouseTracking(True)
        self.covers.views = [self.table, self.grid]
        self.views = QStackedWidget(); self.views.addWidget(self.table); self.views.addWidget(self.grid)
        self.empty = QWidget(); empty = box(self.empty, margins=(30, 60, 30, 60)); empty.addStretch()
        self.empty_title = label('Your collection starts here', 'section'); self.empty_title.setAlignment(Qt.AlignCenter)
        self.empty_detail = label('Connect an iPod in Disk Mode to browse its media.', 'muted', True); self.empty_detail.setAlignment(Qt.AlignCenter)
        empty.addWidget(self.empty_title); empty.addWidget(self.empty_detail)
        self.empty_action = button('Find iPod', self.activate_empty, 'primary')
        empty.addWidget(self.empty_action, 0, Qt.AlignHCenter)
        empty.addStretch(); self.views.addWidget(self.empty)
        outer.addWidget(self.views, 1)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.grid.selectionModel().selectionChanged.connect(self.selection_changed)
        self.grid.activated.connect(self.open_group)
        self.table.activated.connect(self.inspect_selection)
        self.selection_bar = QFrame(); self.selection_bar.setObjectName('selectionBar'); selection = box(self.selection_bar, horizontal=True, margins=(16, 9, 12, 9))
        self.selection_text = label(); selection.addWidget(self.selection_text, 1)
        selection.addWidget(button('Clear', self.clear_selection, 'quiet'))
        self.info_button = button('Details', self.inspect_selection); selection.addWidget(self.info_button)
        self.restore_button = button('Restore', self.restore_selected, None, 'back'); selection.addWidget(self.restore_button)
        self.remove_button = button('Move to Trash', self.remove_selected, 'danger', 'trash'); selection.addWidget(self.remove_button)
        outer.addWidget(self.selection_bar); self.selection_bar.hide()
        self.hint = label('Double-click an item for details. Ctrl+click or Shift+click to select multiple files.', 'muted', True); outer.addWidget(self.hint)
        return page

    def scroll_page(self):
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        content = QWidget(); content.setObjectName('pageContent')
        layout = box(content, margins=(34, 32, 34, 28), spacing=14)
        scroll.setWidget(content)
        return scroll, layout

    def build_preparation(self):
        page = QWidget(); page.setObjectName('workspace')
        outer = box(page, spacing=0)
        scroll, layout = self.scroll_page()
        scroll.setObjectName('preparationScroll')
        self.preparation_scroll = scroll
        outer.addWidget(scroll, 1)
        self.heading(layout, 'Prepare your media', 'Turn your files into an iPod-ready collection. Your originals stay on the device.')
        self.prep_checks, self.prep_labels = {}, {}
        descriptions = {'Music': 'Build the song library and album artwork', 'Photos': 'Create thumbnails and zoomable photos', 'Videos': 'Validate existing videos and prepare them for this iPod', 'Notes': 'Prepare text and Markdown for the reader'}
        for kind in ('Music', 'Photos', 'Videos', 'Notes'):
            card = QFrame(); card.setObjectName('card'); row = box(card, horizontal=True, margins=(20, 18, 20, 18), spacing=15)
            check = CheckBox(kind); check.setChecked(True); check.setMinimumWidth(110); self.prep_checks[kind] = check; row.addWidget(check)
            text = box(spacing=5); text.addWidget(label(descriptions[kind], 'cardTitle'))
            state = label('Connect an iPod to check this library.', 'muted'); self.prep_labels[kind] = state; text.addWidget(state); row.addLayout(text, 1)
            if kind == 'Videos':
                self.choose_videos_button = button('Choose videos', self.choose_videos); row.addWidget(self.choose_videos_button)
            layout.addWidget(card)
        self.online_artwork = CheckBox('Find missing iTunes album covers online (MusicBrainz / Cover Art Archive)')
        self.online_artwork.setChecked(self.settings.value('onlineArtwork', True, type=bool))
        self.online_artwork.toggled.connect(lambda enabled: self.settings.setValue('onlineArtwork', enabled))
        layout.addWidget(self.online_artwork)
        layout.addSpacing(10); layout.addWidget(label('Up next', 'section'))
        self.queue_model = MediaModel(self)
        self.queue_table = QTableView(); self.queue_table.setModel(self.queue_model); self.queue_table.verticalHeader().hide(); self.queue_table.setShowGrid(False)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows); self.queue_table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.queue_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.queue_table.setMinimumHeight(125); self.queue_table.setMaximumHeight(200)
        layout.addWidget(self.queue_table)
        queue_actions = box(horizontal=True)
        self.queue_add = button('Add files or folder', self.add_media, None, 'plus'); queue_actions.addWidget(self.queue_add)
        self.queue_open = button('Show source', self.open_queued, None, 'folder'); queue_actions.addWidget(self.queue_open)
        self.queue_remove = button('Remove from queue', self.remove_queued, 'quiet'); queue_actions.addWidget(self.queue_remove); queue_actions.addStretch()
        self.queue_remove.setToolTip('Remove selected entries from this queue. Source files stay on your computer.')
        self.queue_table.selectionModel().selectionChanged.connect(self.update_queue_controls)
        self.queue_table.activated.connect(self.open_queued)
        shortcut = QShortcut(QKeySequence('Delete'), self.queue_table, activated=self.remove_queued)
        shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        layout.addLayout(queue_actions)
        self.prep_results = QTextEdit(); self.prep_results.setReadOnly(True); self.prep_results.setMinimumHeight(130); self.prep_results.hide(); layout.addWidget(self.prep_results)
        self.retry_button = button('Review skipped files', self.review_skipped, 'quiet'); layout.addWidget(self.retry_button, 0, Qt.AlignLeft)
        layout.addStretch()
        footer = QFrame(); footer.setObjectName('preparationFooter')
        actions = box(footer, horizontal=True, margins=(34, 16, 34, 16), spacing=18)
        self.prep_summary = label('Unchanged media is reused. All existing videos are included unless you choose a selection.', 'muted', True)
        actions.addWidget(self.prep_summary, 1)
        self.prepare_button = button('Prepare selected media', self.prepare, 'primary', 'prepare')
        actions.addWidget(self.prepare_button)
        outer.addWidget(footer)
        return page

    def build_screens(self):
        page, layout = self.scroll_page()
        self.heading(layout, 'Screens', 'Choose what appears on your iPod and arrange it in your preferred order.')
        self.screen_state = screen_settings.defaults()
        self.screen_loaded_for = None
        self.screen_picker = ComboBox(); self.screen_picker.addItems(['Home', 'Music', 'Settings'])
        self.screen_picker.currentTextChanged.connect(self.render_screen_items)
        layout.addWidget(self.screen_picker)
        layout.addWidget(label('Check items to include them. Drag to reorder, or use the move buttons.', 'muted', True))
        self.screen_items = QListWidget(); self.screen_items.setObjectName('screenItems'); self.screen_items.setMinimumHeight(350)
        self.screen_items.setDragDropMode(QAbstractItemView.InternalMove)
        self.screen_items.setDefaultDropAction(Qt.MoveAction)
        self.screen_items.itemChanged.connect(self.screen_items_changed)
        self.screen_items.model().rowsMoved.connect(self.screen_items_changed)
        layout.addWidget(self.screen_items)
        self.screen_unavailable = label('', 'muted', True); layout.addWidget(self.screen_unavailable)
        self.screen_hint = label('', 'muted', True); layout.addWidget(self.screen_hint)
        self.screen_items.currentItemChanged.connect(self.screen_item_hint)
        controls = box(horizontal=True)
        controls.addWidget(button('Move up', lambda: self.move_screen_item(-1)))
        controls.addWidget(button('Move down', lambda: self.move_screen_item(1)))
        controls.addStretch()
        controls.addWidget(button('Reset this screen', self.reset_screen))
        layout.addLayout(controls)
        self.screen_status = label('Connect an iPod in Disk Mode to save screen settings.', 'muted', True)
        layout.addWidget(self.screen_status)
        self.screen_save = button('Save to iPod', self.save_screens, 'primary')
        layout.addWidget(self.screen_save)
        self.render_screen_items()
        return page

    def render_screen_items(self, *_):
        name = self.screen_picker.currentText()
        labels = screen_settings.SCREENS[name]
        selected = self.screen_state[name]
        available, unavailable = screen_settings.item_availability(name, self.identity)
        self.screen_unavailable.setText('Not available on this device: ' + ', '.join(labels[i] for i in unavailable))
        self.screen_unavailable.setVisible(bool(unavailable))
        order = [i for i in selected if i in available] + [i for i in available if i not in selected]
        self.screen_items.blockSignals(True); self.screen_items.clear()
        for i in order:
            item = QListWidgetItem(labels[i]); item.setData(Qt.UserRole, i)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsDragEnabled)
            item.setCheckState(Qt.Checked if i in selected else Qt.Unchecked)
            if i in screen_settings.REQUIRED.get(name, set()):
                item.setFlags(item.flags() & ~Qt.ItemIsUserCheckable)
                item.setText(labels[i] + ' (always included)')
                item.setToolTip('Always available so you can reach settings and USB access.')
            elif labels[i] in screen_settings.HINTS:
                item.setToolTip(screen_settings.HINTS[labels[i]])
            self.screen_items.addItem(item)
        self.screen_items.blockSignals(False)
        self.screen_items.setCurrentRow(0)

    def screen_items_changed(self, *_):
        name = self.screen_picker.currentText()
        selected = [self.screen_items.item(i).data(Qt.UserRole) for i in range(self.screen_items.count())
                    if self.screen_items.item(i).checkState() == Qt.Checked]
        self.screen_state[name] = selected
        self.screen_status.setText('Unsaved changes. Save to iPod, then eject safely to apply on startup.'
                                   if all(self.screen_state.values()) else 'Select at least one item on each screen before saving.')
        self.update_controls()

    def screen_item_hint(self, item, *_):
        self.screen_hint.setText(item.toolTip() if item else '')

    def move_screen_item(self, direction):
        row = self.screen_items.currentRow(); target = row + direction
        if row < 0 or not 0 <= target < self.screen_items.count():
            return
        item = self.screen_items.takeItem(row); self.screen_items.insertItem(target, item)
        self.screen_items.setCurrentRow(target); self.screen_items_changed()

    def reset_screen(self):
        name = self.screen_picker.currentText()
        self.screen_state[name] = screen_settings.defaults(self.identity)[name]
        self.render_screen_items(); self.screen_items_changed()

    def load_screens(self):
        if self.identity and not self.busy and self.screen_loaded_for != self.identity['root']:
            identity = self.identity
            self.work('screens', lambda: screen_settings.read(identity), 'Reading screen settings…')

    def save_screens(self):
        if not self.identity or self.busy:
            return
        state = {name: list(rows) for name, rows in self.screen_state.items()}
        try:
            screen_settings.encode(state)
        except ValueError as error:
            self.show_error(str(error)); return
        identity = self.identity
        self.work('save_screens', lambda: screen_settings.save(identity, state), 'Saving screen settings…')

    def build_setup(self):
        page, layout = self.scroll_page()
        self.heading(layout, 'iPod setup', 'Choose your startup software and how your iPod starts.')
        card = QFrame(); card.setObjectName('card'); details = box(card, margins=(24, 24, 24, 24), spacing=12)
        details.addWidget(label('Connected device', 'section'))
        self.setup_device = label('Connect an iPod in Disk Mode.', 'muted', True); details.addWidget(self.setup_device)
        self.setup_software = label('', 'muted', True); details.addWidget(self.setup_software)
        self.install_detail = label('', 'notice', True); self.install_detail.hide(); details.addWidget(self.install_detail)
        self.setup_progress = QProgressBar(); self.setup_progress.setRange(0, 0)
        self.setup_progress.setTextVisible(False); self.setup_progress.hide(); details.addWidget(self.setup_progress)
        layout.addWidget(card)
        layout.addSpacing(12); layout.addWidget(label('Startup software', 'section'))
        layout.addWidget(label('Choose a default or see options available by holding Menu at startup.', 'muted'))
        self.boot_choice = ComboBox(); self.boot_choice.currentIndexChanged.connect(self.update_install_action); layout.addWidget(self.boot_choice)
        self.boot_detail = label('', 'muted', True); layout.addWidget(self.boot_detail)
        self.method_title = label('Startup behavior', 'section'); layout.addWidget(self.method_title)
        self.method_choice = ComboBox(); self.method_choice.currentIndexChanged.connect(self.update_install_action); layout.addWidget(self.method_choice)
        self.method_detail = label('', 'muted', True); layout.addWidget(self.method_detail)
        self.selector_note = label('A startup selector can offer a choice at boot when compatible software is installed.', 'muted', True); layout.addWidget(self.selector_note)
        layout.addSpacing(10)
        self.install_button = button('Install Linnet', self.install_selected, 'primary'); layout.addWidget(self.install_button, 0, Qt.AlignLeft)
        layout.addWidget(label('Your media is kept. Previous startup files are saved for recovery.', 'muted', True))
        layout.addStretch()
        return page

    def build_settings(self):
        page, layout = self.scroll_page()
        self.heading(layout, 'Settings', 'Preparation quality and tools, in one place.')
        layout.addWidget(label('Photo detail', 'section'))
        self.photo_detail = ComboBox(); self.photo_detail.addItems(['Standard · 640 px', 'High detail · 2048 px']); self.photo_detail.setCurrentIndex(int(self.settings.value('photo_detail', 0)))
        self.photo_detail.currentIndexChanged.connect(lambda value: self.settings.setValue('photo_detail', value)); layout.addWidget(self.photo_detail)
        layout.addWidget(label('High detail uses more storage and takes longer to prepare.', 'muted'))
        layout.addSpacing(20); layout.addWidget(label('Conversion tools', 'section'))
        self.tools_label = label('', 'muted', True); layout.addWidget(self.tools_label)
        layout.addWidget(button('Choose FFmpeg folder', self.locate_tools, None, 'folder'), 0, Qt.AlignLeft)
        layout.addSpacing(20); layout.addWidget(label('Advanced preparation', 'section'))
        self.verify_audio = CheckBox('Read entire audio files when verifying (slower)'); layout.addWidget(self.verify_audio)
        self.rebuild = CheckBox('Rebuild content that is already prepared'); layout.addWidget(self.rebuild)
        layout.addStretch(); self.update_tools()
        return page

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
                self.work('trash', lambda: media_trash.removals(self.identity), 'Reading Trash…')
        elif page == 'Preparation':
            self.stack.setCurrentWidget(self.preparation)
        elif page == 'Screens':
            self.stack.setCurrentWidget(self.screens); self.load_screens()
        elif page == 'iPod setup':
            self.stack.setCurrentWidget(self.setup)
            if self.identity and not self.busy and self.review is None:
                self.work('setup', lambda: installer.assess(self.identity), 'Checking installed software…')
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
            self._library_source, self._library_cache = self.rows, {}
        if self.page in self._library_cache:
            return list(self._library_cache[self.page])
        unique = {}
        for row in self.rows:
            if row['kind'] == self.page and row['category'] in ('original', 'published'):
                copy = dict(row)
                if row['kind'] == 'Photos':
                    copy['artwork'] = row.get('artwork') or row['path']
                unique[str(Path(row['path'])).casefold()] = copy
        self._library_cache[self.page] = list(unique.values())
        return list(self._library_cache[self.page])

    def render_library(self):
        if self.page not in (*media.KINDS, 'Trash'):
            return
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
            ids = {r['id'] for r in self.group['members']}
            rows = [r for r in rows if r['id'] in ids]
        scope_count = len(rows)
        if music and (artist or genre):
            rows = [r for r in rows if (not artist or (r.get('artist') or 'Unknown artist') == artist)
                    and (not genre or (r.get('genre') or 'Unknown genre') == genre)]
        if words:
            matches = []
            first, *remaining = words
            for row in rows:
                text = ' '.join(str(row.get(field, '')) for field in ('title', 'artist', 'album', 'genre', 'path')).casefold()
                if first in text and (not remaining or all(word in text for word in remaining)):
                    matches.append(row)
            rows = matches
        matched_count = len(rows)
        filtered = bool(words or (music and (artist or genre)))
        grouped = music and self.view != 'Songs' and self.group is None
        if grouped:
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
            rows = cards
        rows.sort(key=lambda r: (r.get('disc', 0), r.get('track', 0), r['title'].casefold()) if self.group and self.view == 'Albums' else (r['title'].casefold(),))
        self.model.reset(rows, [('title', 'TITLE'), ('album', 'ALBUM'), ('genre', 'GENRE'), ('duration', 'TIME'), ('bytes', 'SIZE')] if music and not grouped else
                         [('title', 'NAME'), ('status', 'STATUS'), ('bytes', 'SIZE')])
        if not grouped and self.group is None:
            header = self.table.horizontalHeader()
            self.model.sort(max(0, min(header.sortIndicatorSection(), self.model.columnCount() - 1)), header.sortIndicatorOrder())
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
        count = len(all_rows)
        albums = len({(r.get('album'), r.get('album_artist') or r.get('artist')) for r in all_rows}) if music else 0
        self.subtitle.setText(f'{count:,} songs  ·  {albums:,} albums  ·  {size(sum(r["bytes"] for r in all_rows))}' if music else
                              'Restore removed files or delete them permanently to free space.' if self.page == 'Trash' else
                              f'{count:,} files on your iPod  ·  {size(sum(r["bytes"] for r in all_rows))}')
        if self.group:
            members = self.group['members']
            self.subtitle.setText((self.group['subtitle'] + '  ·  ' if self.view == 'Albums' else '') + f'{len(members):,} songs  ·  {size(sum(r["bytes"] for r in members))}')
        unit = 'songs' if music else 'items'
        self.result_count.setText(f'{matched_count:,} of {scope_count:,} {unit}' + (f' · {len(rows):,} {self.view.lower()}' if grouped else '') if filtered else
                                  f'{len(rows):,} {self.view.lower() if grouped else unit}')
        self.clear_button.setVisible(filtered)
        self.hint.setText('Delete files in LINNET / VIDEOS, then Sync video folder to update the playback library.' if self.page == 'Videos' else
                          'Double-click to explore. Select one or more groups to manage their songs.' if grouped else
                          'Select a removal to restore it, or permanently delete it to free storage.' if self.page == 'Trash' else
                          'Ctrl+click or Shift+click to select multiple files. Double-click for details.')
        self.selection_bar.hide()

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
        if self.busy:
            return
        self.busy = True; self.stop_event.clear(); self.progress.setRange(0, 0); self.progress.show()
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(tag in ('prepare', 'remove', 'restore')); self.show_progress(message); self.update_controls()
        def run():
            try:
                self.events.done.emit(tag, operation(), '')
            except Exception as error:
                self.events.done.emit(tag, None, str(error) or type(error).__name__)
        self.pool.submit(run)

    @Slot(str)
    def show_progress(self, text):
        self.status.set_message(text)

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

    @Slot(str, object, str)
    def completed(self, tag, result, error):
        self.busy = False; self.progress.hide(); self.cancel_button.hide(); self.update_controls()
        if error:
            if tag == 'screens':
                self.screen_state = screen_settings.defaults(self.identity)
                self.render_screen_items()
                self.screen_status.setText('Could not read settings. Showing defaults for this iPod; saving will replace its screen settings.')
            if tag in ('setup', 'devices', 'scan'):
                self.setup_progress.hide()
                self.setup_software.setText('Could not check iPod setup. Choose Refresh to try again.')
            self.show_error(error)
            if tag == 'save_playlists':
                self.edit_playlists(self.playlist_draft)
            return
        if tag == 'screens':
            self.screen_state = result; self.screen_loaded_for = self.identity['root']; self.render_screen_items()
            self.screen_status.setText('Loaded from iPod. Changes apply after saving and restarting Linnet.'); self.update_controls(); return
        if tag == 'save_screens':
            self.screen_status.setText('Saved to iPod. Eject safely to apply on startup.'); return
        if tag == 'playlists':
            self.show_progress('Playlists loaded.'); self.edit_playlists(result); return
        if tag == 'save_playlists':
            self.show_progress('Playlists saved to iPod. Eject safely when finished.'); return
        if tag == 'devices':
            if not result:
                self.covers.invalidate()
                self.screen_loaded_for = None
                self.identity = None; self.rows = []; self.inventory = None; self.review = None
                self.trash_rows = []; self.readiness = {}; self.group = None; self.video_selection.clear()
                self.update_preparation()
                self.device_name.setText('No iPod connected'); self.device_info.setText('Connect in Disk Mode'); self.render_library()
                self.update_controls()
                self.show_progress('Connect your iPod, then choose Refresh.'); return
            if len(result) > 1:
                dialog = QDialog(self); dialog.setWindowTitle('Choose an iPod'); layout = box(dialog, margins=(24, 24, 24, 24))
                picker = ComboBox()
                for device in result:
                    picker.addItem(f"{device['drive']} · {device['target_name']}", device)
                layout.addWidget(picker); layout.addWidget(button('Use this iPod', dialog.accept, 'primary'))
                if dialog.exec() != QDialog.Accepted:
                    return
                identity = picker.currentData()
            else:
                identity = result[0]
            if self.identity and any(self.identity.get(key) != identity.get(key)
                                     for key in ('disk_serial', 'volume_serial', 'root')):
                self.covers.invalidate(); self.video_selection.clear(); self.group = None
                self.screen_loaded_for = None
            self.identity = identity
            self.refresh()
        elif tag == 'scan':
            cached_photos = {row['path']: (row['bytes'], row['mtime_ns'], row.get('artwork')) for row in self.rows
                             if row['kind'] in ('Photos', 'Music') and
                             (row.get('artwork') in self.covers.cache or row.get('artwork') in self.covers.pending)}
            self.identity, self.inventory, self.rows, self.readiness = result
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
            self.video_selection.intersection_update(self.inventory['Videos']['files'])
            self.review = None; self.notice.hide(); self.update_device(); self.update_filters(); self.update_preparation(); self.render_library()
            self.show_progress('Ready. Eject safely when you’re finished.')
            if self.page == 'Screens':
                self.load_screens()
            if self.page == 'iPod setup':
                self.work('setup', lambda: installer.assess(self.identity), 'Checking installed software…')
            elif self.page == 'Trash':
                self.work('trash', lambda: media_trash.removals(self.identity), 'Reading Trash…')
        elif tag == 'trash':
            self.trash_rows = result; self.render_library(); self.show_progress('Trash uses storage until files are permanently deleted.')
        elif tag == 'setup':
            self.review = result; self.render_setup(); self.show_progress('Device setup is ready.')
        elif tag == 'prepare':
            lines = [result.get('summary') or ('Preparation complete.' if result['complete'] else 'Preparation needs attention.')]
            lines.extend(e['message'] for e in result.get('errors', []))
            self.prep_results.setPlainText('\n'.join(lines)); self.prep_results.show()
            if result['complete']:
                self.pending = [p for p in self.pending if p not in self.submitted]
                self.video_selection.difference_update(self.submitted_videos)
            self.update_preparation(); self.refresh()
        elif tag in ('remove', 'restore', 'erase', 'sync', 'install', 'skipped'):
            self.show_progress(result.get('summary', 'Changes saved.'))
            if result.get('needs_preparation'):
                self.prep_results.setPlainText(result['summary']); self.prep_results.show(); self.navigate('Preparation')
            self.refresh()
        elif tag == 'eject':
            self.covers.invalidate()
            self.screen_loaded_for = None
            self.identity = self.inventory = self.review = None; self.rows = []; self.trash_rows = []
            self.readiness = {}; self.group = None; self.video_selection.clear()
            self.update_preparation()
            self.device_name.setText('Safely ejected'); self.device_info.setText('You can disconnect your iPod.'); self.capacity.setValue(0)
            self.render_library(); self.show_progress('Your iPod is safe to disconnect.')
        self.update_controls()

    def discover(self):
        self.work('devices', media.discover, 'Looking for your iPod…')

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
        self.work('scan', lambda: media_status.inspect(identity, dimension, verification), 'Reading your collection and checking prepared media…')

    def update_device(self):
        identity = self.identity
        self.device_name.setText(identity['target_name'].replace('Linnet for ', ''))
        self.device_info.setText(f"Connected · {identity['drive']}\n{size(identity['free_bytes'])} available")
        total = identity.get('total_bytes') or shutil.disk_usage(identity['root']).total
        self.capacity.setValue(int(100 * (1 - identity['free_bytes'] / total)))

    def update_filters(self):
        for picker, field, title in ((self.genre_filter, 'genre', 'All genres'), (self.artist_filter, 'artist', 'All artists')):
            old = picker.currentData(); picker.blockSignals(True); picker.clear(); picker.addItem(title, '')
            for value in sorted({row.get(field) or f'Unknown {field}' for row in self.rows if row['kind'] == 'Music' and row['category'] == 'original'}, key=str.casefold):
                picker.addItem(value, value)
            picker.setCurrentIndex(max(0, picker.findData(old))); picker.blockSignals(False)

    def update_controls(self):
        ready = self.identity is not None and not self.busy
        supported = media.supported_kinds(self.identity) if ready else ()
        self.screens.setEnabled(not self.busy)
        self.screen_save.setEnabled(ready and all(self.screen_state.values()))
        self.screen_items.setEnabled(not self.busy)
        self.screen_picker.setEnabled(not self.busy)
        for item in (self.eject_button, self.add_button, self.playlists_button, self.sync_button, self.choose_videos_button, self.queue_add, self.folder_button):
            item.setEnabled(ready)
        self.update_queue_controls()
        self.prepare_button.setEnabled(ready and self.inventory is not None)
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

    def update_preparation(self):
        supported = media.supported_kinds(self.identity) if self.identity else ()
        for kind, text in self.prep_labels.items():
            info = (self.inventory or {}).get(kind)
            if self.identity and kind not in supported:
                text.setText(f'{kind} playback is unavailable on this iPod model.')
            elif not info:
                text.setText('Connect an iPod to check this library.')
            elif kind == 'Videos':
                text.setText(f"{info['count']:,} files · {self.readiness.get(kind, 'Not checked')} · " +
                             (f'{len(self.video_selection)} selected' if self.video_selection else 'All existing videos included'))
            else:
                text.setText(f"{info['count']:,} files · {self.readiness.get(kind, 'Not checked')}")
        self.queue_model.reset([dict(title=Path(path).name, kind=kind, path=path) for kind, path in self.pending], [('title', 'FILE'), ('kind', 'TYPE'), ('path', 'FROM YOUR COMPUTER')])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.queue_table.setVisible(bool(self.pending)); self.queue_remove.setVisible(bool(self.pending))
        self.queue_open.setVisible(bool(self.pending)); self.update_queue_controls()
        self.queue_table.setFixedHeight(min(200, max(75, self.queue_table.horizontalHeader().height() + len(self.pending) * self.queue_table.verticalHeader().defaultSectionSize() + 4)))
        self.prep_summary.setText(f'{len(self.pending):,} files or folders queued. Unchanged media is reused.' if self.pending else 'Nothing queued. You can prepare existing iPod files or add media from your computer.')

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
                    added = self.queue_sources(kind, paths)
                except (OSError, ValueError) as error:
                    error_label.setText(str(error)); error_label.show(); return
                source = Path(paths[0])
                self.settings.setValue(f'import_folder/{kind}', str(source if folder else source.parent))
                self.prep_checks[kind].setChecked(True); dialog.accept(); self.update_preparation(); self.navigate('Preparation')
                QTimer.singleShot(0, lambda: self.preparation_scroll.ensureWidgetVisible(self.queue_table))
                self.show_progress(f'{added:,} new queue entries added.' if added else 'These sources are already queued. Review them in Preparation.')
        actions = box(horizontal=True); actions.addWidget(button('Choose files', lambda: choose(), 'primary', 'plus')); actions.addWidget(button('Choose a folder', lambda: choose(True), None, 'folder')); layout.addLayout(actions)
        layout.addWidget(button('Cancel', dialog.reject, 'quiet'), 0, Qt.AlignRight)
        dialog.exec()

    def queue_sources(self, kind, paths):
        if not self.identity or self.busy:
            raise ValueError('Connect an iPod and wait for the current operation to finish before adding media.')
        if kind not in media.supported_kinds(self.identity):
            raise ValueError(f'{kind} is unavailable on this iPod.')
        root = Path(self.identity['root']).resolve(strict=True)
        allowed = media.video_source_extensions(self.identity) if kind == 'Videos' else media.extensions(kind)
        known = {(k, os.path.normcase(str(Path(p).resolve()))) for k, p in self.pending}
        additions = []
        for value in paths:
            source = Path(value).resolve(strict=True)
            if source.is_relative_to(root):
                raise ValueError('This source is already on your iPod. Use Refresh to find existing media, then prepare it from Preparation.')
            if not source.is_dir() and (not source.is_file() or source.suffix.lower() not in allowed):
                raise ValueError(f'{source.name} is not a supported {kind.lower()} file. Choose a supported file or a folder.')
            key = (kind, os.path.normcase(str(source)))
            if key not in known:
                additions.append((kind, str(source))); known.add(key)
        self.pending.extend(additions)
        return len(additions)

    def remove_queued(self):
        if self.busy:
            return
        chosen = {index.row() for index in self.queue_table.selectionModel().selectedRows()}
        self.pending = [item for index, item in enumerate(self.pending) if index not in chosen]; self.update_preparation()

    def choose_videos(self):
        if not self.inventory or self.busy:
            return
        sources = [p for p in self.inventory['Videos']['files']
                   if Path(p).suffix.lower() in media.video_source_extensions(self.identity)
                   and Path(p).suffix.lower() not in media.native_video_extensions(self.identity)]
        dialog = QDialog(self); dialog.setWindowTitle('Choose videos to convert'); dialog.resize(700, 520)
        layout = box(dialog, margins=(24, 24, 24, 24)); layout.addWidget(label('Choose video originals', 'section'))
        layout.addWidget(label('Device-format videos are included automatically. Select other originals to convert; an empty selection includes all.', 'muted', True))
        search = QLineEdit(); search.setPlaceholderText('Find a video…'); layout.addWidget(search)
        table = QTableView(); model = MediaModel(table); table.setModel(model); table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection); table.setEditTriggers(QAbstractItemView.NoEditTriggers); table.verticalHeader().hide(); layout.addWidget(table)
        selected = set(self.video_selection)
        def render():
            if model.rows:
                selected.difference_update(r['path'] for r in model.rows)
                selected.update(model.rows[i.row()]['path'] for i in table.selectionModel().selectedRows())
            model.reset([dict(title=Path(p).name, path=p) for p in sources if search.text().casefold() in p.casefold()], [('title', 'VIDEO'), ('path', 'LOCATION')])
            from PySide6.QtCore import QItemSelectionModel
            for index, row in enumerate(model.rows):
                if row['path'] in selected:
                    table.selectionModel().select(model.index(index, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        search.textChanged.connect(render); render()
        def accept():
            render(); self.video_selection = selected; self.update_preparation(); dialog.accept()
        layout.addWidget(button('Use selected videos', accept, 'primary'), 0, Qt.AlignRight); dialog.exec()

    def prepare(self):
        if self.busy or not self.inventory:
            return
        selected = [kind for kind, check in self.prep_checks.items() if check.isChecked() and check.isEnabled()]
        if not selected:
            self.show_error('Choose at least one media type to prepare.'); return
        identity = self.identity; pending = [item for item in self.pending if item[0] in selected]
        videos = list(self.video_selection); dimension = 2048 if self.photo_detail.currentIndex() else 640
        online_artwork = self.online_artwork.isChecked()
        force, verification = self.rebuild.isChecked(), 'full' if self.verify_audio.isChecked() else 'metadata'
        ffmpeg, ffprobe = self.ffmpeg, self.ffprobe
        self.submitted, self.submitted_videos = pending, set(videos) if 'Videos' in selected else set()
        def run():
            plan = media_status.plan(identity, pending, selected, videos)
            if plan['conversion'] and (not ffmpeg or not ffprobe):
                raise ValueError('Video conversion needs FFmpeg and FFprobe. Choose their folder in Settings.')
            return media.run(identity, selected, pending, photo_dimension=dimension, force=force,
                music_verification=verification, ffmpeg=ffmpeg, ffprobe=ffprobe, video_selection=videos,
                online_artwork=online_artwork,
                progress=self.events.progress.emit, progress_detail=self.events.conversion.emit,
                cancelled=self.stop_event.is_set)
        self.prep_results.hide(); self.work('prepare', run, 'Preparing your selected media…')

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
                    return dict(needs_preparation=True, summary='Files restored. Playback needs preparation: ' + '; '.join(e['message'] for e in prepared['errors']))
            return dict(summary='Files and playback libraries restored.')
        self.work('restore', restore, 'Restoring your files…')

    def sync_videos(self):
        if self.identity and not self.busy:
            identity = self.identity
            self.work('sync', lambda: media_library.organize_videos(identity), 'Syncing the video folder…')

    def render_setup(self):
        review = self.review
        self.setup_device.setText(f"{review['identity']['target_name']} · {review['identity']['drive']}")
        self.setup_software.setText('Linnet: ' + installer.build_description(review['linnet']))
        self.boot_choice.blockSignals(True); self.boot_choice.clear()
        available_boot = review['boot_options']
        for option in available_boot:
            suffix = (' · Current' if option.get('active') else
                      ' · Hold Menu' if option.get('chooser_available') else
                      ' · Unavailable' if not option.get('selectable') else '')
            self.boot_choice.addItem(option['label'] + suffix, option)
            self.boot_choice.setItemData(self.boot_choice.count() - 1, option.get('detail', ''), Qt.ToolTipRole)
        selected = next((i for i, option in enumerate(available_boot) if option.get('active')),
                        next((i for i, option in enumerate(available_boot) if option.get('selectable')), -1))
        self.boot_choice.setPlaceholderText('No verified startup software')
        self.boot_choice.setCurrentIndex(selected); self.boot_choice.blockSignals(False)
        self.method_choice.blockSignals(True); self.method_choice.clear()
        for method in review['installation_methods']:
            if not method.get('enabled'):
                continue
            self.method_choice.addItem(method['label'], method)
            self.method_choice.setItemData(self.method_choice.count() - 1, method['detail'], Qt.ToolTipRole)
            if method['id'] == review.get('default_installation_method'):
                self.method_choice.setCurrentIndex(self.method_choice.count() - 1)
        self.method_choice.blockSignals(False)
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
            for name in ('ffmpeg', 'ffprobe'):
                candidate = Path(folder) / (name + '.exe')
                if candidate.is_file():
                    setattr(self, name, str(candidate)); self.settings.setValue(name, str(candidate))
            self.update_tools()

    def update_tools(self):
        self.tools_label.setText('FFmpeg and FFprobe are ready.' if self.ffmpeg and self.ffprobe else 'Choose the folder containing ffmpeg.exe and ffprobe.exe to enable conversion.')

    def review_skipped(self):
        if self.busy or not self.identity:
            return
        rows = media.list_skipped_files(self.identity)
        dialog = QDialog(self); dialog.setWindowTitle('Skipped files'); dialog.resize(680, 400)
        layout = box(dialog, margins=(24, 24, 24, 24)); layout.addWidget(label('Skipped during preparation', 'section'))
        table = QTableView(); model = MediaModel(table); model.reset([dict(title=row['relative'], kind=row['kind']) for row in rows], [('title', 'FILE'), ('kind', 'TYPE')]); table.setModel(model)
        table.setSelectionBehavior(QAbstractItemView.SelectRows); table.setSelectionMode(QAbstractItemView.ExtendedSelection); table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch); layout.addWidget(table)
        def restore():
            selected = [rows[i.row()] for i in table.selectionModel().selectedRows()]
            if selected:
                identity = self.identity; dialog.accept()
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
        self.stop_event.set(); self.cancel_button.setEnabled(False); self.show_progress('Finishing the current step before stopping…')

    def show_error(self, message):
        self.notice.setText(message); self.notice.show(); self.show_progress(message)
        if self.stack.currentWidget() != self.library:
            self.prep_results.setPlainText(message); self.prep_results.show()
            if self.page != 'Preparation':
                self.dialog('Needs attention', message, 'OK', cancel=False)

    def closeEvent(self, event):
        if self.busy:
            self.show_progress('Wait for the current operation to finish before closing.'); event.ignore(); return
        self.covers.closed = True
        self.covers.pool.shutdown(wait=False, cancel_futures=True); self.pool.shutdown(wait=False, cancel_futures=True)
        event.accept()


def launch():
    # Qt still decodes photos with malformed ICC metadata; avoid repeating
    # profile diagnostics as their previews enter and leave the artwork cache.
    QLoggingCategory.setFilterRules('qt.gui.icc.warning=false')
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setStyle('Fusion'); app.setFont(QFont(UI_FONT, 10))
    window = MediaWindow(); window.show()
    app.exec()
