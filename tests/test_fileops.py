from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fileops  # noqa: E402


class FileOpsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "ws"
        self.src = self.root / "output" / "a"
        self.dest = self.root / "artifacts" / "b"
        self.jobs = self.root / "agent_lab" / "jobs" / "20261018-000000-x"
        for folder in (self.src, self.dest, self.jobs):
            folder.mkdir(parents=True)
        self.file = self.src / "report.md"
        self.file.write_text("new", encoding="utf-8")
        (self.dest / "report.md").write_text("existing", encoding="utf-8")
        self.record = self.jobs / "manifest.json"
        self.record.write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_never_overwrites(self):
        result = fileops.copy_files([self.file, self.file], self.dest, self.root)
        self.assertEqual([target.name for _, target in result.done], ["report (2).md", "report (3).md"])
        self.assertEqual((self.dest / "report.md").read_text(encoding="utf-8"), "existing")
        self.assertEqual((self.dest / "report (2).md").read_text(encoding="utf-8"), "new")
        self.assertTrue(self.file.exists())

    def test_move_renames_and_removes_source(self):
        result = fileops.move_files([self.file], self.dest, self.root)
        self.assertEqual(len(result.done), 1)
        self.assertFalse(self.file.exists())
        self.assertEqual((self.dest / "report.md").read_text(encoding="utf-8"), "existing")
        self.assertEqual((self.dest / "report (2).md").read_text(encoding="utf-8"), "new")

    def test_move_skips_same_folder_missing_and_bad_destination(self):
        result = fileops.move_files([self.file, self.src / "gone.md"], self.src, self.root)
        self.assertEqual(len(result.skipped), 2)
        self.assertTrue(self.file.exists())
        for dest in (self.root / "nope", self.jobs):
            result = fileops.move_files([self.file], dest, self.root)
            self.assertEqual(len(result.skipped), 1)
            self.assertTrue(self.file.exists())

    def test_job_records_and_running_exe_protected(self):
        calls = []
        result = fileops.trash_files([self.record, self.file], self.root, running=self.file.resolve(),
                                     trash=lambda path: calls.append(path) or True)
        self.assertEqual(calls, [])
        self.assertEqual(len(result.skipped), 2)
        self.assertTrue(self.record.exists() and self.file.exists())
        self.assertEqual(len(fileops.copy_files([self.record], self.dest, self.root).skipped), 1)

    def test_trash_failures_never_delete(self):
        for backend in (lambda path: False, lambda path: (_ for _ in ()).throw(OSError("denied")),
                        lambda path: True):  # True but file still there: reported, not retried
            result = fileops.trash_files([self.file], self.root, trash=backend)
            self.assertEqual(len(result.failed), 1)
            self.assertTrue(self.file.exists())
        self.assertIn("실패 1개", result.summary())

    def test_trash_success_and_default_backend(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        result = fileops.trash_files([self.file], self.root, trash=lambda path: bool(path.replace(bin_dir / path.name)))
        self.assertEqual(len(result.done), 1)
        self.assertFalse(self.file.exists())
        self.assertEqual(fileops.trash_files.__defaults__[-1], fileops.default_trash)

    def race(self, op):
        """A file appears under the chosen name right after it was picked."""
        real = fileops.free_target
        calls = []

        def racing(folder, name):
            target = real(folder, name)
            if not calls:
                target.write_text("intruder", encoding="utf-8")
            calls.append(target)
            return target
        fileops.free_target = racing
        try:
            return op()
        finally:
            fileops.free_target = real

    def test_copy_and_move_never_overwrite_a_racing_file(self):
        result = self.race(lambda: fileops.copy_files([self.file], self.dest, self.root))
        self.assertEqual(result.done[0][1].name, "report (3).md")
        self.assertEqual((self.dest / "report (2).md").read_text(encoding="utf-8"), "intruder")
        result = self.race(lambda: fileops.move_files([self.file], self.dest, self.root))
        self.assertEqual(result.done[0][1].name, "report (5).md")
        self.assertEqual((self.dest / "report (4).md").read_text(encoding="utf-8"), "intruder")
        self.assertEqual((self.dest / "report (5).md").read_text(encoding="utf-8"), "new")

    def test_failed_copy_removes_only_its_own_file(self):
        real = fileops.shutil.copyfileobj
        fileops.shutil.copyfileobj = lambda *args: (_ for _ in ()).throw(OSError("disk full"))
        try:
            result = fileops.copy_files([self.file], self.dest, self.root)
        finally:
            fileops.shutil.copyfileobj = real
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(sorted(path.name for path in self.dest.iterdir()), ["report.md"])
        self.assertEqual((self.dest / "report.md").read_text(encoding="utf-8"), "existing")
        self.assertTrue(self.file.exists())

    def test_cross_volume_move_uses_exclusive_copy(self):
        real_stat = Path.stat
        dest = self.dest

        class FakeStat:
            def __init__(self, stat):
                self.stat = stat

            def __getattr__(self, name):
                return getattr(self.stat, name)

            @property
            def st_dev(self):
                return -1  # pretend the destination is another volume

        def stat(path, *args, **kwargs):
            value = real_stat(path, *args, **kwargs)
            return FakeStat(value) if path == dest else value
        real_copy, copied = fileops.exclusive_copy, []
        fileops.exclusive_copy = lambda source, folder: copied.append(source) or real_copy(source, folder)
        Path.stat = stat
        try:
            result = fileops.move_files([self.file], self.dest, self.root)
        finally:
            Path.stat = real_stat
            fileops.exclusive_copy = real_copy
        self.assertEqual(copied, [self.file])
        self.assertEqual(result.done[0][1].name, "report (2).md")
        self.assertFalse(self.file.exists())
        self.assertEqual((self.dest / "report.md").read_text(encoding="utf-8"), "existing")

    def test_free_target(self):
        self.assertEqual(fileops.free_target(self.dest, "new.txt").name, "new.txt")
        self.assertEqual(fileops.free_target(self.dest, "report.md").name, "report (2).md")


if __name__ == "__main__":
    unittest.main()
