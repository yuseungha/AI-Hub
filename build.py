"""Build dist/AIHub.exe with local-only build/cache paths (same approach as Dayline)."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / ".build"


def main():
    BUILD.mkdir(exist_ok=True)
    (BUILD / "tmp").mkdir(exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(BUILD / "tmp")
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(BUILD / "pyinstaller-cache")
    # Keep incompatible ICU DLLs from other tools on PATH out of dependency analysis.
    windows = Path(os.environ.get("WINDIR", "C:/Windows"))
    os.environ["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix),
        windows / "System32", windows, windows / "System32" / "Wbem",
    )))
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication
    from app import make_icon, configure_fonts
    application = QApplication([])
    configure_fonts()
    icon = BUILD / "aihub.ico"
    if not make_icon().pixmap(256, 256).save(str(icon)):
        raise RuntimeError("Could not generate app icon")
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
               "--add-data", str(ROOT / "assets") + os.pathsep + "assets",
               "--copy-metadata", "pypdf", "--hidden-import", "smoke",
               "--name", "AIHub", "--icon", str(icon), "--distpath", str(ROOT / "dist"),
               "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
               "--paths", str(ROOT), str(ROOT / "app.py")]
    subprocess.run(command, cwd=ROOT, check=True)
    print(f"Built: {ROOT / 'dist' / 'AIHub.exe'}")


if __name__ == "__main__":
    main()
