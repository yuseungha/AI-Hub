import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from appearance import DEFAULT_AI_COLORS, ASSETS, ai_icon, load_ai_colors, text_color
from smoke import make_fixture, JOB_A
from ui import MainWindow, Settings, AppearanceDialog


class AppearanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        make_fixture(self.root / "workspace")
        self.settings = Settings(self.root / "profile" / "settings.json")
        self.window = MainWindow(self.root / "workspace", self.settings)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_custom_colors_survive_restart_and_reach_navigation_html_and_phases(self):
        self.window.select_node("history")
        self.window.show_job(JOB_A)
        self.window.apply_ai_colors({"codex": "#123456", "claude": "#654321"})
        self.assertEqual(self.window.current_key, "history")
        self.assertEqual(self.window.current_job, JOB_A)
        self.assertEqual(self.window.preview.kind, "job")
        self.assertEqual(self.window.nodes["ai:codex"].foreground(0).color().name(), "#123456")
        html = self.window.preview.browser.toHtml().lower()
        self.assertIn("#123456", html)
        self.assertIn("#654321", html)
        self.assertIn("codex.png", html)
        profile = Settings(self.settings.path)
        again = MainWindow(self.root / "workspace", profile)
        self.assertEqual(again.ai_colors["codex"], "#123456")
        self.assertEqual(again.ai_colors["chatgpt"], DEFAULT_AI_COLORS["chatgpt"])
        again.close()

    def test_malformed_color_settings_cannot_inject_styles(self):
        for broken in (None, [], "x", 3):
            self.assertEqual(load_ai_colors(broken), DEFAULT_AI_COLORS)
        self.assertEqual(load_ai_colors({"codex": "#fff; color:red"})["codex"], DEFAULT_AI_COLORS["codex"])
        self.assertEqual(load_ai_colors({"codex": "#abcdef"})["codex"], "#ABCDEF")

    def test_light_accents_stay_readable_without_changing_saved_accent(self):
        self.window.apply_ai_colors({"codex": "#FFFFFF"})
        self.assertEqual(self.window.ai_colors["codex"], "#FFFFFF")
        self.assertNotEqual(text_color("#FFFFFF"), "#ffffff")
        self.assertNotEqual(self.window.nodes["ai:codex"].foreground(0).color().name(), "#ffffff")

    def test_cancel_and_restore_in_dialog_do_not_mutate_profile(self):
        before = dict(self.window.ai_colors)
        dialog = AppearanceDialog(before, self.window)
        dialog.colors["codex"] = "#FF0000"
        dialog.reject()
        self.assertEqual(self.window.ai_colors, before)
        self.assertNotIn("ai_colors", self.settings)
        dialog.reset_colors()
        self.assertEqual(dialog.colors, DEFAULT_AI_COLORS)

    def test_icons_are_available_for_native_and_rich_text(self):
        for ai in DEFAULT_AI_COLORS:
            self.assertFalse(ai_icon(ai).pixmap(24, 24).isNull(), ai)
            if ai in ("codex", "claude", "chatgpt"):
                self.assertTrue((ASSETS / f"{ai}.png").is_file())
                self.assertFalse(self.window.nodes[f"ai:{ai}"].icon(0).isNull())

    def test_small_window_and_preview_alignment(self):
        self.window.root_label.setText("C:/" + "very-long-folder/" * 40)
        for width, height in ((1024, 640), (1280, 720), (1440, 860)):
            self.window.resize(width, height)
            self.app.processEvents()
            self.assertLessEqual(self.window.centralWidget().minimumSizeHint().width(), width)
            self.assertEqual(self.window.width(), width)
            self.assertLessEqual(self.window.cards_area.height(), max(96, int(self.window.center.height() * .4)))
            preview = self.window.preview
            self.assertEqual(preview.layout().contentsMargins().left(), 16)
            self.assertEqual(preview.browser.document().documentMargin(), 0)
            self.assertEqual(preview.title.x(), preview.stack.x())
            self.assertFalse(preview.open_button.isVisible())
            for widget in (self.window.search, self.window.export_button, self.window.appearance_button):
                right = widget.mapTo(self.window, widget.rect().topRight()).x()
                self.assertLess(right, self.window.width())

    def test_color_changes_keep_search_and_file_preview_without_rescanning(self):
        index = self.window.index
        self.window.search.setText("README")
        self.app.processEvents()
        item = next(self.window.list.topLevelItem(i) for i in range(self.window.list.topLevelItemCount())
                    if self.window.list.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)[0] == "file")
        self.window.list.setCurrentItem(item)
        path = self.window.preview.path
        self.window.apply_ai_colors({"codex": "#112233"})
        self.assertIs(self.window.index, index)
        self.assertEqual(self.window.search.text(), "README")
        self.assertEqual(self.window.page_title.text(), "검색 결과")
        self.assertEqual(self.window.preview.path, path)
        self.assertEqual(self.window.preview.kind, "markdown")

    def test_root_button_returns_to_secondary_after_root_is_chosen(self):
        self.window.root_button.setObjectName("primary")
        self.window.reload()
        self.assertEqual(self.window.root_button.objectName(), "")

    def test_fresh_columns_fit_visible_table_and_manual_widths_are_preserved(self):
        from PySide6.QtTest import QTest
        self.window.resize(1440, 860)
        self.window.select_node("project:output/report")
        self.app.processEvents()
        width = self.window.list.viewport().width()
        self.assertGreaterEqual(width, 504)
        self.assertLessEqual(sum(self.window.list.columnWidth(c) for c in range(6)), width)
        QTest.qWait(450)
        self.assertNotIn("list_columns", self.settings)
        self.window.list.setColumnWidth(1, 310)
        self.window.resize(1280, 720)
        self.app.processEvents()
        self.assertEqual(self.window.list.columnWidth(1), 310)
        self.window.save_column_widths()
        self.assertEqual(Settings(self.settings.path)["list_columns"][1], 310)

    def test_empty_workspace_has_a_valid_read_only_view(self):
        empty = self.root / "empty"
        empty.mkdir()
        window = MainWindow(empty, Settings(self.root / "empty-settings.json"))
        window.show()
        self.app.processEvents()
        self.assertEqual(window.index.jobs, {})
        self.assertIn("아직 작업 기록이 없습니다", window.preview.browser.toPlainText())
        window.select_node("unclassified")
        self.app.processEvents()
        self.assertEqual(window.list.topLevelItemCount(), 0)
        self.assertTrue(window.list.empty_label.isVisible())
        self.assertEqual(list(empty.iterdir()), [])
        window.close()

    def test_workspace_with_aliases_and_no_jobs_is_valid(self):
        from smoke import check_real, write
        from indexer import build_index
        root = self.root / "alias-only"
        (root / "01_Empty" / "output").mkdir(parents=True)
        write(root / "agent_lab" / "path-aliases.json", {"version": 1, "aliases": [
            {"old": "output", "new": "01_Empty/output"}]})
        self.assertTrue(build_index(root).aliases)
        shots = self.root / "alias-shots"
        shots.mkdir()
        checks = check_real(self.app, root, shots, shots)
        self.assertEqual(checks["real_jobs"], 0)
        for flag in ("real_loaded", "real_alias_links", "real_unchanged", "real_numbered_groups"):
            self.assertTrue(checks[flag], flag)


if __name__ == "__main__":
    unittest.main()
