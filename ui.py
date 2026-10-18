"""Main window: navigation tree, item list and preview pane.

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

from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QDesktopServices, QPixmap, QFont, QKeySequence, QShortcut, QColor
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QTextBrowser, QPlainTextEdit, QStackedWidget, QScrollArea,
    QFileDialog, QCheckBox, QHeaderView, QMessageBox, QApplication, QFrame, QMenu, QAbstractItemView)

import chatgpt
import fileops
from indexer import (AIS, UNKNOWN, AI_LABELS, ACTION_LABELS, STATUS_LABELS, STALE_DAYS, build_index,
                     SCAN_AREAS, search_content, stale_files, rel_key, Index, Project)
from preview import build_preview, can_open_externally, human_size

PURPLE = "#635BDF"
AI_COLORS = {"codex": "#2563EB", "claude": "#C2410C", "chatgpt": "#0E8A6A", UNKNOWN: "#7A7F93", "local": "#7A7F93"}
ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1  # numeric sort key per column
KEY_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # tree node key, used to restore selection
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
QLabel#brand { color: #2B2A3A; font-size: 15px; font-weight: 700; }
QLabel#rootLabel { color: #75798F; }
QLineEdit { background: #F6F6FA; border: 1px solid #E1E0EA; border-radius: 8px; padding: 7px 10px; }
QLineEdit:focus { border-color: #7B72E8; background: white; }
QPushButton { background: white; border: 1px solid #E1E0EA; border-radius: 8px; padding: 7px 12px; color: #3B3A4E; }
QPushButton:hover { background: #F1F0FB; border-color: #CFCBF3; }
QPushButton:disabled { color: #A9ABBB; }
QPushButton#primary { background: #635BDF; color: white; border-color: #635BDF; font-weight: 700; }
QTreeWidget { background: white; border: 1px solid #E6E5EF; border-radius: 10px; padding: 4px; outline: none; }
QTreeWidget::item { padding: 5px 4px; border-radius: 6px; }
QTreeWidget::item:hover { background: #F1F0FB; }
QTreeWidget::item:selected { background: #E9E7FB; color: #2B2A3A; }
QHeaderView::section { background: white; border: none; border-bottom: 1px solid #ECEBF3; padding: 6px; color: #75798F; font-weight: 600; }
QTextBrowser, QPlainTextEdit, QScrollArea { background: white; border: 1px solid #E6E5EF; border-radius: 10px; }
QLabel#previewTitle { font-size: 14px; font-weight: 700; color: #2B2A3A; }
QLabel#previewMeta { color: #75798F; }
QSplitter::handle { background: transparent; width: 6px; }
QStatusBar { color: #75798F; }
"""


def ai_badges_html(ais, roles=None):
    parts = []
    for ai in sorted(ais, key=lambda key: (list(AI_COLORS).index(key) if key in AI_COLORS else 9)):
        label = AI_LABELS.get(ai, ai)
        if roles and roles.get(ai):
            label += " · " + ", ".join(roles[ai])
        parts.append(f'<span style="background:{AI_COLORS.get(ai, "#7A7F93")};color:white;'
                     f'padding:2px 6px;border-radius:4px;">&nbsp;{escape(label)}&nbsp;</span>')
    return " ".join(parts) if parts else '<span style="color:#7A7F93">미분류 · 작업 기록 없음</span>'


def ai_text(ais):
    return ", ".join(AI_LABELS.get(ai, ai) for ai in sorted(ais)) if ais else "미분류"


def fmt_time(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value)
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


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


