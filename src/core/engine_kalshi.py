"""Kalshi bot engine — Mean Reversion / "Rubber Band" on BTC Up/Down.

Same strategy as the Polymarket engine (``engine_poly.py``): a Binance price
feed drives ``evaluate_entry``/``evaluate_exit`` from ``strategy/mean_reversion``;
the only difference is the venue. Kalshi has no single "Up or Down" market, so
``execution/kalshi_market`` synthesizes one from the KXBTCD above/below ladder
(strike nearest the period open = the up/down pivot).

- PAPER mode reuses the shared, exchange-agnostic ``PaperExecutor`` (simulated
  fills, estimated share price) — identical to Polymarket paper trading.
- LIVE mode uses ``KalshiLiveExecutor`` against the real Kalshi CLOB; share
  prices come from the discovered market's order book.

QObject so it can emit the same Qt signals the (Kalshi-branded) BTC dashboard
consumes — the wiring mirrors ``PolyEngine`` one-for-one.
"""
from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import logging
import re
from enum import Enum

from PySide6.QtCore import QObject, Signal

from src.core import secrets as secret_store
from src.core.status import ConnectionMonitor
from src.execution.kalshi_client import (
    KalshiClient,
    KalshiError,
    best_prices_from_orderbook,
)
from src.execution.kalshi_live import KalshiLiveExecutor
from src.execution.kalshi_market import best_prices_for_side, find_btc_market
from src.execution.paper import (
    PaperExecutor,
    estimate_otm_share_price,
    position_share_price,
)
from src.execution.resume import decide_restore
from src.feed.binance import BinanceFeed
from src.feed.coinbase import CoinbaseFeed
from src.storage.db import ScopedDatabase
from src.strategy.filters import (
    coinbase_premium_pct,
    is_premium_exploding,
    is_volume_escalating,
)
from src.strategy.mean_reversion import (
    Action,
    StrategyConfig,
    evaluate_entry,
    evaluate_exit,
    period_start_utc,
    scale_config_for_timeframe,
    stretch_scale,
    target_side,
)

filelog = logging.getLogger("sportsbet.engine_kalshi")

DEFAULT_RISK_USD = 100.0
# Market timeframe -> Binance kline interval (for the period open / strike).
# Kalshi's clean up/down ladder (KXBTCD) is hourly, so 1h is the default and
# the only reliably tradeable LIVE timeframe (daily attempted if listed).
TF_TO_INTERVAL = {"daily": "1d", "4h": "4h", "1h": "1h", "15m": "15m"}


