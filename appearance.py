"""Shared visual tokens, local AI icons and validated per-profile accent colours."""
from functools import lru_cache
from html import escape
from pathlib import Path
import re

from PySide6.QtGui import QColor, QIcon

ASSETS = Path(__file__).resolve().parent / "assets"
DEFAULT_AI_COLORS = {"codex": "#2563EB", "claude": "#C2410C", "chatgpt": "#0E8A6A",
                     "unknown": "#7A7F93", "local": "#7A7F93"}


def load_ai_colors(saved=None):
    colors = dict(DEFAULT_AI_COLORS)
    if isinstance(saved, dict):
        for ai in colors:
            value = saved.get(ai)
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                colors[ai] = value.upper()
    return colors


def text_color(value):
    """Keep even a user-selected light accent readable on a white surface."""
    color = QColor(value)
    def luminance(c):
        rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
               for v in (c.redF(), c.greenF(), c.blueF())]
        return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
    # The darkest selection surface used for AI labels is #D9D5FA.
    # This tighter limit also exceeds 4.5:1 on the white normal surface.
    while luminance(color) > .11:
        color = color.darker(110)
    return color.name()


def swatch_text_color(value):
    c = QColor(value)
    rgb = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4
           for v in (c.redF(), c.greenF(), c.blueF())]
    luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
    return "#FFFFFF" if luminance < .179 else "#000000"


@lru_cache(maxsize=8)
def ai_icon(ai):
    path = ASSETS / f"{ai}.svg"
    return QIcon(str(path)) if path.is_file() else QIcon()


def icon_html(ai, size=18):
    path = ASSETS / f"{ai}.png"
    return (f'<img src="{escape(path.as_uri(), quote=True)}" width="{size}" height="{size}" style="vertical-align:middle"> '
            if path.is_file() else "")


DOCUMENT_STYLE = """
body { color: #2B2A3A; font-family: 'Malgun Gothic'; font-size: 10pt; line-height: 150%; }
h2 { font-size: 12pt; margin-top: 20px; margin-bottom: 10px; }
h3 { font-size: 11pt; margin-top: 20px; margin-bottom: 8px; }
p { margin-top: 0; margin-bottom: 12px; line-height: 150%; }
ul, ol { margin-top: 4px; margin-bottom: 14px; margin-left: 0; -qt-list-indent: 1; }
li { margin-bottom: 8px; }
a { color: #5149C5; text-decoration: none; }
table { border-collapse: collapse; }
td, th { padding: 6px 10px; }
pre { white-space: pre-wrap; }
"""
