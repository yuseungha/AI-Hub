import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chatgpt  # noqa: E402
import smoke  # noqa: E402


class ChatGPTExportTest(unittest.TestCase):
    def test_zip_current_branch_only(self):
        with tempfile.TemporaryDirectory() as temp:
            conversations = chatgpt.load_export(smoke.make_export(Path(temp) / "export.zip"))
        self.assertEqual([conv.id for conv in conversations], ["conv-1", "conv-2"])
        self.assertEqual([(m.role, m.text) for m in conversations[0].messages],
                         [("user", "요약해줘"), ("assistant", "요약 결과"), ("user", "고마워")])
        self.assertEqual(conversations[1].messages, [])
        self.assertIn("표시할 메시지 없음", chatgpt.to_markdown(conversations[1]))

    def test_plain_json_fallback_leaf_and_attachments(self):
        data = [{"title": "t", "current_node": "missing", "mapping": {
            "s": {"message": {"author": {"role": "system"}, "content": {"parts": ["sys"]}},
                  "parent": None, "children": ["a"]},
            "a": {"message": {"author": {"role": "assistant"},
                              "content": {"parts": ["hi", {"content_type": "image_asset_pointer"}]}},
                  "parent": "s", "children": []}}},
            "junk"]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "conversations.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            result = chatgpt.load_export(path)
        self.assertEqual(len(result), 1)
        self.assertEqual([(m.role, m.text) for m in result[0].messages],
                         [("assistant", "hi\n[image_asset_pointer]")])

    def test_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "bad.json").write_text("{", encoding="utf-8")
            (folder / "wrong.json").write_text('"text"', encoding="utf-8")
            with zipfile.ZipFile(folder / "empty.zip", "w") as archive:
                archive.writestr("other.txt", "x")
            (folder / "broken.zip").write_bytes(b"not a zip")
            for name in ("bad.json", "wrong.json", "empty.zip", "broken.zip", "missing.json"):
                with self.assertRaises(chatgpt.ExportError, msg=name):
                    chatgpt.load_export(folder / name)


if __name__ == "__main__":
    unittest.main()
