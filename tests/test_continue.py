"""'이어가기 요청 복사' in the job detail: what it copies, and that copying changes no file."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication  # noqa: E402

import smoke  # noqa: E402
from ui import MainWindow, Settings, continue_request  # noqa: E402


class ContinueRequestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "workspace"
        smoke.make_fixture(self.root)
        self.window = MainWindow(self.root, Settings(base / "profile" / "settings.json"))
        self.addCleanup(self.window.close)
        self.window.show()
        self.app.processEvents()

    def test_text_names_the_job_folder_status_and_request(self):
        job = self.window.index.jobs[smoke.JOB_A]
        lines = continue_request(job).splitlines()
        self.assertEqual(lines[0], f"`{job.path}` 의 agent_lab 작업 기록(task.json·manifest.json·단계별 로그)을 읽고 "
                                   f"이어서 진행해줘. 작업 ID: {smoke.JOB_A}")
        self.assertTrue(lines[1].startswith("현재 상태: 완료"))
        self.assertEqual(lines[2], "요청: 주간 보고서 웹페이지 만들어줘")
        self.assertEqual(len(lines), 3)  # a finished job gets no extra instruction

    def test_needs_repair_job_says_where_to_start(self):
        text = continue_request(self.window.index.jobs[smoke.JOB_B])
        self.assertIn("현재 상태: 수정 필요", text)
        self.assertTrue(text.endswith("마지막 검토에서 수정 필요로 끝났으니 지적된 부분부터 고쳐줘."))

    def test_link_in_job_detail_copies_without_touching_files(self):
        before = smoke.tree_hash(self.root)
        self.window.show_job(smoke.JOB_B)
        self.assertIn("이어가기 요청 복사", self.window.preview.browser.toPlainText())
        QApplication.clipboard().clear()
        self.window.open_link(f"hub:continue/{smoke.JOB_B}")
        self.assertEqual(QApplication.clipboard().text(), continue_request(self.window.index.jobs[smoke.JOB_B]))
        self.assertIn("이어가기 요청을 복사했습니다", self.window.statusBar().currentMessage())
        self.window.open_link("hub:continue/no-such-job")  # stale link: nothing happens
        self.assertEqual(smoke.tree_hash(self.root), before)


if __name__ == "__main__":
    unittest.main()
