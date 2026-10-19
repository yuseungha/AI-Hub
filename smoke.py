"""Self-check used by tests and the packaged EXE (--smoke-test).

Builds a throwaway workspace fixture, drives the real MainWindow and writes a
JSON report of named flags. An optional real workspace is opened read-only.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from urllib.parse import quote

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
JOB_A, JOB_B, JOB_C = "20261010-100000-aaaa1111", "20261011-090000-bbbb2222", "20261012-080000-cccc3333"
CONTENT_TOKEN = "zebra-quokka-7731"


def write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    elif isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def make_fixture(root: Path):
    """Workspace with Codex- and Claude-written jobs, a corrupt job and unlinked files."""
    jobs = root / "agent_lab" / "jobs"
    a = jobs / JOB_A
    logs = str(a).replace("/", "\\")
    write(a / "task.json", {"request": "주간 보고서 웹페이지 만들어줘", "goal": "보고서 페이지 작성",
                            "acceptance": [{"id": "page", "description": "보고서 표시"}],
                            "files": ["output/report/README.md", "output/report/data.json", "output/summary.md"],
                            "checks": [["python", "-c", "print(1)"]]})
    write(a / "manifest.json", {
        "version": 2, "mode": "planned", "complexity": "complex", "implementer": "codex", "status": "completed",
        "checks_passed": True, "review": {"passed": True},
        "history": [{"action": "plan", "logs": logs + "\\01-plan", "provider": "claude", "outcome": "active", "notes": "plan"},
                    {"action": "check", "logs": logs + "\\02-check", "outcome": "checked", "notes": ""},
                    {"action": "review", "logs": logs + "\\03-review", "provider": "claude", "outcome": "reviewed", "notes": ""},
                    {"action": "finish", "logs": logs + "\\04-finish", "outcome": "completed", "notes": "done"}]})
    write(a / "01-plan" / "plan.model.json", {"provider": "claude", "model": "opus"})
    write(a / "01-plan" / "response.md", "# 계획\n\n- 단계 1\n")
    write(a / "02-check" / "checks.json", [{"command": ["python"], "exit_code": 0}])
    write(a / "03-review" / "review.model.json", {"provider": "claude", "model": "sonnet"})
    write(a / "03-review" / "review.json", {"passed": True})
    (a / "04-finish").mkdir(parents=True, exist_ok=True)
    write(a / "WORK_SUMMARY.md", "# Work summary\n")

    b = jobs / JOB_B
    write(b / "task.json", {"request": "차트 도구 수정", "goal": "",
                            "files": ["tool/main.py", "output/report/chart.png", "output/report/gone.txt"]})
    write(b / "manifest.json", {
        "version": 2, "mode": "review", "complexity": "standard", "implementer": "claude", "status": "needs_repair",
        "checks_passed": False,
        "history": [{"action": "check", "logs": str(b / "01-check"), "outcome": "needs_repair", "notes": ""},
                    {"action": "review", "logs": str(b / "02-review"), "outcome": "failed", "notes": "",
                     "error": "auth failed"},
                    {"action": "investigate", "logs": str(b / "03-investigate"), "provider": "claude",
                     "outcome": "investigated", "notes": ""}]})
    write(b / "01-check" / "checks.json", [])
    write(b / "02-review" / "review.model.json", {"provider": "codex", "model": "gpt-6.1-sol"})
    # Model-only record: provider must still come from history.
    write(b / "03-investigate" / "investigate.model.json", {"model": "opus"})

    c = jobs / JOB_C
    write(c / "manifest.json", "{ broken")
    write(jobs / "not-a-job-smoke" / "probe.log", "x")

    out = root / "output" / "report"
    write(out / "README.md", "# 주간 보고서\n\n| 항목 | 값 |\n|---|---|\n| A | 1 |\n")
    write(out / "data.json", {"b": 2, "a": [1, 2]})
    write(out / "chart.png", PNG_1PX)
    write(out / "gpt-revision-prompt.md", "# ChatGPT에 보낼 수정 프롬프트\n")
    write(out / "notes.txt", f"메모 {CONTENT_TOKEN}\n")
    write(out / "node_modules" / "pkg" / "index.js", "module.exports = 1\n")
    write(out / "sub" / "deep.txt", "nested\n")
    write(root / "output" / "summary.md", "# 요약\n")
    write(root / "artifacts" / "top.png", PNG_1PX)
    write(root / "artifacts" / "pack" / "log.txt", "artifact log\n")
    write(root / "tool" / "main.py", "print('tool')\n")
    write(root / "tool" / ".venv" / "lib.py", "x = 1\n")
    write(root / "tmp" / "scratch.txt", "scratch\n")
    return root


def make_export(path: Path):
    conversations = [
        {"id": "conv-1", "title": "보고서 문장 다듬기", "create_time": 1760000000, "update_time": 1760000500,
         "current_node": "m3", "mapping": {
             "root": {"message": None, "parent": None, "children": ["m1"]},
             "m1": {"message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["요약해줘"]},
                                "create_time": 1760000001}, "parent": "root", "children": ["m2", "m2b"]},
             "m2b": {"message": {"author": {"role": "assistant"},
                                 "content": {"content_type": "text", "parts": ["버려진 답변"]}}, "parent": "m1", "children": []},
             "m2": {"message": {"author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["요약 결과"]}},
                    "parent": "m1", "children": ["m3"]},
             "m3": {"message": {"author": {"role": "user"}, "content": {"content_type": "text", "parts": ["고마워"]}},
                    "parent": "m2", "children": []}}},
        {"id": "conv-2", "title": "빈 대화", "create_time": 1750000000, "mapping": {}},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("conversations.json", json.dumps(conversations, ensure_ascii=False))
    return path


def tree_hash(root: Path):
    digest = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def stat_snapshot(index, ignore: Path | None = None):
    """File stats, skipping the report folder this self-check writes into."""
    return {key: (entry.size, entry.mtime) for key, entry in index.files.items()
            if ignore is None or not entry.path.is_relative_to(ignore)}


def list_rows(window):
    return [window.list.topLevelItem(row) for row in range(window.list.topLevelItemCount())]


def select_row(window, kind, key):
    for item in list_rows(window):
        if tuple(item.data(0, 256)) == (kind, key):
            window.list.setCurrentItem(item)
            return True
    return False


def check_fixture(app, work: Path, shots: Path):
    from indexer import rel_key
    from ui import MainWindow, Settings

    root = make_fixture(work / "workspace")
    export = make_export(work / "export" / "chatgpt-export.zip")
    before = tree_hash(root)
    settings = Settings(work / "profile" / "settings.json")
    window = MainWindow(root, settings)
    window.resize(1440, 860)
    window.show()
    app.processEvents()
    index = window.index
    f = {}
    f["jobs_indexed"] = sorted(index.jobs) == [JOB_A, JOB_B, JOB_C]
    f["non_job_folder_skipped"] = "not-a-job-smoke" not in index.jobs
    f["roles_codex_writer"] = index.jobs[JOB_A].roles() == {"codex": ["구현"], "claude": ["계획", "검토"]}
    f["roles_claude_writer"] = index.jobs[JOB_B].roles() == {"claude": ["구현", "조사"], "codex": ["검토"]}
    f["model_only_uses_history"] = [(p.provider, p.model) for p in index.jobs[JOB_B].phases][-1] == ("claude", "opus")
    f["phase_models"] = [(p.name, p.provider, p.model) for p in index.jobs[JOB_A].phases] == [
        ("01-plan", "claude", "opus"), ("02-check", "local", ""), ("03-review", "claude", "sonnet"),
        ("04-finish", "codex", "")]
    f["corrupt_job_unknown"] = index.jobs[JOB_C].implementer == "unknown" and len(index.jobs[JOB_C].problems) == 2
    files = index.files
    readme, chart = files[rel_key("output/report/README.md")], files[rel_key("output/report/chart.png")]
    f["exact_file_links"] = readme.jobs == [JOB_A] and chart.jobs == [JOB_B]
    f["file_ais"] = index.file_ais(readme) == {"codex", "claude"}
    unclassified = {entry.rel for entry in index.unclassified()}
    f["unclassified_not_guessed"] = ("output/report/notes.txt" in unclassified and "artifacts/pack/log.txt" in unclassified
                                     and index.file_ais(files[rel_key("output/report/notes.txt")]) == set())
    f["chatgpt_prompt_detected"] = [entry.rel for entry in index.chatgpt_prompts()] == ["output/report/gpt-revision-prompt.md"]
    f["excluded_dirs"] = not any(part in key for key in files for part in ("node_modules", ".venv", "tmp/"))
    f["referenced_app_scanned"] = "tool" in index.projects and rel_key("tool/main.py") in files
    f["project_jobs"] = index.projects["output/report"].jobs == [JOB_A, JOB_B]
    f["direct_files_indexed"] = ([entry.rel for entry in index.projects["output"].files] == ["output/summary.md"]
                                 and index.projects["output"].jobs == [JOB_A]
                                 and [entry.rel for entry in index.projects["artifacts"].files] == ["artifacts/top.png"]
                                 and files[rel_key("output/summary.md")].jobs == [JOB_A])

    f["tree_sections"] = all(key in window.nodes for key in (
        "overview", "ai:codex", "ai:claude", "ai:chatgpt", "ai:unknown", "project:output/report", "project:output",
        "folder:output/report|sub",
        "day:2026-10-11", "unclassified", "problems", "stale:90", "stale:180", "stale:365", "stale:90:unlinked"))
    window.select_node("ai:claude")
    app.processEvents()
    f["ai_filter_list"] = {tuple(item.data(0, 256)) for item in list_rows(window)} == {("job", JOB_A), ("job", JOB_B)}
    window.select_node("project:output/report")
    app.processEvents()
    kinds = [item.data(0, 256)[0] for item in list_rows(window)]
    f["project_list"] = kinds.count("job") == 2 and kinds.count("file") == 6
    f["project_preview"] = window.preview.kind == "project"
    window.select_node("folder:output/report|sub")
    app.processEvents()
    f["folder_navigation"] = ([tuple(item.data(0, 256)) for item in list_rows(window)]
                              == [("file", rel_key("output/report/sub/deep.txt"))] and window.preview.kind == "folder")
    window.select_node("project:output/report")
    app.processEvents()

    select_row(window, "job", JOB_A)
    app.processEvents()
    html = window.preview.browser.toHtml()
    f["job_preview"] = (window.preview.kind == "job" and "Claude (opus)" in html and "Claude (sonnet)" in html
                        and "주간 보고서 웹페이지" in html)
    window.grab().save(str(shots / "fixture-job.png"))
    select_row(window, "file", rel_key("output/report/README.md"))
    app.processEvents()
    f["markdown_preview"] = window.preview.kind == "markdown" and "주간 보고서" in window.preview.browser.toPlainText()
    select_row(window, "file", rel_key("output/report/data.json"))
    app.processEvents()
    f["json_preview"] = window.preview.kind == "json" and '"a": [\n    1' in window.preview.code.toPlainText()
    select_row(window, "file", rel_key("output/report/chart.png"))
    app.processEvents()
    f["image_preview"] = window.preview.kind == "image" and not window.preview.image.pixmap.isNull()
    window.preview.set_path(root / "tool" / "main.py")
    f["exe_not_opened"] = not window.preview.open_button.isEnabled()

    window.open_link("hub:file/" + quote(str(root / "output" / "report" / "notes.txt"), safe=""))
    app.processEvents()
    f["file_link_navigation"] = window.preview.path == root / "output" / "report" / "notes.txt"
    window.open_link("hub:job/" + JOB_B)
    f["job_link_navigation"] = window.preview.title.text() == "차트 도구 수정" and "현재 없음" in window.preview.browser.toHtml()

    window.search.setText("보고서")
    app.processEvents()
    names = {tuple(item.data(0, 256)) for item in list_rows(window)}
    f["name_search"] = ("job", JOB_A) in names and ("file", rel_key("output/report/README.md")) not in names
    window.content_check.setChecked(True)
    window.search.setText(CONTENT_TOKEN)
    count = window.run_search()
    f["content_search"] = count == 1 and select_row(window, "file", rel_key("output/report/notes.txt"))
    window.search.clear()

    f["export_loaded"] = window.load_export(str(export)) and len(window.conversations) == 2
    app.processEvents()
    window.select_node("ai:chatgpt")
    app.processEvents()
    kinds = [item.data(0, 256)[0] for item in list_rows(window)]
    f["chatgpt_list"] = kinds.count("conv") == 2 and kinds.count("file") == 1
    select_row(window, "conv", "conv-1")
    app.processEvents()
    text = window.preview.browser.toPlainText()
    f["conversation_preview"] = "요약 결과" in text and "고마워" in text and "버려진 답변" not in text
    window.grab().save(str(shots / "fixture-chatgpt.png"))
    saved = json.loads(settings.path.read_text(encoding="utf-8"))
    f["settings_isolated"] = saved.get("chatgpt_export") == str(export) and not (root / "settings.json").exists()
    window.reload()
    app.processEvents()
    f["reload_keeps_export"] = window.nodes["ai:chatgpt"].text(0).endswith("(3)")
    f["workspace_unchanged"] = tree_hash(root) == before  # browsing only; file operations follow
    f.update(check_file_ops(app, window, root, work, shots))
    window.close()
    return f


def check_file_ops(app, window, root: Path, work: Path, shots: Path):
    """Size sort, stale views and copy/move/trash on the throwaway fixture."""
    import os
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication
    from indexer import rel_key, FileEntry
    from PySide6.QtWidgets import QHeaderView
    from preview import human_size
    from ui import (SORT_ROLE, KEY_ROLE, GROUP_ROLE, SIZE_COLUMN, STATUS_COLORS, MainWindow, Settings)

    f = {}
    report = root / "output" / "report"
    for name, size in (("s9.bin", 9), ("s100.bin", 100), ("s1200.bin", 1200)):
        write(report / "sizes" / name, b"x" * size)
    old = time.time()
    os.utime(report / "notes.txt", (old - 200 * 86400, old - 200 * 86400))
    os.utime(report / "chart.png", (old - 400 * 86400, old - 400 * 86400))
    window.reload()
    app.processEvents()

    window.select_node("folder:output/report|sizes")
    window.list.sortByColumn(SIZE_COLUMN, Qt.SortOrder.AscendingOrder)
    ascending = [item.text(1).rsplit("/", 1)[-1] for item in list_rows(window)]
    window.list.sortByColumn(SIZE_COLUMN, Qt.SortOrder.DescendingOrder)
    descending = [item.text(1).rsplit("/", 1)[-1] for item in list_rows(window)]
    # Text order would be "1.2 KB" < "100 B" < "9 B"; numeric order must win.
    f["size_sort_numeric"] = (ascending == ["s9.bin", "s100.bin", "s1200.bin"]
                              and descending == ascending[::-1]
                              and list_rows(window)[0].text(SIZE_COLUMN) == "1.2 KB")
    window.select_node("project:output/report")
    app.processEvents()
    index = window.index
    rows = {tuple(row.data(0, 256)): row for row in list_rows(window)}
    size_a, size_b = index.job_size(JOB_A), index.job_size(JOB_B)
    # Job A lists README.md, data.json, summary.md; job B lists main.py, chart.png and a missing file.
    f["job_size_shown"] = (size_a == sum(index.files[rel_key(p)].size for p in
                                         ("output/report/README.md", "output/report/data.json", "output/summary.md"))
                           and size_b == sum(index.files[rel_key(p)].size for p in
                                             ("tool/main.py", "output/report/chart.png"))
                           and rows[("job", JOB_A)].text(SIZE_COLUMN) == human_size(size_a)
                           and rows[("job", JOB_B)].text(SIZE_COLUMN) == human_size(size_b)
                           and rows[("job", JOB_A)].data(SIZE_COLUMN, SORT_ROLE) == float(size_a))
    window.list.sortByColumn(SIZE_COLUMN, Qt.SortOrder.AscendingOrder)
    ordered = [row.data(SIZE_COLUMN, SORT_ROLE) for row in list_rows(window)]
    f["size_sort_includes_jobs"] = ordered == sorted(ordered) and None not in ordered

    # Status colours: jobs by status, linked files by their latest job, unlinked files plain.
    groups = {key: row.data(0, GROUP_ROLE) for key, row in rows.items()}
    f["status_groups"] = (groups[("job", JOB_A)] == "done" and groups[("job", JOB_B)] == "repair"
                          and groups[("file", rel_key("output/report/README.md"))] == "done"
                          and groups[("file", rel_key("output/report/chart.png"))] == "repair"
                          and groups[("file", rel_key("output/report/notes.txt"))] is None
                          and set(window.legend_chips) == set(STATUS_COLORS))
    window.list.clearSelection()
    window.list.setCurrentItem(None)
    app.processEvents()
    shot = window.list.viewport().grab().toImage()

    def row_colour(key):
        rect = window.list.visualItemRect(rows[key])
        ratio = shot.devicePixelRatio()  # e.g. 1.5 on a 150% Windows display
        return shot.pixelColor(int((rect.left() + 3) * ratio), int(rect.center().y() * ratio)).name().upper()
    f["status_colours_painted"] = (row_colour(("job", JOB_A)) == STATUS_COLORS["done"].upper()
                                   and row_colour(("job", JOB_B)) == STATUS_COLORS["repair"].upper()
                                   and row_colour(("file", rel_key("output/report/notes.txt"))) == "#FFFFFF")
    window.grab().save(str(shots / "fixture-colours.png"))

    # Column separators: short light-grey vertical marks between columns only.
    from ui import SEPARATOR_COLOR, SeparatedHeader

    def close(colour, hex_value, tolerance=14):
        target = QColor(hex_value)
        return all(abs(a - b) <= tolerance for a, b in ((colour.red(), target.red()),
                                                        (colour.green(), target.green()), (colour.blue(), target.blue())))

    def pixel(image, x, y):
        ratio = image.devicePixelRatio()
        return image.pixelColor(int((x + 0.5) * ratio), int((y + 0.5) * ratio))
    header = window.list.header()
    row = window.list.visualItemRect(rows[("job", JOB_A)])  # green 'done' row, not selected
    marks, ends, inside = [], [], []
    for column in range(header.count() - 1):
        x = header.sectionViewportPosition(column) + header.sectionSize(column) - 1
        marks.append(close(pixel(shot, x, row.center().y()), SEPARATOR_COLOR))
        ends.append(close(pixel(shot, x, row.top() + 1), STATUS_COLORS["done"], 4)
                    and close(pixel(shot, x, row.bottom() - 1), STATUS_COLORS["done"], 4))
        inside.append(close(pixel(shot, x - 3, row.center().y()), STATUS_COLORS["done"], 4))
    last = header.sectionViewportPosition(header.count() - 1) + header.sectionSize(header.count() - 1) - 1
    no_horizontal = all(close(pixel(shot, header.sectionViewportPosition(c) + 4, row.bottom()), STATUS_COLORS["done"], 4)
                        for c in range(header.count()))
    head = header.grab().toImage()
    head_marks = [close(pixel(head, header.sectionViewportPosition(c) + header.sectionSize(c) - 1, header.height() // 2),
                        SEPARATOR_COLOR) for c in range(header.count() - 1)]
    # Row under the mouse cursor turns white; other rows keep their status colour and a
    # selected row keeps the selection colour.
    from PySide6.QtTest import QTest
    viewport = window.list.viewport()
    row_b = window.list.visualItemRect(rows[("job", JOB_B)])
    window.list.setCurrentItem(rows[("job", JOB_B)])  # selected row, cursor elsewhere
    app.processEvents()
    window.raise_()
    window.activateWindow()
    # Native Windows delivers the real cursor move through the event loop, so wait briefly.
    QTest.mouseMove(viewport, row.center())  # hover job A's green row
    QTest.qWait(150)
    hover_shot = viewport.grab().toImage()
    hovered = pixel(hover_shot, row.left() + 3, row.center().y())
    selected = pixel(hover_shot, row_b.left() + 3, row_b.center().y())
    QTest.mouseMove(viewport, row_b.center())  # leave job A
    QTest.qWait(150)
    after = pixel(viewport.grab().toImage(), row.left() + 3, row.center().y())
    f["hover_row_white"] = (close(hovered, "#FFFFFF", 3) and close(selected, "#D9D5FA", 6)
                            and close(after, STATUS_COLORS["done"], 4)
                            and close(pixel(hover_shot, header.sectionViewportPosition(0) + header.sectionSize(0) - 1,
                                            row.center().y()), SEPARATOR_COLOR))
    window.list.clearSelection()
    window.list.setCurrentItem(None)
    f["column_separators"] = (all(marks) and all(ends) and all(inside) and no_horizontal
                              and not close(pixel(shot, last, row.center().y()), SEPARATOR_COLOR, 4)
                              and isinstance(header, SeparatedHeader) and all(head_marks)
                              and header.sectionsClickable())

    window.select_node("ai:chatgpt")
    app.processEvents()
    convs = [row for row in list_rows(window) if row.data(0, 256)[0] == "conv"]
    f["conversation_size_shown"] = (len(convs) == 2 and all(row.data(SIZE_COLUMN, SORT_ROLE) is not None for row in convs)
                                    and all(row.data(0, GROUP_ROLE) is None for row in convs)
                                    and any(row.text(SIZE_COLUMN) not in ("", "0 B") for row in convs))

    # Every column resizable by dragging, none stretching; widths persist in settings.
    header = window.list.header()
    f["columns_resizable"] = (all(header.sectionResizeMode(column) == QHeaderView.ResizeMode.Interactive
                                  for column in range(header.count()))
                              and not header.stretchLastSection())
    window.list.setColumnWidth(1, 333)
    window.list.setColumnWidth(SIZE_COLUMN, 91)
    window.save_column_widths()
    again = MainWindow(root, Settings(window.settings.path))
    f["column_widths_saved"] = (again.list.columnWidth(1) == 333 and again.list.columnWidth(SIZE_COLUMN) == 91
                                and json.loads(window.settings.path.read_text(encoding="utf-8"))["list_columns"][1] == 333)
    again.close()

    # Out-of-range or broken entries affect only their own column; dragging is capped the same way.
    from ui import MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH, DEFAULT_COLUMN_WIDTHS
    window.list.setColumnWidth(1, 333)
    window.list.setColumnWidth(SIZE_COLUMN, 2400)
    capped = window.list.columnWidth(SIZE_COLUMN)
    window.settings.update(list_columns=[48, 333, "x", 5, 2400, 118])
    third = MainWindow(root, Settings(window.settings.path))
    f["column_widths_per_column"] = (capped == MAX_COLUMN_WIDTH
                                     and [third.list.columnWidth(c) for c in range(6)]
                                     == [48, 333, DEFAULT_COLUMN_WIDTHS[2], MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH, 118])
    third.close()

    def stale_rows(key):
        window.select_node(key)
        app.processEvents()
        return [item.data(0, 256)[1] for item in list_rows(window)]
    notes, chart = rel_key("output/report/notes.txt"), rel_key("output/report/chart.png")
    f["stale_views"] = (stale_rows("stale:180") == [chart, notes] and stale_rows("stale:365") == [chart]
                        and stale_rows("stale:90:unlinked") == [notes] and window.preview.kind == "stale"
                        and window.nodes["stale:90"].text(0).endswith("(2)"))
    f["old_files_title"] = (window.nodes["stale:90"].parent().text(0) == "오래된 파일"
                            and window.preview.title.text().startswith("오래된 파일 · ")
                            and "정리 후보" not in window.preview.title.text())
    window.grab().save(str(shots / "fixture-stale.png"))

    pack = root / "artifacts" / "pack"
    window.select_node("project:output/report")
    app.processEvents()
    first = window.file_action("copy", [window.index.files[notes]], pack, confirm=False)
    second = window.file_action("copy", [window.index.files[notes]], pack, confirm=False)
    f["copy_no_overwrite"] = (len(first.done) == 1 and len(second.done) == 1 and (report / "notes.txt").exists()
                              and (pack / "notes.txt").exists() and (pack / "notes (2).txt").exists())
    f["selection_kept_after_op"] = window.tree.currentItem().data(0, KEY_ROLE) == "project:output/report"

    # Right-click menu is the only path: its actions reach the pick-folder and confirm steps,
    # while the former shortcuts (Ctrl+Shift+C/M, Delete) do nothing.
    from PySide6.QtTest import QTest
    asked = []
    window.pick_folder = lambda op, start: asked.append(("pick", op)) or pack
    window.confirm_action = lambda op, entries, dest: asked.append(("confirm", op)) or True
    window.activateWindow()
    select_row(window, "file", notes)
    window.list.setFocus()
    app.processEvents()
    for key, modifiers in ((Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier),
                           (Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier),
                           (Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)):
        QTest.keyClick(window.list, key, modifiers)
        app.processEvents()
    f["no_file_shortcuts"] = asked == [] and (report / "notes.txt").exists() and not (pack / "notes (3).txt").exists()
    menu = window.build_list_menu()
    ops = {action.data(): action for action in menu.actions() if action.data()}
    labels = [action.text() for action in ops.values()]
    ops["copy"].trigger()
    app.processEvents()
    select_row(window, "file", rel_key("output/report/sizes/s9.bin"))
    move_action = next(action for action in window.build_list_menu().actions() if action.data() == "move")
    move_action.trigger()
    app.processEvents()
    f["right_click_menu_ops"] = (labels == ["복사…", "이동…", "휴지통으로 삭제"] and not any("\t" in text for text in labels)
                                 and asked == [("pick", "copy"), ("confirm", "copy"), ("pick", "move"), ("confirm", "move")]
                                 and (pack / "notes (3).txt").exists() and (pack / "s9.bin").exists()
                                 and not (report / "sizes" / "s9.bin").exists())
    del window.pick_folder, window.confirm_action

    moved = window.file_action("move", [window.index.files[rel_key("output/report/data.json")]], pack, confirm=False)
    f["move"] = (len(moved.done) == 1 and not (report / "data.json").exists() and (pack / "data.json").exists()
                 and rel_key("artifacts/pack/data.json") in window.index.files)
    same = window.file_action("move", [window.index.files[rel_key("artifacts/pack/data.json")]], pack, confirm=False)
    f["move_same_folder_skipped"] = len(same.skipped) == 1 and (pack / "data.json").exists()

    trash_dir = work / "fake-trash"
    trash_dir.mkdir()
    window.trash = lambda path: bool(path.replace(trash_dir / path.name)) or True
    trashed = window.file_action("trash", [window.index.files[rel_key("output/report/README.md")]], confirm=False)
    f["trash_uses_backend"] = (len(trashed.done) == 1 and not (report / "README.md").exists()
                               and (trash_dir / "README.md").exists())
    window.select_node("folder:output/report|sub")
    app.processEvents()
    emptied = window.file_action("trash", [window.index.files[rel_key("output/report/sub/deep.txt")]], confirm=False)
    f["emptied_folder_kept_selected"] = (len(emptied.done) == 1 and (report / "sub").is_dir()
                                         and window.tree.currentItem().data(0, KEY_ROLE) == "folder:output/report|sub"
                                         and window.list.topLevelItemCount() == 0)
    window.trash = lambda path: False
    refused = window.file_action("trash", [window.index.files[rel_key("output/summary.md")]], confirm=False)
    f["trash_failure_keeps_file"] = len(refused.failed) == 1 and (root / "output" / "summary.md").exists()

    # Last direct file of output/ (trash) and artifacts/ (move): the '(직속 파일)' node stays selected.
    window.trash = lambda path: bool(path.replace(trash_dir / path.name)) or True
    kept = []
    for area, op, name, dest in (("output", "trash", "summary.md", None), ("artifacts", "move", "top.png", pack)):
        window.select_node("project:" + area)
        app.processEvents()
        done = window.file_action(op, [window.index.files[rel_key(f"{area}/{name}")]], dest, confirm=False)
        app.processEvents()
        kept.append(len(done.done) == 1 and not (root / area / name).exists()
                    and window.tree.currentItem().data(0, KEY_ROLE) == "project:" + area
                    and window.list.topLevelItemCount() == 0 and window.preview.kind == "project")
    f["emptied_area_kept_selected"] = kept == [True, True]

    # Areas holding only direct files (no sub-projects): emptying them removes the whole
    # area group from the index, yet the selection must survive this and a later F5.
    from ui import MainWindow, Settings
    bare = work / "bare"
    (bare / "agent_lab" / "jobs").mkdir(parents=True)
    write(bare / "output" / "only.md", "x\n")
    write(bare / "artifacts" / "only.png", PNG_1PX)
    bare_dest = work / "bare-dest"
    bare_dest.mkdir()
    other = MainWindow(bare, Settings(work / "bare-profile" / "settings.json"))
    other.trash = lambda path: bool(path.replace(trash_dir / ("bare-" + path.name))) or True
    bare_ok = []
    for area, op, name in (("output", "trash", "only.md"), ("artifacts", "move", "only.png")):
        other.select_node("project:" + area)
        app.processEvents()
        done = other.file_action(op, [other.index.files[rel_key(f"{area}/{name}")]],
                                 bare_dest if op == "move" else None, confirm=False)
        app.processEvents()
        selected = other.tree.currentItem().data(0, KEY_ROLE) == "project:" + area
        first = len(done.done) == 1 and selected and other.list.topLevelItemCount() == 0
        other.reload()
        app.processEvents()
        bare_ok.append(first and other.tree.currentItem().data(0, KEY_ROLE) == "project:" + area
                       and other.preview.kind == "project")
    other.close()
    f["bare_area_kept_selected"] = bare_ok == [True, True]

    record = root / "agent_lab" / "jobs" / JOB_A / "manifest.json"
    fake = FileEntry(path=record, rel="agent_lab/jobs/x", area="app", project="agent_lab", size=1, mtime=0)
    window.trash = lambda path: bool(path.replace(trash_dir / "record.json")) or True
    guarded = window.file_action("trash", [fake], confirm=False)
    f["job_records_protected"] = len(guarded.skipped) == 1 and record.exists()

    def cancel_dialog():
        dialog = QApplication.activeModalWidget()
        if dialog is not None:
            dialog.reject()
    QTimer.singleShot(50, cancel_dialog)
    cancelled = window.file_action("trash", [window.index.files[rel_key("output/report/gpt-revision-prompt.md")]])
    f["confirm_cancel_keeps_file"] = cancelled is None and (report / "gpt-revision-prompt.md").exists()
    return f


def check_real(app, root: Path, shots: Path, ignore: Path):
    from indexer import build_index
    from ui import MainWindow, Settings

    started = time.perf_counter()
    snapshot = stat_snapshot(build_index(root), ignore)
    with tempfile.TemporaryDirectory() as profile:
        window = MainWindow(root, Settings(Path(profile) / "settings.json"))
        window.resize(1440, 860)
        window.show()
        app.processEvents()
        index = window.index
        seconds = round(time.perf_counter() - started, 2)
        window.grab().save(str(shots / "real-overview.png"))
        jobs = index.sorted_jobs()
        if jobs:
            window.show_job(jobs[0].id)
            app.processEvents()
            window.grab().save(str(shots / "real-job.png"))
        window.close()
    return {"real_jobs": len(index.jobs), "real_projects": len(index.projects), "real_files": len(index.files),
            "real_load_seconds": seconds,
            "real_loaded": bool(index.jobs) and bool(index.projects),
            "real_unchanged": stat_snapshot(build_index(root), ignore) == snapshot}


def run(report: Path, real_root: Path | None = None):
    from PySide6.QtWidgets import QApplication
    from app import configure_fonts, make_icon

    report = report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    shots = report.parent / (report.stem + "-shots")
    shots.mkdir(exist_ok=True)
    data = {"passed": False, "packaged": bool(getattr(sys, "frozen", False))}
    try:
        app = QApplication.instance() or QApplication([])
        configure_fonts()
        app.setWindowIcon(make_icon())
        with tempfile.TemporaryDirectory() as work:
            flags = check_fixture(app, Path(work), shots)
        data.update(flags)
        if real_root is not None:
            data.update(check_real(app, real_root.resolve(), shots, report.parent))
        booleans = [value for key, value in data.items() if key not in ("passed", "packaged") and isinstance(value, bool)]
        data["failed"] = [key for key, value in data.items() if value is False and key not in ("passed", "packaged")]
        data["passed"] = bool(booleans) and all(booleans)
    except Exception:
        data["error"] = traceback.format_exc()
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if data["passed"] else 1
