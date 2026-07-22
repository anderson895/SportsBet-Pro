"""Dark theme (QSS) — SportsBet Pro "Slate + Emerald" palette.

Base = malamig na slate + emerald primary. Bawat exchange panel ay may
sariling accent (Polymarket = indigo, Kalshi = teal) na ipinapatong sa
ibabaw ng base palette via panel-level stylesheet (tingnan
`panel_accent_qss` sa widgets.py).
"""
from src.core.paths import resource_path

# Icon assets para sa QSS subcontrols (ang CSS border-triangle trick ay
# hindi maaasahan sa Qt) — gawa via tests/make_arrows.py
_PLUS = resource_path("assets/plus.png").as_posix()
_MINUS = resource_path("assets/minus.png").as_posix()
_CHEVRON = resource_path("assets/chevron_down.png").as_posix()
_CHECK = resource_path("assets/check.png").as_posix()

# ---- Palette (Kalshi-inspired near-black + mint) --------------------------
BG = "#0a0c0d"          # near-black — window background (Kalshi vibe)
BG_ELEV = "#101314"     # bahagyang mas mataas (bottom bar / top strip)
CARD = "#15181a"        # cards
CARD_HOVER = "#1c2023"  # card hover
BORDER = "#282d31"      # borders
BORDER_SOFT = "#1e2225" # mas mahinang divider
INPUT_BG = "#101315"    # input fields
TEXT = "#f0f2f3"        # near-white
MUTED = "#9aa4ad"       # muted gray
FAINT = "#616b73"       # faintest gray

ACCENT = "#12cf8a"      # Kalshi mint — shared primary
ACCENT_HOVER = "#3ee0a6"
ACCENT_DIM = "#0d3a2b"  # mint na napaka-dim (selection bg)
ACCENT_SOFT = "#0b2a20"

GREEN = "#12cf8a"       # mint (tugma sa Kalshi)
RED = "#f75d6b"         # rose (Kalshi-style)
AMBER = "#f5b23b"
BTC_BLUE = "#4c8dff"

# ---- Per-exchange accents -------------------------------------------------
POLY_ACCENT = "#8b8cf8"       # indigo/violet (Polymarket brand)
POLY_ACCENT_DIM = "#211f45"
KALSHI_ACCENT = "#12cf8a"     # Kalshi mint
KALSHI_ACCENT_DIM = "#0d3a2b"
KALSHI_TEAL = KALSHI_ACCENT   # back-compat alias

STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Segoe UI';
    font-size: 13px;
}}
QLabel {{ background: transparent; border: none; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[h1="true"] {{ font-size: 27px; font-weight: 800; letter-spacing: -0.5px; }}
QLabel[h2="true"] {{ font-size: 16px; font-weight: 700; }}
QLabel[accent="true"] {{ color: {ACCENT}; font-weight: 700; font-size: 14px;
    letter-spacing: 0.3px; }}

QFrame[card="true"] {{
    background: {CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 12px;
}}

/* ---- Status pill badges ---- */
QLabel[pill="ok"], QLabel[pill="info"], QLabel[pill="warn"],
QLabel[pill="bad"], QLabel[pill="muted"], QLabel[pill="outline"] {{
    border-radius: 9px;
    padding: 3px 11px;
    font-size: 11px;
    font-weight: 700;
}}
QLabel[pill="ok"]      {{ background: {ACCENT_DIM}; color: {ACCENT_HOVER}; }}
QLabel[pill="info"]    {{ background: {CARD_HOVER}; color: {MUTED};
                          border: 1px solid {BORDER}; }}
QLabel[pill="warn"]    {{ background: #3b2c0a; color: {AMBER}; }}
QLabel[pill="bad"]     {{ background: #3b1717; color: #fca5a5; }}
QLabel[pill="muted"]   {{ background: {CARD_HOVER}; color: {FAINT}; }}
QLabel[pill="outline"] {{ background: transparent; color: {ACCENT};
                          border: 1px solid {ACCENT}; font-size: 13px; }}

QListWidget#sidebar {{
    background: transparent;
    border: none;
    outline: none;
    font-size: 14px;
}}
QListWidget#sidebar::item {{
    padding: 11px 14px;
    border-radius: 9px;
    margin: 3px 8px;
    color: {MUTED};
}}
QListWidget#sidebar[collapsed="true"]::item {{
    padding: 11px 6px;
    margin: 3px 4px;
}}
QListWidget#sidebar::item:hover {{ background: {CARD_HOVER}; color: {TEXT}; }}
QListWidget#sidebar::item:selected {{
    background: {ACCENT_DIM};
    color: {ACCENT_HOVER};
    font-weight: 600;
}}

