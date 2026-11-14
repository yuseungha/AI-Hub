"""Main window: navigation, project pages (jobs / results / folders) and the preview pane.

Browsing never changes files; copy, move and recycle happen only after the
user confirms them (see fileops.py).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, unquote

from PySide6.QtCore import Qt, QUrl, QTimer, QSize, QRect, QRectF, Signal
from PySide6.QtGui import (QDesktopServices, QPixmap, QFont, QKeySequence, QShortcut, QColor, QPen, QPainter,
                           QFontMetrics, QTextLayout, QTextOption)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextBrowser, QPlainTextEdit, QStackedWidget, QScrollArea,
    QFileDialog, QCheckBox, QHeaderView, QMessageBox, QApplication, QFrame, QMenu, QAbstractItemView,
    QStyledItemDelegate, QStyle, QSizePolicy, QListWidget, QListWidgetItem, QListView, QTabBar, QGridLayout,
    QDialog, QDialogButtonBox, QColorDialog, QStyleOptionViewItem, QStyleOptionButton)

from appearance import (DEFAULT_AI_COLORS, DOCUMENT_STYLE, ai_icon, icon_html,
                        load_ai_colors, text_color, swatch_text_color)

import chatgpt
import fileops
from indexer import (AIS, UNKNOWN, AI_LABELS, ACTION_LABELS, STATUS_LABELS, STALE_DAYS, build_index,
                     SCAN_AREAS, PROJECT_FOLDER, search_content, stale_files, rel_key, Index, Project,
                     NO_GROUP, group_label, is_deliverable)
from preview import build_preview, can_open_externally, human_size

PURPLE = "#635BDF"
AI_COLORS = DEFAULT_AI_COLORS
ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # numeric sort key per column
KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # tree node key, used to restore selection
GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 3  # status colour group of a list row
GROUP_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 4  # project group of a folder-tab row
CARD_ROLE = int(Qt.ItemDataRole.UserRole) + 5  # status, roles and counts drawn on a job card
AI_ROLE = int(Qt.ItemDataRole.UserRole) + 6
COLUMNS = ["종류", "이름", "AI", "상태", "크기", "날짜"]
SIZE_COLUMN, DATE_COLUMN = 4, 5
STALE_LABELS = {90: "90일 이상", 180: "180일 이상", 365: "1년 이상"}
FILE_OPS = (("copy", "복사…"), ("move", "이동…"), ("trash", "휴지통으로 삭제"))  # right-click menu only


class SortItem(QTreeWidgetItem):
    """Sorts by SORT_ROLE when both rows carry one (sizes, timestamps); rows without
    a value (jobs and conversations in the size column) sort below every file."""

    def __lt__(self, other):
        tree = self.treeWidget()
        column = tree.sortColumn() if tree else 0
        mine, theirs = self.data(column, SORT_ROLE), other.data(column, SORT_ROLE)
        if mine is None and theirs is None:
            # Plain text order. Calling QTreeWidgetItem.__lt__ via super() crashes PySide6 6.12.
            return self.text(column).casefold() < other.text(column).casefold()
        return (mine if mine is not None else -1.0) < (theirs if theirs is not None else -1.0)

STYLE = """
QMainWindow, QWidget#central { background: #F6F6FA; }
QFrame#toolbar { background: white; border-bottom: 1px solid #E6E5EF; }
QWidget { font-size: 10pt; }
QLabel#brand { color: #2B2A3A; font-size: 12pt; font-weight: 700; }
QLabel#rootLabel { color: #676B80; font-size: 9pt; font-family: 'Segoe UI'; }
QLineEdit { background: #F6F6FA; border: 1px solid #E1E0EA; border-radius: 8px; padding: 7px 10px; }
QLineEdit:focus { border-color: #7B72E8; background: white; }
QPushButton { background: white; border: 1px solid #E1E0EA; border-radius: 8px; padding: 6px 14px; min-height: 20px; color: #3B3A4E; }
QPushButton:hover { background: #F1F0FB; border-color: #CFCBF3; }
QPushButton:focus { border: 1px solid #635BDF; }
QPushButton:pressed { background: #E9E7FB; }
QPushButton:disabled { color: #A9ABBB; }
QPushButton#primary { background: #635BDF; color: white; border-color: #635BDF; font-weight: 700; }
QTreeWidget { background: white; border: 1px solid #E6E5EF; border-radius: 10px; padding: 4px; outline: none; }
QTreeWidget::item { padding: 7px 8px; border-radius: 6px; }
QTreeWidget::item:hover { background: #F1F0FB; }
QTreeWidget::item:selected { background: #E9E7FB; color: #2B2A3A; }
QTreeWidget#itemList::item { border-radius: 0; }
QTreeWidget#itemList { font-size: 9pt; }
QTreeWidget#itemList::item:hover { background: #FFFFFF; }
QTreeWidget#itemList::item:selected { background: #D9D5FA; color: #1F1D33; }
QLabel#legendChip { color: #3B3A4E; border-radius: 6px; padding: 3px 10px; font-size: 9pt; }
QLabel#legendTitle { color: #676B80; font-size: 9pt; }
QHeaderView::section { background: white; border: none; border-bottom: 1px solid #ECEBF3; padding: 8px; color: #676B80; font-size: 9pt; font-weight: 600; }
QTextBrowser, QPlainTextEdit, QScrollArea { background: white; border: 1px solid #E6E5EF; border-radius: 10px; }
QWidget#previewCard { background: white; border: 1px solid #E6E5EF; border-radius: 12px; }
QWidget#previewCard QTextBrowser, QWidget#previewCard QPlainTextEdit,
QWidget#previewCard QScrollArea { border: none; border-radius: 0; background: white; }
QLabel#previewTitle { font-size: 12pt; font-weight: 700; color: #2B2A3A; }
QLabel#previewMeta { color: #676B80; font-size: 9pt; font-family: 'Segoe UI', 'Malgun Gothic'; }
QLabel#safetyNote { color: #676B80; font-size: 9pt; }
QFrame#previewRule { border: none; background: #ECEBF3; min-height: 1px; max-height: 1px; }
QSplitter::handle { background: transparent; width: 8px; }
QSplitter::handle:hover { background: #E1E0EA; }
QStatusBar { color: #676B80; font-size: 9pt; }
QTreeWidget#nav { background: transparent; border: none; padding: 0; font-size: 10pt; show-decoration-selected: 1; }
QTreeWidget#nav::branch:selected { background: #E3E0FB; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: #D3D2E0; border-radius: 3px; min-height: 28px; min-width: 28px; }
QScrollBar::handle:hover { background: #B9B7CC; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QTreeWidget#nav::item { padding: 8px 8px; border-radius: 0; }
QTreeWidget#folderTree { show-decoration-selected: 1; }
QTreeWidget#folderTree::item { border-radius: 0; }
QTreeWidget#folderTree::branch:selected { background: #E9E7FB; }
QTreeWidget#nav::item:hover { background: #ECEBF6; }
QTreeWidget#nav::item:selected { background: #E3E0FB; color: #2B2A3A; }
QLabel#pageTitle { font-size: 16pt; font-weight: 700; color: #2B2A3A; }
QLabel#pageMeta { color: #676B80; font-size: 9pt; }
QLabel#sectionLabel { color: #3B3A4E; font-weight: 700; padding-top: 4px; }
QScrollArea#cards, QWidget#cardsBox { background: transparent; border: none; }
QPushButton#projectCard { background: white; border: 1px solid #E6E5EF; border-radius: 10px;
    padding: 14px 16px; text-align: left; color: #3B3A4E; min-height: 78px; }
QPushButton#projectCard:hover { background: #F4F3FD; border-color: #A9A2F0; }
QListWidget#jobList { background: transparent; border: none; outline: none; }
QListWidget#jobList::item { background: transparent; border: none; }
QTabBar#groupTabs::tab { background: transparent; border: none; border-bottom: 2px solid transparent;
    padding: 6px 2px; margin-right: 18px; color: #676B80; }
QTabBar#groupTabs::tab:selected { color: #2B2A3A; border-bottom-color: #635BDF; font-weight: 700; }
QTabBar#groupTabs::tab:hover { color: #2B2A3A; }
"""


def ai_badges_html(ais, roles=None, colors=None):
    colors = colors or AI_COLORS
    parts = []
    for ai in sorted(ais, key=lambda key: (list(AI_COLORS).index(key) if key in AI_COLORS else 9)):
        label = AI_LABELS.get(ai, ai)
        if roles and roles.get(ai):
            label += " · " + ", ".join(roles[ai])
        parts.append(f'{icon_html(ai)}<span style="color:{text_color(colors.get(ai, "#7A7F93"))};'
                     f'font-weight:600;">{escape(label)}</span>')
    return " ".join(parts) if parts else '<span style="color:#7A7F93">미분류 · 작업 기록 없음</span>'


def ai_text(ais):
    return ", ".join(AI_LABELS.get(ai, ai) for ai in sorted(ais)) if ais else "미분류"


def fmt_time(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value)
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


DEFAULT_COLUMN_WIDTHS = (48, 160, 110, 110, 64, 110)
MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH = 36, 2000  # drag limits; saved widths are clamped the same way
STATUS_GROUPS = {"completed": "done", "reviewed": "done", "passed": "done", "completed_unverified": "done",
                 "active": "active", "checked": "checked", "needs_repair": "repair"}
STATUS_COLORS = {"done": "#E2F4E7", "active": "#FFF3C9", "checked": "#E2EDFC", "repair": "#FBE3E3",
                 "unknown": "#ECECF1"}
STATUS_LEGEND = (("done", "완료"), ("active", "진행 중"), ("checked", "검사 통과"), ("repair", "수정 필요"),
                 ("unknown", "미상"))


class StatusDelegate(QStyledItemDelegate):
    """Neutral rows, persistent status markers and AI identities with original icons."""

    def paint(self, painter, option, index):
        group = index.siblingAtColumn(0).data(GROUP_ROLE)
        custom = index.column() == 2 or (index.column() == 3 and group)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if custom:
            opt.text = ""
            opt.icon = ai_icon("")
            option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, option.widget)
        else:
            super().paint(painter, option, index)
        painter.save()
        if group and index.column() == 0:
            painter.fillRect(QRect(option.rect.left(), option.rect.top() + 4, 4, option.rect.height() - 8),
                             QColor(PILL_TEXT[group]))
        if index.column() == 3 and group:
            rect = option.rect.adjusted(8, 4, -8, -4)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(STATUS_COLORS[group]))
            painter.drawRoundedRect(QRectF(rect), 6, 6)
            painter.setFont(option.font)
            painter.setPen(QColor(PILL_TEXT[group]))
            label = index.data() or ""
            if index.siblingAtColumn(0).data(ROLE)[0] == "job":
                label = dict(STATUS_LEGEND)[group]
            text = option.fontMetrics.elidedText(label, Qt.TextElideMode.ElideRight, rect.width() - 12)
            painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, text)
        elif index.column() == 2:
            colors = self.parent().window().ai_colors
            ais = index.siblingAtColumn(0).data(AI_ROLE) or []
            left = option.rect.left() + 8
            for ai in ais:
                if left + 18 > option.rect.right() - 4:
                    break
                ai_icon(ai).paint(painter, QRect(left, option.rect.center().y() - 9, 18, 18))
                left += 24
            painter.setFont(option.font)
            painter.setPen(QColor(text_color(colors.get(ais[0], "#7A7F93")) if ais else "#676B80"))
            rect = QRect(left, option.rect.top(), max(0, option.rect.right() - left - 8), option.rect.height())
            label = "" if len(ais) > 1 else (index.data() or "")
            text = option.fontMetrics.elidedText(label, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, text)
        painter.restore()
        if index.column() < index.model().columnCount() - 1:
            draw_column_separator(painter, option.rect)


class FileList(QTreeWidget):
    """Empty-state copy is an overlay, so it never becomes a selectable file row."""
    resized = Signal()
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empty_label = QLabel("표시할 항목이 없습니다\n다른 프로젝트나 검색어를 선택해 보세요.", self.viewport())
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("color:#676B80; padding:24px; background:white;")
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.empty_label.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.empty_label.setGeometry(self.viewport().rect())
        self.resized.emit()


SEPARATOR_COLOR = "#D5D5DE"
SEPARATOR_FRACTION = 0.5  # share of the cell height the column separator covers


def draw_column_separator(painter, rect):
    """Short light-grey vertical line on the right edge of a cell, vertically centred,
    so columns read as separate without boxing the cells in."""
    length = max(6, round(rect.height() * SEPARATOR_FRACTION))
    top = rect.top() + (rect.height() - length) // 2
    painter.save()
    painter.fillRect(rect.right(), top, 1, length, QColor(SEPARATOR_COLOR))
    painter.restore()


class SeparatedHeader(QHeaderView):
    """List header drawing the same short separators between sections."""

    def paintSection(self, painter, rect, logical):
        super().paintSection(painter, rect, logical)
        if self.visualIndex(logical) < self.count() - 1:
            draw_column_separator(painter, rect)


def status_group(job):
    return STATUS_GROUPS.get(job.status, "unknown")


def status_text(job):
    text = STATUS_LABELS.get(job.status, job.status or "미상")
    if job.review_passed is True:
        text += " · 검토 통과"
    elif job.review_passed is False:
        text += " · 검토 미통과"
    return text


def folder_of(project, entry):
    """Folder of entry relative to its project root ('' for the root itself)."""
    folder = entry.path.parent.relative_to(project.path).as_posix()
    return "" if folder == "." else folder


def direct_files_project(key):
    """(key, area, numbered folder, tree label) when the project key names a '(직속 파일)' project:
    output, artifacts, 01_Name or 01_Name/output, 01_Name/artifacts. None otherwise."""
    if key in SCAN_AREAS:
        return key, key, "", "(직속 파일)"
    folder, _, area = key.partition("/")
    if not PROJECT_FOLDER.match(folder) or (area and area not in SCAN_AREAS):
        return None
    return key, area or "app", folder, (area + " (직속 파일)").strip()


TABS = ("jobs", "results", "folders")  # tabs of a project page
RECENT_JOBS = 30
CARD_COLUMNS, CARD_PADDING = 3, 40
CARD_ROWS_SHOWN, CARD_HEIGHT = 3, 128
PILL_TEXT = {"done": "#1E7B3A", "active": "#8A6100", "checked": "#1F5FAE", "repair": "#B42318", "unknown": "#5B5E70"}


def continue_request(job):
    """What to paste into a Claude or Codex chat to pick a job up again. The job folder holds the
    request, goal, acceptance and stage logs, so the path is enough; the rest says where it stopped."""
    lines = [f"`{job.path}` 의 agent_lab 작업 기록(task.json·manifest.json·단계별 로그)을 읽고 이어서 진행해줘. "
             f"작업 ID: {job.id}",
             f"현재 상태: {status_text(job)}"]
    request = next((line.strip() for line in (job.request or "").splitlines() if line.strip()), "")
    if request:
        lines.append("요청: " + (request if len(request) <= 120 else request[:119] + "…"))
    if status_group(job) == "repair":
        lines.append("마지막 검토에서 수정 필요로 끝났으니 지적된 부분부터 고쳐줘.")
    elif status_group(job) == "active":
        lines.append("마지막으로 끝난 단계 다음부터 이어서 해줘.")
    return "\n".join(lines)


def roles_text(job):
    """'Claude 구현 · Codex 검토' from the recorded roles only."""
    return " · ".join(f"{AI_LABELS.get(ai, ai)} {', '.join(labels)}" for ai, labels in job.roles().items())


class CardsArea(QScrollArea):
    """Home card area; tells the window when its width changes so the columns are redone."""
    resized = Signal()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()


class ProjectCard(QPushButton):
    """Native button with wrapping, measured content instead of clipped multiline text."""
    def content_lines(self, width):
        result = []
        for position, text in enumerate(self.text().splitlines()):
            font = QFont(self.font())
            font.setBold(position == 0)
            font.setPointSizeF(10 if position == 0 else 9)
            for line in JobCardDelegate.wrap(text, font, max(40, width - 36), max(40, width - 36)):
                result.append((line, font, QFontMetrics(font).lineSpacing() + 4))
        return result

    def heightForWidth(self, width):
        return max(CARD_HEIGHT, 32 + sum(height for _, _, height in self.content_lines(width)))

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        top = 16
        for position, (line, font, height) in enumerate(self.content_lines(self.width())):
            painter.setFont(font)
            painter.setPen(QColor("#2B2A3A" if position == 0 else "#676B80"))
            painter.drawText(QRect(18, top, max(0, self.width() - 36), height), Qt.AlignmentFlag.AlignVCenter, line)
            top += height


class JobList(QListWidget):
    """Card heights depend on the width (titles and details wrap), so every width change
    lays the rows out again; otherwise taller cards would overlap the rows below."""

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.doItemsLayout()


CARD_KINDS = ("job",)  # list rows drawn as cards; any other kind is a plain group heading


class JobCardDelegate(QStyledItemDelegate):
    """Job rows as cards: the whole title wrapped over as many lines as it needs, then a status
    pill with the AI roles, file count and project. Date rows are plain group headings."""
    HEADER, PAD, GAP, PILL = 34, 16, 10, 24

    def title_width(self):
        return max(80, self.parent().viewport().width() - 2 * self.PAD - 32)

    @staticmethod
    def wrap(text, font, first_width, width):
        """Text wrapped to the given widths (the first line may be narrower): every line is
        returned whole, nothing is elided."""
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        lines = []
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1, width if lines else first_width))
            lines.append(text[line.textStart():line.textStart() + line.textLength()].strip())
        layout.endLayout()
        return lines or [""]

    def title_lines(self, font, text):
        """The whole title wrapped to the card width."""
        width = self.title_width()
        return self.wrap(text, font, width, width)

    @staticmethod
    def small_font(font):
        small = QFont(font)
        small.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        return small

    def pill_width(self, font, info):
        return QFontMetrics(self.small_font(font)).horizontalAdvance(info.get("status", "")) + 18

    def meta_lines(self, font, info):
        """AI roles, file count and project next to the status pill, wrapped below it when the
        card is narrow or the roles are long, so none of them is hidden."""
        width = self.title_width()
        first = width - self.pill_width(font, info) - 8
        if first < 60:  # no useful room beside the pill: start under it
            return [""] + self.wrap(info.get("meta", ""), self.small_font(font), width, width)
        return self.wrap(info.get("meta", ""), self.small_font(font), first, width)

    def sizeHint(self, option, index):
        if (index.data(ROLE) or ("",))[0] == "empty":
            return QSize(0, 112)
        if (index.data(ROLE) or ("",))[0] not in CARD_KINDS:
            return QSize(0, self.HEADER)
        lines = len(self.title_lines(option.font, index.data(Qt.ItemDataRole.DisplayRole) or ""))
        extra = len(self.meta_lines(option.font, index.data(CARD_ROLE) or {})) - 1
        return QSize(0, 6 + 2 * self.PAD + lines * option.fontMetrics.lineSpacing() + self.GAP + self.PILL
                     + extra * QFontMetrics(self.small_font(option.font)).lineSpacing())

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(option.font)
        if (index.data(ROLE) or ("",))[0] not in CARD_KINDS:
            painter.setPen(QColor("#676B80"))
            if (index.data(ROLE) or ("",))[0] == "empty":
                # A specific empty message (a status filter, the unlinked list) replaces the default one.
                message = text if text and text != "작업 기록 없음" else "아직 작업 기록이 없습니다\n다른 프로젝트를 선택해 보세요."
                painter.drawText(option.rect.adjusted(16, 16, -16, -16),
                                 Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, message)
                painter.restore()
                return
            painter.drawText(option.rect.adjusted(6, 0, 0, -5),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, text)
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        card = QRectF(option.rect).adjusted(1.5, 3.5, -1.5, -2.5)
        painter.setPen(QPen(QColor("#A9A2F0" if selected else "#E6E5EF"), 1))
        painter.setBrush(QColor("#EFEDFD" if selected else "#F8F8FC" if hover else "#FFFFFF"))
        painter.drawRoundedRect(card, 8, 8)
        metrics = option.fontMetrics
        width = self.title_width()
        left, top = option.rect.left() + self.PAD + 2, option.rect.top() + 3 + self.PAD
        ais = index.data(AI_ROLE) or []
        if ais:
            colors = self.parent().window().ai_colors
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors.get(ais[0], "#7A7F93")))
            painter.drawRoundedRect(QRectF(card.left(), card.top() + 12, 3, card.height() - 24), 1.5, 1.5)
            ai_icon(ais[0]).paint(painter, QRect(left, top + 1, 20, 20))
            left += 28
        painter.setPen(QColor("#2B2A3A"))
        flags = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        bottom = top
        for line in self.title_lines(option.font, text):
            painter.drawText(QRect(left, bottom, width + 4, metrics.lineSpacing()), flags, line)
            bottom += metrics.lineSpacing()
        info = index.data(CARD_ROLE) or {}
        group = info.get("group", "unknown")
        small = self.small_font(option.font)
        painter.setFont(small)
        small_metrics = QFontMetrics(small)
        status = info.get("status", "")
        pill = QRectF(left, bottom + self.GAP, self.pill_width(option.font, info), self.PILL)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(STATUS_COLORS[group]))
        painter.drawRoundedRect(pill, self.PILL / 2, self.PILL / 2)
        painter.setPen(QColor(PILL_TEXT[group]))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, status)
        painter.setPen(QColor("#676B80"))
        meta = self.meta_lines(option.font, info)
        meta_left = int(pill.right()) + 8
        painter.drawText(QRect(meta_left, int(pill.top()), left + width + 4 - meta_left, self.PILL), flags, meta[0])
        line_top = int(pill.bottom())
        for line in meta[1:]:  # wrapped under the pill at the full card width
            painter.drawText(QRect(left, line_top, width + 4, small_metrics.lineSpacing()), flags, line)
            line_top += small_metrics.lineSpacing()
        painter.restore()


class ImageView(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.label = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.pixmap = QPixmap()

    def show_image(self, path):
        self.pixmap = QPixmap(str(path))
        self.rescale()
        return not self.pixmap.isNull()

    def rescale(self):
        if self.pixmap.isNull():
            self.label.setText("이미지를 열 수 없음")
            return
        width = max(120, self.viewport().width() - 24)
        shown = self.pixmap if self.pixmap.width() <= width else self.pixmap.scaledToWidth(
            width, Qt.TransformationMode.SmoothTransformation)
        self.label.setPixmap(shown)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.rescale()


class ElidedLabel(QLabel):
    """Long root paths must never determine the toolbar's minimum width."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.full_text = ""
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def setText(self, text):
        self.full_text = text
        self.setToolTip(text)
        self.refresh_text()

    def refresh_text(self):
        super().setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideMiddle, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_text()


class AppearanceDialog(QDialog):
    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI 색상 설정")
        self.colors = dict(colors)
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addWidget(QLabel("AI별 강조색", objectName="previewTitle"))
        note = QLabel("이름·배지·강조선에 적용합니다. 아이콘 원본과 작업 상태 색은 유지합니다.", wordWrap=True)
        layout.addWidget(note)
        self.swatches = {}
        for ai in DEFAULT_AI_COLORS:
            row = QHBoxLayout()
            mark = QLabel()
            mark.setPixmap(ai_icon(ai).pixmap(24, 24))
            row.addWidget(mark)
            row.addWidget(QLabel(AI_LABELS.get(ai, "로컬")), 1)
            button = QPushButton()
            button.clicked.connect(lambda checked=False, ai=ai: self.pick_color(ai))
            row.addWidget(button)
            self.swatches[ai] = button
            layout.addLayout(row)
        reset = QPushButton("기본색으로 복원")
        reset.clicked.connect(self.reset_colors)
        layout.addWidget(reset, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("취소")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_swatches()

    def refresh_swatches(self):
        for ai, button in self.swatches.items():
            color = self.colors[ai]
            button.setText(color.upper())
            button.setStyleSheet(f"background: {color}; color: {swatch_text_color(color)};")
            button.setAccessibleName(f"{AI_LABELS.get(ai, '로컬')} 색상 {color}")

    def pick_color(self, ai):
        value = QColorDialog.getColor(QColor(self.colors[ai]), self, f"{AI_LABELS.get(ai, '로컬')} 강조색")
        if value.isValid():
            self.colors[ai] = value.name().upper()
            self.refresh_swatches()

    def reset_colors(self):
        self.colors = dict(DEFAULT_AI_COLORS)
        self.refresh_swatches()


class PreviewPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.path = None
        self.kind = ""
        self.setObjectName("previewCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(0)
        self.title = QLabel("항목을 선택하세요", objectName="previewTitle", wordWrap=True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.meta = QLabel("", objectName="previewMeta", wordWrap=True, textFormat=Qt.TextFormat.RichText)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.meta.linkActivated.connect(window.open_link)
        for label in (self.title, self.meta):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.open_button = QPushButton("기본 앱으로 열기")
        self.folder_button = QPushButton("폴더 열기")
        self.open_button.clicked.connect(self.open_external)
        self.folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch()
        self.stack = QStackedWidget()
        self.browser = QTextBrowser()
        self.browser.document().setDefaultStyleSheet(DOCUMENT_STYLE)
        self.browser.document().setDocumentMargin(0)
        self.browser.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(lambda url: window.open_link(url.toString()))
        self.code = QPlainTextEdit(readOnly=True)
        self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code.setFont(QFont("Consolas", 10))
        self.code.document().setDocumentMargin(12)
        self.image = ImageView()
        for widget in (self.browser, self.code, self.image):
            self.stack.addWidget(widget)
        layout.addWidget(self.title)
        layout.addSpacing(4)
        layout.addWidget(self.meta)
        layout.addSpacing(10)
        layout.addLayout(buttons)
        layout.addSpacing(12)
        rule = QFrame(objectName="previewRule")
        layout.addWidget(rule)
        layout.addSpacing(12)
        layout.addWidget(self.stack, 1)
        layout.addSpacing(12)
        self.safety_note = QLabel("둘러보기는 파일을 변경하지 않습니다.\n파일 관리는 목록의 우클릭 메뉴에서 확인 후 실행합니다.",
                                 objectName="safetyNote", wordWrap=True)
        self.safety_note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.safety_note)
        self.set_path(None)

    def set_path(self, path):
        self.path = Path(path) if path else None
        self.open_button.setVisible(bool(self.path and self.path.is_file()))
        self.open_button.setEnabled(bool(self.path and self.path.is_file() and can_open_externally(self.path)))
        self.open_button.setToolTip("" if self.open_button.isEnabled() else "실행 파일·스크립트는 열지 않음")
        self.folder_button.setEnabled(bool(self.path and self.path.exists()))
        self.folder_button.setVisible(bool(self.path and self.path.exists()))

    def open_external(self):
        if self.path and self.path.is_file() and can_open_externally(self.path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))

    def open_folder(self):
        if self.path:
            folder = self.path if self.path.is_dir() else self.path.parent
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def show_html(self, title, meta, html, path=None, kind="html"):
        self.kind = kind
        self.title.setText(title)
        self.meta.setText(meta)
        self.browser.setHtml(html)
        self.browser.document().setDocumentMargin(0)
        self.stack.setCurrentWidget(self.browser)
        self.set_path(path)

    def show_file(self, entry_path, title, meta):
        result = build_preview(entry_path)
        self.kind = result.kind
        self.title.setText(title)
        note = f" · {escape(result.note)}" if result.note else ""
        self.meta.setText(meta + note)
        self.set_path(entry_path)
        if result.kind == "markdown":
            self.browser.setSearchPaths([str(entry_path.parent)])
            self.browser.setMarkdown(result.text)
            self.browser.document().setDocumentMargin(0)
            self.stack.setCurrentWidget(self.browser)
        elif result.kind == "image":
            if not self.image.show_image(entry_path):
                self.kind = "error"
            self.stack.setCurrentWidget(self.image)
        elif result.kind in ("text", "json", "pdf"):
            self.code.setPlainText(result.text or result.note)
            self.stack.setCurrentWidget(self.code)
        else:
            self.browser.setHtml(f'<p align="center" style="margin-top:32px;color:#676B80">'
                                 f'{escape(result.note or "미리보기 없음")}</p>'
                                 '<p align="center" style="color:#676B80">다른 항목을 선택해 내용을 확인하세요.</p>')
            self.stack.setCurrentWidget(self.browser)
        self.browser.document().setDocumentMargin(0)
        return result


class MainWindow(QMainWindow):
    def __init__(self, root=None, settings=None):
        super().__init__()
        self.settings = settings
        self.ai_colors = load_ai_colors((settings or {}).get("ai_colors"))
        self.custom_columns = self.saved_column_widths() is not None
        self.adjusting_columns = False
        self.root = Path(root) if root else None
        self.index: Index | None = None
        self.conversations: list[chatgpt.Conversation] = []
        self.export_path = None
        self.current_node = None
        self.setWindowTitle("AI 작업 허브")
        available = self.screen().availableGeometry()
        self.setMinimumSize(min(940, available.width()), min(600, max(360, available.height() - 48)))
        self.resize(min(1440, int(available.width() * .94)), min(900, int(available.height() * .90)))
        self.setStyleSheet(STYLE)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame(objectName="toolbar")
        toolbar_layout = QVBoxLayout(bar)
        toolbar_layout.setContentsMargins(16, 12, 16, 12)
        toolbar_layout.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("AI 작업 허브", objectName="brand"))
        self.root_label = ElidedLabel("", objectName="rootLabel")
        row.addWidget(self.root_label, 1)
        self.search = QLineEdit(placeholderText="프로젝트·작업·파일 검색 (Enter: 내용까지)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(200)
        self.search.textChanged.connect(self.on_search_text)
        self.search.returnPressed.connect(self.run_search)
        self.content_check = QCheckBox("파일 내용 포함")
        self.root_button = QPushButton("폴더 선택")
        self.refresh_button = QPushButton("새로고침")
        self.export_button = QPushButton("ChatGPT 내보내기 열기")
        self.export_button.setIcon(ai_icon("chatgpt"))
        self.appearance_button = QPushButton("AI 색상")
        self.appearance_button.clicked.connect(self.choose_appearance)
        self.root_button.clicked.connect(self.choose_root)
        self.refresh_button.clicked.connect(self.reload)
        self.export_button.clicked.connect(self.choose_export)
        for widget in (self.root_button, self.refresh_button, self.appearance_button):
            row.addWidget(widget)
        toolbar_layout.addLayout(row)
        search_row = QHBoxLayout()
        search_row.setSpacing(12)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(self.content_check)
        search_row.addWidget(self.export_button)
        toolbar_layout.addLayout(search_row)
        outer.addWidget(bar)

        splitter = QSplitter()
        self.splitter = splitter
        splitter.setContentsMargins(16, 16, 16, 8)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(8)
        self.tree = QTreeWidget(objectName="nav")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.setMinimumWidth(176)
        self.tree.setIconSize(QSize(20, 20))
        self.tree.currentItemChanged.connect(self.on_tree)
        self.tree.itemClicked.connect(self.on_nav_clicked)
        self.folder_tree = QTreeWidget(objectName="folderTree")
        self.folder_tree.setHeaderHidden(True)
        self.folder_tree.currentItemChanged.connect(self.on_folder_tree)
        self.list = FileList(objectName="itemList")
        self.list.setRootIsDecorated(False)
        separated = SeparatedHeader(Qt.Orientation.Horizontal, self.list)
        separated.setSectionsClickable(True)  # a fresh QHeaderView is not clickable; sorting needs it
        separated.setHighlightSections(False)
        separated.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.list.setHeader(separated)
        self.list.setHeaderLabels(COLUMNS)
        self.list.setSortingEnabled(True)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list.setItemDelegate(StatusDelegate(self.list))
        header = self.list.header()
        # Every column is user-resizable by dragging its header edge; none stretches.
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(MIN_COLUMN_WIDTH)
        header.setMaximumSectionSize(MAX_COLUMN_WIDTH)
        for column, width in enumerate(self.saved_column_widths() or DEFAULT_COLUMN_WIDTHS):
            self.list.setColumnWidth(column, width)
        self.list.headerItem().setTextAlignment(SIZE_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.column_timer = QTimer(self, singleShot=True, interval=400)
        self.column_timer.timeout.connect(self.save_column_widths)
        header.sectionResized.connect(self.on_column_resized)
        self.list.resized.connect(self.fit_default_columns)
        self.list.currentItemChanged.connect(self.on_list)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_list_menu)
        self.trash = fileops.default_trash  # replaced by a fake in the self-test
        self.last_result: fileops.Result | None = None
        self.preview = PreviewPane(self)
        self.current_key = None  # nav key, or "project:…" / "folder:…" picked on the folder tab
        self.current_group = None
        self.group_tab = "jobs"
        self.current_job = None
        self.show_phases = False  # phase logs in the job detail stay folded until asked for
        self.page_path = None
        self.cards = {}
        self.job_list = JobList(objectName="jobList")
        self.job_list.setItemDelegate(JobCardDelegate(self.job_list))
        self.job_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.job_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.job_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.job_list.setMouseTracking(True)
        self.job_list.currentItemChanged.connect(self.on_job_list)
        self.files_box = QWidget()
        files_layout = QVBoxLayout(self.files_box)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.setSpacing(10)
        self.legend_widget = QWidget()
        self.legend_layout = QHBoxLayout(self.legend_widget)
        self.legend_layout.setContentsMargins(0, 0, 0, 0)
        self.legend_layout.setSpacing(6)
        self.legend_layout.addWidget(QLabel("상태", objectName="legendTitle"))
        self.legend_chips = {}
        for group, label in STATUS_LEGEND:
            chip = QLabel(label, objectName="legendChip")
            chip.setStyleSheet(f"background: {STATUS_COLORS[group]};")
            chip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            self.legend_layout.addWidget(chip)
            self.legend_chips[group] = chip
        self.legend_layout.addStretch(1)
        files_layout.addWidget(self.legend_widget)
        self.files_split = QSplitter()
        self.files_split.addWidget(self.folder_tree)
        self.files_split.addWidget(self.list)
        self.files_split.setSizes([170, 600])
        self.files_split.setStretchFactor(1, 1)
        files_layout.addWidget(self.files_split, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.job_list)
        self.stack.addWidget(self.files_box)

        center = QWidget(objectName="center")
        self.center = center
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(8, 0, 8, 0)
        center_layout.setSpacing(12)
        center.setMinimumWidth(300)
        self.preview.setMinimumWidth(340)
        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = QLabel("", objectName="pageTitle", wordWrap=True)
        self.page_meta = QLabel("", objectName="pageMeta", wordWrap=True)
        for label in (self.page_title, self.page_meta):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_meta)
        head.addLayout(titles, 1)
        self.page_folder_button = QPushButton("폴더 열기")
        self.page_folder_button.clicked.connect(self.open_page_folder)
        head.addWidget(self.page_folder_button, 0, Qt.AlignmentFlag.AlignTop)
        center_layout.addLayout(head)
        self.cards_area = CardsArea(objectName="cards")
        self.cards_area.resized.connect(self.layout_cards)
        self.card_columns = 0
        self.cards_area.setWidgetResizable(True)
        self.cards_area.setFrameShape(QFrame.Shape.NoFrame)
        self.cards_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.cards_box = QWidget(objectName="cardsBox")
        self.cards_grid = QGridLayout(self.cards_box)
        self.cards_grid.setContentsMargins(0, 0, 0, 0)
        self.cards_grid.setSpacing(8)
        self.cards_area.setWidget(self.cards_box)
        center_layout.addWidget(self.cards_area)
        self.section_label = QLabel("", objectName="sectionLabel")
        center_layout.addWidget(self.section_label)
        self.tabs = QTabBar(objectName="groupTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        for _ in TABS:
            self.tabs.addTab("")
        self.tabs.currentChanged.connect(self.on_tab)
        center_layout.addWidget(self.tabs)
        center_layout.addWidget(self.stack, 1)
        splitter.addWidget(self.tree)
        splitter.addWidget(center)
        splitter.addWidget(self.preview)
        splitter.setSizes([200, 720, 480])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        outer.addWidget(splitter, 1)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search.setFocus)
        QShortcut(QKeySequence("F5"), self, self.reload)
        self.statusBar().showMessage("준비")
        if self.settings and self.settings.get("chatgpt_export"):
            self.load_export(self.settings["chatgpt_export"], quiet=True)
        if self.root:
            self.reload()
        else:
            self.root_label.setText("작업 폴더를 선택하세요 (agent_lab이 있는 폴더)")
            self.preview.show_html("시작할 준비가 되었습니다", "",
                                   '<h3>작업 폴더를 선택하세요</h3><p>상단의 폴더 선택을 누르면 프로젝트와 결과물을 볼 수 있습니다.</p>')
        self.root_button.setObjectName("primary" if not self.root else "")

    def ai_badges_html(self, ais, roles=None):
        return ai_badges_html(ais, roles, self.ai_colors)

    def choose_appearance(self):
        dialog = AppearanceDialog(self.ai_colors, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.apply_ai_colors(dialog.colors)

    def apply_ai_colors(self, colors):
        selected = self.list.currentItem()
        selected_data = selected.data(0, ROLE) if selected else None
        preview_kind, preview_path = self.preview.kind, self.preview.path
        selected_job = self.current_job if preview_kind == "job" else None
        show_phases = self.show_phases
        self.ai_colors = load_ai_colors(colors)
        if self.settings is not None:
            saved = self.settings.update(ai_colors=self.ai_colors)
            if saved is False:
                QMessageBox.warning(self, "AI 색상", "이 창에는 적용했지만 설정 파일을 저장하지 못했습니다.")
        if self.index:
            for ai in (*AIS, UNKNOWN):
                node = self.nodes.get("ai:" + ai)
                if node:
                    node.setForeground(0, QColor(text_color(self.ai_colors[ai])))
            if self.search.text().strip():
                self.run_search()
            else:
                self.rerender()
            if selected_data:
                for position in range(self.list.topLevelItemCount()):
                    item = self.list.topLevelItem(position)
                    if item.data(0, ROLE) == selected_data:
                        self.list.setCurrentItem(item)
                        break
            if selected_job and selected_job in self.index.jobs:
                self.current_job = selected_job
                self.show_phases = show_phases
                self.show_job(selected_job)
            elif preview_path and preview_kind in ("markdown", "text", "json", "image", "pdf", "binary", "error"):
                self.show_path(preview_path)
        self.list.viewport().update()
        self.job_list.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "cards_area"):
            QTimer.singleShot(0, self, self.layout_cards)

    def update_root_button(self):
        name = "primary" if not self.root else ""
        if self.root_button.objectName() != name:
            self.root_button.setObjectName(name)
            self.root_button.style().unpolish(self.root_button)
            self.root_button.style().polish(self.root_button)

    # ----- data ---------------------------------------------------------
    def reload(self):
        if not self.root:
            return self.choose_root()
        keep = self.current_key
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.index = build_index(self.root)
        finally:
            QApplication.restoreOverrideCursor()
        self.root_label.setText(str(self.index.root))
        self.root_label.setToolTip(str(self.index.root))
        self.update_root_button()
        self.populate_tree()
        if keep and keep != "overview":
            self.restore_node(keep)
        index = self.index
        self.statusBar().showMessage(
            f"작업 {len(index.jobs)}건 · 프로젝트 {len(index.projects)}개 · 파일 {len(index.files)}개"
            + (f" · ChatGPT 대화 {len(self.conversations)}건" if self.conversations else "")
            + (f" · 점검 {len(index.problems)}건" if index.problems else ""))

    def choose_root(self):
        folder = QFileDialog.getExistingDirectory(self, "작업 폴더 선택", str(self.root or Path.home()))
        if folder:
            self.root = Path(folder)
            if self.settings is not None:
                self.settings.update(root=str(self.root))
            self.reload()

    def choose_export(self):
        path, _ = QFileDialog.getOpenFileName(self, "ChatGPT 내보내기 파일", str(Path.home()),
                                              "ChatGPT 내보내기 (*.zip conversations*.json);;모든 파일 (*)")
        if path:
            self.load_export(path)

    def load_export(self, path, quiet=False):
        try:
            self.conversations = chatgpt.load_export(path)
        except chatgpt.ExportError as error:
            if not quiet:
                QMessageBox.warning(self, "ChatGPT 내보내기", str(error))
            return False
        self.export_path = str(path)
        if self.settings is not None:
            self.settings.update(chatgpt_export=str(path))
        if self.index:
            self.reload()
        return True

    # ----- navigation ---------------------------------------------------
    def add_node(self, parent, text, data=None, count=None, color=None):
        label = f"{text}  ({count})" if count is not None else text
        item = QTreeWidgetItem([label])
        item.setData(0, ROLE, data)
        if color:
            item.setForeground(0, QColor(color))
        (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(item)
        return item

    def add_group_node(self, group, count):
        node = self.add_node(self.projects_node, group_label(group), ("group", group), count)
        node.setToolTip(0, group or str(self.index.root))
        node.setData(0, KEY_ROLE, "group:" + group)
        self.nodes["group:" + group] = node
        self.group_nodes[group] = node
        return node

    def add_project_node(self, project, label):
        """Top-level row of the folder tab; only the rows of the shown group are visible."""
        node = self.add_node(self.folder_tree, label, ("project", project.key), len(project.files))
        node.setData(0, GROUP_NAME_ROLE, project.group)
        node.setToolTip(0, f"{project.key}\n관련 작업 {len(project.jobs)}건 · "
                           f"AI: {ai_text(self.index.project_ais(project))}")
        self.nodes["project:" + project.key] = node
        return node

    def populate_tree(self):
        index = self.index
        self.tree.blockSignals(True)
        self.folder_tree.blockSignals(True)
        self.tree.clear()
        self.folder_tree.clear()
        self.nodes = {}
        self.group_nodes = {}
        overview = self.add_node(self.tree, "홈", ("overview", None))
        self.nodes["overview"] = overview

        history = self.add_node(self.tree, "전체 작업 이력", ("history", None), len(index.jobs))
        self.nodes["history"] = history
        for ai in (*AIS, UNKNOWN):
            count = len(index.jobs_for_ai(ai))
            if ai == "chatgpt":
                count += len(index.chatgpt_prompts()) + len(self.conversations)
            if ai == UNKNOWN and not count:
                continue
            self.nodes["ai:" + ai] = self.add_node(history, AI_LABELS[ai], ("ai", ai), count, text_color(self.ai_colors[ai]))
            self.nodes["ai:" + ai].setIcon(0, ai_icon(ai))
        dates = self.add_node(history, "날짜별", None)
        days = defaultdict(list)
        for job in index.sorted_jobs():
            days[job.when.strftime("%Y-%m-%d") if job.when else "날짜 미상"].append(job)
        months = {}
        for day in sorted(days, reverse=True):
            month = day[:7] if day[0].isdigit() else day
            if month not in months:
                months[month] = self.add_node(dates, month, None)
            self.nodes["day:" + day] = self.add_node(months[month], day, ("day", day), len(days[day]))

        cleanup = self.add_node(self.tree, "파일 정리", ("cleanup", None))
        self.nodes["cleanup"] = cleanup
        self.nodes["unclassified"] = self.add_node(cleanup, "미분류 파일", ("unclassified", None),
                                                   len(index.unclassified()))
        stale = self.add_node(cleanup, "오래된 파일", None)
        stale.setToolTip(0, "마지막 수정 시각 기준")
        for days in STALE_DAYS:
            self.nodes[f"stale:{days}"] = self.add_node(stale, STALE_LABELS[days], ("stale", f"{days}"),
                                                        len(stale_files(index, days)))
        days = STALE_DAYS[0]
        self.nodes[f"stale:{days}:unlinked"] = self.add_node(
            stale, f"{STALE_LABELS[days]} · 작업 기록 없음", ("stale", f"{days}:unlinked"),
            len(stale_files(index, days, unlinked_only=True)))
        if index.problems:
            self.nodes["problems"] = self.add_node(cleanup, "점검 필요", ("problems", None), len(index.problems))

        # One row per project group; its folders live on the project page's folder tab.
        self.projects_node = self.add_node(self.tree, "프로젝트", None)
        for group, members in index.groups().items():
            self.add_group_node(group, len(index.group_jobs(group)))
            for project in members:
                name = project.key[len(group) + 1:] if group and project.key != group else (
                    "" if group else project.key)
                label = name if project.recursive else (name + " (직속 파일)").strip()
                self.add_folders(self.add_project_node(project, label), project)
        loose = index.group_jobs(NO_GROUP)
        if loose:
            self.add_group_node(NO_GROUP, len(loose))
        for key, node in self.nodes.items():
            node.setData(0, KEY_ROLE, key)
        for item in (history, cleanup, stale, self.projects_node):
            item.setExpanded(True)
        self.tree.blockSignals(False)
        self.folder_tree.blockSignals(False)
        self.tree.setCurrentItem(overview)
        self.on_tree(overview, None)

    def add_folders(self, parent, project):
        """Child nodes for each sub-folder; counts include nested files."""
        counts = defaultdict(int)
        for entry in project.files:
            folder = folder_of(project, entry)
            parts = folder.split("/") if folder else []
            for depth in range(1, len(parts) + 1):
                counts["/".join(parts[:depth])] += 1
        nodes = {"": parent}
        for folder in sorted(counts):
            head, _, name = folder.rpartition("/")
            key = f"{project.key}|{folder}"
            nodes[folder] = self.add_node(nodes[head], name, ("folder", key), counts[folder])
            self.nodes["folder:" + key] = nodes[folder]

    def restore_node(self, key):
        """Reselect a node after re-indexing. Folder nodes exist only for folders that
        still hold indexed files, so a folder emptied by a move/delete is re-added
        (count 0) while it exists on disk; otherwise its nearest remaining parent is used."""
        if key in self.nodes:
            return self.select_node(key)
        direct = direct_files_project(key[len("project:"):]) if key.startswith("project:") else None
        if direct is not None:
            # A '(직속 파일)' row exists only while its folder (output/, artifacts/, 01_…/,
            # 01_…/output/ …) holds files directly.
            project_key, area, folder, label = direct
            path = self.index.root / project_key
            if not path.is_dir():
                return self.select_node("overview")
            if folder not in self.group_nodes:  # the group held nothing else, so it vanished too
                self.add_group_node(folder, len(self.index.group_jobs(folder)))
            empty = Project(key=project_key, area=area, path=path, recursive=False, group=folder)
            self.index.projects[project_key] = empty
            name = label if folder else f"{project_key} (직속 파일)"
            self.add_project_node(empty, name).setData(0, KEY_ROLE, key)
            return self.select_node(key)
        if not key.startswith("folder:"):
            return self.select_node("overview")
        project_key, _, folder = key[len("folder:"):].partition("|")
        project = self.index.projects.get(project_key)
        parent = self.nodes.get("project:" + project_key)
        if project is None or parent is None:
            return self.select_node("overview")
        parts = folder.split("/")
        while parts and not (project.path / "/".join(parts)).is_dir():
            parts.pop()
        for depth in range(1, len(parts) + 1):
            sub = "/".join(parts[:depth])
            node_key = f"folder:{project_key}|{sub}"
            if node_key not in self.nodes:
                node = self.add_node(parent, parts[depth - 1], ("folder", f"{project_key}|{sub}"), 0)
                node.setData(0, KEY_ROLE, node_key)
                self.nodes[node_key] = node
            parent = self.nodes[node_key]
        return self.select_node(f"folder:{project_key}|{'/'.join(parts)}" if parts else "project:" + project_key)

    def group_of(self, node):
        """Group of a folder-tab node (stored on its top-level project row)."""
        while node.parent() is not None:
            node = node.parent()
        return node.data(0, GROUP_NAME_ROLE)

    def select_node(self, key):
        node = self.nodes.get(key)
        if node is None:
            return False
        if node.treeWidget() is self.folder_tree:
            group = self.group_of(node)
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(self.group_nodes[group])
            self.tree.blockSignals(False)
            self.current_group = group
            self.group_tab = "folders"
            self.clear_search()
            self.render_group(key)
        elif self.tree.currentItem() is node:
            self.on_tree(node)
        else:
            self.tree.setCurrentItem(node)
        return True

    def clear_search(self):
        if self.search.text().strip():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)

    def rerender(self):
        """Draw the current place again (after a search is cleared)."""
        node = self.nodes.get(self.current_key)
        if node is None:
            return
        if node.treeWidget() is self.folder_tree:
            self.render_group(self.current_key)
        else:
            self.on_tree(node)

    def on_nav_clicked(self, _item, _column=0):
        if self.search.text().strip():  # clicking the place already selected leaves the search results
            self.clear_search()
            self.rerender()

    # ----- pages --------------------------------------------------------
    def set_page(self, title, meta="", view="files", path=None, tabs=False, cards=False, folders=False,
                 section=""):
        self.page_title.setText(title)
        self.page_meta.setText(meta)
        self.page_meta.setVisible(bool(meta))
        self.page_path = Path(path) if path else None
        self.page_folder_button.setVisible(self.page_path is not None)
        self.tabs.setVisible(tabs)
        self.cards_area.setVisible(cards)
        self.section_label.setText(section)
        self.section_label.setVisible(bool(section))
        self.folder_tree.setVisible(folders)
        self.view = view
        self.stack.setCurrentWidget(self.job_list if view == "jobs" else self.files_box)

    def open_page_folder(self):
        if self.page_path and self.page_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.page_path)))

    def show_rows(self, jobs=(), files=(), convs=(), projects=False,
                  sort=(DATE_COLUMN, Qt.SortOrder.DescendingOrder)):
        """Fill the table and the job cards with the same rows; the page picks which one shows."""
        self.fill_jobs(jobs, projects)
        return self.fill_list(jobs=jobs, files=files, convs=convs, sort=sort)

    def fill_jobs(self, jobs, projects=False):
        index = self.index
        self.job_list.blockSignals(True)
        self.job_list.clear()
        day = None
        for job in jobs:
            stamp = job.when.strftime("%Y-%m-%d") if job.when else "날짜 미상"
            if stamp != day:
                day = stamp
                head = QListWidgetItem(stamp)
                head.setFlags(Qt.ItemFlag.NoItemFlags)
                head.setData(ROLE, ("day", stamp))
                self.job_list.addItem(head)
            names = (", ".join(group_label(group) for group in index.job_groups(job.id))
                     or group_label(NO_GROUP)) if projects else ""
            parts = [roles_text(job), f"파일 {len(index.job_files(job.id))}개", names]
            item = QListWidgetItem(job.full_title)  # uncut: the card wraps it to the real width
            item.setData(ROLE, ("job", job.id))
            item.setData(AI_ROLE, sorted(job.ais, key=lambda ai: (ai != job.implementer, ai)))
            item.setData(CARD_ROLE, {"status": status_text(job), "group": status_group(job),
                                     "meta": " · ".join(part for part in parts if part)})
            item.setToolTip("\n\n".join(dict.fromkeys(
                text for text in (job.full_title, (job.request or job.goal)[:600]) if text)))
            self.job_list.addItem(item)
        if not jobs:
            empty = QListWidgetItem("작업 기록 없음")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setData(ROLE, ("empty", None))
            self.job_list.addItem(empty)
        self.job_list.blockSignals(False)

    def fill_cards(self):
        """Home: one card per project group."""
        index = self.index
        while self.cards_grid.count():
            widget = self.cards_grid.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self.cards = {}
        for group in index.groups():
            jobs = index.group_jobs(group)
            last = next((job.when for job in jobs if job.when), None)
            repair = sum(1 for job in jobs if status_group(job) == "repair")
            lines = [group_label(group), f"작업 {len(jobs)}건 · 파일 {len(index.group_files(group)):,}개",
                     f"최근 작업 {last:%Y-%m-%d}" if last else "작업 기록 없음", f"수정 필요 {repair}건"]
            card = ProjectCard("\n".join(lines), objectName="projectCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)  # equal columns
            card.setToolTip("\n".join([group or str(index.root), *lines[1:]]))
            card.clicked.connect(lambda _=False, key="group:" + group: self.select_node(key))
            self.cards[group] = card
        self.card_columns = 0
        self.layout_cards()

    def layout_cards(self):
        """Put the cards in as many columns (at most CARD_COLUMNS) as show every card line whole."""
        if not self.cards:
            return
        spacing = self.cards_grid.spacing()
        needed = CARD_PADDING + max(card.fontMetrics().horizontalAdvance(line)
                                    for card in self.cards.values() for line in card.text().splitlines())
        columns = max(1, min(CARD_COLUMNS, (self.cards_area.viewport().width() + spacing) // (needed + spacing)))
        if columns != self.card_columns:
            self.card_columns = columns
            while self.cards_grid.count():
                self.cards_grid.takeAt(0)
            for position, card in enumerate(self.cards.values()):
                self.cards_grid.addWidget(card, position // columns, position % columns)
        rows = (len(self.cards) + columns - 1) // columns
        card_width = max(1, (self.cards_area.viewport().width() - (columns - 1) * spacing) // columns)
        heights = [CARD_HEIGHT] * rows
        for position, card in enumerate(self.cards.values()):
            row = position // columns
            heights[row] = max(heights[row], card.heightForWidth(card_width))
        for position, card in enumerate(self.cards.values()):
            card.setFixedHeight(heights[position // columns])
        self.cards_box.setMinimumHeight(sum(heights) + (rows - 1) * spacing)
        visible_rows = min(rows, 2 if columns == 1 else CARD_ROWS_SHOWN)
        preferred = sum(heights[:visible_rows]) + (visible_rows - 1) * spacing + 2
        self.cards_area.setFixedHeight(min(preferred, max(96, int(self.center.height() * .4))))

    def render_home(self):
        index = self.index
        self.show_rows(jobs=index.sorted_jobs()[:RECENT_JOBS], projects=True)
        self.fill_cards()
        self.set_page("홈", "프로젝트와 최근 작업을 한눈에 확인하세요.", "jobs", cards=bool(self.cards), section="최근 작업")
        self.layout_cards()
        self.show_overview()

    def on_tab(self, position):
        if 0 <= position < len(TABS) and self.current_group is not None:
            self.group_tab = TABS[position]
            self.clear_search()
            self.render_group()

    def render_group(self, folder_key=None):
        """Project page: jobs / results / folders of one group."""
        index, group = self.index, self.current_group
        real = group != NO_GROUP  # the 'no project' group holds jobs only
        jobs = index.group_jobs(group)
        files = index.group_files(group) if real else []
        results = [entry for entry in files if is_deliverable(entry)]
        tab = self.group_tab if real else "jobs"
        self.tabs.blockSignals(True)
        for position, text in enumerate((f"작업 {len(jobs)}", f"결과물 {len(results)}", "폴더")):
            self.tabs.setTabText(position, text)
            self.tabs.setTabVisible(position, real or position == 0)
        self.tabs.setCurrentIndex(TABS.index(tab))
        self.tabs.blockSignals(False)
        last = next((job.when for job in jobs if job.when), None)
        meta = f"작업 {len(jobs)}건 · 파일 {len(files):,}개" + (f" · 마지막 작업 {last:%Y-%m-%d}" if last else "")
        path = (index.root / group if group else index.root) if real else None
        self.current_key = "group:" + group
        if tab == "folders":
            first = None
            for row in range(self.folder_tree.topLevelItemCount()):
                item = self.folder_tree.topLevelItem(row)
                shown = item.data(0, GROUP_NAME_ROLE) == group
                item.setHidden(not shown)
                first = first or (item if shown else None)
            self.set_page(group_label(group), meta, "files", path, tabs=True, folders=True)
            target = self.nodes.get(folder_key) if folder_key else None
            if target is None or target.treeWidget() is not self.folder_tree:
                target = first
            if target is not None:
                self.folder_tree.blockSignals(True)
                self.folder_tree.setCurrentItem(target)
                self.folder_tree.blockSignals(False)
                return self.on_folder_tree(target)
            self.fill_list()
        elif tab == "results":
            self.fill_jobs(jobs)
            self.fill_list(files=results)
            self.set_page(group_label(group), meta, "files", path, tabs=True)
        else:
            self.show_rows(jobs=jobs)
            self.set_page(group_label(group), meta, "jobs", path, tabs=True)
        self.show_group(group, jobs, files, results)

    def on_folder_tree(self, item, _previous=None):
        """Folder tab: a project folder or one of its sub-folders."""
        if item is None or item.data(0, ROLE) is None:
            return
        data = item.data(0, ROLE)
        self.current_node = data
        self.current_key = item.data(0, KEY_ROLE)
        self.clear_search()
        kind, key = data
        index = self.index
        if kind == "project":
            project = index.projects[key]
            jobs = [index.jobs[job_id] for job_id in reversed(project.jobs)]
            self.fill_list(jobs=jobs, files=project.files)
            self.show_project(project)
        else:
            project_key, folder = key.split("|", 1)
            project = index.projects[project_key]
            files = [entry for entry in project.files
                     if (folder_of(project, entry) + "/").startswith(folder + "/")]
            self.fill_list(files=files)
            path = project.path / folder
            jobs = sorted({job_id for entry in files for job_id in entry.jobs}, reverse=True)
            self.preview.show_html(
                f"{project.key}/{folder}", escape(str(path)),
                f"<p>파일 {len(files)}개 (하위 폴더 포함)</p><p>{self.ai_badges_html(self.ais_of(jobs))}</p>"
                + "".join(f'<p><a href="hub:job/{escape(job_id)}">{escape(index.jobs[job_id].title)}</a></p>'
                          for job_id in jobs), path, kind="folder")

    def on_tree(self, item, _previous=None):
        if item is None:
            return
        data = item.data(0, ROLE)
        self.current_node = data
        if data is None:
            return
        self.current_key = item.data(0, KEY_ROLE)
        self.clear_search()
        kind, key = data
        index = self.index
        ascending = (DATE_COLUMN, Qt.SortOrder.AscendingOrder)
        if kind == "overview":
            self.render_home()
        elif kind == "group":
            self.current_group = key
            self.render_group()
        elif kind == "history":
            jobs = index.sorted_jobs()
            self.show_rows(jobs=jobs, projects=True)
            self.set_page("전체 작업 이력", f"작업 {len(jobs)}건 · 최근 순", "jobs")
            self.show_history(jobs)
        elif kind == "ai":
            files = index.chatgpt_prompts() if key == "chatgpt" else []
            convs = self.conversations if key == "chatgpt" else []
            jobs = index.jobs_for_ai(key)
            self.show_rows(jobs=jobs, files=files, convs=convs, projects=True)
            # ChatGPT mixes prompts and conversations with jobs, so it keeps the table.
            self.set_page(AI_LABELS[key], f"참여 작업 {len(jobs)}건", "files" if files or convs else "jobs")
            self.show_ai(key)
        elif kind == "day":
            jobs = [job for job in index.sorted_jobs()
                    if (job.when.strftime("%Y-%m-%d") if job.when else "날짜 미상") == key]
            self.show_rows(jobs=jobs, projects=True)
            self.set_page(key, f"작업 {len(jobs)}건", "jobs")
            self.preview.show_html(key, f"작업 {len(jobs)}건", "".join(
                f'<p><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a><br>{self.ai_badges_html(job.ais, job.roles())}</p>'
                for job in jobs))
        elif kind == "cleanup":
            files = stale_files(index, STALE_DAYS[0], unlinked_only=True)
            self.show_rows(files=files, sort=ascending)
            self.set_page("파일 정리", "오래 수정하지 않았고 작업 기록에도 없는 파일부터 표시", "files")
            links = [("unclassified", "미분류 파일", len(index.unclassified()))]
            links += [(f"stale:{days}", f"오래된 파일 · {STALE_LABELS[days]}", len(stale_files(index, days)))
                      for days in STALE_DAYS]
            if index.problems:
                links.append(("problems", "점검 필요", len(index.problems)))
            self.preview.show_html(
                "파일 정리", f"{STALE_LABELS[STALE_DAYS[0]]} · 작업 기록 없음 {len(files)}개 · "
                             f"합계 {human_size(sum(entry.size for entry in files))}",
                "<p>정리 후보를 모아 보는 곳. 판단 근거는 마지막 <b>수정</b> 시각이며, 실제로 쓰지 않는 "
                "파일인지는 직접 확인 필요.</p><ul>"
                + "".join(f'<li><a href="hub:node/{key}">{escape(label)}</a> {count}개</li>'
                          for key, label, count in links)
                + "</ul><p>파일을 하나 또는 여러 개 고른 뒤 <b>우클릭</b>해서 복사·이동·휴지통으로 삭제.</p>",
                kind="cleanup")
        elif kind == "unclassified":
            files = index.unclassified()
            self.show_rows(files=files)
            self.set_page("미분류 파일", f"{len(files):,}개", "files")
            self.preview.show_html("미분류 파일", f"{len(files)}개",
                                   "<p>어떤 작업의 task.json 파일 목록에도 없어 AI를 특정할 근거가 없는 파일.</p>"
                                   "<p>프로젝트 단위 관련 작업은 프로젝트 화면에서 확인.</p>")
        elif kind == "stale":
            days, _, flag = key.partition(":")
            files = stale_files(index, int(days), unlinked_only=flag == "unlinked")
            self.show_rows(files=files, sort=ascending)
            total = sum(entry.size for entry in files)
            title = f"오래된 파일 · {STALE_LABELS[int(days)]}" + (" · 작업 기록 없음" if flag else "")
            self.set_page(title, f"파일 {len(files)}개 · 합계 {human_size(total)} · 오래된 순", "files")
            self.preview.show_html(
                title, f"파일 {len(files)}개 · 합계 {human_size(total)}",
                f"<p>마지막 <b>수정</b> 시각이 {STALE_LABELS[int(days)]} 지난 파일, 오래된 순.</p>"
                + ("<p>그중 어떤 작업의 task.json 파일 목록에도 없는 파일만 표시.</p>" if flag else "")
                + "<p style='color:#676B80'>마지막으로 연 시각은 미리보기·백신 검사·OneDrive 동기화만으로도 바뀌어 "
                  "판단 근거로 쓰지 않음. 실제로 쓰지 않는 파일인지는 직접 확인 필요.</p>"
                  "<p>파일을 하나 또는 여러 개 고른 뒤 <b>우클릭</b>해서 복사·이동·휴지통으로 삭제.</p>",
                kind="stale")
        elif kind == "problems":
            self.show_rows()
            self.set_page("점검 필요", f"{len(index.problems)}건", "files")
            self.preview.show_html("점검 필요", f"{len(index.problems)}건",
                                   "<ul>" + "".join(f"<li>{escape(text)}</li>" for text in index.problems) + "</ul>")

    def saved_column_widths(self):
        """Saved widths checked column by column: a bad entry falls back to that column's
        default and out-of-range values are clamped to the header's drag limits, so one
        column never resets the others."""
        widths = (self.settings or {}).get("list_columns")
        if not isinstance(widths, list):
            return None
        result = []
        for column, default in enumerate(DEFAULT_COLUMN_WIDTHS):
            width = widths[column] if column < len(widths) else None
            valid = isinstance(width, int) and not isinstance(width, bool)
            result.append(min(max(width, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH) if valid else default)
        return result

    def save_column_widths(self):
        self.custom_columns = True
        if self.settings is not None:
            self.settings.update(list_columns=[self.list.columnWidth(column) for column in range(len(COLUMNS))])

    def on_column_resized(self, *_):
        if not self.adjusting_columns:
            self.custom_columns = True
            self.column_timer.start()

    def fit_default_columns(self):
        if self.custom_columns:
            return
        width = self.list.viewport().width()
        widths = [48, max(100, width - 404), 94, 92, 72, 98]
        self.adjusting_columns = True
        try:
            for column, value in enumerate(widths):
                self.list.setColumnWidth(column, value)
        finally:
            self.adjusting_columns = False

    def ais_of(self, job_ids):
        found = set()
        for job_id in job_ids:
            found |= self.index.jobs[job_id].ais
        return found

    def fill_list(self, jobs=(), files=(), convs=(), sort=(DATE_COLUMN, Qt.SortOrder.DescendingOrder)):
        self.list.setSortingEnabled(False)
        self.list.clear()
        index = self.index
        rows = []  # (texts, data, tooltip, size or None, timestamp or None, status group or None, size tooltip)
        for job in jobs:
            linked = index.job_files(job.id)
            size = sum(entry.size for entry in linked)
            rows.append((["작업", job.title, ai_text(job.ais), status_text(job), human_size(size), fmt_time(job.when)],
                         ("job", job.id), job.request or job.goal, size, job.when.timestamp() if job.when else None,
                         status_group(job), f"작업 결과 파일 {len(linked)}개 합계"))
        for entry in files:
            # A linked file takes the colour of the most recent job that lists it.
            latest = index.jobs[max(entry.jobs)] if entry.jobs else None
            rows.append((["파일", entry.path.name, ai_text(index.file_ais(entry)),
                          f"작업 {len(entry.jobs)}건" if entry.jobs else ("ChatGPT 프롬프트" if entry.chatgpt_prompt else "미분류"),
                          human_size(entry.size), fmt_time(entry.mtime)],
                         ("file", rel_key(entry.rel)), entry.rel, entry.size, entry.mtime,
                         status_group(latest) if latest else None, ""))
        for conv in convs:
            size = sum(len(message.text.encode("utf-8")) for message in conv.messages)
            rows.append((["대화", conv.title, "ChatGPT", f"메시지 {len(conv.messages)}", human_size(size),
                          fmt_time(conv.when)],
                         ("conv", conv.id), conv.title, size, conv.when.timestamp() if conv.when else None,
                         None, "대화 텍스트 크기"))
        items = []
        for values, data, tip, size, stamp, group, size_tip in rows:
            item = SortItem(values)
            # Keep year/full precision available without spending a wide column on every row.
            if stamp is not None:
                item.setToolTip(DATE_COLUMN, fmt_time(stamp))
                item.setText(DATE_COLUMN, datetime.fromtimestamp(stamp).strftime("%m-%d %H:%M"))
            item.setData(0, ROLE, data)
            if data[0] == "job":
                ais = index.jobs[data[1]].ais
            elif data[0] == "file":
                entry = index.files[data[1]]
                ais = index.file_ais(entry) or ({"chatgpt"} if entry.chatgpt_prompt else set())
            else:
                ais = {"chatgpt"}
            item.setData(0, AI_ROLE, sorted(ais))
            item.setToolTip(2, ai_text(ais))
            item.setToolTip(1, tip[:600])
            item.setToolTip(3, values[3])
            item.setTextAlignment(SIZE_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if size_tip:
                item.setToolTip(SIZE_COLUMN, size_tip)
            if size is not None:
                item.setData(SIZE_COLUMN, SORT_ROLE, float(size))
            if stamp is not None:
                item.setData(DATE_COLUMN, SORT_ROLE, float(stamp))
            if group:
                item.setData(0, GROUP_ROLE, group)  # painted by StatusDelegate
            items.append(item)
        self.list.addTopLevelItems(items)
        self.list.empty_label.setGeometry(self.list.viewport().rect())
        self.list.empty_label.setVisible(not items)
        self.list.setSortingEnabled(True)
        self.list.sortByColumn(*sort)
        return len(items)

    # ----- file operations ----------------------------------------------
    def selected_entries(self):
        entries = []
        for item in self.list.selectedItems():
            kind, key = item.data(0, ROLE)
            if kind == "file" and key in self.index.files:
                entries.append(self.index.files[key])
        return entries

    def show_list_menu(self, position):
        menu = self.build_list_menu()
        if menu is not None:
            menu.exec(self.list.viewport().mapToGlobal(position))

    def build_list_menu(self):
        """Right-click menu for the selected files (the only way to copy, move or delete)."""
        entries = self.selected_entries()
        if not entries:
            return None
        menu = QMenu(self)
        count = f" ({len(entries)}개)" if len(entries) > 1 else ""
        if len(entries) == 1:
            single = entries[0].path
            open_action = menu.addAction("기본 앱으로 열기",
                                         lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(single))))
            open_action.setEnabled(can_open_externally(single))
            menu.addAction("폴더 열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(single.parent))))
            menu.addSeparator()
        for op, label in FILE_OPS:
            if op == "trash":
                menu.addSeparator()
            action = menu.addAction(f"{label}{count}", lambda op=op: self.file_action(op))
            action.setData(op)
        return menu

    def file_action(self, op, entries=None, dest=None, confirm=True):
        """Copy/move/trash the selected files. Returns fileops.Result or None if cancelled."""
        entries = self.selected_entries() if entries is None else entries
        if not entries or not self.index:
            return None
        if op in ("copy", "move") and dest is None:
            dest = self.pick_folder(op, entries[0].path.parent)
            if dest is None:
                return None
        if confirm and not self.confirm_action(op, entries, dest):
            return None
        paths = [entry.path for entry in entries]
        running = fileops.running_executable()
        root = self.index.root
        if op == "copy":
            result = fileops.copy_files(paths, Path(dest), root, running)
        elif op == "move":
            result = fileops.move_files(paths, Path(dest), root, running)
        else:
            result = fileops.trash_files(paths, root, running, self.trash)
        self.last_result = result
        self.reload()
        self.statusBar().showMessage(result.summary())
        if confirm and (result.skipped or result.failed):
            QMessageBox.warning(self, fileops.LABELS[op], result.summary() + "\n\n" + result.details())
        return result

    def pick_folder(self, op, start):
        folder = QFileDialog.getExistingDirectory(self, f"{fileops.LABELS[op]}할 폴더 선택", str(start))
        return Path(folder) if folder else None

    def confirm_action(self, op, entries, dest):
        names = "\n".join(f"  · {entry.rel}" for entry in entries[:10])
        if len(entries) > 10:
            names += f"\n  외 {len(entries) - 10}개"
        total = human_size(sum(entry.size for entry in entries))
        if op == "trash":
            text = f"파일 {len(entries)}개({total})를 Windows 휴지통으로 보냅니다.\n휴지통에서 복원할 수 있습니다."
        else:
            text = f"파일 {len(entries)}개({total})를 다음 폴더로 {fileops.LABELS[op]}합니다.\n{dest}"
            text += "\n같은 이름이 있으면 덮어쓰지 않고 '이름 (2)' 형식으로 저장합니다."
        linked = [entry for entry in entries if entry.jobs]
        if linked and op != "copy":
            text += (f"\n\n주의: 작업 기록에 연결된 파일 {len(linked)}개가 포함되어 있습니다. "
                     "이동·삭제하면 해당 작업 화면에서 '현재 없음'으로 표시됩니다.")
        box = QMessageBox(QMessageBox.Icon.Warning if op == "trash" else QMessageBox.Icon.Question,
                          fileops.LABELS[op], text + "\n\n" + names, parent=self)
        ok = box.addButton(fileops.LABELS[op], QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)  # Enter cancels; the action needs a deliberate click
        box.exec()
        return box.clickedButton() is ok

    def on_list(self, item, _previous=None):
        if item is None:
            return
        kind, key = item.data(0, ROLE)
        {"job": self.show_job, "file": self.show_file, "conv": self.show_conversation}[kind](key)

    def on_job_list(self, item, _previous=None):
        if item is not None and (item.data(ROLE) or ("",))[0] == "job":
            self.show_job(item.data(ROLE)[1])

    # ----- search -------------------------------------------------------
    def on_search_text(self, text):
        if text.strip():
            self.run_search(content=False)
        else:
            self.rerender()

    def run_search(self, content=None):
        query = self.search.text().strip().lower()
        if not query or not self.index:
            return 0
        content = self.content_check.isChecked() if content is None else content
        index = self.index
        jobs = [job for job in index.sorted_jobs()
                if query in f"{job.id}\n{job.request}\n{job.goal}".lower()]
        files = [entry for entry in index.files.values() if query in entry.rel.lower()]
        if content:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                found = {entry.rel for entry in files}
                files += [entry for entry in search_content(index.files.values(), query) if entry.rel not in found]
            finally:
                QApplication.restoreOverrideCursor()
        convs = [conv for conv in self.conversations
                 if query in conv.title.lower() or (content and any(query in m.text.lower() for m in conv.messages))]
        count = self.show_rows(jobs=jobs, files=files, convs=convs, projects=True)
        self.set_page("검색 결과", f"'{query}' {count}건" + (" (내용 포함)" if content else ""), "files")
        self.statusBar().showMessage(f"'{query}' 검색 결과 {count}건" + (" (내용 포함)" if content else ""))
        return count

    # ----- previews -----------------------------------------------------
    def open_link(self, link):
        if link.startswith("hub:job/"):
            self.show_job(link[len("hub:job/"):])
        elif link.startswith("hub:file/"):
            self.show_path(Path(unquote(link[len("hub:file/"):])))
        elif link.startswith("hub:node/"):
            self.select_node(link[len("hub:node/"):])
        elif link.startswith("hub:continue/"):
            self.copy_continue_request(link[len("hub:continue/"):])
        elif link == "hub:toggle/phases" and self.current_job in self.index.jobs:
            self.show_phases = not self.show_phases
            self.show_job(self.current_job)

    def copy_continue_request(self, job_id):
        job = self.index.jobs.get(job_id) if self.index else None
        if job is None:
            return
        QApplication.clipboard().setText(continue_request(job))
        self.statusBar().showMessage("이어가기 요청을 복사했습니다 · Claude·Codex 채팅에 붙여 넣으세요")

    def show_path(self, path):
        entry = self.index.files.get(rel_key(path.relative_to(self.index.root).as_posix())) \
            if self.index and path.is_relative_to(self.index.root) else None
        if entry is not None:
            return self.show_file(rel_key(entry.rel))
        return self.preview.show_file(path, path.name, escape(str(path)))

    def file_link(self, path, label=None):
        return f'<a href="hub:file/{quote(str(path), safe="")}">{escape(label or path.name)}</a>'

    def show_file(self, key):
        entry = self.index.files[key]
        jobs = [self.index.jobs[job_id] for job_id in entry.jobs]
        links = " ".join(f'<a href="hub:job/{escape(job.id)}">{escape(job.id)}</a>' for job in jobs)
        roles = {}
        for job in jobs:
            for ai, labels in job.roles().items():
                roles.setdefault(ai, [])
                roles[ai] += [label for label in labels if label not in roles[ai]]
        ais = self.index.file_ais(entry)
        if entry.chatgpt_prompt:
            roles.setdefault("chatgpt", []).append("프롬프트 대상")
        meta = (f"{escape(entry.rel)} · {human_size(entry.size)} · {fmt_time(entry.mtime)}<br>"
                f"{self.ai_badges_html(ais, roles)}" + (f"<br>작업: {links}" if links else ""))
        return self.preview.show_file(entry.path, entry.name, meta)

    def show_job(self, job_id):
        job = self.index.jobs[job_id]
        if job_id != self.current_job:
            self.show_phases = False  # phase logs start folded for every job
        self.current_job = job_id
        root = self.index.root
        rows, steps = [], []
        for phase in job.phases:
            who = AI_LABELS.get(phase.provider, phase.provider) + (f" ({phase.model})" if phase.model else "")
            color = text_color(self.ai_colors.get(phase.provider, "#7A7F93"))
            action = ACTION_LABELS.get(phase.action, phase.action)
            steps.append(f'{escape(action)} <span style="color:{color}"><b>{escape(who)}</b></span>')
            files = " · ".join(self.file_link(path) for path in phase.files[:12])
            notes = escape(phase.notes[:400] + ("…" if len(phase.notes) > 400 else ""))
            error = f'<br><span style="color:#B42318">{escape(phase.error[:300])}</span>' if phase.error else ""
            rows.append(f'<tr><td style="padding:6px 12px 6px 0;vertical-align:top"><b>{escape(phase.name)}</b></td>'
                        f'<td style="padding:6px 12px;vertical-align:top">{escape(action)}</td>'
                        f'<td style="padding:6px 12px;vertical-align:top;color:{color}"><b>{escape(who)}</b></td>'
                        f'<td style="padding:6px 12px;vertical-align:top">{escape(STATUS_LABELS.get(phase.outcome, phase.outcome))}'
                        f'{"<br><span style=color:#676B80>" + notes + "</span>" if notes else ""}{error}'
                        f'{"<br>" + files if files else ""}</td></tr>')
        task_files = []
        for item in job.files:
            key = self.index.resolve(item)  # old paths follow moved-folder aliases
            entry = self.index.files.get(key)
            path = entry.path if entry else (root / item if key == rel_key(item) else root / key)
            task_files.append(f"<li>{self.file_link(path, item)}</li>" if path.exists()
                              else f'<li>{escape(item)} <span style="color:#B42318">(현재 없음)</span></li>')
        acceptance = "".join(f"<li><b>{escape(str(item.get('id', '')))}</b> {escape(str(item.get('description', '')))}</li>"
                             for item in job.acceptance)
        checks = "".join(f"<li><code>{escape(' '.join(map(str, check)) if isinstance(check, list) else str(check))}</code></li>"
                         for check in job.checks)
        extra = []
        if job.summary:
            extra.append(self.file_link(job.summary, "WORK_SUMMARY.md"))
        extra.append(self.file_link(job.path / "manifest.json", "manifest.json"))
        problems = "".join(f'<p style="color:#B42318">{escape(text)}</p>' for text in job.problems)
        groups = ", ".join(group_label(group) for group in self.index.job_groups(job_id)) or "프로젝트 미지정"
        verdict = [status_text(job)]
        if job.checks_passed is not None:
            verdict.append(f"검사 {'통과' if job.checks_passed else '실패'}")
        counts = defaultdict(int)
        for phase in job.phases:
            counts[phase.action] += 1
        verdict += [f"{ACTION_LABELS[action]} {counts[action]}회" for action in ("check", "review") if counts[action]]
        toggle = (f'<a href="hub:toggle/phases">{"단계별 로그 접기" if self.show_phases else "단계별 로그 보기"}</a>'
                  f' <span style="color:#676B80">({len(job.phases)}단계)</span>')
        detail = (f"<table>{''.join(rows) or '<tr><td>기록 없음</td></tr>'}</table>" if self.show_phases else "")
        resume = (f'<p><a href="hub:continue/{escape(job.id)}">이어가기 요청 복사</a><br>'
                  '<span style="color:#676B80">복사한 요청을 Claude·Codex 채팅에 붙여 넣으면 '
                  '이 작업 기록을 읽고 이어서 진행합니다.</span></p>')
        html = (f"{resume}{problems}<h3>요청 원문</h3><p style='white-space:pre-wrap'>{escape(job.request) or '없음'}</p>"
                f"<h3>결과 파일</h3><ul>{''.join(task_files) or '<li>없음</li>'}</ul>"
                f"<h3>검사와 검토</h3><p>{escape(' · '.join(verdict))}</p>"
                f"<p>{self.ai_badges_html(job.ais, job.roles())}</p>"
                f"<p>{' → '.join(steps) or '단계 기록 없음'}</p>"
                f"<p style='color:#676B80'>역할은 manifest의 implementer와 단계별 model 기록만 근거로 표시.</p>"
                f"<p>{toggle}</p>{detail}"
                f"<h3>목표</h3><p style='white-space:pre-wrap'>{escape(job.goal) or '없음'}</p>"
                f"<h3>완료 기준</h3><ul>{acceptance or '<li>없음</li>'}</ul>"
                f"<h3>검사 명령</h3><ul>{checks or '<li>없음</li>'}</ul>"
                f"<p>{' · '.join(extra)}</p>")
        meta = (f"{escape(groups)} · {escape(fmt_time(job.when) or '날짜 미상')} · {escape(job.id)} · "
                f"{escape(job.mode or '모드 미상')}/{escape(job.complexity or '-')} · {escape(status_text(job))}"
                + (f" · 검사 {'통과' if job.checks_passed else '실패'}" if job.checks_passed is not None else ""))
        self.preview.show_html(job.title, meta, html, job.path, kind="job")
        return html

    def show_conversation(self, conv_id):
        conv = next(conv for conv in self.conversations if conv.id == conv_id)
        self.preview.browser.setSearchPaths([])
        self.preview.show_html(conv.title, f"ChatGPT 대화 · 메시지 {len(conv.messages)} · {fmt_time(conv.when)}",
                               "", Path(self.export_path) if self.export_path else None, kind="conversation")
        self.preview.browser.setMarkdown(chatgpt.to_markdown(conv))
        self.preview.browser.document().setDocumentMargin(0)

    def show_overview(self):
        index = self.index
        cards = []
        for ai in AIS:
            jobs = index.jobs_for_ai(ai)
            if ai == "chatgpt":
                detail = (f"프롬프트 파일 {len(index.chatgpt_prompts())}개 · 대화 {len(self.conversations)}건"
                          + ("" if self.conversations else "<br>상단 'ChatGPT 내보내기 열기'로 대화 가져오기"))
            else:
                implemented = sum(1 for job in jobs if job.implementer == ai)
                detail = f"참여 작업 {len(jobs)}건 · 구현 {implemented}건 · 계획/검토 {len(jobs) - implemented}건"
            cards.append(f'<p style="margin-top:18px;margin-bottom:4px">{icon_html(ai, 22)}'
                         f'<a href="hub:node/ai:{ai}" style="color:{text_color(self.ai_colors[ai])};'
                         f'font-size:12pt;font-weight:700;text-decoration:none">{AI_LABELS[ai]}</a></p>'
                         f'<p style="margin-bottom:16px">{detail}</p>')
        recent = "".join(f'<li><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a> '
                         f'<span style="color:#676B80">{fmt_time(job.when)}</span></li>'
                         for job in index.sorted_jobs()[:8])
        html = ('<h3 style="margin-top:0">AI별 참여</h3>' + "".join(cards)
                + "<h3>최근 작업</h3>"
                + (f"<ul>{recent}</ul>" if recent else '<p style="color:#676B80">아직 작업 기록이 없습니다.</p>')
                + f"<p style='color:#676B80'>미분류 파일 {len(index.unclassified()):,}개</p>")
        self.preview.show_html("홈", escape(str(index.root)), html, index.root, kind="overview")

    def show_history(self, jobs):
        counts = defaultdict(int)
        for job in jobs:
            counts[status_group(job)] += 1
        summary = " · ".join(f"{label} {counts[group]}건" for group, label in STATUS_LEGEND if counts[group])
        self.preview.show_html("전체 작업 이력", f"작업 {len(jobs)}건",
                               f"<p>{escape(summary) or '작업 기록 없음'}</p>"
                               "<p>작업을 고르면 요청, 결과 파일, 검사·검토 결과를 표시.</p>"
                               "<p style='color:#676B80'>왼쪽에서 AI별·날짜별로 좁혀 볼 수 있음.</p>", kind="history")

    def show_group(self, group, jobs, files, results):
        index = self.index
        ais = set()
        for job in jobs:
            ais |= job.ais
        linked = sum(1 for entry in files if entry.jobs)
        readme = index.files.get(rel_key(f"{group}/README.md")) if group and group != NO_GROUP else None
        recent = "".join(f'<li><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a> '
                         f'<span style="color:#676B80">{fmt_time(job.when)}</span></li>' for job in jobs[:5])
        html = (f"<p>{self.ai_badges_html(ais)}</p>"
                f"<p>작업 {len(jobs)}건 · 파일 {len(files):,}개 · 결과물 {len(results):,}개 · "
                f"작업과 직접 연결된 파일 {linked:,}개</p>"
                f"<h3>최근 작업</h3><ul>{recent or '<li>작업 기록 없음</li>'}</ul>"
                "<p style='color:#676B80'>이 프로젝트의 작업은 그 작업의 파일 목록에 이 프로젝트 폴더의 파일이 "
                "있다는 뜻이며, 폴더의 모든 파일을 그 AI가 만들었다는 근거는 아님. 결과물은 문서·실행 파일·"
                "이미지처럼 열어 볼 파일만 모은 것이고 검증·테스트·기록 폴더는 제외.</p>")
        if readme is not None:
            html += f"<p>{self.file_link(readme.path, 'README.md 보기')}</p>"
        path = (index.root / group if group else index.root) if group != NO_GROUP else None
        self.preview.show_html(group_label(group), escape(str(path)) if path else "", html, path, kind="group")

    def show_ai(self, ai):
        index = self.index
        jobs = index.jobs_for_ai(ai)
        counts = defaultdict(int)
        for job in jobs:
            for label in job.roles().get(ai, []):
                counts[label] += 1
        summary = " · ".join(f"{label} {count}건" for label, count in counts.items()) or "작업 기록 없음"
        extra = ""
        if ai == "chatgpt":
            extra = (f"<p>프롬프트 파일 {len(index.chatgpt_prompts())}개, 가져온 대화 {len(self.conversations)}건.</p>"
                     "<p style='color:#676B80'>ChatGPT 웹 대화는 로컬 기록이 없어 데이터 내보내기 파일을 열어야 표시.</p>")
        self.preview.show_html(AI_LABELS[ai], summary,
                               f'<p>{self.ai_badges_html({ai})}</p><p>{escape(summary)}</p>{extra}', kind="ai")

    def show_project(self, project):
        index = self.index
        jobs = [index.jobs[job_id] for job_id in reversed(project.jobs)]
        linked = sum(1 for entry in project.files if entry.jobs)
        readme = next((entry for entry in project.files if entry.path.parent == project.path
                       and entry.name.lower() == "readme.md"), None)
        html = (f"<p>{self.ai_badges_html(index.project_ais(project))}</p>"
                f"<p>파일 {len(project.files)}개{' (일부만 표시)' if project.truncated else ''} · "
                f"작업과 직접 연결된 파일 {linked}개</p>"
                "<h3>관련 작업</h3><ul>" + ("".join(
                    f'<li><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a> {self.ai_badges_html(job.ais, job.roles())}</li>'
                    for job in jobs) or "<li>작업 기록 없음 · AI 미분류</li>") + "</ul>"
                "<p style='color:#676B80'>프로젝트 관련 작업은 그 작업의 파일 목록이 이 폴더를 포함한다는 뜻이며, "
                "폴더의 모든 파일을 그 AI가 만들었다는 근거는 아님.</p>")
        if readme:
            html += f"<p>{self.file_link(readme.path, 'README.md 보기')}</p>"
        self.preview.show_html(project.key, escape(str(project.path)), html, project.path, kind="project")


class Settings(dict):
    """Small JSON settings file stored outside the scanned workspace."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                super().update(data)
        except (OSError, ValueError):
            pass

    def update(self, **values):
        super().update(values)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(dict(self), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp, self.path)
            return True
        except OSError:
            return False


def default_settings_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path.home() / ".local" / "share"
    return base / "AIHub" / "settings.json"
