"""SportsBet Pro — entry point.

Run:  .\\venv\\Scripts\\python.exe -m src.main
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# PySide6 ang Qt binding ng app. Kung may PyQt6 na maka-install (dependency
# ng ibang library), ito ang pumipigil sa qtawesome/qtpy na doon kumapit —
# nagko-crash ang icons kapag naghalo ang dalawang binding.
os.environ.setdefault("QT_API", "pyside6")
os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

# Para gumana kahit direktang patakbuhin (python main.py) —
# idagdag ang project root sa path bago ang src.* imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import truststore

truststore.inject_into_ssl()  # gamitin ang Windows cert store para sa TLS

from src.core.netdns import install_doh_resolver

install_doh_resolver()  # DoH para sa *.polymarket.com / *.kalshi.com — iwas DNS poisoning

import qasync
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.core.applog import asyncio_exception_handler, setup_logging
from src.core.engine_kalshi import KalshiEngine
from src.core.engine_poly import PolyEngine
from src.core.paths import resource_path
from src.storage.db import Database
from src.ui.main_window import MainWindow


def main() -> None:
    setup_logging()  # lahat ng errors -> data/app.log

    # Windows: itakda ang sariling AppUserModelID BAGO gumawa ng window.
    # Kung wala nito, iginugrupo ng Windows ang app sa ilalim ng host
    # process at ipinapakita ang GENERIC na taskbar icon kahit tama ang
    # setWindowIcon — kaya "walang icon" ang lumalabas sa taskbar.
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "SportsBetPro.Trading.App"
            )
        except Exception:  # hindi kritikal — huwag pigilan ang startup
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("SportsBet Pro")
    icon_file = resource_path("icon_square.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    loop.set_exception_handler(asyncio_exception_handler)

    db = Database()
    poly_db = db.scope("polymarket")
    kalshi_db = db.scope("kalshi")
    poly_engine = PolyEngine(poly_db)
    kalshi_engine = KalshiEngine(kalshi_db)
    window = MainWindow(db, poly_engine, kalshi_engine, poly_db, kalshi_db)
    window.showMaximized()  # default: fullscreen/maximized pag-open

    # I-defer ang startup hanggang tumatakbo na ang event loop
    # (kailangan ng asyncio.create_task ng running loop)
    def _on_loop_started() -> None:
        poly_engine.start_monitors()
        kalshi_engine.start_monitors()
        poly_engine.log("INFO", "Application started")
        kalshi_engine.log("INFO", "Application started")

    QTimer.singleShot(0, _on_loop_started)

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    main()
