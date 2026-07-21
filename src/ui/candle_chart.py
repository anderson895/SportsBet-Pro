"""Candlestick chart (finplot) — 1-minute candles + volume bars (Binance-style).

LAZY ang pag-import ng finplot/pandas (mabigat sa startup) — ang widget
na ito ay ginagawa lang kapag pinili ng user ang "Candles" sa dashboard.

Data source: live 1m kline stream ng Binance (eksaktong OHLCV, hindi tick
aggregation) + 2h history prefill mula REST klines.

Ang price badge ay pyqtgraph InfiniteLine — ang finplot ay nakapatong
sa pyqtgraph kaya direktang madadagdag sa viewbox nito.
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.ui import theme

MAX_CANDLES = 1440        # 24 oras ng 1m candles


class CandleChart(QWidget):
    def __init__(self) -> None:
        super().__init__()
        import finplot as fplt  # lazy — mabigat ang pandas import

        self._fplt = fplt
        fplt.background = theme.CARD
        fplt.odd_plot_background = theme.CARD
        fplt.foreground = theme.MUTED
        fplt.cross_hair_color = "#6b7280"
        fplt.candle_bull_color = theme.GREEN
        fplt.candle_bull_body_color = theme.GREEN
        fplt.candle_bear_color = theme.RED
        fplt.candle_bear_body_color = theme.RED
        fplt.volume_bull_color = "#1a5c33"
        fplt.volume_bull_body_color = "#1a5c33"
        fplt.volume_bear_color = "#6b2323"
        fplt.volume_bear_body_color = "#6b2323"
        # Intraday bot — oras lang sa axis. Ang truncation ng finplot ay
        # s[:s.rindex(':')] para sa 60s period, kaya "%H:%M:%S" -> "HH:MM"
        fplt.timestamp_format = "%H:%M:%S"

        # 2 rows gaya ng Binance: candles sa taas, volume sa baba
        self.ax, self.ax_vol = fplt.create_plot_widget(master=self, rows=2)
        self.axs = [self.ax, self.ax_vol]  # kailangan ng finplot embed pattern
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.ax.ax_widget, stretch=4)
        layout.addWidget(self.ax_vol.ax_widget, stretch=1)

        # candles: list ng [t0, open, close, high, low, volume]
        self._candles: list[list[float]] = []
        self._item = None
        self._vol_item = None

        # Price badge — parehong pyqtgraph item gaya ng line chart
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
        self.ax.vb.addItem(self._price_marker, ignoreBounds=True)

    # ------------------------------------------------------------------ API

    def update_candle(self, k: tuple) -> None:
        """Live 1m kline mula Binance: (t0, o, h, l, c, v)."""
        t0, o, h, l, c, v = k
        if self._candles and self._candles[-1][0] == t0:
            self._candles[-1] = [t0, o, c, h, l, v]
        else:
            self._candles.append([t0, o, c, h, l, v])
            if len(self._candles) > MAX_CANDLES:
                self._candles.pop(0)
        self._redraw()
        self._update_marker(c)

    def add_point(self, price: float) -> None:
        """Tick update sa pagitan ng kline events — close/high/low lang."""
        if not self._candles:
            return  # hintayin ang unang kline/history
        c = self._candles[-1]
        c[2] = price
        c[3] = max(c[3], price)
        c[4] = min(c[4], price)
        self._redraw()
        self._update_marker(price)

    def load_history(self, rows: list) -> None:
        """Prefill mula 1m klines — totoong merge by timestamp; ang
        existing (live) candles ang panalo sa magkaparehong t0."""
        merged = {c[0]: c for c in self._candles}
        for ts, o, h, l, c, v in rows:
            if ts not in merged:
                merged[ts] = [ts, o, c, h, l, v]
        self._candles = [merged[t] for t in sorted(merged)][-MAX_CANDLES:]
        self._redraw()

    def clear_data(self) -> None:
        self._candles.clear()
        self._price_marker.hide()

    # -------------------------------------------------------------- helpers

    def _update_marker(self, price: float) -> None:
        self._price_marker.setValue(price)
        self._price_marker.show()
        # setFormat (hindi setText) — ang InfLineLabel ay nagre-re-render
        # mula sa format string sa bawat galaw, buburahin ang setText
        self._price_marker.label.setFormat(f"{price:,.2f}")

    def _redraw(self) -> None:
        # Hintayin ang >=2 candles — sa 1 row, mali ang period detection ng
        # finplot (1ns) kaya sumasabog ang time axis format sa microseconds
        if len(self._candles) < 2:
            return
        import pandas as pd

        df = pd.DataFrame(
            self._candles,
            columns=["time", "open", "close", "high", "low", "volume"],
        )
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        if self._item is None:
            self._item = self._fplt.candlestick_ochl(
                df[["open", "close", "high", "low"]], ax=self.ax
            )
            self._vol_item = self._fplt.volume_ocv(
                df[["open", "close", "volume"]], ax=self.ax_vol
            )
            self._fplt.refresh()
        else:
            self._item.update_data(df[["open", "close", "high", "low"]])
            self._vol_item.update_data(df[["open", "close", "volume"]])
