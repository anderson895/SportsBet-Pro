"""Shared sub-pages ng bawat exchange panel: Trades, Logs, Statistics, About.

Galing sa PolyTradePro main_window.py — na-parameterize lang per exchange
(ScopedDatabase + currency label) para magamit ng Polymarket AT Kalshi panel.
"""
from __future__ import annotations

import datetime as dt
from typing import Callable, Optional

import qtawesome as qta
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.storage.db import ScopedDatabase
from src.ui import theme
from src.ui.widgets import Card

# Ang isang "trade" row ay naitatala pagka-PLACE ng order, hindi pagka-fill.
# Kailangang malinaw ito sa table — kung hindi, mukhang nagastos na ang pera
# gayong nakapila pa lang ang order at buo pa ang balance.
STATUS_LABELS = {
    "OPEN": "RESTING (not filled)",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELLED",
}
STATUS_COLORS = {
    "OPEN": theme.AMBER,
    "FILLED": theme.GREEN,
    "CANCELLED": theme.MUTED,
}
# Napalitan na ng totoong exchange fills — nasa DB pa para sa audit pero
# hindi na ipinapakita, kung hindi ay doble ang parehong straddle
HIDDEN_STATUSES = {"SUPERSEDED"}


def local_time(ts: str) -> str:
    """ISO timestamp -> HH:MM:SS sa LOCAL time ng user.

    Ang mga ts ay naka-UTC (galing sa app o sa Kalshi) at may iba-ibang
    hugis: "…+00:00" mula sa atin, "…Z" na may microseconds mula sa
    Kalshi. Kapag hindi ma-parse, ibabalik ang hilaw na hiwa kaysa
    magkamali ng oras.
    """
    raw = (ts or "").strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[11:19]
    if parsed.tzinfo is None:            # walang zone = UTC ang assume
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone().strftime("%H:%M:%S")


def local_datetime(ts: str) -> str:
    """ISO timestamp -> "Jul 26, 2026  09:27:36 AM" sa LOCAL time.

    Para sa Trades table: kasama ang PETSA at 12-hour na oras na may
    AM/PM — mas madaling maintindihan kaysa sa 24-hour na oras lang,
    lalo na kapag maraming araw ang trade history. Gaya ng local_time(),
    ibinabalik ang hilaw na hiwa kapag hindi ma-parse.
    """
    raw = (ts or "").strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone().strftime("%b %d, %Y  %I:%M:%S %p")


class TradesPage(QWidget):
    cleared = Signal()  # emitted after the trade history is wiped

    def __init__(self, db: ScopedDatabase, currency: str = "USD",
                 on_sync: Optional[Callable[[], None]] = None) -> None:
        super().__init__()
        self._db = db
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Date & Time", "Market", "Side", "Action", "Price",
             f"Size ({currency})", "Status", "PnL"]
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        # Date & Time: auto-fit sa "Jul 26, 2026  09:27:36 AM"
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setCursor(Qt.CursorShape.PointingHandCursor)
        self.table.cellDoubleClicked.connect(self._open_details)
        self._currency = currency

        title = QLabel("Trades")
        title.setProperty("accent", True)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch()
        # Ang lokal na tala ay isinusulat pagka-PLACE ng order; ang exchange
        # ang may ground truth kung ano talaga ang na-fill. Ito ang paraan
        # para ma-reconcile ang dalawa.
        if on_sync is not None:
            sync_btn = QPushButton("  Sync from exchange")
            sync_btn.setIcon(qta.icon("fa6s.cloud-arrow-down",
                                      color=theme.TEXT))
            sync_btn.setToolTip(
                "Import the real fill history from the exchange so this "
                "table matches your account exactly."
            )
            sync_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            sync_btn.clicked.connect(on_sync)
            head.addWidget(sync_btn)

        clear_btn = QPushButton("  Clear Trades")
        clear_btn.setIcon(qta.icon("fa6s.trash-can", color=theme.MUTED))
        clear_btn.setToolTip(
            "Permanently delete this exchange's trade history from the local "
            "database. Does not touch your exchange account."
        )
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_trades)
        head.addWidget(clear_btn)

        self.status = QLabel("")
        self.status.setProperty("muted", True)

        hint = QLabel("Double-click a row to see the full trade details.")
        hint.setProperty("muted", True)

        root = QVBoxLayout(self)
        root.addLayout(head)
        root.addWidget(self.table, stretch=1)
        root.addWidget(hint)
        root.addWidget(self.status)
        self.reload()

    def _open_details(self, row: int, _col: int) -> None:
        item = self.table.item(row, 1)   # Market column
        if item is None:
            return
        # Naka-import dito para maiwasan ang circular import (ang
        # trade_details ay gumagamit ng mga helper mula sa module na ito)
        from src.ui.trade_details import TradeDetailDialog
        TradeDetailDialog(self._db, item.text(), self._currency, self).exec()

    def _clear_trades(self) -> None:
        """Wipe this exchange's local trade history (with confirmation)."""
        count = len(self._db.recent_trades(limit=100000))
        if count == 0:
            self.set_status("No trades to clear.", theme.MUTED)
            return
        reply = QMessageBox.question(
            self,
            "Clear trade history?",
            f"Permanently delete all {count} trade record(s) for this "
            "exchange from the local database?\n\nThis only clears the "
            "local history and statistics — it does NOT cancel or change "
            "anything on your exchange account. It cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._db.clear_trades()
        self.reload()
        self.set_status(f"Cleared {count} trade record(s).", theme.MUTED)
        self.cleared.emit()

    def set_status(self, text: str, color: str = theme.MUTED) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}")

    def reload(self) -> None:
        self.table.setRowCount(0)
        for row in self._db.recent_trades(limit=200):
            status = row["status"] or ""
            if status in HIDDEN_STATUSES:
                continue
            r = self.table.rowCount()
            self.table.insertRow(r)
            pnl = row["pnl"]
            values = [
                local_datetime(row["ts"]), row["market"], row["side"], row["action"],
                f"{row['price']:.2f}", f"{row['size']:.2f}",
                STATUS_LABELS.get(status, status),
                "" if pnl is None else f"{pnl:+.2f}",
            ]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                if col == 6:
                    item.setForeground(QColor(STATUS_COLORS.get(status,
                                                                theme.MUTED)))
                elif col == 7 and pnl is not None:
                    item.setForeground(QColor(theme.GREEN if pnl >= 0 else theme.RED))
                self.table.setItem(r, col, item)


