"""Live Kalshi-style probability chart (pyqtgraph).

Dalawang linya tulad ng kalshi.com: YES (mint) at NO (rose), parehong
nakaporsyento (0-100%). Dahil binary ang market, ang YES + NO ≈ 100,
kaya nagmi-mirror ang dalawang linya sa paligid ng 50 — doon nakaangkla
ang straddle target.

In-memory lang (per session) — nagsisimula sa blanko kada bagong market;
pinapakain ng engine ang bawat market tick via `add_tick`.
"""
from __future__ import annotations

import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.ui import theme

MAX_POINTS = 5000


class KalshiChart(pg.PlotWidget):
    def __init__(self) -> None:
        super().__init__(axisItems={"bottom": pg.DateAxisItem()})
        self.setBackground(theme.CARD)
        self.setMinimumHeight(230)
        self.showGrid(x=True, y=True, alpha=0.10)
        self.setMouseEnabled(x=True, y=False)
        self.hideAxis("left")
        self.showAxis("right")
        self.getAxis("right").setWidth(44)
        # Auto-zoom ang Y sa nakikitang data (tulad ng 30-70% zoom ng
        # kalshi.com) — mas kitang-kita ang galaw kaysa fixed 0-100
        self.getViewBox().setAutoVisible(y=True)
        self.enableAutoRange(axis="y")

        self._t: deque[float] = deque(maxlen=MAX_POINTS)
        self._yes: deque[float] = deque(maxlen=MAX_POINTS)
        self._no: deque[float] = deque(maxlen=MAX_POINTS)
        self._window_secs = 30 * 60  # ipakita ang huling 30 min (auto-follow)

        # 50% reference line — dito nakaangkla ang box-arbitrage entry
        mid_line = pg.InfiniteLine(
            pos=50, angle=0,
            pen=pg.mkPen("#3a4655", width=1, style=Qt.PenStyle.DashLine),
        )
        self.addItem(mid_line, ignoreBounds=True)

        yes_fill = QColor(theme.ACCENT)
        yes_fill.setAlpha(26)
        self._yes_curve = self.plot(pen=pg.mkPen(theme.ACCENT, width=2))
        self._no_curve = self.plot(pen=pg.mkPen(theme.RED, width=2))

        self._yes_badge = self._make_badge(theme.ACCENT)
        self._no_badge = self._make_badge(theme.RED)
        for badge in (self._yes_badge, self._no_badge):
            badge.hide()
            self.addItem(badge, ignoreBounds=True)

        # Default na time window kahit walang data pa (para malinis ang axis)
        now = time.time()
        self.setXRange(now - self._window_secs, now, padding=0.02)

    def _make_badge(self, color: str) -> pg.InfiniteLine:
        return pg.InfiniteLine(
            angle=0, pen=pg.mkPen(None),
            label="", labelOpts={
                "position": 0.997, "color": "#ffffff",
                "fill": pg.mkBrush(color),
                "anchors": [(1, 0.5), (1, 0.5)],
            },
        )

    # ------------------------------------------------------------------ API

    def reset(self) -> None:
        self._t.clear()
        self._yes.clear()
        self._no.clear()
        self._yes_curve.setData([], [])
        self._no_curve.setData([], [])
        self._yes_badge.hide()
        self._no_badge.hide()

    def add_tick(self, yes_pct: float, no_pct: float) -> None:
        now = time.time()
        self._t.append(now)
        self._yes.append(yes_pct)
        self._no.append(no_pct)
        ts = list(self._t)
        self._yes_curve.setData(ts, list(self._yes))
        self._no_curve.setData(ts, list(self._no))

        self._yes_badge.setValue(yes_pct)
        self._yes_badge.label.setFormat(f"{yes_pct:.0f}%")
        self._yes_badge.show()
        self._no_badge.setValue(no_pct)
        self._no_badge.label.setFormat(f"{no_pct:.0f}%")
        self._no_badge.show()

        start = now - self._window_secs if len(ts) > 1 else now - 60
        self.setXRange(max(start, ts[0]), now, padding=0.02)
