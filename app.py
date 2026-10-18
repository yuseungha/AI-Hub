"""Windows entry point. --smoke-test runs against an isolated temporary fixture."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (QIcon, QPixmap, QPainter, QPainterPath, QColor, QFont, QFontDatabase,
                           QLinearGradient, QRadialGradient, QPen)
from PySide6.QtWidgets import QApplication

from indexer import find_root
from ui import MainWindow, Settings, default_settings_path


def configure_fonts():
    # The offscreen Qt plugin does not enumerate system fonts; load them explicitly.
    folder = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    for filename in ("malgun.ttf", "malgunbd.ttf", "segoeui.ttf", "seguisb.ttf", "consola.ttf"):
        path = folder / filename
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    QApplication.setFont(QFont("Malgun Gothic", 10))


def paint_icon(painter: QPainter):
    """Silver mini desktop with an engraved 'AI', transparent background, 256×256 box (no logos)."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    shadow = QRadialGradient(QPointF(128, 214), 120)
    shadow.setColorAt(0, QColor(0, 0, 0, 90))
    shadow.setColorAt(1, QColor(0, 0, 0, 0))
    painter.setBrush(shadow)
    painter.drawEllipse(QRectF(14, 200, 228, 28))

    base = QPainterPath()  # dark vented foot, slightly inset
    base.moveTo(26, 172)
    base.lineTo(230, 172)
    base.lineTo(218, 204)
    base.quadTo(216, 210, 209, 210)
    base.lineTo(47, 210)
    base.quadTo(40, 210, 38, 204)
    base.closeSubpath()
    painter.setBrush(QColor("#1C1E22"))
    painter.drawPath(base)
    painter.setPen(QPen(QColor("#40444B"), 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for x in range(50, 208, 7):
        painter.drawLine(QPointF(x, 182), QPointF(x, 201))
    painter.setPen(Qt.PenStyle.NoPen)

    body = QRectF(8, 66, 240, 112)
    metal = QLinearGradient(0, body.top(), 0, body.bottom())
    metal.setColorAt(0, QColor("#FDFDFE"))
    metal.setColorAt(0.18, QColor("#ECEDEF"))
    metal.setColorAt(0.85, QColor("#D3D5D9"))
    metal.setColorAt(1, QColor("#BEC1C6"))
    painter.setBrush(metal)
    painter.setPen(QPen(QColor(20, 30, 50, 90), 1.6))  # edge stays visible on white desktops
    painter.drawRoundedRect(body, 20, 20)
    sheen = QLinearGradient(body.left(), 0, body.right(), 0)  # soft side shading
    sheen.setColorAt(0, QColor(255, 255, 255, 0))
    sheen.setColorAt(0.5, QColor(255, 255, 255, 70))
    sheen.setColorAt(1, QColor(120, 125, 135, 40))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(sheen)
    painter.drawRoundedRect(body, 20, 20)
    painter.setPen(QPen(QColor(255, 255, 255, 230), 2))
    painter.drawLine(QPointF(28, 69), QPointF(228, 69))

    painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
    for x in (30, 50):  # two USB-C style slots
        painter.setBrush(QColor("#26282C"))
        painter.drawRoundedRect(QRectF(x, 104, 9, 34), 4.5, 4.5)
    painter.setPen(Qt.PenStyle.NoPen)
    glow = QRadialGradient(QPointF(204, 121), 11)
    glow.setColorAt(0, QColor(255, 255, 255, 200))
    glow.setColorAt(1, QColor(255, 255, 255, 0))
    painter.setBrush(glow)
    painter.drawEllipse(QPointF(204, 121), 11, 11)
    painter.setBrush(QColor("white"))
    painter.drawEllipse(QPointF(204, 121), 4, 4)
    painter.setBrush(QColor("#17181B"))
    painter.drawEllipse(QPointF(226, 121), 7, 7)

    # 'AI' filled as a path: plain text rendering may add ClearType colour fringes.
    font = QFont("Segoe UI", 60, QFont.Weight.Bold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
    text = QPainterPath()
    text.addText(0, 0, font, "AI")
    box = text.boundingRect()
    text.translate(124 - box.center().x(), 122 - box.center().y())
    painter.setBrush(QColor(255, 255, 255, 200))  # light lower edge reads as engraving
    painter.drawPath(text.translated(0, 1.5))
    painter.setBrush(QColor("#2E3135"))
    painter.drawPath(text)


def make_icon():
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(QColor("transparent"))
        painter = QPainter(pixmap)
        painter.scale(size / 256, size / 256)
        paint_icon(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def app_dir():
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def resolve_root(cli_root, settings):
    if cli_root:
        return Path(cli_root)
    saved = settings.get("root")
    if saved and Path(saved).is_dir():
        return Path(saved)
    return find_root(app_dir()) or find_root(Path.cwd())


def main(argv=None):
    parser = argparse.ArgumentParser(description="AI 작업 허브")
    parser.add_argument("--root", help="agent_lab이 있는 작업 폴더")
    parser.add_argument("--smoke-test", metavar="REPORT", help="격리된 픽스처로 자체 검사 후 JSON 보고")
    parser.add_argument("--real-root", help="스모크 테스트에서 추가로 읽기 전용 검사할 실제 작업 폴더")
    args = parser.parse_args(argv)
    if args.smoke_test:
        import smoke
        return smoke.run(Path(args.smoke_test), Path(args.real_root) if args.real_root else None)
    app = QApplication.instance() or QApplication(sys.argv)
    configure_fonts()
    app.setWindowIcon(make_icon())
    settings = Settings(default_settings_path())
    window = MainWindow(resolve_root(args.root, settings), settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
