"""App paths — gumagana sa dev mode AT sa PyInstaller frozen exe.

Sa dev mode: project root = dalawang folder pataas mula dito.
Sa frozen exe (PyInstaller onefile): ang __file__ ay nasa temp extraction
dir (_MEIPASS) na nabubura pagsara — kaya ang data/ ay dapat nasa TABI ng
.exe mismo para hindi mawala ang database at logs.
"""
from __future__ import annotations

import sys
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(name: str) -> Path:
    """Path ng bundled read-only resource (hal. icon.png).

    Sa frozen onefile exe, ang mga resource na idinagdag via --add-data ay
    nasa temp extraction dir (sys._MEIPASS), HINDI sa tabi ng exe.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / name
    return app_root() / name


DATA_DIR = app_root() / "data"
