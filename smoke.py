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
JOB_N = "20261013-070000-dddd4444"
JOB_L = "20261014-060000-eeee5555"
JOB_D = "20261015-050000-ffff6666"
LONG_GOAL = "번호 프로젝트 폴더의 보고서와 도구를 한 번에 정리하고 결과를 확인하는 아주 긴 작업 목표 문장 " * 7
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


def make_numbered_fixture(root: Path, aliases=True):
    """Workspace already split into numbered project folders; the job still lists old paths."""
    job = root / "agent_lab" / "jobs" / JOB_N
    write(job / "task.json", {"request": "보고서와 도구 정리", "goal": "",
                              "files": ["output/report/README.md", "tool/main.py", "output/report/gone.txt"]})
    write(job / "manifest.json", {"version": 2, "mode": "review", "implementer": "claude", "status": "completed",
                                  "checks_passed": True, "review": {"passed": True}, "history": []})
    if aliases:
        write(root / "agent_lab" / "path-aliases.json", {"version": 1, "aliases": [
            {"old": "output/report", "new": "01_Sample/output/report"}, {"old": "tool", "new": "01_Sample/tool"}]})
    sample = root / "01_Sample"
    write(sample / "output" / "report" / "README.md", "# 옮긴 보고서\n")
    write(sample / "output" / "report" / "sub" / "deep.txt", "nested\n")
    write(sample / "output" / "summary.md", "# 요약\n")
    write(sample / "artifacts" / "pack" / "log.txt", "artifact log\n")
    write(sample / "tool" / "main.py", "print('tool')\n")
    write(sample / "tool" / ".venv" / "lib.py", "x = 1\n")
    write(sample / "tmp" / "scratch.txt", "scratch\n")
    write(sample / ".runtime" / "remote.txt", "not shown\n")
    write(sample / "README.md", "# 샘플 프로젝트\n")
    write(root / "02_Other" / "output" / "note.txt", "other\n")
    write(root / "notes" / "free.txt", "unrelated root folder\n")
    return root