class PreviewPane(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.path = None
        self.kind = ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.title = QLabel("항목을 선택하세요", objectName="previewTitle", wordWrap=True)
        self.meta = QLabel("", objectName="previewMeta", wordWrap=True, textFormat=Qt.TextFormat.RichText)
        self.meta.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self.meta.linkActivated.connect(window.open_link)
        buttons = QHBoxLayout()
        self.open_button = QPushButton("기본 앱으로 열기")
        self.folder_button = QPushButton("폴더 열기")
        self.open_button.clicked.connect(self.open_external)
        self.folder_button.clicked.connect(self.open_folder)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.folder_button)
        buttons.addStretch()
        self.stack = QStackedWidget()
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(lambda url: window.open_link(url.toString()))
        self.code = QPlainTextEdit(readOnly=True)
        self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.code.setFont(QFont("Consolas", 10))
        self.image = ImageView()
        for widget in (self.browser, self.code, self.image):
            self.stack.addWidget(widget)
        layout.addWidget(self.title)
        layout.addWidget(self.meta)
        layout.addLayout(buttons)
        layout.addWidget(self.stack, 1)
        self.set_path(None)

    def set_path(self, path):
        self.path = Path(path) if path else None
        self.open_button.setEnabled(bool(self.path and self.path.is_file() and can_open_externally(self.path)))
        self.open_button.setToolTip("" if self.open_button.isEnabled() else "실행 파일·스크립트는 열지 않음")
        self.folder_button.setEnabled(bool(self.path and self.path.exists()))

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
            self.stack.setCurrentWidget(self.browser)
        elif result.kind == "image":
            if not self.image.show_image(entry_path):
                self.kind = "error"
            self.stack.setCurrentWidget(self.image)
        elif result.kind in ("text", "json", "pdf"):
            self.code.setPlainText(result.text or result.note)
            self.stack.setCurrentWidget(self.code)
        else:
            self.browser.setHtml(f'<p style="color:#75798F">{escape(result.note or "미리보기 없음")}</p>')
            self.stack.setCurrentWidget(self.browser)
        return result


