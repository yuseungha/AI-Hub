import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import smoke  # noqa: E402


class WindowSmokeTest(unittest.TestCase):
    def test_fixture_window(self):
        with tempfile.TemporaryDirectory() as temp:
            report = Path(temp) / "report.json"
            code = smoke.run(report)
            data = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(data.get("failed"), [], data.get("error"))
        self.assertIsNone(data.get("error"))
        self.assertEqual(code, 0)
        self.assertTrue(data["passed"])
        self.assertGreaterEqual(sum(value is True for value in data.values()), 30)


if __name__ == "__main__":
    unittest.main()
