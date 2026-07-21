"""Dark theme (QSS) — pattern sa PolyTrade Pro mockup."""
from src.core.paths import resource_path

# Icon assets para sa QSS subcontrols (ang CSS border-triangle trick ay
# hindi maaasahan sa Qt) — gawa via tests/make_arrows.py
_PLUS = resource_path("assets/plus.png").as_posix()
_MINUS = resource_path("assets/minus.png").as_posix()
_CHEVRON = resource_path("assets/chevron_down.png").as_posix()
_CHECK = resource_path("assets/check.png").as_posix()

# Palette
BG = "#0b0f1a"
CARD = "#111827"
BORDER = "#1f2937"
INPUT_BG = "#0d1424"
TEXT = "#e5e7eb"
MUTED = "#9ca3af"
ACCENT = "#6366f1"
ACCENT_DIM = "#1e1b4b"
GREEN = "#22c55e"
RED = "#ef4444"
AMBER = "#f59e0b"
BTC_BLUE = "#3b82f6"
KALSHI_TEAL = "#14b8a6"

STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: 'Segoe UI';
    font-size: 13px;
}}
QLabel {{ background: transparent; border: none; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[h1="true"] {{ font-size: 26px; font-weight: bold; }}
QLabel[h2="true"] {{ font-size: 16px; font-weight: bold; }}
QLabel[accent="true"] {{ color: {ACCENT}; font-weight: bold; font-size: 14px; }}

QFrame[card="true"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}

QListWidget#sidebar {{
    background: {BG};
    border: none;
    outline: none;
    font-size: 14px;
}}
QListWidget#sidebar::item {{
    padding: 10px 14px;
    border-radius: 6px;
    margin: 2px 8px;
    color: {MUTED};
}}
/* Collapsed (icon-only): mas maliit na padding para kasya at nakagitna
   ang icons sa makitid na sidebar */
QListWidget#sidebar[collapsed="true"]::item {{
    padding: 10px 6px;
    margin: 2px 4px;
}}
QListWidget#sidebar::item:hover {{ background: {CARD}; }}
QListWidget#sidebar::item:selected {{
    background: {ACCENT_DIM};
    color: #c7d2fe;
}}

/* Exchange switcher tabs (Polymarket / Kalshi) */
QPushButton[exchangeTab="true"] {{
    background: transparent;
    border: none;
    border-bottom: 3px solid transparent;
    border-radius: 0;
    padding: 10px 24px;
    color: {MUTED};
    font-size: 15px;
    font-weight: bold;
}}
QPushButton[exchangeTab="true"]:hover {{ color: {TEXT}; }}
QPushButton[exchangeTab="true"][active="true"] {{
    color: #c7d2fe;
    border-bottom: 3px solid {ACCENT};
}}

QPushButton {{
    background: {BORDER};
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 8px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #374151; }}
QPushButton:disabled {{ color: #6b7280; }}
QPushButton#startBtn {{
    background: #16a34a; color: white;
    font-weight: bold; font-size: 15px; padding: 10px 28px;
    border: none;
}}
QPushButton#startBtn:hover {{ background: {GREEN}; }}
QPushButton#startBtn:disabled {{ background: #14532d; color: {MUTED}; }}
QPushButton#stopBtn {{
    background: transparent; color: {RED};
    border: 1px solid {RED};
    font-weight: bold; font-size: 15px; padding: 10px 28px;
}}
QPushButton#stopBtn:hover {{ background: #7f1d1d; }}
QPushButton#stopBtn:disabled {{ border-color: #7f1d1d; color: #7f1d1d; }}
QPushButton#accentBtn {{ background: {ACCENT}; color: white; border: none; }}
QPushButton#accentBtn:hover {{ background: #818cf8; }}

QComboBox {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 22px;
    color: {TEXT};
}}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox:hover {{ border-color: #4b5563; background: #111a2e; }}
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
    padding: 6px 10px;
    border-radius: 4px;
    min-height: 22px;
}}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT_DIM};
    color: #c7d2fe;
}}

QLineEdit, QDoubleSpinBox, QSpinBox {{
    background: {INPUT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    min-height: 22px;
    color: {TEXT};
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}

QDoubleSpinBox::up-button, QSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    border-top-right-radius: 6px;
    background: {CARD};
}}
QDoubleSpinBox::down-button, QSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 24px;
    border-left: 1px solid {BORDER};
    border-bottom-right-radius: 6px;
    background: {CARD};
}}
QDoubleSpinBox::up-button:hover, QSpinBox::up-button:hover,
QDoubleSpinBox::down-button:hover, QSpinBox::down-button:hover {{
    background: #374151;
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
    border: 1px solid {BORDER};
    border-radius: 8px;
    gridline-color: {BORDER};
}}
QTableWidget::item {{ padding: 4px; }}
QHeaderView::section {{
    background: {INPUT_BG};
    border: none;
    padding: 8px;
    color: {MUTED};
    font-weight: bold;
}}
QListWidget {{ background: {CARD}; border: none; border-radius: 8px; }}
QToolButton {{ background: transparent; border: none; color: {MUTED}; font-size: 14px; }}
QToolButton:hover {{ color: {TEXT}; }}

QCheckBox {{ spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER}; border-radius: 4px;
    background: {INPUT_BG};
}}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{
    background: {ACCENT}; border-color: {ACCENT};
    image: url("{_CHECK}");
}}

QScrollBar:vertical {{
    background: {BG}; width: 10px; border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: #374151; border-radius: 5px; min-height: 24px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
"""
