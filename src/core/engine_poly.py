"""Polymarket bot engine / orchestrator (port ng PolyTradePro BotEngine).

Feed (Binance) -> strategy (mean reversion) -> executor (paper/live).

QObject ito para maka-emit ng Qt signals papunta sa UI. Dahil qasync
ang event loop, ang asyncio callbacks ay tumatakbo sa Qt thread —
safe mag-emit ng signals nang direkta.
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

filelog = logging.getLogger("sportsbet.engine_poly")
from src.core.status import ConnectionMonitor
from src.execution.paper import (
    PaperExecutor,
    estimate_otm_share_price,
    position_share_price,
)
from src.execution.polymarket import (
    LiveExecutor,
    PolymarketClient,
    PolymarketError,
    find_btc_market,
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

DEFAULT_RISK_USDC = 200.0
# Polymarket timeframe -> Binance kline interval (para sa period open)
TF_TO_INTERVAL = {"daily": "1d", "4h": "4h", "1h": "1h", "15m": "15m"}


class BotState(Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


class PolyEngine(QObject):
    priceUpdated = Signal(float)          # latest BTC price
    dailyOpenUpdated = Signal(float)      # period open / "Price to Beat"
                                          # (daily = 12PM ET strike)
    stretchUpdated = Signal(float)        # % distance from daily open
    connectionChanged = Signal(str, bool)  # (service, is_up)
    stateChanged = Signal(str)            # BotState value
    strategyStatus = Signal(str)          # human-readable strategy state
    tradeExecuted = Signal()              # may bagong trade sa DB
    logAdded = Signal(str, str)           # (level, message)
    modeChanged = Signal(str)             # "PAPER" | "LIVE"
    liveBalance = Signal(float)           # totoong USDC balance (live mode)
    historyLoaded = Signal(list)          # 1m klines para sa chart prefill
    klineUpdated = Signal(tuple)          # live 1m kline (t,o,h,l,c,v)
    rangeHistoryLoaded = Signal(list)     # on-demand klines (Time filter)

    def __init__(self, db: ScopedDatabase, config: StrategyConfig | None = None) -> None:
        super().__init__()
        self._db = db
        self.state = BotState.STOPPED
        self.config = config or StrategyConfig()
        self.executor = PaperExecutor(db)
        self._trades_today = 0  # trades sa KASALUKUYANG market period
        self._trades_period: float | None = None  # aligned period start
        # One-time WARN flags para hindi mag-spam ang log kada tick
        self._volume_veto_logged = False
        self._premium_veto_logged = False
        # Huling na-log na WATCHING reason (digits stripped) — para makita
        # sa Recent Logs KUNG BAKIT hindi pumapasok, nang walang spam
        self._watch_log_key = ""
        # Live mode state
        self._live_client: PolymarketClient | None = None
        self._live_books: dict[str, tuple[float | None, float | None]] = {}
        self._live_price_task: asyncio.Task | None = None
        self._live_balance_task: asyncio.Task | None = None
        self._live_pending = False
        # Market timeframe (daily/4h/1h/15m) — sine-set sa start() mula
        # sa settings; ang scale ay para sa paper share-price model
        self._timeframe = "daily"
        self._price_scale = 1.0
        self._period_secs = 86400.0
        self._live_market_switching = False

        self._feed = BinanceFeed(
            on_price=self._handle_price,
            on_daily_open=self._handle_daily_open,
            on_status=lambda up: self.connectionChanged.emit("binance_ws", up),
            on_history=self.historyLoaded.emit,
            on_kline=self.klineUpdated.emit,
        )
        self._monitor = ConnectionMonitor(
            on_status=lambda name, up: self.connectionChanged.emit(name, up)
        )
        self._coinbase = CoinbaseFeed()

    # ------------------------------------------------------------------ API

    def start_monitors(self) -> None:
        """Tumatakbo kahit STOPPED ang bot: connection checks + LIVE CHART.

        Ang Binance price feed ay laging bukas para gumagalaw ang chart
        kahit hindi pa naka-START — ang START/STOP ay para lang sa
        trading (strategy evaluation).
        """
        # I-apply ang naka-save na timeframe para tama ang period open at
        # stretch % kahit hindi pa naka-START ang bot
        tf = str(self._db.get_setting("market_timeframe", "daily"))
        self._feed.set_period(TF_TO_INTERVAL.get(tf, "1d"))
        self._monitor.start()
        self._feed.start()

    def start(self) -> None:
        if self.state is BotState.RUNNING:
            return
        self.config = self._load_config()  # kunin ang latest settings
        self.state = BotState.RUNNING
        self._watch_log_key = ""  # fresh session = i-log ang unang reason

        mode = str(self._db.get_setting("trading_mode", "paper")).lower()
        if mode == "live":
            # Async setup — huwag i-freeze ang UI habang kumokonekta
            self._live_pending = True
            asyncio.create_task(self._setup_live())
        else:
            self.executor = PaperExecutor(self._db)
            self.modeChanged.emit("PAPER")
            self._restore_position()

        self._feed.set_period(TF_TO_INTERVAL[self._timeframe])
        self._feed.start()  # idempotent — tumatakbo na mula start_monitors
        self._coinbase.start()
        self.stateChanged.emit(self.state.value)
        self.log("INFO", f"Bot STARTED [{mode.upper()} MODE] — "
                         f"{self._timeframe.upper()} market, "
                         "mean reversion strategy active")

    async def stop(self) -> None:
        if self.state is BotState.STOPPED:
            return
        self.state = BotState.STOPPED
        # HINDI hinihinto ang _feed — tuloy ang live chart kahit STOPPED
        await self._coinbase.stop()
        if self._live_price_task is not None:
            self._live_price_task.cancel()
            self._live_price_task = None
        if self._live_balance_task is not None:
            self._live_balance_task.cancel()
            self._live_balance_task = None
        self.stateChanged.emit(self.state.value)
        self.strategyStatus.emit("idle (press START BOT)")
        self.log("INFO", "Bot STOPPED")

    # ------------------------------------------------------------ live mode

    async def _setup_live(self) -> None:
        """Kumonekta sa Polymarket; kapag pumalya, bumalik sa PAPER."""
        try:
            pk = secret_store.get_secret(secret_store.KEY_PM_PRIVATE)
            funder = secret_store.get_secret(secret_store.KEY_PM_FUNDER)
            if not pk or not funder:
                raise PolymarketError(
                    "Polymarket Private Key / Funder Address not set in Settings"
                )
            sig_type = int(self._db.get_setting("pm_signature_type", 1))
            client = PolymarketClient(
                private_key=pk, funder=funder, signature_type=sig_type
            )
            await asyncio.to_thread(client.connect)
            now = dt.datetime.now(dt.timezone.utc)
            market = await asyncio.to_thread(
                find_btc_market, self._timeframe, now
            )

            executor = LiveExecutor(self._db, client)
            executor.set_market(market)
            self._live_client = client
            self.executor = executor
            self._live_books = {}
            self._live_price_task = asyncio.create_task(self._live_price_loop())
            self._live_balance_task = asyncio.create_task(self._live_balance_loop())
            self.log("INFO", f"LIVE mode ready — market: {market.question}")
            self.modeChanged.emit("LIVE")
            self._restore_position()
        except Exception as e:
            filelog.exception("Live setup failed (full traceback):")
            self.log("ERROR", f"Live setup failed: {e} — falling back to PAPER mode")
            self.executor = PaperExecutor(self._db)
            self.modeChanged.emit("PAPER")
        finally:
            self._live_pending = False

    async def _live_price_loop(self) -> None:
        """I-refresh ang best bid/ask kada 5 segundo + market rollover.

        Sa 15m/1h/4h timeframes, BAGO ang market bawat period — kapag
        pumasok na sa bagong period at flat tayo (ginagarantiya ng
        end-of-period exit), awtomatikong lilipat sa bagong market.
        """
        assert isinstance(self.executor, LiveExecutor)
        fetch_failed_logged = False
        current_period = self._aligned_period_start()
        while True:
            try:
                # --- market rollover check --------------------------------
                aligned = self._aligned_period_start()
                if aligned != current_period and self.executor.position is None:
                    now = dt.datetime.now(dt.timezone.utc)
                    market = await asyncio.to_thread(
                        find_btc_market, self._timeframe, now
                    )
                    self.executor.set_market(market)
                    self._live_books = {}
                    current_period = aligned
                    self.log("INFO", f"New {self._timeframe} period — "
                                     f"market: {market.question}")

                market = self.executor.market
                for side in ("UP", "DOWN"):
                    token = market.token_for(side)
                    self._live_books[side] = await asyncio.to_thread(
                        self._live_client.get_best_prices, token
                    )
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
        """I-refresh ang totoong USDC balance nang paulit-ulit.

        Kada 60s kapag OK; kada 10s kapag pumalya — para hindi maiwang
        "…" ang balance card dahil sa isang panandaliang network error
        (nangyari ito: isang beses lang tinatawag dati, walang retry).
        """
        failed_logged = False
        while True:
            try:
                balance = await asyncio.to_thread(
                    self._live_client.get_usdc_balance
                )
                self.liveBalance.emit(balance)
                failed_logged = False
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not failed_logged:
                    filelog.exception("Balance fetch failed:")
                    self.log("WARN", f"Balance fetch failed: {e} — "
                                     "retrying every 10s")
                    failed_logged = True
                await asyncio.sleep(10)

    async def _refresh_live_balance(self) -> None:
        try:
            balance = await asyncio.to_thread(self._live_client.get_usdc_balance)
            self.liveBalance.emit(balance)
        except Exception as e:
            filelog.exception("Balance fetch failed:")
            self.log("WARN", f"Balance fetch failed: {e}")

    def fetch_range_history(self, interval: str, limit: int) -> None:
        """On-demand klines para sa Time filter (4H/1D/1W views)."""
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
        """I-restore ang open position mula sa DB pagkatapos ng app restart."""
        # Period-based ang staleness sa LAHAT ng timeframes (ang daily ay
        # tanghali-ET anchored via period_start_utc)
        period_start = dt.datetime.fromtimestamp(
            self._aligned_period_start(), dt.timezone.utc
        )
        position, level, message = decide_restore(
            self._db.load_open_position(), self.executor.MODE, period_start
        )
        if position is not None:
            self.executor.position = position
        elif message:
            self._db.clear_open_position()  # stale/mismatch — huwag nang ulitin
        if message:
            self.log(level, message)

    def log(self, level: str, message: str) -> None:
        self._db.add_log(level, message)
        self.logAdded.emit(level, message)
        # Mirror sa data/app.log para maisubmit bilang error report
        py_level = {"WARN": logging.WARNING, "ERROR": logging.ERROR}.get(
            level, logging.INFO
        )
        filelog.log(py_level, message)

    def _load_config(self) -> StrategyConfig:
        """Buuin ang StrategyConfig mula sa user settings sa DB.

        Ang mga setting ay DAILY-calibrated; kapag mas maikli ang napiling
        market timeframe, awtomatikong sini-scale (oras = fraction ng
        period, stretch = sqrt-of-time).
        """
        g = self._db.get_setting
        base = StrategyConfig()
        cfg = StrategyConfig(
            min_stretch_pct=float(g("min_stretch_pct", base.min_stretch_pct)),
            max_stretch_pct=float(g("max_stretch_pct", base.max_stretch_pct)),
            profit_target_pct=float(g("profit_target_pct", base.profit_target_pct)),
            volume_spike_mult=float(g("volume_spike_mult", base.volume_spike_mult)),
            premium_threshold_pct=float(
                g("premium_threshold_pct", base.premium_threshold_pct)
            ),
        )
        self._timeframe = str(g("market_timeframe", "daily"))
        if self._timeframe not in TF_TO_INTERVAL:
            self._timeframe = "daily"
        self._price_scale = stretch_scale(self._timeframe)
        cfg = scale_config_for_timeframe(cfg, self._timeframe)
        self._period_secs = cfg.period_hours * 3600.0
        if self._timeframe == "daily":
            # Daily market = tanghali-ET anchor. Kinukuwenta sa START
            # (DST-dependent: 57600 EDT / 61200 EST); sapat na dahil
            # nire-reload ang config sa bawat START.
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
        # Chart/labels ay laging updated; ang TRADING lang ang naka-gate
        # sa START — walang strategy evaluation habang STOPPED
        if self.state is BotState.RUNNING:
            self._evaluate_strategy(stretch)

    def _handle_daily_open(self, open_price: float) -> None:
        self.dailyOpenUpdated.emit(open_price)
        if self._timeframe == "daily":
            # Polymarket daily strike = Binance 1m close, nakaraang 12PM ET
            self.log("INFO", f"Price to beat (12:00 PM ET strike) = "
                             f"${open_price:,.2f}")
        else:
            self.log("INFO", f"Period open = ${open_price:,.2f}")

    # ------------------------------------------------------------- strategy

    def _evaluate_strategy(self, stretch: float) -> None:
        now = dt.datetime.now(dt.timezone.utc)
        self._reset_daily_counter(now)

        if self._live_pending:
            self.strategyStatus.emit("CONNECTING — setting up Polymarket live mode…")
            return

        live = isinstance(self.executor, LiveExecutor)
        if live and self.executor.market is not None:
            market = f"{self.executor.market.question} [LIVE]"
        else:
            market = (f"BTC Up/Down [{self._timeframe}] "
                      f"{now.strftime('%Y-%m-%d %H:%M')} [PAPER]")

        if self.executor.position is None:
            # Death trap guard #1: Economic Data Day (manual toggle sa Settings)
            if self._db.get_setting("econ_block_date") == now.date().isoformat():
                self.strategyStatus.emit(
                    "PAUSED — economic data day (Fed/CPI), entries blocked today"
                )
                return

            if live:
                # Totoong order book: bibili tayo sa best ASK ng target side
                book = self._live_books.get(target_side(stretch))
                share_price = book[1] if book else None
                if share_price is None:
                    self.strategyStatus.emit("WAITING — no live order book data yet")
                    return
            else:
                share_price = estimate_otm_share_price(stretch, self._price_scale)
            sig = evaluate_entry(now, stretch, share_price, self._trades_today, self.config)
            if sig.action is Action.ENTER:
                # Death trap guard #2: volume escalation veto
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
                    return
                self._volume_veto_logged = False

                # Death trap guard #3: Coinbase premium veto (fail-open kung
                # walang Coinbase data)
                if self._coinbase.last_price is not None:
                    premium = coinbase_premium_pct(
                        self._coinbase.last_price, self._feed.last_price
                    )
                    exploding, why = is_premium_exploding(
                        premium, stretch, self.config.premium_threshold_pct
                    )
                    if exploding:
                        if not self._premium_veto_logged:
                            self.log("WARN", f"Entry blocked — {why}")
                            self._premium_veto_logged = True
                        self.strategyStatus.emit(f"BLOCKED — {why}")
                        return
                    self._premium_veto_logged = False

                risk = float(self._db.get_setting("risk_usdc", DEFAULT_RISK_USDC))
                tag = self.executor.MODE
                try:
                    pos = self.executor.buy(market, sig.side, share_price, risk)
                except Exception as e:
                    filelog.exception("BUY order failed:")
                    self.log("ERROR", f"BUY order failed: {e}")
                    self.strategyStatus.emit(f"ERROR — BUY failed: {e}")
                    return
                self._trades_today += 1
                self.log("TRADE", f"[{tag}] BUY {pos.shares:,.1f} {sig.side} @ "
                                  f"{share_price:.2f} (${risk:.2f}) — {sig.reason}")
                self.tradeExecuted.emit()
                if live:
                    asyncio.create_task(self._refresh_live_balance())
                self.strategyStatus.emit(
                    f"IN POSITION: {sig.side} @ {share_price:.2f}"
                )
            else:
                self.strategyStatus.emit(f"WATCHING — {sig.reason}")
                # I-log ang reason kapag NAGBAGO ang klase nito (numbers
                # stripped sa dedup key para hindi mag-log kada tick)
                key = re.sub(r"[0-9.+-]+", "#", sig.reason)
                if key != self._watch_log_key:
                    self._watch_log_key = key
                    self.log("INFO", f"Watching: {sig.reason}")
        else:
            pos = self.executor.position
            if live:
                # Magbebenta tayo sa best BID ng hawak nating side
                book = self._live_books.get(pos.side)
                share_price = book[0] if book else None
                if share_price is None:
                    self.strategyStatus.emit("WAITING — no live order book data yet")
                    return
            else:
                share_price = position_share_price(
                    stretch, pos.side, self._price_scale
                )
            sig = evaluate_exit(now, pos, share_price, self.config)
            if sig.action is Action.EXIT:
                tag = self.executor.MODE
                try:
                    pnl = self.executor.sell(market, share_price)
                except Exception as e:
                    filelog.exception("SELL order failed:")
                    self.log("ERROR", f"SELL order failed: {e}")
                    self.strategyStatus.emit(f"ERROR — SELL failed: {e}")
                    return
                self.log("TRADE", f"[{tag}] SELL {pos.side} @ {share_price:.2f} — "
                                  f"PnL {pnl:+,.2f} USDC — {sig.reason}")
                self.tradeExecuted.emit()
                if live:
                    asyncio.create_task(self._refresh_live_balance())
                self.strategyStatus.emit(f"FLAT — last PnL {pnl:+,.2f} USDC")
            else:
                self.strategyStatus.emit(
                    f"IN POSITION: {pos.side} @ {pos.entry_price:.2f} "
                    f"(now ~{share_price:.2f}) — {sig.reason}"
                )

    def _reset_daily_counter(self, now: dt.datetime) -> None:
        """I-reset ang trade counter KADA MARKET PERIOD (hindi kada araw).

        Sa daily timeframe, pareho lang ito ng dating per-day reset; sa
        15m/1h/4h, bawat bagong period ay bagong market — may panibagong
        1-trade allowance (kung hindi, titigil ang bot buong araw
        pagkatapos ng unang trade sa 15m mode).
        """
        period = self._aligned_period_start()
        if self._trades_period != period:
            self._trades_period = period
            self._trades_today = 0