class MainWindow(QMainWindow):
    def __init__(self, root=None, settings=None):
        super().__init__()
        self.settings = settings
        self.root = Path(root) if root else None
        self.index: Index | None = None
        self.conversations: list[chatgpt.Conversation] = []
        self.export_path = None
        self.current_node = None
        self.setWindowTitle("AI 작업 허브")
        self.resize(1440, 860)
        self.setStyleSheet(STYLE)

        central = QWidget(objectName="central")
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame(objectName="toolbar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)
        row.addWidget(QLabel("AI 작업 허브", objectName="brand"))
        self.root_label = QLabel("", objectName="rootLabel")
        self.root_label.setMinimumWidth(80)
        row.addWidget(self.root_label, 1)
        self.search = QLineEdit(placeholderText="이름·작업 요청 검색 (Enter: 내용까지)")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(320)
        self.search.textChanged.connect(self.on_search_text)
        self.search.returnPressed.connect(self.run_search)
        self.content_check = QCheckBox("파일 내용 포함")
        self.root_button = QPushButton("폴더 선택")
        self.refresh_button = QPushButton("새로고침")
        self.export_button = QPushButton("ChatGPT 내보내기 열기")
        self.root_button.clicked.connect(self.choose_root)
        self.refresh_button.clicked.connect(self.reload)
        self.export_button.clicked.connect(self.choose_export)
        for widget in (self.search, self.content_check, self.export_button, self.root_button, self.refresh_button):
            row.addWidget(widget)
        outer.addWidget(bar)

        splitter = QSplitter()
        splitter.setContentsMargins(12, 12, 12, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self.on_tree)
        self.list = QTreeWidget()
        self.list.setRootIsDecorated(False)
        self.list.setHeaderLabels(COLUMNS)
        self.list.setSortingEnabled(True)
        self.list.setUniformRowHeights(True)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.list.header()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column, width in ((0, 52), (2, 100), (3, 100), (SIZE_COLUMN, 72), (DATE_COLUMN, 122)):
            self.list.setColumnWidth(column, width)
        header.setStretchLastSection(False)
        self.list.headerItem().setTextAlignment(SIZE_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.list.currentItemChanged.connect(self.on_list)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.show_list_menu)
        self.trash = fileops.default_trash  # replaced by a fake in the self-test
        self.last_result: fileops.Result | None = None
        self.preview = PreviewPane(self)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.list)
        splitter.addWidget(self.preview)
        splitter.setSizes([280, 560, 600])
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

    # ----- data ---------------------------------------------------------
    def reload(self):
        if not self.root:
            return self.choose_root()
        current = self.tree.currentItem()
        keep = current.data(0, KEY_ROLE) if current is not None else None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.index = build_index(self.root)
        finally:
            QApplication.restoreOverrideCursor()
        self.root_label.setText(str(self.index.root))
        self.root_label.setToolTip(str(self.index.root))
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

    # ----- tree ---------------------------------------------------------
    def add_node(self, parent, text, data=None, count=None, color=None):
        label = f"{text}  ({count})" if count is not None else text
        item = QTreeWidgetItem([label])
        item.setData(0, ROLE, data)
        if color:
            item.setForeground(0, QColor(color))
        (parent.addChild if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem)(item)
        return item

    def populate_tree(self):
        index = self.index
        self.tree.blockSignals(True)
        self.tree.clear()
        self.nodes = {}
        self.area_nodes = {}
        overview =self.add_node(self.tree, "개요", ("overview", None))
        self.nodes["overview"] = overview

        by_ai = self.add_node(self.tree, "AI별", None)
        for ai in (*AIS, UNKNOWN):
            count = len(index.jobs_for_ai(ai))
            if ai == "chatgpt":
                count += len(index.chatgpt_prompts()) + len(self.conversations)
            if ai == UNKNOWN and not count:
                continue
            self.nodes["ai:" + ai] = self.add_node(by_ai, AI_LABELS[ai], ("ai", ai), count, AI_COLORS[ai])

        projects = self.add_node(self.tree, "프로젝트", None)
        self.projects_node = projects
        area_labels = {"output": "output", "artifacts": "artifacts", "app": "앱·도구"}
        for area, label in area_labels.items():
            members = [project for project in index.projects.values() if project.area == area]
            if not members:
                continue
            group = self.add_node(projects, label, None, len(members))
            self.area_nodes[area] = group
            for project in members:
                name = project.key.split("/", 1)[-1] if project.recursive else "(직속 파일)"
                node = self.add_node(group, name, ("project", project.key), len(project.files))
                node.setToolTip(0, f"{project.key}\n관련 작업 {len(project.jobs)}건 · AI: {ai_text(index.project_ais(project))}")
                self.nodes["project:" + project.key] = node
                self.add_folders(node, project)

        dates = self.add_node(self.tree, "날짜별 작업", None)
        days = defaultdict(list)
        for job in index.sorted_jobs():
            days[job.when.strftime("%Y-%m-%d") if job.when else "날짜 미상"].append(job)
        months = {}
        for day in sorted(days, reverse=True):
            month = day[:7] if day[0].isdigit() else day
            if month not in months:
                months[month] = self.add_node(dates, month, None)
            self.nodes["day:" + day] = self.add_node(months[month], day, ("day", day), len(days[day]))

        self.nodes["unclassified"] = self.add_node(self.tree, "미분류 파일", ("unclassified", None),
                                                   len(index.unclassified()))
        stale = self.add_node(self.tree, "오래된 파일", None)
        stale.setToolTip(0, "마지막 수정 시각 기준")
        for days in STALE_DAYS:
            self.nodes[f"stale:{days}"] = self.add_node(stale, STALE_LABELS[days], ("stale", f"{days}"),
                                                        len(stale_files(index, days)))
        days = STALE_DAYS[0]
        self.nodes[f"stale:{days}:unlinked"] = self.add_node(
            stale, f"{STALE_LABELS[days]} · 작업 기록 없음", ("stale", f"{days}:unlinked"),
            len(stale_files(index, days, unlinked_only=True)))
        if index.problems:
            self.nodes["problems"] = self.add_node(self.tree, "점검 필요", ("problems", None), len(index.problems))
        for key, node in self.nodes.items():
            node.setData(0, KEY_ROLE, key)
        for item in (by_ai, projects, dates, stale):
            item.setExpanded(True)
        for month in list(months.values())[:1]:
            month.setExpanded(True)
        self.tree.blockSignals(False)
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
        if key.startswith("project:") and key[len("project:"):] in SCAN_AREAS:
            # The '(직속 파일)' node exists only while output/ or artifacts/ hold files directly.
            area = key[len("project:"):]
            if not (self.index.root / area).is_dir():
                return self.select_node("overview")
            group = self.area_nodes.get(area)
            if group is None:  # the area held only direct files, so its group vanished too
                group = self.add_node(self.projects_node, area, None, 1)
                self.area_nodes[area] = group
                self.projects_node.setExpanded(True)
            group.setExpanded(True)
            empty = Project(key=area, area=area, path=self.index.root / area, recursive=False)
            self.index.projects[area] = empty
            node = self.add_node(group, "(직속 파일)", ("project", area), 0)
            node.setData(0, KEY_ROLE, key)
            self.nodes[key] = node
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

    def select_node(self, key):
        node = self.nodes.get(key)
        if node is not None:
            self.tree.setCurrentItem(node)
        return node is not None

    # ----- list ---------------------------------------------------------
    def on_tree(self, item, _previous=None):
        if item is None:
            return
        data = item.data(0, ROLE)
        self.current_node = data
        if data is None:
            return
        if self.search.text().strip():
            self.search.blockSignals(True)
            self.search.clear()
            self.search.blockSignals(False)
        kind, key = data
        index = self.index
        if kind == "overview":
            self.fill_list(jobs=index.sorted_jobs()[:30])
            self.show_overview()
        elif kind == "ai":
            files = index.chatgpt_prompts() if key == "chatgpt" else []
            convs = self.conversations if key == "chatgpt" else []
            self.fill_list(jobs=index.jobs_for_ai(key), files=files, convs=convs)
            self.show_ai(key)
        elif kind == "project":
            project = index.projects[key]
            jobs = [index.jobs[job_id] for job_id in reversed(project.jobs)]
            self.fill_list(jobs=jobs, files=project.files)
            self.show_project(project)
        elif kind == "folder":
            project_key, folder = key.split("|", 1)
            project = index.projects[project_key]
            files = [entry for entry in project.files
                     if (folder_of(project, entry) + "/").startswith(folder + "/")]
            self.fill_list(files=files)
            path = project.path / folder
            jobs = sorted({job_id for entry in files for job_id in entry.jobs}, reverse=True)
            self.preview.show_html(
                f"{project.key}/{folder}", escape(str(path)),
                f"<p>파일 {len(files)}개 (하위 폴더 포함)</p><p>{ai_badges_html(self.ais_of(jobs))}</p>"
                + "".join(f'<p><a href="hub:job/{escape(job_id)}">{escape(index.jobs[job_id].title)}</a></p>'
                          for job_id in jobs), path, kind="folder")
        elif kind == "day":
            jobs = [job for job in index.sorted_jobs()
                    if (job.when.strftime("%Y-%m-%d") if job.when else "날짜 미상") == key]
            self.fill_list(jobs=jobs)
            self.preview.show_html(key, f"작업 {len(jobs)}건", "".join(
                f'<p><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a><br>{ai_badges_html(job.ais, job.roles())}</p>'
                for job in jobs))
        elif kind == "unclassified":
            files = index.unclassified()
            self.fill_list(files=files)
            self.preview.show_html("미분류 파일", f"{len(files)}개",
                                   "<p>어떤 작업의 task.json 파일 목록에도 없어 AI를 특정할 근거가 없는 파일.</p>"
                                   "<p>프로젝트 단위 관련 작업은 프로젝트 화면에서 확인.</p>")
        elif kind == "stale":
            days, _, flag = key.partition(":")
            files = stale_files(index, int(days), unlinked_only=flag == "unlinked")
            self.fill_list(files=files, sort=(DATE_COLUMN, Qt.SortOrder.AscendingOrder))
            total = sum(entry.size for entry in files)
            self.preview.show_html(
                f"오래된 파일 · {STALE_LABELS[int(days)]}" + (" · 작업 기록 없음" if flag else ""),
                f"파일 {len(files)}개 · 합계 {human_size(total)}",
                f"<p>마지막 <b>수정</b> 시각이 {STALE_LABELS[int(days)]} 지난 파일, 오래된 순.</p>"
                + ("<p>그중 어떤 작업의 task.json 파일 목록에도 없는 파일만 표시.</p>" if flag else "")
                + "<p style='color:#75798F'>마지막으로 연 시각은 미리보기·백신 검사·OneDrive 동기화만으로도 바뀌어 "
                  "판단 근거로 쓰지 않음. 실제로 쓰지 않는 파일인지는 직접 확인 필요.</p>"
                  "<p>파일을 하나 또는 여러 개 고른 뒤 <b>우클릭</b>해서 복사·이동·휴지통으로 삭제.</p>",
                kind="stale")
        elif kind == "problems":
            self.fill_list()
            self.preview.show_html("점검 필요", f"{len(index.problems)}건",
                                   "<ul>" + "".join(f"<li>{escape(text)}</li>" for text in index.problems) + "</ul>")

    def ais_of(self, job_ids):
        found = set()
        for job_id in job_ids:
            found |= self.index.jobs[job_id].ais
        return found

    def fill_list(self, jobs=(), files=(), convs=(), sort=(DATE_COLUMN, Qt.SortOrder.DescendingOrder)):
        self.list.setSortingEnabled(False)
        self.list.clear()
        rows = []  # (texts, data, tooltip, size or None, timestamp or None)
        for job in jobs:
            rows.append((["작업", job.title, ai_text(job.ais), status_text(job), "", fmt_time(job.when)],
                         ("job", job.id), job.request or job.goal, None, job.when.timestamp() if job.when else None))
        for entry in files:
            rows.append((["파일", entry.rel, ai_text(self.index.file_ais(entry)),
                          f"작업 {len(entry.jobs)}건" if entry.jobs else ("ChatGPT 프롬프트" if entry.chatgpt_prompt else "미분류"),
                          human_size(entry.size), fmt_time(entry.mtime)],
                         ("file", rel_key(entry.rel)), entry.rel, entry.size, entry.mtime))
        for conv in convs:
            rows.append((["대화", conv.title, "ChatGPT", f"메시지 {len(conv.messages)}", "", fmt_time(conv.when)],
                         ("conv", conv.id), conv.title, None, conv.when.timestamp() if conv.when else None))
        items = []
        for values, data, tip, size, stamp in rows:
            item = SortItem(values)
            item.setData(0, ROLE, data)
            item.setToolTip(1, tip[:600])
            item.setTextAlignment(SIZE_COLUMN, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if size is not None:
                item.setData(SIZE_COLUMN, SORT_ROLE, float(size))
            if stamp is not None:
                item.setData(DATE_COLUMN, SORT_ROLE, float(stamp))
            items.append(item)
        self.list.addTopLevelItems(items)
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

    # ----- search -------------------------------------------------------
    def on_search_text(self, text):
        if text.strip():
            self.run_search(content=False)
        elif self.tree.currentItem() is not None:
            self.on_tree(self.tree.currentItem())

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
        count = self.fill_list(jobs=jobs, files=files, convs=convs)
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
                f"{ai_badges_html(ais, roles)}" + (f"<br>작업: {links}" if links else ""))
        return self.preview.show_file(entry.path, entry.name, meta)

    def show_job(self, job_id):
        job = self.index.jobs[job_id]
        root = self.index.root
        rows = []
        for phase in job.phases:
            who = AI_LABELS.get(phase.provider, phase.provider) + (f" ({phase.model})" if phase.model else "")
            color = AI_COLORS.get(phase.provider, "#7A7F93")
            files = " · ".join(self.file_link(path) for path in phase.files[:12])
            notes = escape(phase.notes[:400] + ("…" if len(phase.notes) > 400 else ""))
            error = f'<br><span style="color:#B42318">{escape(phase.error[:300])}</span>' if phase.error else ""
            rows.append(f'<tr><td style="padding:4px 8px 4px 0;vertical-align:top"><b>{escape(phase.name)}</b></td>'
                        f'<td style="padding:4px 8px;vertical-align:top">{escape(ACTION_LABELS.get(phase.action, phase.action))}</td>'
                        f'<td style="padding:4px 8px;vertical-align:top;color:{color}"><b>{escape(who)}</b></td>'
                        f'<td style="padding:4px 8px;vertical-align:top">{escape(STATUS_LABELS.get(phase.outcome, phase.outcome))}'
                        f'{"<br><span style=color:#75798F>" + notes + "</span>" if notes else ""}{error}'
                        f'{"<br>" + files if files else ""}</td></tr>')
        task_files = []
        for item in job.files:
            entry = self.index.files.get(rel_key(item))
            path = entry.path if entry else (root / item)
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
        html = (f"{problems}<h3>AI 역할</h3><p>{ai_badges_html(job.ais, job.roles())}</p>"
                f"<p style='color:#75798F'>역할은 manifest의 implementer와 단계별 model 기록만 근거로 표시.</p>"
                f"<h3>요청 원문</h3><p style='white-space:pre-wrap'>{escape(job.request) or '없음'}</p>"
                f"<h3>목표</h3><p style='white-space:pre-wrap'>{escape(job.goal) or '없음'}</p>"
                f"<h3>단계</h3><table>{''.join(rows) or '<tr><td>기록 없음</td></tr>'}</table>"
                f"<h3>완료 기준</h3><ul>{acceptance or '<li>없음</li>'}</ul>"
                f"<h3>검사 명령</h3><ul>{checks or '<li>없음</li>'}</ul>"
                f"<h3>작업 파일</h3><ul>{''.join(task_files) or '<li>없음</li>'}</ul>"
                f"<p>{' · '.join(extra)}</p>")
        meta = (f"{escape(job.id)} · {escape(job.mode or '모드 미상')}/{escape(job.complexity or '-')} · "
                f"{escape(status_text(job))}" + (f" · 검사 {'통과' if job.checks_passed else '실패'}"
                                                  if job.checks_passed is not None else ""))
        self.preview.show_html(job.title, meta, html, job.path, kind="job")
        return html

    def show_conversation(self, conv_id):
        conv = next(conv for conv in self.conversations if conv.id == conv_id)
        self.preview.browser.setSearchPaths([])
        self.preview.show_html(conv.title, f"ChatGPT 대화 · 메시지 {len(conv.messages)} · {fmt_time(conv.when)}",
                               "", Path(self.export_path) if self.export_path else None, kind="conversation")
        self.preview.browser.setMarkdown(chatgpt.to_markdown(conv))

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
            cards.append(f'<p><a href="hub:node/ai:{ai}" style="color:{AI_COLORS[ai]};font-size:15px;font-weight:700;'
                         f'text-decoration:none">{AI_LABELS[ai]}</a><br>{detail}</p>')
        recent = "".join(f'<li><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a> '
                         f'<span style="color:#75798F">{fmt_time(job.when)}</span></li>'
                         for job in index.sorted_jobs()[:8])
        html = ("<h3>AI별 참여</h3>" + "".join(cards)
                + f"<h3>최근 작업</h3><ul>{recent or '<li>없음</li>'}</ul>"
                + f"<p style='color:#75798F'>미분류 파일 {len(index.unclassified())}개 · 둘러보기만으로는 파일을 바꾸지 않음. "
                  "복사·이동·휴지통 삭제는 파일 목록 우클릭에서 확인 후 실행.</p>")
        self.preview.show_html("개요", escape(str(index.root)), html, index.root, kind="overview")

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
                     "<p style='color:#75798F'>ChatGPT 웹 대화는 로컬 기록이 없어 데이터 내보내기 파일을 열어야 표시.</p>")
        self.preview.show_html(AI_LABELS[ai], summary, f"<p>{escape(summary)}</p>{extra}", kind="ai")

    def show_project(self, project):
        index = self.index
        jobs = [index.jobs[job_id] for job_id in reversed(project.jobs)]
        linked = sum(1 for entry in project.files if entry.jobs)
        readme = next((entry for entry in project.files if entry.path.parent == project.path
                       and entry.name.lower() == "readme.md"), None)
        html = (f"<p>{ai_badges_html(index.project_ais(project))}</p>"
                f"<p>파일 {len(project.files)}개{' (일부만 표시)' if project.truncated else ''} · "
                f"작업과 직접 연결된 파일 {linked}개</p>"
                "<h3>관련 작업</h3><ul>" + ("".join(
                    f'<li><a href="hub:job/{escape(job.id)}">{escape(job.title)}</a> {ai_badges_html(job.ais, job.roles())}</li>'
                    for job in jobs) or "<li>작업 기록 없음 · AI 미분류</li>") + "</ul>"
                "<p style='color:#75798F'>프로젝트 관련 작업은 그 작업의 파일 목록이 이 폴더를 포함한다는 뜻이며, "
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
        except OSError:
            pass


def default_settings_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    else:
        base = Path.home() / ".local" / "share"
    return base / "AIHub" / "settings.json"
