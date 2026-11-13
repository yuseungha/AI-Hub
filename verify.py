"""One verification command: unit tests, then the packaged EXE smoke test (offscreen + native)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from indexer import find_root  # noqa: E402

# The app may sit directly in the workspace or inside a numbered project folder (03_AI-Hub/ai-hub).
WORKSPACE = find_root(ROOT.parent) or ROOT.parent
SOURCES = ("app.py", "ui.py", "indexer.py", "preview.py", "chatgpt.py", "fileops.py", "smoke.py", "build.py")


def main():
    temp = ROOT / ".build" / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    results = ROOT / "verification"
    results.mkdir(exist_ok=True)
    env = dict(os.environ, TEMP=str(temp), TMP=str(temp), QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1")
    command = [sys.executable, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-v"]
    test = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)
    (results / "tests.log").write_text(test.stdout + test.stderr, encoding="utf-8")
    print(test.stdout + test.stderr)
    summary = {"tests_passed": test.returncode == 0}
    exe = ROOT / "dist" / "AIHub.exe"
    if test.returncode == 0:
        if not exe.exists():
            print("Missing packaged EXE; run build.py first")
            summary["exe"] = "missing"
        elif exe.stat().st_mtime < max((ROOT / name).stat().st_mtime for name in SOURCES):
            print("AIHub.exe is older than the sources; run build.py again")
            summary["exe"] = "stale"
        else:
            summary["exe_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
            summary["exe_bytes"] = exe.stat().st_size
            platforms = ["offscreen", "windows"] if sys.platform == "win32" else ["offscreen"]
            for platform in platforms:
                report = results / f"packaged-{platform}.json"
                report.unlink(missing_ok=True)
                run = subprocess.run([str(exe), "--smoke-test", str(report), "--real-root", str(WORKSPACE)],
                                     cwd=ROOT, env=env | {"QT_QPA_PLATFORM": platform}, timeout=180)
                data = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
                summary[platform] = {
                    "exit_code": run.returncode, "passed": data.get("passed") is True,
                    "packaged": data.get("packaged") is True, "failed": data.get("failed"),
                    "error": data.get("error"), "real_jobs": data.get("real_jobs"),
                    "real_unchanged": data.get("real_unchanged"), "workspace_unchanged": data.get("workspace_unchanged")}
    platforms = [value for key, value in summary.items() if isinstance(value, dict)]
    summary["passed"] = (summary["tests_passed"] and bool(platforms) and all(
        item["exit_code"] == 0 and item["passed"] and item["packaged"] and item["real_unchanged"] is True
        and item["workspace_unchanged"] is True and (item["real_jobs"] or 0) > 0 for item in platforms))
    (results / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
