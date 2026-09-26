"""MAF brand theme: brown, gold, white. One place for colours so every screen matches."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

from stockcompass.paths import resource

BROWN = "#6b3410"
BROWN_2 = "#94481a"
BROWN_DARK = "#2a1609"
GOLD = "#b8860b"
GOLD_SOFT = "#f3e6c4"
BG = "#faf7f2"
CARD = "#ffffff"
LINE = "#e8dfd2"
INK = "#2b2118"
MUTED = "#7a6a5a"
GOOD = "#2e7d4f"
GOOD_BG = "#e3f2e8"
WARN = "#b7791f"
WARN_BG = "#fdf1d8"
BAD = "#b3261e"
BAD_BG = "#fbe4e1"

STATUS = {"good": (GOOD, GOOD_BG), "warn": (WARN, WARN_BG), "bad": (BAD, BAD_BG), "": (MUTED, "#f1ece4")}

# Chart colours: brand-led, distinguishable, colour-blind safe enough for 3–6 series
SERIES = ["#94481a", "#b8860b", "#3b6ea5", "#6c8e3a", "#8a5a9e", "#c0604d"]

_loaded = False


def load_fonts():
    global _loaded
    if _loaded:
        return
    for f in ["NotoNastaliqUrdu-Regular.ttf", "NotoNastaliqUrdu-Bold.ttf", "NotoNaskhArabic-Regular.ttf",
              "NotoNaskhArabic-Bold.ttf"]:
        p = resource("assets", "fonts", f)
        if p.exists():
            QFontDatabase.addApplicationFont(str(p))
    _loaded = True


def base_font(urdu: bool, urdu_font: str = "Noto Nastaliq Urdu") -> QFont:
    if urdu:
        f = QFont(urdu_font)
        f.setPointSizeF(10.5 if "Nastaliq" in urdu_font else 10)
    else:
        f = QFont("Segoe UI")
        f.setPointSizeF(9.5)
    return f


def qss(urdu: bool = False) -> str:
    return f"""
    QWidget {{ color: {INK}; }}
    QMainWindow, QWidget#page {{ background: {BG}; }}
    QFrame#sidebar {{ background: {BROWN_DARK}; }}
    QLabel#brand {{ color: white; font-size: 17px; font-weight: 700; }}
    QLabel#brandsub {{ color: {GOLD_SOFT}; font-size: 11px; }}
    QPushButton#nav {{ color: #eadccb; background: transparent; border: none; text-align: {'right' if urdu else 'left'};
        padding: 9px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; }}
    QPushButton#nav:hover {{ background: #3d2413; }}
    QPushButton#nav:checked {{ background: #4a2c16; color: white; border-{'right' if urdu else 'left'}: 3px solid {GOLD}; }}
    QLabel#h1 {{ font-size: 22px; font-weight: 800; color: {INK}; }}
    QLabel#sub {{ color: {MUTED}; font-size: 12.5px; }}
    QLabel#h2 {{ font-size: 14px; font-weight: 800; }}
    QLabel#muted {{ color: {MUTED}; }}
    QLabel#chip {{ background: {GOLD_SOFT}; color: {BROWN}; border-radius: 9px; padding: 2px 8px; font-weight: 700; }}
    QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
    QFrame#kpi {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
    QFrame#kpi:hover {{ border: 1px solid {GOLD}; }}
    QFrame#insight {{ background: #fffdf9; border: 1px solid {LINE}; border-radius: 10px; }}
    QFrame#insight:hover {{ border: 1px solid {GOLD}; }}
    QFrame#topbar {{ background: {BG}; border-bottom: 1px solid {LINE}; }}
    QPushButton {{ background: white; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 12px; font-weight: 600; }}
    QPushButton:hover {{ border-color: {GOLD}; }}
    QPushButton#primary {{ background: {BROWN_2}; color: white; border: none; }}
    QPushButton#primary:hover {{ background: {BROWN}; }}
    QPushButton#primary:disabled {{ background: #c9b6a4; }}
    QPushButton#link {{ border: none; background: transparent; color: {BROWN_2}; padding: 0; text-align: left; }}
    QComboBox, QLineEdit, QDateEdit, QSpinBox, QDoubleSpinBox {{ background: white; border: 1px solid {LINE};
        border-radius: 8px; padding: 5px 8px; min-height: 22px; }}
    QComboBox:hover, QLineEdit:focus {{ border-color: {GOLD}; }}
    QTabWidget::pane {{ border: none; }}
    QTabBar::tab {{ background: transparent; padding: 8px 14px; margin-right: 4px; border-radius: 8px;
        color: {MUTED}; font-weight: 700; }}
    QTabBar::tab:selected {{ background: {BROWN_2}; color: white; }}
    QTabBar::tab:hover:!selected {{ background: {GOLD_SOFT}; color: {BROWN}; }}
    QTableView {{ background: white; border: 1px solid {LINE}; border-radius: 10px; gridline-color: #f2ece3;
        selection-background-color: {GOLD_SOFT}; selection-color: {INK}; alternate-background-color: #fcfaf6; }}
    QHeaderView::section {{ background: #f6f1ea; color: {MUTED}; font-weight: 800; border: none;
        border-bottom: 1px solid {LINE}; padding: 6px; }}
    QProgressBar {{ border: 1px solid {LINE}; border-radius: 6px; background: white; text-align: center; height: 16px; }}
    QProgressBar::chunk {{ background: {GOLD}; border-radius: 6px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QToolTip {{ background: {INK}; color: white; border: none; padding: 6px; }}
    """


def color(name: str) -> QColor:
    return QColor(name)