class LogsPage(QWidget):
    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Time", "Level", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        root = QVBoxLayout(self)
        title = QLabel("Logs")
        title.setProperty("accent", True)
        root.addWidget(title)
        root.addWidget(self.table, stretch=1)

        # local_time(): ang mga naka-imbak na ts ay UTC, pero LOCAL ang
        # gamit ng add_log() sa mga live entry — dapat pareho ang basehan
        for row in self._db.recent_logs(limit=500):
            self._add_row(local_time(row["ts"]), row["level"], row["message"])

    def add_log(self, level: str, message: str) -> None:
        self._add_row(dt.datetime.now().strftime("%H:%M:%S"), level, message, prepend=True)

    def _add_row(self, ts: str, level: str, message: str, prepend: bool = False) -> None:
        r = 0 if prepend else self.table.rowCount()
        self.table.insertRow(r)
        for col, val in enumerate([ts, level, message]):
            self.table.setItem(r, col, QTableWidgetItem(val))


class StatsPage(QWidget):
    def __init__(self, db: ScopedDatabase, currency: str = "USD") -> None:
        super().__init__()
        self._db = db
        self._currency = currency
        title = QLabel("Statistics")
        title.setProperty("accent", True)

        self._labels: dict[str, QLabel] = {}
        panel = Card()
        col = QVBoxLayout(panel)
        col.setContentsMargins(16, 14, 16, 14)
        for key in ("Closed Trades", "Wins", "Losses", "Win Rate", "Total PnL"):
            lab = QLabel(f"{key}: —")
            lab.setStyleSheet("font-size: 15px")
            self._labels[key] = lab
            col.addWidget(lab)

        root = QVBoxLayout(self)
        root.addWidget(title)
        root.addWidget(panel)
        root.addStretch()
        self.refresh()

    def refresh(self) -> None:
        stats = self._db.trade_stats()
        pnl = self._db.total_pnl()
        closed = stats["closed"]
        win_rate = (stats["wins"] / closed * 100) if closed else 0.0
        self._labels["Closed Trades"].setText(f"Closed Trades: {closed}")
        self._labels["Wins"].setText(f"Wins: {stats['wins']}")
        self._labels["Losses"].setText(f"Losses: {stats['losses']}")
        self._labels["Win Rate"].setText(f"Win Rate: {win_rate:.0f}%")
        color = theme.GREEN if pnl >= 0 else theme.RED
        self._labels["Total PnL"].setText(f"Total PnL: {pnl:+,.2f} {self._currency}")
        self._labels["Total PnL"].setStyleSheet(f"font-size: 15px; color: {color}")


# NB: ang AboutPage ay lumipat sa about_page.py — searchable na ito ngayon
# at may buong dokumentasyon (tingnan ang help_content.py).
