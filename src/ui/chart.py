"""Live BTC price chart (pyqtgraph) — dark style, trading-app look.

Mga elemento:
- Blue line na may gradient fill : live BTC price
- Price badge (kanan)            : kasalukuyang presyo, naka-highlight
- Y-axis sa KANAN (gaya ng trading apps), oras sa baba
- Time filter (1s-All) sa dashboard header
"""
from __future__ import annotations

import bisect
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from src.ui import theme

MAX_POINTS = 20000  # live ticks + on-demand history (hanggang 1W view)


class PriceChart(pg.PlotWidget):
    def __init__(self) -> None:
        super().__init__(axisItems={"bottom": pg.DateAxisItem()})
        self.setBackground(theme.CARD)
        self.setMinimumHeight(220)
        self.showGrid(x=True, y=True, alpha=0.15)
        self.setMouseEnabled(x=True, y=False)
        # Y-axis sa KANAN gaya ng trading apps
        self.hideAxis("left")
        self.showAxis("right")
        self.getAxis("right").setWidth(86)

        self._times: deque[float] = deque(maxlen=MAX_POINTS)
        self._prices: deque[float] = deque(maxlen=MAX_POINTS)
        self._window_secs: int | None = 15 * 60  # default: last 15 min

        # Gradient fill sa ilalim ng price line
        fill = QColor(theme.BTC_BLUE)
        fill.setAlpha(38)
        self._curve = self.plot(
            pen=pg.mkPen(theme.BTC_BLUE, width=2), brush=fill, fillLevel=0
        )

        # Current price badge sa kanang gilid (walang linya, badge lang)
        self._price_marker = pg.InfiniteLine(
            angle=0, pen=pg.mkPen(None),
            label="", labelOpts={
                "position": 0.997,
                "color": "#ffffff",
                "fill": pg.mkBrush(theme.BTC_BLUE),
                "anchors": [(1, 0.5), (1, 0.5)],
            },
        )
        self._price_marker.hide()
        self.addItem(self._price_marker, ignoreBounds=True)

        # Hover crosshair — ipinapakita ang eksaktong presyo/oras ng
        # pinakamalapit na data point (Binance-style)
        cross_pen = pg.mkPen("#6b7280", width=1, style=Qt.PenStyle.DashLine)
        self._cross_v = pg.InfiniteLine(angle=90, pen=cross_pen)
        self._cross_h = pg.InfiniteLine(angle=0, pen=cross_pen)
        self._hover_dot = pg.ScatterPlotItem(
            size=8, brush=pg.mkBrush(theme.BTC_BLUE),
            pen=pg.mkPen("#ffffff", width=1),
        )
        self._hover_label = pg.TextItem(
            color=theme.TEXT, fill=pg.mkBrush("#1f2937"),
            border=pg.mkPen(theme.BORDER), anchor=(0, 1),
        )
        for item in (self._cross_v, self._cross_h, self._hover_dot,
                     self._hover_label):
            item.hide()
            item.setZValue(100)
            self.addItem(item, ignoreBounds=True)
        self.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Y auto-range batay sa NAKIKITANG data lang (visible x window)
        self.getViewBox().setAutoVisible(y=True)

    # ------------------------------------------------------------------ API

    def load_history(self, rows: list) -> None:
        """Merge ng klines (ts, o, h, l, c, v) sa existing data.

        TOTOONG merge by timestamp — ang bagong rows ay naisisingit saanman
        sila nabibilang, hindi lang sa unahan. Kailangan ito dahil iba-iba
        ang granularity ng Time filter fetches at kahit anong pagkakasunod
        (hal. All muna bago 1W) ay dapat buo pa rin ang resulta.

        Mga panuntunan:
        - t = OPEN time ng candle (interval-agnostic, laging monotonic)
        - walang future points (gumugulo sa linya kapag humalo sa ticks)
        - sa magkaparehong timestamp, ang EXISTING point ang panalo
          (live ticks / mas pinong data)
        """
        now = time.time()
        merged = dict(zip(self._times, self._prices))
        for t, _o, _h, _l, close, _v in rows:
            if t <= now and t not in merged:
                merged[t] = close
        self._times.clear()
        self._prices.clear()
        for t in sorted(merged):
            self._times.append(t)
            self._prices.append(merged[t])
        if self._prices:
            self._curve.setData(list(self._times), list(self._prices))
            self._apply_x_window()

    def add_point(self, price: float) -> None:
        self._times.append(time.time())
        self._prices.append(price)
        self._curve.setData(list(self._times), list(self._prices))

        self._price_marker.setValue(price)
        self._price_marker.show()
        # setFormat (hindi setText): ang InfLineLabel ay nagre-re-render mula
        # sa format string sa bawat galaw/range change — buburahin nito ang
        # setText, kaya ang format mismo ang lagyan ng final na text
        self._price_marker.label.setFormat(f"{price:,.2f}")

        self._apply_x_window()

    def set_window_minutes(self, minutes: int | None) -> None:
        """Ipakita ang huling N minuto lang; None = lahat ng data."""
        self._window_secs = None if minutes is None else minutes * 60
        self._apply_x_window()

    # -------------------------------------------------------------- helpers

    def _apply_x_window(self) -> None:
        """Laging sumunod sa pinakabagong presyo (auto-follow).

        Tinatawag ito kada tick — kahit na-drag/na-zoom ng mouse ang view,
        babalik ito sa tamang window sa susunod na update, para hindi
        maiwang 'nakapako' ang chart.
        """
        if not self._times:
            return
        now = self._times[-1]
        start = self._times[0] if self._window_secs is None else now - self._window_secs
        self.setXRange(start, now, padding=0.02)

        # Ang gradient fill ay hanggang sa ibaba ng NAKIKITANG data lang —
        # kung global min ang gamit, ang lumang history (hal. $3k noong 2017
        # mula sa All view) ay hihilain pababa ang y-axis ng ibang windows.
        visible = [p for t, p in zip(self._times, self._prices) if t >= start]
        if visible:
            span = max(visible) - min(visible)
            self._curve.setFillLevel(min(visible) - max(span * 0.02, 2))

    def _hide_hover(self) -> None:
        for item in (self._cross_v, self._cross_h, self._hover_dot,
                     self._hover_label):
            item.hide()

    def leaveEvent(self, ev) -> None:  # noqa: N802 (Qt naming)
        self._hide_hover()
        super().leaveEvent(ev)

    def _on_mouse_moved(self, scene_pos) -> None:
        """Hover: i-snap ang crosshair sa pinakamalapit na data point at
        ipakita ang eksaktong presyo + oras nito."""
        if not self._times:
            return
        vb = self.getViewBox()
        if not vb.sceneBoundingRect().contains(scene_pos):
            self._hide_hover()
            return
        view_pos = vb.mapSceneToView(scene_pos)

        # Pinakamalapit na data point sa x (binary search — mabilis)
        times = self._times
        i = bisect.bisect_left(list(times), view_pos.x())
        candidates = [j for j in (i - 1, i) if 0 <= j < len(times)]
        if not candidates:
            self._hide_hover()
            return
        j = min(candidates, key=lambda k: abs(times[k] - view_pos.x()))
        t, price = times[j], self._prices[j]

        self._cross_v.setPos(t)
        self._cross_h.setPos(price)
        self._hover_dot.setData([t], [price])

        # Oras: may petsa kapag mahaba ang window (1D pataas)
        long_range = self._window_secs is None or self._window_secs > 86400
        fmt = "%b %d  %H:%M" if long_range else "%H:%M:%S"
        self._hover_label.setText(
            f" {time.strftime(fmt, time.localtime(t))} \n ${price:,.2f} "
        )
        # Ilagay ang label sa tabi ng point; iwas-labas sa kanang gilid
        (xlo, xhi), (ylo, yhi) = vb.viewRange()
        anchor_x = 1 if t > xlo + (xhi - xlo) * 0.8 else 0
        self._hover_label.setAnchor((anchor_x, 1))
        self._hover_label.setPos(t, price)

        for item in (self._cross_v, self._cross_h, self._hover_dot,
                     self._hover_label):
            item.show()

    def clear_data(self) -> None:
        self._times.clear()
        self._prices.clear()
        self._curve.setData([], [])
        self._price_marker.hide()