/* ---- Exchange switcher tabs (Polymarket / Kalshi) ---- */
QPushButton[exchangeTab="true"] {{
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    padding: 12px 22px;
    color: {MUTED};
    font-size: 15px;
    font-weight: 700;
}}
QPushButton[exchangeTab="true"]:hover {{ color: {TEXT}; }}
QPushButton[exchangeTab="true"][active="true"] {{
    color: {TEXT};
    border-bottom: 3px solid {ACCENT};
}}

QPushButton {{
    background: {BORDER};
    border: 1px solid #3d4b63;
    border-radius: 9px;
    padding: 9px 15px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #3d4b63; }}
QPushButton:disabled {{ color: {FAINT}; }}

QPushButton#startBtn {{
    background: {ACCENT}; color: #04231a;
    font-weight: 800; font-size: 15px; padding: 11px 30px;
    border: 1px solid {ACCENT_HOVER};
    border-radius: 10px;
}}
QPushButton#startBtn:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#startBtn:disabled {{ background: {ACCENT_SOFT}; color: {FAINT};
    border-color: {ACCENT_SOFT}; }}
QPushButton#stopBtn {{
    background: transparent; color: {RED};
    border: 1px solid {RED};
    font-weight: 800; font-size: 15px; padding: 11px 30px;
    border-radius: 10px;
}}
QPushButton#stopBtn:hover {{ background: #3b1717; }}
QPushButton#stopBtn:disabled {{ border-color: #4a2020; color: #6b2f2f; }}
QPushButton#accentBtn {{ background: {ACCENT}; color: #04231a;
    font-weight: 700; border: none; }}
QPushButton#accentBtn:hover {{ background: {ACCENT_HOVER}; }}

QComboBox {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 11px;
    min-height: 22px;
    color: {TEXT};
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox:hover {{ border-color: #47566f; background: #1a2437; }}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url("{_CHEVRON}");
    width: 14px;
    height: 14px;
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    color: {TEXT};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 7px 10px;
    border-radius: 6px;
    min-height: 22px;
}}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT_DIM};
    color: {ACCENT_HOVER};
}}

QLineEdit, QDoubleSpinBox, QSpinBox, QPlainTextEdit {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 9px;
    padding: 7px 11px;
    min-height: 22px;
    color: {TEXT};
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus,
QPlainTextEdit:focus {{ border-color: {ACCENT}; }}

QDoubleSpinBox::up-button, QSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    border-top-right-radius: 9px;
    background: {CARD};
}}
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border-left: 1px solid {BORDER};
    border-bottom-right-radius: 9px;
    background: {CARD};
}}
QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {{
    background: #3d4b63;
}}
QDoubleSpinBox::up-arrow, QSpinBox::up-arrow {{
    image: url("{_PLUS}");
    width: 11px;
    height: 11px;
}}
QDoubleSpinBox::down-arrow, QSpinBox::down-arrow {{
    image: url("{_MINUS}");
    width: 11px;
    height: 11px;
}}

QScrollArea {{ background: transparent; border: none; }}

QTableWidget {{
    background: {CARD};
    border: 1px solid {BORDER_SOFT};
    border-radius: 12px;
    gridline-color: {BORDER_SOFT};
}}
QTableWidget::item {{ padding: 5px; }}
QTableWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}
QHeaderView::section {{
    background: {INPUT_BG};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px;
    color: {MUTED};
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QListWidget {{ background: {CARD}; border: none; border-radius: 12px; }}
QToolButton {{ background: transparent; border: none; color: {MUTED};
    font-size: 14px; }}
QToolButton:hover {{ color: {TEXT}; }}

QCheckBox {{ spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {BORDER}; border-radius: 5px;
    background: {INPUT_BG};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
    image: url("{_CHECK}");
}}

QScrollBar:vertical {{
    background: transparent; width: 10px; border-radius: 5px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #3d4b63; border-radius: 5px; min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: #47566f; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:horizontal {{ background: #3d4b63; border-radius: 5px;
    min-width: 28px; }}
"""