class BotState(Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


class KalshiEngine(QObject):
    priceUpdated = Signal(float)          # latest BTC price
    dailyOpenUpdated = Signal(float)      # period open / "Price to Beat"
    stretchUpdated = Signal(float)        # % distance from period open
    connectionChanged = Signal(str, bool)  # (service, is_up) — unused (shared)
    stateChanged = Signal(str)            # BotState value
    strategyStatus = Signal(str)          # human-readable strategy state
    tradeExecuted = Signal()              # bagong trade sa DB
    logAdded = Signal(str, str)           # (level, message)
    modeChanged = Signal(str)             # "PAPER" | "LIVE"
    liveBalance = Signal(float)           # totoong USD balance (live mode)
    historyLoaded = Signal(list)          # 1m klines para sa chart prefill
    klineUpdated = Signal(tuple)          # live 1m kline (t,o,h,l,c,v)
    rangeHistoryLoaded = Signal(list)     # on-demand klines (Time filter)

    def __init__(
        self, db: ScopedDatabase, config: StrategyConfig | None = None
    ) -> None:
        super().__init__()
        self._db = db
        self.state = BotState.STOPPED
        self.config = config or StrategyConfig()
        self.executor: PaperExecutor | KalshiLiveExecutor = PaperExecutor(db)
        self._trades_today = 0
        self._trades_period: float | None = None
        self._volume_veto_logged = False
        self._premium_veto_logged = False
        self._watch_log_key = ""
        # Live mode state
        self._live_client: KalshiClient | None = None
        self._live_books: dict[str, tuple[float | None, float | None]] = {}
        self._live_price_task: asyncio.Task | None = None
        self._live_balance_task: asyncio.Task | None = None
        self._live_pending = False
        self._order_in_flight = False  # guard: one async order at a time
        # Kalshi's usable up/down ladder is hourly — default to 1h
        self._timeframe = "1h"
        self._price_scale = stretch_scale("1h")
        self._period_secs = 3600.0

        self._feed = BinanceFeed(
            on_price=self._handle_price,
            on_daily_open=self._handle_daily_open,
            on_status=lambda up: self.connectionChanged.emit("binance_ws", up),
            on_history=self.historyLoaded.emit,
            on_kline=self.klineUpdated.emit,
        )
        # Shared connection monitor lives on the Poly engine; here we still
        # create the feed but rely on that monitor's "kalshi" status fan-out.
        self._coinbase = CoinbaseFeed()

    # ------------------------------------------------------------------ API

    def start_monitors(self) -> None:
        """Always-on Binance chart feed (runs even while STOPPED)."""
        tf = str(self._db.get_setting("market_timeframe", "1h"))
        self._feed.set_period(TF_TO_INTERVAL.get(tf, "1h"))
        self._feed.start()

    def start(self) -> None:
        if self.state is BotState.RUNNING:
            return
        self.config = self._load_config()
        self.state = BotState.RUNNING
        self._watch_log_key = ""

        mode = str(self._db.get_setting("trading_mode", "paper")).lower()
        if mode == "live":
            self._live_pending = True
            asyncio.create_task(self._setup_live())
        else:
            self.executor = PaperExecutor(self._db)
            self.modeChanged.emit("PAPER")
            self._restore_position()

        self._feed.set_period(TF_TO_INTERVAL[self._timeframe])
        self._feed.start()
        self._coinbase.start()
        self.stateChanged.emit(self.state.value)
        self.log("INFO", f"Bot STARTED [{mode.upper()} MODE] — "
                         f"{self._timeframe.upper()} market, "
                         "mean reversion strategy active")

    async def stop(self) -> None:
        if self.state is BotState.STOPPED:
            return
        self.state = BotState.STOPPED
        await self._coinbase.stop()
        for attr in ("_live_price_task", "_live_balance_task"):
            task = getattr(self, attr)
            if task is not None:
                task.cancel()
                setattr(self, attr, None)
        self.stateChanged.emit(self.state.value)
        self.strategyStatus.emit("idle (press START BOT)")
        self.log("INFO", "Bot STOPPED")

    # ------------------------------------------------------------ live mode

    async def _setup_live(self) -> None:
        """Connect to Kalshi; on failure fall back to PAPER."""
        try:
            env = str(self._db.get_setting("env", "prod"))
            key_id = secret_store.get_secret(secret_store.KEY_KALSHI_API_ID)
            pem = secret_store.get_secret(secret_store.KEY_KALSHI_PEM)
            if not pem:
                pem = str(self._db.get_setting("pem_path", "")).strip() or None
            if not key_id or not pem:
                raise KalshiError(
                    "Kalshi API Key ID / RSA private key not set in Settings"
                )
            client = KalshiClient(env=env, key_id=key_id, private_key_pem=pem)
            balance = await client.get_balance()  # creds check
            executor = KalshiLiveExecutor(self._db, client)
            self._live_client = client
            self.executor = executor
            self._live_books = {}
            self._live_price_task = asyncio.create_task(self._live_price_loop())
            self._live_balance_task = asyncio.create_task(
                self._live_balance_loop())
            self.liveBalance.emit(balance)
            self.log("INFO", f"LIVE mode ready [{env}] — balance "
                             f"${balance:,.2f}")
            self.modeChanged.emit("LIVE")
            self._restore_position()
        except Exception as e:
            filelog.exception("Kalshi live setup failed (full traceback):")
            self.log("ERROR", f"Live setup failed: {e} — falling back to "
                              "PAPER mode")
            self.executor = PaperExecutor(self._db)
            self.modeChanged.emit("PAPER")
        finally:
            self._live_pending = False

    async def _live_price_loop(self) -> None:
        """Resolve/rollover the Kalshi market + refresh best bid/ask every 5s.

        The market is the KXBTCD above/below strike nearest to this period's
        open ("price to beat"). On a new period (and while flat) we re-discover
        so the pivot strike tracks the fresh open.
        """
        assert isinstance(self.executor, KalshiLiveExecutor)
        fetch_failed_logged = False
        current_period = self._aligned_period_start()
        while True:
            try:
                open_price = self._feed.daily_open
                aligned = self._aligned_period_start()
                need_market = (
                    self.executor.market is None
                    or (aligned != current_period
                        and self.executor.position is None)
                )
                if need_market and open_price is not None:
                    period_start = dt.datetime.fromtimestamp(
                        aligned, dt.timezone.utc)
                    market = await find_btc_market(
                        self._live_client, self._timeframe, period_start,
                        open_price,
                    )
                    self.executor.set_market(market)
                    self._live_books = {}
                    current_period = aligned
                    self.log("INFO", f"Kalshi market — {market.question} "
                                     f"[{market.ticker}]")

                market = self.executor.market
                if market is not None:
                    book = await self._live_client.get_orderbook(market.ticker)
                    prices = best_prices_from_orderbook(book)
                    for side in ("UP", "DOWN"):
                        self._live_books[side] = best_prices_for_side(
                            prices, side)
                fetch_failed_logged = False
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not fetch_failed_logged:
                    filelog.exception("Live order book fetch failed:")
                    self.log("WARN", f"Live order book fetch failed: {e}")
                    fetch_failed_logged = True
            await asyncio.sleep(5)

    def _aligned_period_start(self) -> float:
        now = dt.datetime.now(dt.timezone.utc)
        return period_start_utc(now, self._timeframe).timestamp()

    async def _live_balance_loop(self) -> None:
        failed_logged = False
        while True:
            try:
                balance = await self.executor.get_balance()
                if balance is not None:
                    self.liveBalance.emit(balance)
                failed_logged = False
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not failed_logged:
                    filelog.exception("Kalshi balance fetch failed:")
                    self.log("WARN", f"Balance fetch failed: {e} — "
                                     "retrying every 10s")
                    failed_logged = True
                await asyncio.sleep(10)

    async def _refresh_live_balance(self) -> None:
        try:
            balance = await self.executor.get_balance()
            if balance is not None:
                self.liveBalance.emit(balance)
        except Exception as e:
            filelog.warning("Balance refresh failed: %s", e)

    def fetch_range_history(self, interval: str, limit: int) -> None:
        try:
            asyncio.create_task(self._fetch_range(interval, limit))
        except RuntimeError:
            pass  # walang running event loop (hal. sa UI tests)

    async def _fetch_range(self, interval: str, limit: int) -> None:
        try:
            rows = await self._feed.fetch_klines(interval, limit)
            self.rangeHistoryLoaded.emit(rows)
        except Exception as e:
            filelog.exception("Range history fetch failed:")
            self.log("WARN", f"History fetch failed ({interval}): {e}")

    def _restore_position(self) -> None:
        period_start = dt.datetime.fromtimestamp(
            self._aligned_period_start(), dt.timezone.utc
        )
        position, level, message = decide_restore(
            self._db.load_open_position(), self.executor.MODE, period_start
        )
        if position is not None:
            self.executor.position = position
        elif message:
            self._db.clear_open_position()
        if message:
            self.log(level, message)

    def log(self, level: str, message: str) -> None:
        self._db.add_log(level, message)
        self.logAdded.emit(level, message)
        py_level = {"WARN": logging.WARNING, "ERROR": logging.ERROR}.get(
            level, logging.INFO
        )
        filelog.log(py_level, message)

    def _load_config(self) -> StrategyConfig:
        g = self._db.get_setting
        base = StrategyConfig()
        cfg = StrategyConfig(
            min_stretch_pct=float(g("min_stretch_pct", base.min_stretch_pct)),
            max_stretch_pct=float(g("max_stretch_pct", base.max_stretch_pct)),
            profit_target_pct=float(g("profit_target_pct",
                                      base.profit_target_pct)),
            volume_spike_mult=float(g("volume_spike_mult",
                                      base.volume_spike_mult)),
            premium_threshold_pct=float(
                g("premium_threshold_pct", base.premium_threshold_pct)
            ),
        )
        self._timeframe = str(g("market_timeframe", "1h"))
        if self._timeframe not in TF_TO_INTERVAL:
            self._timeframe = "1h"
        self._price_scale = stretch_scale(self._timeframe)
        cfg = scale_config_for_timeframe(cfg, self._timeframe)
        self._period_secs = cfg.period_hours * 3600.0
        if self._timeframe == "daily":
            now = dt.datetime.now(dt.timezone.utc)
            offset = period_start_utc(now, "daily").timestamp() % 86400.0
            cfg = dataclasses.replace(cfg, anchor_offset_secs=offset)
        return cfg

    # ------------------------------------------------------------- handlers

    def _handle_price(self, price: float) -> None:
        self.priceUpdated.emit(price)
        stretch = self._feed.pct_from_open
        if stretch is None:
            return
        self.stretchUpdated.emit(stretch)
        if self.state is BotState.RUNNING:
            self._evaluate_strategy(stretch)

    def _handle_daily_open(self, open_price: float) -> None:
        self.dailyOpenUpdated.emit(open_price)
        self.log("INFO", f"Period open / price to beat = ${open_price:,.2f}")

    # ------------------------------------------------------------- strategy

    def _evaluate_strategy(self, stretch: float) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self._reset_daily_counter(now)

        if self._live_pending:
            self.strategyStatus.emit("CONNECTING — setting up Kalshi live mode…")
            return
        if self._order_in_flight:
            return  # a live BUY/SELL task is running; wait for it to settle

        live = isinstance(self.executor, KalshiLiveExecutor)
        if live and self.executor.market is not None:
            market = f"{self.executor.market.question} [LIVE]"
        else:
            market = (f"BTC Up/Down [{self._timeframe}] "
                      f"{now.strftime('%Y-%m-%d %H:%M')} [PAPER]")

        if self.executor.position is None:
            if self._db.get_setting("econ_block_date") == now.date().isoformat():
                self.strategyStatus.emit(
                    "PAUSED — economic data day (Fed/CPI), entries blocked today")
                return

            if live:
                if self.executor.market is None:
                    self.strategyStatus.emit(
                        "WAITING — resolving Kalshi BTC market…")
                    return
                book = self._live_books.get(target_side(stretch))
                share_price = book[1] if book else None
                if share_price is None:
                    self.strategyStatus.emit("WAITING — no live order book data yet")
                    return
            else:
                share_price = estimate_otm_share_price(stretch, self._price_scale)

            sig = evaluate_entry(now, stretch, share_price, self._trades_today,
                                 self.config)
            if sig.action is not Action.ENTER:
                self.strategyStatus.emit(f"WATCHING — {sig.reason}")
                key = re.sub(r"[0-9.+-]+", "#", sig.reason)
                if key != self._watch_log_key:
                    self._watch_log_key = key
                    self.log("INFO", f"Watching: {sig.reason}")
                return

            # Death trap guards (same as Polymarket)
            if self._entry_vetoed(stretch):
                return

            risk = float(self._db.get_setting("risk_usd", DEFAULT_RISK_USD))
            if live:
                self._order_in_flight = True
                asyncio.create_task(
                    self._live_buy(market, sig.side, share_price, risk,
                                   sig.reason))
                return
            self._paper_buy(market, sig.side, share_price, risk, sig.reason)
        else:
            pos = self.executor.position
            if live:
                book = self._live_books.get(pos.side)
                share_price = book[0] if book else None
                if share_price is None:
                    self.strategyStatus.emit("WAITING — no live order book data yet")
                    return
            else:
                share_price = position_share_price(
                    stretch, pos.side, self._price_scale)

            sig = evaluate_exit(now, pos, share_price, self.config)
            if sig.action is not Action.EXIT:
                self.strategyStatus.emit(
                    f"IN POSITION: {pos.side} @ {pos.entry_price:.2f} "
                    f"(now ~{share_price:.2f}) — {sig.reason}")
                return
            if live:
                self._order_in_flight = True
                asyncio.create_task(
                    self._live_sell(market, share_price, sig.reason))
                return
            self._paper_sell(market, share_price, sig.reason)

    def _entry_vetoed(self, stretch: float) -> bool:
        """Volume-escalation + Coinbase-premium death-trap guards."""
        escalating, why = is_volume_escalating(
            self._feed.hourly_volumes,
            recent_hours=self.config.volume_recent_hours,
            baseline_hours=self.config.volume_baseline_hours,
            spike_mult=self.config.volume_spike_mult,
        )
        if escalating:
            if not self._volume_veto_logged:
                self.log("WARN", f"Entry blocked — {why}")
                self._volume_veto_logged = True
            self.strategyStatus.emit(f"BLOCKED — {why}")
            return True
        self._volume_veto_logged = False

        if self._coinbase.last_price is not None:
            premium = coinbase_premium_pct(
                self._coinbase.last_price, self._feed.last_price)
            exploding, why = is_premium_exploding(
                premium, stretch, self.config.premium_threshold_pct)
            if exploding:
                if not self._premium_veto_logged:
                    self.log("WARN", f"Entry blocked — {why}")
                    self._premium_veto_logged = True
                self.strategyStatus.emit(f"BLOCKED — {why}")
                return True
            self._premium_veto_logged = False
        return False

    # -------------------------------------------------------- trade helpers

    def _paper_buy(self, market: str, side: str, share_price: float,
                   risk: float, reason: str) -> None:
        try:
            pos = self.executor.buy(market, side, share_price, risk)
        except Exception as e:
            filelog.exception("BUY order failed:")
            self.log("ERROR", f"BUY order failed: {e}")
            self.strategyStatus.emit(f"ERROR — BUY failed: {e}")
            return
        self._trades_today += 1
        self.log("TRADE", f"[{self.executor.MODE}] BUY {pos.shares:,.1f} "
                          f"{side} @ {share_price:.2f} (${risk:.2f}) — {reason}")
        self.tradeExecuted.emit()
        self.strategyStatus.emit(f"IN POSITION: {side} @ {share_price:.2f}")

    def _paper_sell(self, market: str, share_price: float,
                    reason: str) -> None:
        pos = self.executor.position
        try:
            pnl = self.executor.sell(market, share_price)
        except Exception as e:
            filelog.exception("SELL order failed:")
            self.log("ERROR", f"SELL order failed: {e}")
            self.strategyStatus.emit(f"ERROR — SELL failed: {e}")
            return
        self.log("TRADE", f"[{self.executor.MODE}] SELL {pos.side} @ "
                          f"{share_price:.2f} — PnL {pnl:+,.2f} USD — {reason}")
        self.tradeExecuted.emit()
        self.strategyStatus.emit(f"FLAT — last PnL {pnl:+,.2f} USD")

    async def _live_buy(self, market: str, side: str, share_price: float,
                        risk: float, reason: str) -> None:
        try:
            pos = await self.executor.buy(market, side, share_price, risk)
            self._trades_today += 1
            self.log("TRADE", f"[LIVE] BUY {pos.shares:,.0f} {side} @ "
                              f"{share_price:.2f} (${risk:.2f}) — {reason}")
            self.tradeExecuted.emit()
            self.strategyStatus.emit(f"IN POSITION: {side} @ {share_price:.2f}")
            await self._refresh_live_balance()
        except Exception as e:
            filelog.exception("LIVE BUY failed:")
            self.log("ERROR", f"BUY order failed: {e}")
            self.strategyStatus.emit(f"ERROR — BUY failed: {e}")
        finally:
            self._order_in_flight = False

    async def _live_sell(self, market: str, share_price: float,
                         reason: str) -> None:
        pos = self.executor.position
        try:
            pnl = await self.executor.sell(market, share_price)
            self.log("TRADE", f"[LIVE] SELL {pos.side} @ {share_price:.2f} — "
                              f"PnL {pnl:+,.2f} USD — {reason}")
            self.tradeExecuted.emit()
            self.strategyStatus.emit(f"FLAT — last PnL {pnl:+,.2f} USD")
            await self._refresh_live_balance()
        except Exception as e:
            filelog.exception("LIVE SELL failed:")
            self.log("ERROR", f"SELL order failed: {e}")
            self.strategyStatus.emit(f"ERROR — SELL failed: {e}")
        finally:
            self._order_in_flight = False

    def _reset_daily_counter(self, now: dt.datetime) -> None:
        period = self._aligned_period_start()
        if self._trades_period != period:
            self._trades_period = period
            self._trades_today = 0