def check_numbered(app, work: Path, shots: Path):
    from indexer import NO_GROUP, build_index, rel_key
    from ui import CARD_ROLE, GROUP_NAME_ROLE, KEY_ROLE, MainWindow, Settings

    root = make_numbered_fixture(work / "numbered")
    before = tree_hash(root)
    window = MainWindow(root, Settings(work / "numbered-profile" / "settings.json"))
    window.resize(1440, 860)
    window.show()
    app.processEvents()
    index = window.index
    f = {}
    f["numbered_projects"] = set(index.projects) == {
        "01_Sample", "01_Sample/output", "01_Sample/output/report", "01_Sample/artifacts/pack", "01_Sample/tool",
        "02_Other/output"} and {p.group for p in index.projects.values()} == {"01_Sample", "02_Other"}
    keys = set(index.files)
    f["numbered_scope"] = (not any("/tmp/" in k or ".runtime" in k or ".venv" in k or k.startswith("notes/") for k in keys)
                           and sum(len(p.files) for p in index.projects.values()) == len(keys))
    # One nav row per numbered folder (name without the number); its projects sit on the folder tab.
    group = window.projects_node.child(0)
    tree = window.folder_tree
    names = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())
             if tree.topLevelItem(i).data(0, GROUP_NAME_ROLE) == "01_Sample"]
    f["numbered_tree_groups"] = (group.text(0).startswith("Sample") and group.toolTip(0) == "01_Sample"
                                 and group.childCount() == 0 and group.data(0, KEY_ROLE) == "group:01_Sample"
                                 and [window.projects_node.child(i).data(0, KEY_ROLE)
                                      for i in range(window.projects_node.childCount())]
                                 == ["group:01_Sample", "group:02_Other"]
                                 and any(name.startswith("output/report") for name in names)
                                 and any(name.startswith("(직속 파일)") for name in names))
    window.select_node("group:01_Sample")
    app.processEvents()
    cards = [window.job_list.item(i) for i in range(window.job_list.count())]
    f["numbered_group_page"] = (window.page_title.text() == "Sample" and "작업 1건" in window.page_meta.text()
                                and [tuple(item.data(256)) for item in cards] == [("day", "2026-10-13"), ("job", JOB_N)]
                                and window.page_path == root / "01_Sample" and window.preview.kind == "group")
    moved = index.files[rel_key("01_Sample/output/report/README.md")]
    tool = index.files[rel_key("01_Sample/tool/main.py")]
    f["alias_file_links"] = moved.jobs == [JOB_N] and tool.jobs == [JOB_N] and index.file_ais(moved) == {"claude"}
    f["alias_job_size"] = index.job_size(JOB_N) == moved.size + tool.size
    window.show_job(JOB_N)
    app.processEvents()
    text = window.preview.browser.toPlainText()
    f["alias_job_detail"] = ("output/report/README.md" in text and "output/report/gone.txt (현재 없음)" in text
                             and "output/report/README.md (현재 없음)" not in text)
    window.grab().save(str(shots / "fixture-numbered.png"))
    f["numbered_unchanged"] = tree_hash(root) == before  # browsing only; file operations follow

    # Last direct file of 01_…/output (trash), of 01_… itself (move) and of a folder holding nothing
    # else (02_Other/output, its group vanishes): the '(직속 파일)' node stays selected, also after F5.
    trash_dir, dest = work / "numbered-trash", work / "numbered-dest"
    trash_dir.mkdir()
    dest.mkdir()
    window.trash = lambda path: bool(path.replace(trash_dir / path.name)) or True
    kept = []
    for key, op, rel in (("01_Sample/output", "trash", "01_Sample/output/summary.md"),
                         ("01_Sample", "move", "01_Sample/README.md"),
                         ("02_Other/output", "trash", "02_Other/output/note.txt")):
        window.select_node("project:" + key)
        app.processEvents()
        done = window.file_action(op, [window.index.files[rel_key(rel)]], dest if op == "move" else None,
                                  confirm=False)
        app.processEvents()

        def still_selected():
            return (window.current_key == "project:" + key
                    and window.list.topLevelItemCount() == 0 and window.preview.kind == "project")
        first = len(done.done) == 1 and not (root / rel).exists() and still_selected()
        window.reload()
        app.processEvents()
        kept.append(first and still_selected())
    f["numbered_direct_kept_selected"] = kept == [True, True, True]
    window.close()

    plain_root = make_numbered_fixture(work / "numbered-plain", aliases=False)
    # A numbered folder with nothing indexed, one holding only scratch space, and a job whose
    # one-line goal is far longer than the 90 characters the table keeps.
    (plain_root / "03_Empty").mkdir()
    write(plain_root / "04_OnlyScratch" / "tmp" / "scratch.txt", "scratch\n")
    long_job = plain_root / "agent_lab" / "jobs" / JOB_L
    write(long_job / "task.json", {"request": "정리", "goal": LONG_GOAL, "files": ["01_Sample/tool/main.py"]})
    write(long_job / "manifest.json", {"version": 2, "implementer": "claude", "status": "completed", "history": []})
    # A job whose only listed result (and its sub-folder) was deleted stays with its project folder.
    gone_job = plain_root / "agent_lab" / "jobs" / JOB_D
    write(gone_job / "task.json", {"request": "지운 결과", "goal": "", "files": ["02_Other/removed/gone.md"]})
    write(gone_job / "manifest.json", {"version": 2, "implementer": "codex", "status": "completed", "history": []})
    plain = MainWindow(plain_root, Settings(work / "numbered-plain-profile" / "settings.json"))
    plain.resize(1440, 860)
    plain.show()
    app.processEvents()
    nav = [plain.projects_node.child(i) for i in range(plain.projects_node.childCount())]
    home = (list(plain.cards) == ["01_Sample", "02_Other", "03_Empty", "04_OnlyScratch", ""]
            and "작업 1건 · 파일 0개" in plain.cards[""].text()
            and [item.text(0) for item in nav[4:]] == ["작업 폴더 직속  (1)"]
            and all("수정 필요 0건" in card.text() for card in plain.cards.values())
            and "작업 0건 · 파일 0개" in plain.cards["03_Empty"].text()
            and "작업 기록 없음" in plain.cards["03_Empty"].text())
    plain.select_node("group:03_Empty")
    app.processEvents()
    empty_jobs = [tuple(plain.job_list.item(i).data(256)) for i in range(plain.job_list.count())]
    plain.tabs.setCurrentIndex(2)
    app.processEvents()
    f["empty_numbered_folders_listed"] = (
        home and [item.text(0) for item in nav[:4]] == ["Sample  (1)", "Other  (1)", "Empty  (0)", "OnlyScratch  (0)"]
        and plain.page_title.text() == "Empty" and empty_jobs == [("empty", None)]
        and plain.page_path == plain_root / "03_Empty" and plain.list.topLevelItemCount() == 0
        and plain.current_key == "group:03_Empty" and plain.preview.kind == "group")
    plain.select_node("group:01_Sample")
    plain.tabs.setCurrentIndex(0)
    app.processEvents()
    rows = {plain.job_list.item(i).data(256)[1]: i for i in range(plain.job_list.count())}
    long_item = plain.job_list.item(rows[JOB_L])
    delegate = plain.job_list.itemDelegate()
    width = delegate.title_width()
    metrics = plain.job_list.fontMetrics()
    # Title longer than two lines: every wrapped line is drawn in full (no elision), the row grows
    # by one line each, and the rendered card has text pixels on every one of those lines.
    lines = delegate.title_lines(plain.job_list.font(), long_item.text())
    rect = plain.job_list.visualItemRect(long_item)
    shot = plain.job_list.viewport().grab().toImage()
    ratio = shot.devicePixelRatio()
    top = rect.top() + 3 + delegate.PAD

    def inked(row):  # dark title pixels in the band of one text line
        y0, y1 = top + row * metrics.lineSpacing(), top + (row + 1) * metrics.lineSpacing()
        return sum(1 for y in range(int(y0 * ratio), int(y1 * ratio))
                   for x in range(int((rect.left() + delegate.PAD) * ratio), int((rect.left() + delegate.PAD + width) * ratio), 2)
                   if shot.pixelColor(x, y).lightness() < 120)
    f["long_title_fully_shown"] = (
        long_item.text() == LONG_GOAL.strip() and len(long_item.text()) > 90 and len(lines) >= 3
        and "".join(lines).replace(" ", "") == LONG_GOAL.replace(" ", "")
        and not any("…" in line or "..." in line for line in lines)
        and all(metrics.horizontalAdvance(line) <= width for line in lines)
        and rect.height() == plain.job_list.sizeHintForRow(rows[JOB_L])
        == 6 + 2 * delegate.PAD + len(lines) * metrics.lineSpacing() + delegate.GAP + delegate.PILL
        and all(inked(row) > 20 for row in range(len(lines)))
        and plain.job_list.viewport().rect().contains(rect)
        and JOB_N not in rows  # without the alias table the old-path job is not in this project
        and LONG_GOAL.strip() in long_item.toolTip()
        and len(plain.index.jobs[JOB_L].title) == 90)  # the table keeps the short form
    f["long_title_lines"] = len(lines)
    plain.grab().save(str(shots / "fixture-long-title.png"))
    plain.select_node("group:02_Other")
    app.processEvents()
    kept = [tuple(plain.job_list.item(i).data(256)) for i in range(plain.job_list.count())]
    plain.select_node("history")
    app.processEvents()
    metas = {plain.job_list.item(i).data(256)[1]: (plain.job_list.item(i).data(CARD_ROLE) or {}).get("meta", "")
             for i in range(plain.job_list.count())}
    f["deleted_path_job_kept_in_project"] = (
        kept == [("day", "2026-10-15"), ("job", JOB_D)] and not (plain_root / "02_Other" / "removed").exists()
        and "작업 1건" in plain.cards["02_Other"].text() and metas[JOB_D].endswith("· Other")
        and metas[JOB_L].endswith("· Sample") and metas[JOB_N].endswith("· 작업 폴더 직속")
        and "group:" + NO_GROUP not in plain.nodes)

    # Card details are wrapped, never elided: long AI roles push the file count and the project
    # onto further lines, and a narrow card does the same; every line is really drawn.
    from PySide6.QtGui import QFontMetrics
    from PySide6.QtWidgets import QSplitter
    font = plain.job_list.font()
    small = QFontMetrics(delegate.small_font(font))

    def card_state(item):
        info = item.data(CARD_ROLE)
        lines = delegate.meta_lines(font, info)
        rect = plain.job_list.visualItemRect(item)
        titles = len(delegate.title_lines(font, item.text()))
        expected = (6 + 2 * delegate.PAD + titles * metrics.lineSpacing() + delegate.GAP + delegate.PILL
                    + (len(lines) - 1) * small.lineSpacing())
        shot = plain.job_list.viewport().grab().toImage()
        ratio = shot.devicePixelRatio()
        pill_top = rect.top() + 3 + delegate.PAD + titles * metrics.lineSpacing() + delegate.GAP
        last_top = pill_top + delegate.PILL + (len(lines) - 2) * small.lineSpacing() if len(lines) > 1 else pill_top
        last_height = small.lineSpacing() if len(lines) > 1 else delegate.PILL
        skip = delegate.pill_width(font, info) + 8 if len(lines) == 1 else 0
        ink = sum(1 for y in range(int(last_top * ratio), int((last_top + last_height) * ratio))
                  for x in range(int((rect.left() + delegate.PAD + skip) * ratio), int(rect.right() * ratio), 2)
                  if shot.pixelColor(x, y).lightness() < 170)
        whole = "".join(lines).replace(" ", "") == info["meta"].replace(" ", "")
        fits = all(small.horizontalAdvance(line) <= delegate.title_width() for line in lines)
        # Rows are laid out again for the current width: each row has its own height and none overlaps.
        rects = [plain.job_list.visualItemRect(plain.job_list.item(i)) for i in range(plain.job_list.count())]
        apart = (all(a.bottom() < b.top() for a, b in zip(rects, rects[1:]))
                 and all(r.height() == plain.job_list.sizeHintForRow(i) for i, r in enumerate(rects)))
        return {"lines": lines, "ok": (whole and fits and not any("…" in line for line in lines)
                                       and rect.height() == expected and ink > 10 and apart
                                       and plain.job_list.viewport().rect().contains(rect))}

    item_d = next(plain.job_list.item(i) for i in range(plain.job_list.count())
                  if plain.job_list.item(i).data(256) == ("job", JOB_D))
    wide = card_state(item_d)
    long_roles = "Codex 구현, 조사, 계획, 검토 · Claude 구현, 조사, 계획, 검토 · " * 5 + "파일 12개 · Other"
    item_d.setData(CARD_ROLE, dict(item_d.data(CARD_ROLE), meta=long_roles))
    app.processEvents()
    roles = card_state(item_d)
    # Narrow centre column with an ordinary two-AI job tied to two projects.
    usual = "Claude 구현, 조사 · Codex 계획, 검토 · 파일 12개 · LectureStudy, Other"
    item_d.setData(CARD_ROLE, dict(item_d.data(CARD_ROLE), meta=usual))
    app.processEvents()
    usual_wide = card_state(item_d)
    plain.centralWidget().findChild(QSplitter).setSizes([190, 250, 1000])  # squeeze the centre column
    app.processEvents()
    narrow_width = delegate.title_width()
    narrow = card_state(item_d)
    f["card_details_never_hidden"] = (
        wide["ok"] and len(wide["lines"]) == 1 and wide["lines"][0].endswith("파일 0개 · Other")
        and roles["ok"] and len(roles["lines"]) >= 2 and roles["lines"][-1].endswith("파일 12개 · Other")
        and usual_wide["ok"] and len(usual_wide["lines"]) == 1
        and narrow_width < 340 and narrow["ok"] and len(narrow["lines"]) >= 2
        and "".join(narrow["lines"]).replace(" ", "").endswith("파일12개·LectureStudy,Other"))
    f["card_detail_lines"] = [len(wide["lines"]), len(roles["lines"]), len(narrow["lines"]), narrow_width]
    plain.grab().save(str(shots / "fixture-narrow-cards.png"))

    # Home cards: as many columns as show every line of every card whole; a longer line or a
    # narrower page means fewer columns, never a clipped card.
    def cards_fit():
        return all(max(card.fontMetrics().horizontalAdvance(line) for line in card.text().splitlines()) + 30
                   <= card.width() for card in plain.cards.values())
    plain.centralWidget().findChild(QSplitter).setSizes([210, 780, 426])
    plain.select_node("overview")
    app.processEvents()
    lines = plain.cards["01_Sample"].text().splitlines()
    wide = (plain.card_columns, cards_fit(), plain.cards_area.height())
    plain.cards["02_Other"].setText("Other" + chr(10) + "작업 123,456건 · 파일 1,234,567개 · 아주 긴 요약 줄"
                                    + chr(10) + "최근 작업 2026-10-15" + chr(10) + "수정 필요 0건")
    plain.layout_cards()
    app.processEvents()
    longer = (plain.card_columns, cards_fit(), plain.cards_area.height())
    plain.centralWidget().findChild(QSplitter).setSizes([190, 250, 1000])
    app.processEvents()
    narrow = (plain.card_columns, cards_fit())
    plain.grab().save(str(shots / "fixture-narrow-home.png"))
    f["home_cards_fit_any_width"] = (
        wide == (3, True, 2 * 102) and longer[:2] == (2, True) and longer[2] == 3 * 102
        and narrow[1] and narrow[0] <= longer[0]
        and lines == ["Sample", "작업 1건 · 파일 6개", "최근 작업 2026-10-14", "수정 필요 0건"]
        and plain.cards_grid.count() == len(plain.cards) == 5)
    f["home_card_columns"] = [wide[0], longer[0], narrow[0]]
    # Numbered folders without the alias table: reported under 파일 정리 → 점검 필요, and the
    # old-path job is not linked to the file at its new place.
    plain.select_node("problems")
    app.processEvents()
    f["missing_aliases_reported"] = (plain.preview.title.text() == "점검 필요"
                                     and "path-aliases.json 없음" in plain.preview.browser.toPlainText()
                                     and plain.index.files[rel_key("01_Sample/output/report/README.md")].jobs == []
                                     and plain.current_key == "problems" and plain.page_title.text() == "점검 필요"
                                     and plain.nodes["problems"].parent() is plain.nodes["cleanup"]
                                     and plain.stack.currentWidget() is plain.files_box
                                     and plain.list.topLevelItemCount() == 0)
    plain.close()
    broken = make_numbered_fixture(work / "numbered-broken", aliases=False)
    write(broken / "agent_lab" / "path-aliases.json", "{ broken")
    damaged = build_index(broken)
    f["bad_aliases_reported"] = (any("path-aliases.json 손상" in text for text in damaged.problems)
                                 and damaged.files[rel_key("01_Sample/output/report/README.md")].jobs == [])
    return f


