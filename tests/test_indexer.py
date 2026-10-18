import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer import build_index, rel_key, search_content, load_job, norm_ai, find_root, stale_files  # noqa: E402
from preview import build_preview, can_open_externally, decode  # noqa: E402
import smoke  # noqa: E402


class IndexerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = smoke.make_fixture(Path(self.temp.name) / "ws")
        self.before = smoke.tree_hash(self.root)
        self.index = build_index(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_roles_come_only_from_records(self):
        jobs = self.index.jobs
        self.assertEqual(jobs[smoke.JOB_A].roles(), {"codex": ["구현"], "claude": ["계획", "검토"]})
        self.assertEqual(jobs[smoke.JOB_B].roles(), {"claude": ["구현", "조사"], "codex": ["검토"]})
        investigate = jobs[smoke.JOB_B].phases[-1]
        self.assertEqual((investigate.action, investigate.provider, investigate.model), ("investigate", "claude", "opus"))
        self.assertEqual(jobs[smoke.JOB_B].phases[1].error, "auth failed")
        self.assertEqual(jobs[smoke.JOB_C].implementer, "unknown")
        self.assertEqual(len(self.index.problems), 2)

    def test_exact_file_links_and_unclassified(self):
        files = self.index.files
        self.assertEqual(files[rel_key("output/report/README.md")].jobs, [smoke.JOB_A])
        self.assertEqual(files[rel_key("output/report/chart.png")].jobs, [smoke.JOB_B])
        notes = files[rel_key("output/report/notes.txt")]
        self.assertEqual(notes.jobs, [])
        self.assertEqual(self.index.file_ais(notes), set())
        self.assertIn(notes, self.index.unclassified())
        self.assertEqual(self.index.project_ais(self.index.projects["output/report"]), {"codex", "claude"})

    def test_scan_scope(self):
        keys = set(self.index.files)
        self.assertFalse(any("node_modules" in key or ".venv" in key for key in keys))
        self.assertNotIn("tmp", self.index.projects)
        self.assertIn("tool", self.index.projects)
        self.assertNotIn("agent_lab", self.index.projects)
        direct = self.index.projects["output"]
        self.assertFalse(direct.recursive)
        self.assertEqual([entry.rel for entry in direct.files], ["output/summary.md"])
        self.assertEqual(direct.jobs, [smoke.JOB_A])
        self.assertIn(rel_key("artifacts/top.png"), keys)
        self.assertIn(rel_key("output/report/sub/deep.txt"), keys)
        # Each file belongs to exactly one project.
        self.assertEqual(sum(len(project.files) for project in self.index.projects.values()), len(keys))

    def test_file_limit_marks_truncation(self):
        index = build_index(self.root, limit=2)
        self.assertTrue(index.projects["output/report"].truncated)
        self.assertEqual(len(index.projects["output/report"].files), 2)
        self.assertTrue(any("2개까지만" in text for text in index.problems))

    def test_stale_files_by_modification_time(self):
        now = 2_000_000_000.0
        for entry in self.index.files.values():
            entry.mtime = now
        notes = self.index.files[rel_key("output/report/notes.txt")]
        readme = self.index.files[rel_key("output/report/README.md")]
        notes.mtime, readme.mtime = now - 100 * 86400, now - 400 * 86400
        self.assertEqual(stale_files(self.index, 90, now=now), [readme, notes])
        self.assertEqual(stale_files(self.index, 365, now=now), [readme])
        self.assertEqual(stale_files(self.index, 90, unlinked_only=True, now=now), [notes])
        self.assertEqual(stale_files(self.index, 500, now=now), [])

    def test_content_search(self):
        hits = search_content(self.index.files.values(), smoke.CONTENT_TOKEN.upper())
        self.assertEqual([entry.rel for entry in hits], ["output/report/notes.txt"])

    def test_missing_and_odd_records(self):
        odd = self.root / "agent_lab" / "jobs" / "20261013-000000-dddd"
        odd.mkdir()
        (odd / "manifest.json").write_text(json.dumps({"implementer": 3, "history": "x", "review": []}), encoding="utf-8")
        (odd / "task.json").write_text(json.dumps({"files": "nope", "acceptance": ["x"]}), encoding="utf-8")
        job = load_job(odd)
        self.assertEqual((job.implementer, job.files, job.acceptance, job.review_passed), ("unknown", [], [], None))
        self.assertEqual(norm_ai("Claude"), "claude")
        self.assertEqual(norm_ai("gpt-6.1-sol"), "codex")
        self.assertEqual(find_root(self.root / "output" / "report"), self.root)

    def test_index_is_read_only(self):
        build_index(self.root)
        search_content(self.index.files.values(), "x")
        for entry in self.index.files.values():
            build_preview(entry.path)
        self.assertEqual(smoke.tree_hash(self.root), self.before)


class PreviewTest(unittest.TestCase):
    def test_kinds(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "a.md").write_text("# 제목", encoding="utf-8")
            (folder / "b.json").write_text('{"x":1}', encoding="utf-8")
            (folder / "c.json").write_text("{bad", encoding="utf-8")
            (folder / "d.txt").write_bytes("한글".encode("cp949"))
            (folder / "e.bin").write_bytes(b"\x00\x01" * 10)
            (folder / "f.png").write_bytes(smoke.PNG_1PX)
            names = ("a.md", "b.json", "c.json", "d.txt", "e.bin", "f.png", "zz")
            kinds = {name: build_preview(folder / name).kind for name in names}
            self.assertEqual(kinds, {"a.md": "markdown", "b.json": "json", "c.json": "text", "d.txt": "text",
                                     "e.bin": "binary", "f.png": "image", "zz": "error"})
            self.assertEqual(build_preview(folder / "d.txt").text, "한글")
        self.assertFalse(can_open_externally(Path("x.exe")))
        self.assertFalse(can_open_externally(Path("x.PS1")))
        self.assertTrue(can_open_externally(Path("x.pdf")))
        self.assertEqual(decode("가".encode("utf-8")), "가")


if __name__ == "__main__":
    unittest.main()
