import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from indexer import (build_index, rel_key, search_content, load_job, norm_ai, find_root, stale_files,  # noqa: E402
                     NO_GROUP, group_label, is_deliverable)
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

    def test_job_size_sums_existing_listed_files(self):
        files = self.index.files
        expected = sum(files[rel_key(path)].size for path in ("tool/main.py", "output/report/chart.png"))
        self.assertEqual(self.index.job_size(smoke.JOB_B), expected)  # gone.txt is missing, not counted
        self.assertEqual([entry.rel for entry in self.index.job_files(smoke.JOB_B)],
                         ["tool/main.py", "output/report/chart.png"])
        self.assertEqual(self.index.job_size(smoke.JOB_C), 0)  # corrupt record lists nothing
        self.index.jobs[smoke.JOB_A].files.append("output/report/README.md")  # duplicate counted once
        self.assertEqual(len(self.index.job_files(smoke.JOB_A)), 3)

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


class NumberedLayoutTest(unittest.TestCase):
    """Workspace split into 01_… project folders while job records keep the old paths."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = smoke.make_numbered_fixture(Path(self.temp.name) / "ws")
        self.before = smoke.tree_hash(self.root)
        self.index = build_index(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_project_folders_and_scope(self):
        projects = self.index.projects
        self.assertEqual(set(projects), {"01_Sample", "01_Sample/output", "01_Sample/output/report",
                                         "01_Sample/artifacts/pack", "01_Sample/tool", "02_Other/output"})
        self.assertEqual({key: (p.area, p.recursive, p.group) for key, p in projects.items()}, {
            "01_Sample": ("app", False, "01_Sample"), "01_Sample/output": ("output", False, "01_Sample"),
            "01_Sample/output/report": ("output", True, "01_Sample"),
            "01_Sample/artifacts/pack": ("artifacts", True, "01_Sample"),
            "01_Sample/tool": ("app", True, "01_Sample"), "02_Other/output": ("output", False, "02_Other")})
        self.assertEqual([e.rel for e in projects["01_Sample"].files], ["01_Sample/README.md"])
        self.assertEqual([e.rel for e in projects["01_Sample/output"].files], ["01_Sample/output/summary.md"])
        keys = set(self.index.files)
        self.assertFalse(any("/tmp/" in key or ".runtime" in key or ".venv" in key for key in keys))
        self.assertNotIn(rel_key("notes/free.txt"), keys)  # unnumbered root folder not referenced by any job
        self.assertEqual(sum(len(p.files) for p in projects.values()), len(keys))  # each file in one project

    def test_old_job_paths_follow_aliases(self):
        files = self.index.files
        moved, tool = files[rel_key("01_Sample/output/report/README.md")], files[rel_key("01_Sample/tool/main.py")]
        self.assertEqual((moved.jobs, tool.jobs), ([smoke.JOB_N], [smoke.JOB_N]))
        self.assertEqual(self.index.job_size(smoke.JOB_N), moved.size + tool.size)  # gone.txt stays missing
        self.assertEqual(self.index.resolve("OUTPUT\\Report/sub/deep.txt"), rel_key("01_Sample/output/report/sub/deep.txt"))
        self.assertEqual(self.index.resolve("output/reporting.md"), "output/reporting.md")  # prefix must end at a folder
        self.assertIn(smoke.JOB_N, self.index.projects["01_Sample/tool"].jobs)
        self.assertEqual(self.index.problems, [])
        self.assertEqual(smoke.tree_hash(self.root), self.before)

    def test_longest_alias_wins(self):
        (self.root / "agent_lab" / "path-aliases.json").write_text(json.dumps({"aliases": [
            {"old": "output", "new": "02_Other/output"}, {"old": "output/report", "new": "01_Sample/output/report"},
            {"old": 5, "new": "x"}]}), encoding="utf-8")
        index = build_index(self.root)
        self.assertEqual(index.resolve("output/report/README.md"), rel_key("01_Sample/output/report/README.md"))
        self.assertEqual(index.resolve("output/note.txt"), rel_key("02_Other/output/note.txt"))
        self.assertTrue(any("잘못된 항목 1개" in text for text in index.problems))

    def test_missing_or_broken_aliases(self):
        alias_file = self.root / "agent_lab" / "path-aliases.json"
        alias_file.unlink()
        index = build_index(self.root)
        self.assertEqual(index.files[rel_key("01_Sample/output/report/README.md")].jobs, [])
        self.assertEqual(index.resolve("output/report/README.md"), "output/report/readme.md")  # original path kept
        self.assertEqual([text for text in index.problems if "path-aliases.json 없음" in text], [index.problems[0]])
        self.assertEqual(len(index.problems), 1)
        alias_file.write_text("{ broken", encoding="utf-8")
        index = build_index(self.root)
        self.assertEqual(index.files[rel_key("01_Sample/output/report/README.md")].jobs, [])
        self.assertTrue(any("path-aliases.json 손상" in text for text in index.problems))


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


class GroupTest(unittest.TestCase):
    """Project groups (numbered folders), the jobs tied to them and the deliverable filter."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_numbered_groups_and_their_jobs(self):
        index = build_index(smoke.make_numbered_fixture(self.work / "numbered"))
        self.assertEqual(list(index.groups()), ["01_Sample", "02_Other"])
        self.assertEqual([job.id for job in index.group_jobs("01_Sample")], [smoke.JOB_N])
        self.assertEqual(index.group_jobs("02_Other"), [])
        self.assertEqual(index.job_groups(smoke.JOB_N), ["01_Sample"])
        self.assertEqual(index.group_jobs(NO_GROUP), [])
        self.assertEqual(len(index.group_files("01_Sample")), sum(
            len(project.files) for project in index.projects.values() if project.group == "01_Sample"))
        self.assertEqual((group_label("01_Sample"), group_label("99_기타"), group_label(""), group_label(NO_GROUP)),
                         ("Sample", "기타", "작업 폴더 직속", "프로젝트 미지정"))

    def test_numbered_folder_without_indexed_files_is_still_a_group(self):
        root = smoke.make_numbered_fixture(self.work / "numbered")
        (root / "03_Empty").mkdir()
        smoke.write(root / "04_OnlyScratch" / "tmp" / "scratch.txt", "scratch\n")
        smoke.write(root / "04_OnlyScratch" / ".venv" / "lib.py", "x = 1\n")
        index = build_index(root)
        self.assertEqual(list(index.groups()), ["01_Sample", "02_Other", "03_Empty", "04_OnlyScratch"])
        self.assertEqual((index.groups()["03_Empty"], index.group_jobs("03_Empty"), index.group_files("03_Empty"),
                          index.deliverables("04_OnlyScratch")), ([], [], [], []))

    def test_jobs_stay_with_their_project_after_files_are_deleted(self):
        root = smoke.make_numbered_fixture(self.work / "numbered")
        (root / "03_Empty").mkdir()
        jobs = root / "agent_lab" / "jobs"
        cases = {"20261101-010000-aaaa0001": ["02_Other/removed-folder/gone.md"],  # sub-folder deleted
                 "20261101-020000-aaaa0002": ["tool/removed.py"],  # old path, alias → 01_Sample/tool, file deleted
                 "20261101-030000-aaaa0003": ["03_Empty/output/report.pdf"],  # folder now empty
                 "20261101-040000-aaaa0004": ["01_SAMPLE\\README.md", "02_Other/output/note.txt"],  # two projects
                 "20261101-050000-aaaa0005": ["09_Missing/output/x.md", "../outside.txt"]}
        for job_id, files in cases.items():
            smoke.write(jobs / job_id / "task.json", {"request": job_id, "goal": "", "files": files})
            smoke.write(jobs / job_id / "manifest.json", {"version": 2, "implementer": "codex", "status": "completed",
                                                          "history": []})
        index = build_index(root)
        ids = list(cases)
        self.assertEqual([index.job_groups(job_id) for job_id in ids],
                         [["02_Other"], ["01_Sample"], ["03_Empty"], ["01_Sample", "02_Other"], []])
        self.assertEqual([job.id for job in index.group_jobs("02_Other")], [ids[3], ids[0]])
        self.assertEqual([job.id for job in index.group_jobs("01_Sample")], [ids[3], ids[1], smoke.JOB_N])
        self.assertEqual([job.id for job in index.group_jobs("03_Empty")], [ids[2]])
        self.assertEqual([job.id for job in index.group_jobs(NO_GROUP)], [ids[4]])  # folder gone or never a project

    def test_root_jobs_stay_after_files_are_deleted(self):
        root = smoke.make_fixture(self.work / "ws")
        job = root / "agent_lab" / "jobs" / "20261101-010000-aaaa0001"
        smoke.write(job / "task.json", {"request": "지운 결과", "goal": "", "files": ["output/removed/gone.md"]})
        smoke.write(job / "manifest.json", {"version": 2, "implementer": "codex", "status": "completed", "history": []})
        index = build_index(root)
        self.assertEqual(index.job_groups(job.name), [""])
        self.assertEqual([item.id for item in index.group_jobs("")], [job.name, smoke.JOB_B, smoke.JOB_A])
        self.assertEqual([item.id for item in index.group_jobs(NO_GROUP)], [smoke.JOB_C])

    def test_root_paths_keep_the_root_group_without_indexed_files(self):
        # Nothing is left under output/ or artifacts/ (or they never existed), yet the recorded
        # paths still tie the jobs to the workspace-root group instead of 'no project'.
        bare = self.work / "bare"
        job = bare / "agent_lab" / "jobs" / "20261101-010000-aaaa0001"
        smoke.write(job / "task.json", {"request": "지운 결과", "goal": "", "files": ["artifacts/gone/x.png"]})
        smoke.write(job / "manifest.json", {"version": 2, "implementer": "codex", "status": "completed", "history": []})
        index = build_index(bare)
        self.assertEqual((list(index.groups()), index.groups()[""], index.group_files("")), ([""], [], []))
        self.assertEqual(([item.id for item in index.group_jobs("")], index.group_jobs(NO_GROUP)), ([job.name], []))

        # Numbered layout without the alias table: old 'output/…' paths go to the root group, listed last.
        plain = build_index(smoke.make_numbered_fixture(self.work / "plain", aliases=False))
        self.assertEqual(list(plain.groups()), ["01_Sample", "02_Other", ""])
        self.assertEqual((plain.job_groups(smoke.JOB_N), plain.group_jobs(NO_GROUP)), ([""], []))

    def test_other_root_paths_belong_to_the_root_group(self):
        # A root app folder that was deleted and files sitting in the workspace root are still
        # workspace-root work; paths outside the workspace, scratch space and excluded folders are not.
        root = smoke.make_numbered_fixture(self.work / "numbered")
        jobs = root / "agent_lab" / "jobs"
        cases = {"20261101-010000-aaaa0001": ["removed-tool/main.py"], "20261101-020000-aaaa0002": ["PROGRESS.md"],
                 "20261101-030000-aaaa0003": ["agent_lab/settings.json", "01_Sample/README.md"],
                 "20261101-040000-aaaa0004": ["../outside.txt", "C:/abs/x.md", "tmp/scratch.txt", ".venv/lib.py",
                                              ".runtime/x", "", "09_Missing/x.md"]}
        for job_id, files in cases.items():
            smoke.write(jobs / job_id / "task.json", {"request": job_id, "goal": "", "files": files})
            smoke.write(jobs / job_id / "manifest.json", {"version": 2, "implementer": "codex", "status": "completed",
                                                          "history": []})
        index = build_index(root)
        ids = list(cases)
        self.assertEqual([index.job_groups(job_id) for job_id in ids], [[""], [""], ["01_Sample", ""], []])
        self.assertEqual(list(index.groups()), ["01_Sample", "02_Other", ""])
        self.assertEqual([job.id for job in index.group_jobs(NO_GROUP)], [ids[3]])

    def test_check_and_record_folders_are_not_deliverables(self):
        root = smoke.make_fixture(self.work / "ws")
        for folder in ("checks", "check", "records", "record", "Verification", "sub/logs"):
            smoke.write(root / "output" / "report" / folder / "result.pdf", b"%PDF-1.4")
            smoke.write(root / "output" / "report" / folder / "result.txt", "x\n")
        smoke.write(root / "output" / "report" / "docs" / "guide.pdf", b"%PDF-1.4")
        index = build_index(root)
        names = {entry.rel for entry in index.deliverables("")}
        self.assertIn("output/report/docs/guide.pdf", names)
        self.assertEqual([name for name in names if "/result." in name], [])

    def test_full_title_is_not_cut(self):
        root = smoke.make_fixture(self.work / "ws")
        long = "아주 긴 작업 목표 문장 " * 12  # 150+ characters, one line
        job = root / "agent_lab" / "jobs" / "20261014-060000-eeee5555"
        smoke.write(job / "task.json", {"request": "짧은 요청", "goal": long + "\n둘째 줄", "files": []})
        smoke.write(job / "manifest.json", {"version": 2, "implementer": "claude", "status": "completed", "history": []})
        loaded = build_index(root).jobs[job.name]
        self.assertEqual(loaded.full_title, long.strip())
        self.assertGreater(len(loaded.full_title), 90)
        self.assertTrue(loaded.title.endswith("…") and len(loaded.title) == 90)  # the table keeps the short form

    def test_root_group_and_jobs_without_project(self):
        index = build_index(smoke.make_fixture(self.work / "ws"))
        self.assertEqual(list(index.groups()), [""])
        self.assertEqual([job.id for job in index.group_jobs("")], [smoke.JOB_B, smoke.JOB_A])  # newest first
        self.assertEqual([job.id for job in index.group_jobs(NO_GROUP)], [smoke.JOB_C])  # corrupt record, no files
        self.assertEqual(index.job_groups(smoke.JOB_C), [])

    def test_deliverables_keep_viewable_results_only(self):
        root = smoke.make_fixture(self.work / "ws")
        smoke.write(root / "output" / "report" / "verification" / "shot.png", smoke.PNG_1PX)
        smoke.write(root / "output" / "report" / "run-shots" / "a.png", smoke.PNG_1PX)
        smoke.write(root / "output" / "report" / "tests" / "guide.md", "# test notes\n")
        smoke.write(root / "output" / "report" / "app.exe", b"MZ")
        index = build_index(root)
        names = sorted(entry.rel for entry in index.deliverables(""))
        smoke.write(root / "output" / "report" / "logs" / "run.txt", "log\n")
        smoke.write(root / "output" / "report" / "history" / "old.txt", "old\n")
        index = build_index(root)
        names = sorted(entry.rel for entry in index.deliverables(""))
        # Plain text documents count; the same files under check/log/record folders do not.
        self.assertEqual(names, ["artifacts/pack/log.txt", "artifacts/top.png", "output/report/README.md",
                                 "output/report/app.exe", "output/report/chart.png",
                                 "output/report/gpt-revision-prompt.md", "output/report/notes.txt",
                                 "output/report/sub/deep.txt", "output/summary.md"])
        self.assertFalse(is_deliverable(index.files[rel_key("output/report/data.json")]))
        self.assertFalse(is_deliverable(index.files[rel_key("tool/main.py")]))


if __name__ == "__main__":
    unittest.main()