# Real keyboard, IME and mouse-button messages: WM_KEYDOWN … WM_UNICHAR, IME composition and
# char, WM_LBUTTONDOWN … WM_MOUSEHWHEEL. WM_MOUSEMOVE (0x0200) passes for the hover check.
BLOCKED_MESSAGES = frozenset({*range(0x0100, 0x010A), 0x010D, 0x010E, 0x010F, 0x0286, *range(0x0201, 0x020F)})


def install_input_guard(app):
    """Native Windows run: drop real keyboard, IME and mouse-button input. The test window takes
    the focus, so a user typing or clicking meanwhile would change the state under test (a stray
    key once filtered the list). QTest key events skip the native layer and real cursor moves are
    kept, so the checks themselves are unaffected."""
    if sys.platform != "win32" or app.platformName() != "windows":
        return None
    from ctypes import wintypes
    from PySide6.QtCore import QAbstractNativeEventFilter

    class InputGuard(QAbstractNativeEventFilter):
        def nativeEventFilter(self, event_type, message):
            name = event_type.data() if hasattr(event_type, "data") else bytes(event_type)
            if name.startswith(b"windows") and wintypes.MSG.from_address(int(message)).message in BLOCKED_MESSAGES:
                return True, 0
            return False, 0

    guard = InputGuard()
    app.installNativeEventFilter(guard)
    return guard


def stray_input_blocked(window):
    """Post a real 'm' key press to the native window while the search box has focus."""
    import ctypes
    from ctypes import wintypes
    from PySide6.QtTest import QTest

    post = ctypes.windll.user32.PostMessageW
    post.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    window.search.setFocus()
    hwnd = int(window.winId())
    for message, value, flags in ((0x0100, 0x4D, 0x00320001), (0x0102, ord("m"), 0x00320001),
                                  (0x0101, 0x4D, 0xC0320001)):  # WM_KEYDOWN, WM_CHAR, WM_KEYUP
        post(hwnd, message, value, flags)
    QTest.qWait(150)
    text = window.search.text()
    window.search.clear()
    return text == ""


def hover_at(widget, pos):
    """Mouse move sent to the top-level window, which routes it to the widget under pos and raises
    the enter/hover events like platform input, without moving the user's real cursor."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    top = widget.window()
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(widget.mapTo(top, pos)), QPointF(widget.mapToGlobal(pos)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(top.windowHandle(), event)


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
    if app.platformName() == "windows":
        f["native_input_blocked"] = stray_input_blocked(window)
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
    f.update(check_layout(app, window, root, shots))
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


def job_cards(window):
    return [window.job_list.item(row) for row in range(window.job_list.count())]


def check_layout(app, window, root: Path, shots: Path):
    """Project-centred layout: nav rows, home cards, project tabs, job cards and the job detail order."""
    from indexer import NO_GROUP, rel_key
    from ui import CARD_ROLE, KEY_ROLE, TABS

    f = {}
    nav = window.tree
    top = [nav.topLevelItem(i) for i in range(nav.topLevelItemCount())]
    f["nav_sections"] = ([item.text(0).split("  (")[0] for item in top] == ["홈", "전체 작업 이력", "파일 정리", "프로젝트"]
                         and [top[3].child(i).data(0, KEY_ROLE) for i in range(top[3].childCount())]
                         == ["group:", "group:" + NO_GROUP]
                         and top[3].child(0).text(0) == "작업 폴더 직속  (2)"
                         and top[3].child(1).text(0) == "프로젝트 미지정  (1)"
                         and window.nodes["ai:claude"].parent() is top[1]
                         and window.nodes["unclassified"].parent() is top[2]
                         and window.nodes["problems"].parent() is top[2]
                         and all(window.nodes[key].treeWidget() is window.folder_tree
                                 for key in ("project:output/report", "folder:output/report|sub")))

    # Home: one card per project group and the recent jobs as cards with their project name.
    f["home_page"] = (window.current_key == "overview" and window.page_title.text() == "홈"
                      and window.stack.currentWidget() is window.job_list and window.cards_area.isVisible()
                      and not window.tabs.isVisible() and list(window.cards) == [""]
                      and "작업 2건" in window.cards[""].text() and "수정 필요 1건" in window.cards[""].text()
                      and [tuple(item.data(256)) for item in job_cards(window)]
                      == [("day", "2026-10-12"), ("job", JOB_C), ("day", "2026-10-11"), ("job", JOB_B),
                          ("day", "2026-10-10"), ("job", JOB_A)])
    window.grab().save(str(shots / "fixture-home.png"))
    window.cards[""].click()
    app.processEvents()

    # Project page, jobs tab: this project's jobs by date, newest first; full titles on cards.
    cards = job_cards(window)
    info = {item.data(256)[1]: item.data(CARD_ROLE) for item in cards if item.data(256)[0] == "job"}
    f["group_jobs_tab"] = (window.current_key == "group:" and window.tabs.isVisible()
                           and [window.tabs.tabText(i) for i in range(3)] == ["작업 2", "결과물 8", "폴더"]
                           and window.tabs.currentIndex() == 0 and window.stack.currentWidget() is window.job_list
                           and not window.cards_area.isVisible() and window.preview.kind == "group"
                           and [item.data(256)[1] for item in cards] == ["2026-10-11", JOB_B, "2026-10-10", JOB_A]
                           and cards[3].text() == "보고서 페이지 작성"
                           and info[JOB_A] == {"status": "완료 · 검토 통과", "group": "done",
                                               "meta": "Codex 구현 · Claude 계획, 검토 · 파일 3개"}
                           and info[JOB_B]["group"] == "repair" and "파일 2개" in info[JOB_B]["meta"]
                           and window.page_path == root and "작업 2건 · 파일 10개" in window.page_meta.text())
    # A long title wraps onto a second line instead of being cut to a column width.
    delegate = window.job_list.itemDelegate()
    short = window.job_list.sizeHintForRow(3)
    cards[3].setText("보고서 페이지 작성 " * 20)
    app.processEvents()
    f["job_card_two_lines"] = window.job_list.sizeHintForRow(3) > short and delegate is not None
    cards[3].setText("보고서 페이지 작성")
    window.job_list.setCurrentItem(cards[3])
    app.processEvents()

    # Job detail: request, then result files, then checks/review with the phase summary; logs folded.
    text = window.preview.browser.toPlainText()
    order = [text.find(mark) for mark in ("요청 원문", "결과 파일", "검사와 검토", "단계별 로그 보기", "목표")]
    f["job_detail_order"] = (window.preview.kind == "job" and -1 not in order and order == sorted(order)
                             and "계획 Claude (opus)" in text and "검토 Claude (sonnet)" in text
                             and "검사 1회" in text and "response.md" not in text
                             and "작업 폴더 직속" in window.preview.meta.text())
    window.open_link("hub:toggle/phases")
    app.processEvents()
    opened = window.preview.browser.toPlainText()
    window.open_link("hub:toggle/phases")
    app.processEvents()
    f["job_phase_logs_toggle"] = ("response.md" in opened and "단계별 로그 접기" in opened
                                  and "response.md" not in window.preview.browser.toPlainText())
    # Logs opened for one job are folded again when another job is shown, and when coming back.
    window.open_link("hub:toggle/phases")
    window.job_list.setCurrentItem(cards[1])  # job B
    app.processEvents()
    other = window.preview.browser.toPlainText()
    window.job_list.setCurrentItem(cards[3])  # back to job A
    app.processEvents()
    back = window.preview.browser.toPlainText()
    f["job_phase_logs_folded_per_job"] = (
        window.preview.title.text() == "보고서 페이지 작성" and "차트 도구 수정" not in back
        and all("단계별 로그 보기" in text and "단계별 로그 접기" not in text for text in (other, back))
        and "checks.json" not in other and "review.model.json" not in other and "response.md" not in back)
    window.grab().save(str(shots / "fixture-group.png"))

    # Results tab: files worth opening only; folder tab: the old project tree and file table.
    window.tabs.setCurrentIndex(TABS.index("results"))
    app.processEvents()
    f["group_results_tab"] = (window.stack.currentWidget() is window.files_box and not window.folder_tree.isVisible()
                              and {tuple(item.data(0, 256)) for item in list_rows(window)}
                              == {("file", rel_key(path)) for path in (
                                  "output/report/README.md", "output/report/chart.png",
                                  "output/report/gpt-revision-prompt.md", "output/summary.md", "artifacts/top.png",
                                  "output/report/notes.txt", "output/report/sub/deep.txt", "artifacts/pack/log.txt")}
                              and window.current_key == "group:")
    window.reload()
    app.processEvents()
    f["group_tab_kept_on_reload"] = (window.current_key == "group:" and window.tabs.currentIndex() == 1
                                     and window.list.topLevelItemCount() == 8)
    window.tabs.setCurrentIndex(TABS.index("folders"))
    app.processEvents()
    tree = window.folder_tree
    f["group_folders_tab"] = (tree.isVisible() and window.stack.currentWidget() is window.files_box
                              and [tree.topLevelItem(i).text(0).split("  (")[0] for i in range(tree.topLevelItemCount())]
                              == ["output (직속 파일)", "output/report", "artifacts (직속 파일)", "artifacts/pack", "tool"]
                              and window.current_key == "project:output" and window.preview.kind == "project"
                              and nav.currentItem() is window.nodes["group:"])

    # Jobs tied to no project folder, and the whole history with project names.
    window.select_node("group:" + NO_GROUP)
    app.processEvents()
    f["no_project_jobs"] = ([tuple(item.data(256)) for item in job_cards(window)] == [("day", "2026-10-12"), ("job", JOB_C)]
                            and window.page_title.text() == "프로젝트 미지정" and window.page_path is None
                            and not window.page_folder_button.isVisible()
                            and [window.tabs.isTabVisible(i) for i in range(3)] == [True, False, False])
    window.select_node("history")
    app.processEvents()
    metas = {item.data(256)[1]: item.data(CARD_ROLE)["meta"] for item in job_cards(window) if item.data(256)[0] == "job"}
    f["history_page"] = (window.page_title.text() == "전체 작업 이력" and set(metas) == {JOB_A, JOB_B, JOB_C}
                         and metas[JOB_A].endswith("· 작업 폴더 직속") and "작업 폴더 직속" not in metas[JOB_C]
                         and metas[JOB_C].endswith("· 프로젝트 미지정")
                         and window.preview.kind == "history" and window.stack.currentWidget() is window.job_list)
    window.select_node("cleanup")
    app.processEvents()
    f["cleanup_page"] = (window.page_title.text() == "파일 정리" and window.preview.kind == "cleanup"
                         and window.stack.currentWidget() is window.files_box
                         and "미분류 파일" in window.preview.browser.toPlainText())

    # Search shows the table over any page and clearing it returns to the page.
    window.select_node("group:")
    window.tabs.setCurrentIndex(0)
    window.search.setText("차트")
    app.processEvents()
    searching = (window.page_title.text() == "검색 결과" and not window.tabs.isVisible()
                 and window.stack.currentWidget() is window.files_box
                 and ("job", JOB_B) in {tuple(item.data(0, 256)) for item in list_rows(window)})
    window.search.clear()
    app.processEvents()
    f["search_returns_to_page"] = (searching and window.page_title.text() == "작업 폴더 직속" and window.tabs.isVisible()
                                   and window.stack.currentWidget() is window.job_list)
    window.select_node("overview")
    app.processEvents()
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
    # The move goes through the window, not the real cursor: on native Windows another app in front
    # (the test window cannot take the foreground while the user works elsewhere) would catch a real
    # cursor move. A user's own mouse moving over the window meanwhile can still spoil an attempt.
    for attempt in range(1, 4):
        hover_at(viewport, row.center())  # hover job A's green row
        QTest.qWait(150)
        hover_shot = viewport.grab().toImage()
        hovered = pixel(hover_shot, row.left() + 3, row.center().y())
        selected = pixel(hover_shot, row_b.left() + 3, row_b.center().y())
        hover_at(viewport, row_b.center())  # leave job A
        QTest.qWait(150)
        after = pixel(viewport.grab().toImage(), row.left() + 3, row.center().y())
        f["hover_row_white"] = (close(hovered, "#FFFFFF", 3) and close(selected, "#D9D5FA", 6)
                                and close(after, STATUS_COLORS["done"], 4)
                                and close(pixel(hover_shot, header.sectionViewportPosition(0) + header.sectionSize(0) - 1,
                                                row.center().y()), SEPARATOR_COLOR))
        f["hover_attempts"] = attempt
        if f["hover_row_white"]:
            break
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
    f["selection_kept_after_op"] = window.current_key == "project:output/report"

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
                                         and window.current_key == "folder:output/report|sub"
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
                    and window.current_key == "project:" + area
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
        selected = other.current_key == "project:" + area
        first = len(done.done) == 1 and selected and other.list.topLevelItemCount() == 0
        other.reload()
        app.processEvents()
        bare_ok.append(first and other.current_key == "project:" + area
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
        cards = len(window.cards)
        busiest = max(index.groups(), key=lambda group: len(index.group_jobs(group)), default=None)
        if busiest is not None:
            window.select_node("group:" + busiest)
            app.processEvents()
            window.grab().save(str(shots / "real-project.png"))
        window.close()
    # Expected groups worked out without the indexer: every 'digits_' folder holding any file.
    numbered = sorted(child.name for child in root.iterdir()
                      if child.is_dir() and child.name.split("_", 1)[0].isdigit() and "_" in child.name
                      and any(path.is_file() for path in child.rglob("*")))
    groups = sorted({p.group for p in index.projects.values() if p.group})
    linked = [entry for entry in index.files.values() if entry.jobs and entry.project.split("/", 1)[0] in numbered]
    return {"real_jobs": len(index.jobs), "real_projects": len(index.projects), "real_files": len(index.files),
            "real_numbered_group_names": groups,
            "real_numbered_groups": groups == numbered,
            "real_project_cards": cards == len(index.groups()) and cards >= len(numbered),
            "real_alias_links": bool(linked) or not index.aliases,
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
        guard = install_input_guard(app)  # noqa: F841  kept alive for the whole run
        configure_fonts()
        app.setWindowIcon(make_icon())
        with tempfile.TemporaryDirectory() as work:
            flags = check_fixture(app, Path(work), shots)
            flags.update(check_numbered(app, Path(work), shots))
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
