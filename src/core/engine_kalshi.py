"""Kalshi bot engine — Internal Straddle / Box Arbitrage sa sports markets.

Flow kada cycle:
1. SCAN     : hanapin ang mga ~50/50 high-volume sports market (public API)
2. PLACE    : dalawang post-only resting BUY (YES @49¢ + NO @49¢)
3. MONITOR  : i-poll ang fills kada ~3s; ang StraddleCycle state machine
              (strategy/straddle.py) ang nagdedesisyon
4. SENTINEL : kapag single-sided masyadong matagal (o tumakbo ang presyo),
              kanselahin ang lagging order at i-hedge hanggang 51¢
5. RECORD   : LOCKED (+~1.1%), HEDGED (~breakeven), CANCELLED, o
              UNHEDGED_HOLD (hihintayin ang settlement)

QObject para maka-emit ng Qt signals sa UI (parehong pattern ng PolyEngine).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from enum import Enum
from typing import Optional

from PySide6.QtCore import QObject, Signal

from src.core import secrets as secret_store
from src.execution.kalshi_client import (
    KalshiClient,
    KalshiError,
    best_prices_from_orderbook,
)
from src.execution.kalshi_live import KalshiLiveExecutor
from src.execution.kalshi_paper import KalshiPaperExecutor
from src.storage.db import ScopedDatabase
from src.strategy.straddle import (
    CycleState,
    MarketCandidate,
    ScanConfig,
    SentinelConfig,
    StraddleCycle,
    is_candidate,
    rank_candidates,
    straddle_sizing,
)

filelog = logging.getLogger("sportsbet.engine_kalshi")

SCAN_INTERVAL_SECS = 30
FILL_POLL_SECS = 3
SETTLE_POLL_SECS = 60
STRADDLE_KEY = "open_straddle"  # settings key (naka-scope na sa kalshi)

DEFAULTS = {
    "risk_usd": 100.0,
    "entry_price_cents": 49,
    "hedge_timeout_secs": 90.0,
    "hedge_max_price": 51,
    "hedge_retries": 3,
    "min_volume": 5000,
    "min_close_mins": 45.0,
    "max_close_hours": 12.0,
    "paper_start_usd": 1000.0,
}


class BotState(Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


class KalshiEngine(QObject):
    stateChanged = Signal(str)            # BotState value
    strategyStatus = Signal(str)          # human-readable strategy state
    straddleStatus = Signal(str)          # active cycle state machine text
    marketsScanned = Signal(list)         # list[dict] para sa dashboard table
    tradeExecuted = Signal()              # may bagong trade sa DB
    logAdded = Signal(str, str)           # (level, message)
    modeChanged = Signal(str)             # "PAPER" | "LIVE"
    liveBalance = Signal(float)           # totoong USD balance (live mode)
    connectionChanged = Signal(str, bool)  # unused (shared monitor sa poly)

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self.state = BotState.STOPPED
        self.executor: KalshiPaperExecutor | KalshiLiveExecutor = KalshiPaperExecutor()
        self._client: Optional[KalshiClient] = None
        self._run_task: Optional[asyncio.Task] = None
        self._balance_task: Optional[asyncio.Task] = None
        self._cycle: Optional[StraddleCycle] = None
        self._traded_tickers: set[str] = set()  # iwasang i-straddle ulit

    # ------------------------------------------------------------------ API

    def start_monitors(self) -> None:
        """Walang laging-bukas na feed ang Kalshi panel (walang chart) —
        ang shared ConnectionMonitor sa poly engine ang nagche-check ng
        kalshi endpoint. Placeholder para pareho ang engine interface."""

    def start(self) -> None:
        if self.state is BotState.RUNNING:
            return
        self.state = BotState.RUNNING
        mode = str(self._db.get_setting("trading_mode", "paper")).lower()
        self._run_task = asyncio.create_task(self._run(mode), name="kalshi-run")
        self.stateChanged.emit(self.state.value)
        self.log("INFO", f"Bot STARTED [{mode.upper()} MODE] — Internal "
                         "Straddle (box arbitrage) on 50/50 sports markets")

    async def stop(self) -> None:
        if self.state is BotState.STOPPED:
            return
        self.state = BotState.STOPPED
        for task in (self._run_task, self._balance_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._run_task = None
        self._balance_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self.stateChanged.emit(self.state.value)
        self.strategyStatus.emit("idle (press START BOT)")
        self.straddleStatus.emit("—")
        self.log("INFO", "Bot STOPPED — resting orders (if any) remain on "
                         "the exchange in LIVE mode; cancel them on kalshi.com "
                         "if you do not want them")

    def log(self, level: str, message: str) -> None:
        self._db.add_log(level, message)
        self.logAdded.emit(level, message)
        py_level = {"WARN": logging.WARNING, "ERROR": logging.ERROR}.get(
            level, logging.INFO
        )
        filelog.log(py_level, message)

    # ------------------------------------------------------------- main loop

    async def _run(self, mode: str) -> None:
        try:
            await self._setup(mode)
        except Exception as e:
            filelog.exception("Kalshi setup failed:")
            self.log("ERROR", f"Kalshi setup failed: {e} — bot stopped")
            self.state = BotState.STOPPED
            self.stateChanged.emit(self.state.value)
            return

        self._restore_cycle()

        while self.state is BotState.RUNNING:
            try:
                if self._cycle is None:
                    await self._scan_and_place()
                    await asyncio.sleep(self._scan_interval())
                elif self._cycle.state is CycleState.UNHEDGED_HOLD:
                    await self._watch_settlement()
                    await asyncio.sleep(SETTLE_POLL_SECS)
                else:
                    await self._monitor_cycle()
                    await asyncio.sleep(FILL_POLL_SECS)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                filelog.exception("Kalshi engine loop error:")
                self.log("WARN", f"Engine loop error: {e} — retrying in 10s")
                await asyncio.sleep(10)

    async def _setup(self, mode: str) -> None:
        env = str(self._db.get_setting("env", "prod"))
        if mode == "live":
            key_id = secret_store.get_secret(secret_store.KEY_KALSHI_API_ID)
            pem = secret_store.get_secret(secret_store.KEY_KALSHI_PEM)
            if not pem:
                pem = str(self._db.get_setting("pem_path", "")) or None
            if not key_id or not pem:
                raise KalshiError(
                    "Kalshi API Key ID / RSA private key not set in Settings"
                )
            self._client = KalshiClient(env=env, key_id=key_id,
                                        private_key_pem=pem)
            balance = await self._client.get_balance()  # creds check
            self.executor = KalshiLiveExecutor(self._client)
            self.modeChanged.emit("LIVE")
            self.liveBalance.emit(balance)
            self._balance_task = asyncio.create_task(self._balance_loop())
            self.log("INFO", f"LIVE mode ready [{env}] — balance "
                             f"${balance:,.2f}")
        else:
            self._client = KalshiClient(env=env)  # public data lang
            self.executor = KalshiPaperExecutor()
            self.modeChanged.emit("PAPER")
            self.log("INFO", f"PAPER mode — simulated fills on real {env} "
                             "market data")
        await self._ensure_series_tickers()

    async def _ensure_series_tickers(self) -> None:
        """Kapag walang naka-set na sports series, i-discover sa API."""
        raw = str(self._db.get_setting("series_tickers", "")).strip()
        if raw:
            return
        try:
            series = await self._client.get_series_list("Sports")
        except Exception as e:
            self.log("WARN", f"Sports series discovery failed: {e} — "
                             "set Series Tickers manually in Settings")
            return
        tickers = [s.get("ticker", "") for s in series if s.get("ticker")]
        # Unahin ang major leagues na malamang may aktibong games (ang
        # alphabetical na unang anim ay puro off-season na soccer league)
        preferred_order = (
            "KXMLBGAME", "KXWNBAGAME", "KXNBAGAME", "KXNFLGAME",
            "KXNHLGAME", "KXNCAAFGAME", "KXEPLGAME", "KXUCLGAME",
        )
        game_series = [t for t in tickers if "GAME" in t.upper()]
        preferred = [t for t in preferred_order if t in tickers]
        rest = [t for t in game_series if t not in preferred]
        chosen = (preferred + rest)[:6] or tickers[:6]
        if chosen:
            self._db.set_setting("series_tickers", ",".join(chosen))
            self.log("INFO", f"Discovered sports series: {', '.join(chosen)} "
                             f"(all available: {len(tickers)}) — editable in "
                             "Settings")

    # ------------------------------------------------------------------ scan

    def _scan_config(self) -> ScanConfig:
        g = self._db.get_setting
        return ScanConfig(
            entry_price_cents=int(float(g("entry_price_cents",
                                          DEFAULTS["entry_price_cents"]))),
            min_volume=int(float(g("min_volume", DEFAULTS["min_volume"]))),
            min_secs_to_close=float(g("min_close_mins",
                                      DEFAULTS["min_close_mins"])) * 60,
            max_secs_to_close=float(g("max_close_hours",
                                      DEFAULTS["max_close_hours"])) * 3600,
        )

    def _sentinel_config(self) -> SentinelConfig:
        g = self._db.get_setting
        return SentinelConfig(
            hedge_timeout_secs=float(g("hedge_timeout_secs",
                                       DEFAULTS["hedge_timeout_secs"])),
            hedge_max_price_cents=int(float(g("hedge_max_price",
                                              DEFAULTS["hedge_max_price"]))),
            hedge_retries=int(float(g("hedge_retries",
                                      DEFAULTS["hedge_retries"]))),
        )

    def _scan_interval(self) -> float:
        return float(self._db.get_setting("scan_interval_secs",
                                          SCAN_INTERVAL_SECS))

    async def _scan_and_place(self) -> None:
        cfg = self._scan_config()
        series = [s.strip() for s in
                  str(self._db.get_setting("series_tickers", "")).split(",")
                  if s.strip()]
        now = time.time()
        found: list[MarketCandidate] = []
        rows: list[dict] = []

        for ticker in series[:6]:
            try:
                data = await self._client.get_markets(series_ticker=ticker)
            except Exception as e:
                self.log("WARN", f"Market scan failed for {ticker}: {e}")
                continue
            for m in data.get("markets", []):
                cand = _to_candidate(m)
                if cand is None:
                    continue
                ok, reason = is_candidate(cand, now, cfg)
                rows.append({
                    "ticker": cand.ticker, "title": cand.title,
                    "yes_bid": cand.yes_bid, "yes_ask": cand.yes_ask,
                    "no_bid": cand.no_bid, "no_ask": cand.no_ask,
                    "volume": cand.volume,
                    "status": "READY" if ok else reason,
                })
                if ok and cand.ticker not in self._traded_tickers:
                    found.append(cand)

        rows.sort(key=lambda r: -r["volume"])
        self.marketsScanned.emit(rows[:50])

        ranked = rank_candidates(
            [c for c in found if c.ticker not in self._traded_tickers],
            now, cfg,
        )
        if not ranked:
            self.strategyStatus.emit(
                f"SCANNING — {len(rows)} markets checked, none in the "
                f"{cfg.min_entry_cents}-{cfg.max_entry_cents}¢ 50/50 band yet"
            )
            return

        target = ranked[0]
        risk = float(self._db.get_setting("risk_usd", DEFAULTS["risk_usd"]))
        entry = cfg.entry_price_cents
        count = straddle_sizing(risk, entry, entry)
        if count < 1:
            self.strategyStatus.emit(
                f"WAITING — risk ${risk:.2f} too small for one "
                f"{entry}¢+{entry}¢ pair"
            )
            return

        try:
            await self.executor.place_straddle(target.ticker, entry, count)
        except Exception as e:
            filelog.exception("Straddle placement failed:")
            self.log("ERROR", f"Straddle placement failed on "
                              f"{target.ticker}: {e}")
            return

        self._cycle = StraddleCycle(
            ticker=target.ticker, count=count, entry_cents=entry,
            started_ts=now, cfg=self._sentinel_config(),
        )
        self._traded_tickers.add(target.ticker)
        self._persist_cycle()
        cost = count * entry * 2 / 100.0
        for side in ("YES", "NO"):
            self._db.add_trade(
                market=target.ticker, side=side, action="BUY",
                price=entry / 100.0, size=count * entry / 100.0,
                status="OPEN",
            )
        self.tradeExecuted.emit()
        tag = self.executor.MODE
        self.log("TRADE", f"[{tag}] STRADDLE placed on {target.ticker}: "
                          f"BUY {count} YES @ {entry}¢ + {count} NO @ {entry}¢ "
                          f"(${cost:,.2f}) — {target.title}")
        self.strategyStatus.emit(
            f"STRADDLE WORKING — {target.ticker} ({count} pairs @ {entry}¢)"
        )

    # --------------------------------------------------------------- monitor

    async def _monitor_cycle(self) -> None:
        cycle = self._cycle
        assert cycle is not None
        prices: dict = {}
        try:
            book = await self._client.get_orderbook(cycle.ticker)
            prices = best_prices_from_orderbook(book)
        except Exception as e:
            filelog.warning("Orderbook fetch failed for %s: %s",
                            cycle.ticker, e)

        # Paper: ipakain ang book snapshot para gumalaw ang simulated fills
        if isinstance(self.executor, KalshiPaperExecutor) and prices:
            self.executor.on_book(prices)

        yes_filled, no_filled = await self.executor.get_fills(cycle.ticker)

        lagging = cycle.lagging_side
        lag_ask = None
        if lagging is not None and prices:
            lag_ask = prices.get("yes_ask" if lagging == "YES" else "no_ask")

        decision = cycle.on_tick(time.time(), yes_filled, no_filled, lag_ask)
        self._persist_cycle()
        self.straddleStatus.emit(
            f"{cycle.ticker}: {cycle.state.value} — YES {yes_filled}/"
            f"{cycle.count}, NO {no_filled}/{cycle.count} — {decision.reason}"
        )

        if decision.action == "WAIT":
            return

        if decision.action == "CANCEL_ALL":
            await self.executor.cancel_all(cycle.ticker)
            self._db.add_trade(
                market=cycle.ticker, side="PAIR", action="CANCEL",
                price=cycle.entry_cents / 100.0, size=0.0, status="CANCELLED",
            )
            self.log("INFO", f"Straddle cancelled on {cycle.ticker} — "
                             f"{decision.reason}")
            self._finish_cycle()
            return

        if decision.action == "HEDGE":
            side = cycle.lagging_side
            if side is None:
                return
            self.log("WARN", decision.reason)
            await self.executor.cancel(cycle.ticker, side)
            need = cycle.count - (yes_filled if side == "YES" else no_filled)
            filled = await self.executor.hedge(
                cycle.ticker, side, cycle.cfg.hedge_max_price_cents, need,
                prices=prices,
            )
            if filled >= need:
                cycle.mark_hedged(cycle.cfg.hedge_max_price_cents)
                self._record_completed()
            return

        if decision.action == "GIVE_UP":
            self.log("ERROR", f"{cycle.ticker}: {decision.reason}")
            self._persist_cycle()  # mananatili hanggang settlement
            return

        if decision.action == "DONE":
            self._record_completed()

    def _record_completed(self) -> None:
        """I-record ang natapos na cycle (LOCKED / HEDGED) at mag-reset."""
        cycle = self._cycle
        assert cycle is not None
        pnl_cents = cycle.realized_pnl_cents()
        if pnl_cents is None:
            return
        pnl = pnl_cents / 100.0
        tag = self.executor.MODE
        if cycle.state is CycleState.LOCKED:
            action, note = "SETTLE", "both sides filled — $1.00/pair locked"
            price = cycle.entry_cents / 100.0
        else:
            action = "HEDGE"
            note = (f"scratch via sentinel @ "
                    f"{cycle.hedge_price_cents or 0}¢ hedge")
            price = (cycle.hedge_price_cents or 0) / 100.0
        pairs = min(cycle.yes_filled, cycle.no_filled)
        self._db.add_trade(
            market=cycle.ticker, side="PAIR", action=action,
            price=price, size=pairs * 1.0, status="FILLED", pnl=pnl,
        )
        self.log("TRADE", f"[{tag}] {cycle.ticker} {cycle.state.value} — "
                          f"{pairs} pairs, PnL {pnl:+,.2f} USD ({note})")
        self.tradeExecuted.emit()
        self.strategyStatus.emit(
            f"FLAT — last cycle {cycle.state.value}, PnL {pnl:+,.2f} USD"
        )
        if isinstance(self.executor, KalshiLiveExecutor):
            asyncio.create_task(self._refresh_balance())
        self._finish_cycle()

    async def _watch_settlement(self) -> None:
        """UNHEDGED_HOLD: hintayin ang market settlement, i-record ang PnL."""
        cycle = self._cycle
        assert cycle is not None
        try:
            market = await self._client.get_market(cycle.ticker)
        except Exception as e:
            filelog.warning("Settlement check failed: %s", e)
            return
        status = str(market.get("status", "")).lower()
        result = str(market.get("result", "")).lower()
        self.straddleStatus.emit(
            f"{cycle.ticker}: UNHEDGED_HOLD — waiting for settlement "
            f"(status: {status or '?'})"
        )
        if status not in ("settled", "finalized") or result not in ("yes", "no"):
            return
        held = "YES" if cycle.yes_filled > cycle.no_filled else "NO"
        won = held.lower() == result
        pnl = cycle.settlement_pnl_cents(won) / 100.0
        held_count = max(cycle.yes_filled, cycle.no_filled)
        self._db.add_trade(
            market=cycle.ticker, side=held, action="SETTLE",
            price=1.0 if won else 0.0, size=held_count * 1.0,
            status="FILLED", pnl=pnl,
        )
        self.log("TRADE", f"[{self.executor.MODE}] {cycle.ticker} settled "
                          f"{result.upper()} — held {held}, "
                          f"PnL {pnl:+,.2f} USD")
        self.tradeExecuted.emit()
        self._finish_cycle()

    # -------------------------------------------------------------- balance

    async def _balance_loop(self) -> None:
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

    async def _refresh_balance(self) -> None:
        try:
            balance = await self.executor.get_balance()
            if balance is not None:
                self.liveBalance.emit(balance)
        except Exception as e:
            filelog.warning("Balance refresh failed: %s", e)

    # ---------------------------------------------------------- persistence

    def _persist_cycle(self) -> None:
        import json
        if self._cycle is None:
            self._db.set_setting(STRADDLE_KEY, "")
        else:
            payload = self._cycle.to_dict()
            payload["mode"] = self.executor.MODE
            self._db.set_setting(STRADDLE_KEY, json.dumps(payload))

    def _finish_cycle(self) -> None:
        self._cycle = None
        self._db.set_setting(STRADDLE_KEY, "")

    def _restore_cycle(self) -> None:
        """I-restore ang naiwang straddle pagkatapos ng app restart."""
        import json
        raw = self._db.get_setting(STRADDLE_KEY, "")
        if not raw:
            return
        try:
            saved = json.loads(raw)
        except (ValueError, TypeError):
            self._db.set_setting(STRADDLE_KEY, "")
            return
        saved_mode = saved.pop("mode", "PAPER")
        if saved_mode != self.executor.MODE:
            level = "ERROR" if saved_mode == "LIVE" else "WARN"
            self.log(level, (
                f"A {saved_mode} straddle on {saved.get('ticker')} was left "
                f"open but the bot is now in {self.executor.MODE} mode — "
                "it cannot be tracked. Manage it on kalshi.com."
            ))
            self._db.set_setting(STRADDLE_KEY, "")
            return
        try:
            self._cycle = StraddleCycle.from_dict(
                saved, cfg=self._sentinel_config()
            )
        except (KeyError, ValueError, TypeError) as e:
            self.log("WARN", f"Corrupt saved straddle discarded ({e})")
            self._db.set_setting(STRADDLE_KEY, "")
            return
        self._traded_tickers.add(self._cycle.ticker)
        self.log("INFO", f"Restored open straddle after restart: "
                         f"{self._cycle.ticker} "
                         f"({self._cycle.state.value})")
        if saved_mode == "PAPER":
            # Ibalik ang simulated orders sa paper executor
            asyncio.create_task(self.executor.place_straddle(
                self._cycle.ticker, self._cycle.entry_cents, self._cycle.count
            ))


def _money_cents(m: dict, dollars_key: str, cents_key: str) -> int:
    """Presyo sa cents — suportado ang bago ("0.3800" dollar strings) at
    lumang (integer cents) API format ng Kalshi."""
    raw = m.get(dollars_key)
    if raw not in (None, ""):
        return int(round(float(raw) * 100))
    return int(m.get(cents_key) or 0)


def _to_candidate(m: dict) -> Optional[MarketCandidate]:
    """Kalshi /markets row -> MarketCandidate; None kung kulang ang data."""
    try:
        # expected_expiration_time = katapusan ng game (ito ang mahalaga);
        # ang close_time ay may +2 araw na postponement buffer
        close_raw = m.get("expected_expiration_time") or m.get("close_time")
        close_ts = 0.0
        if close_raw:
            close_ts = dt.datetime.fromisoformat(
                str(close_raw).replace("Z", "+00:00")
            ).timestamp()
        yes_bid = _money_cents(m, "yes_bid_dollars", "yes_bid")
        yes_ask = _money_cents(m, "yes_ask_dollars", "yes_ask")
        no_bid = _money_cents(m, "no_bid_dollars", "no_bid")
        no_ask = _money_cents(m, "no_ask_dollars", "no_ask")
        volume = int(float(m.get("volume_fp") or m.get("volume") or 0))
        oi = int(float(m.get("open_interest_fp") or m.get("open_interest") or 0))
        title = str(m.get("title", m["ticker"]))
        side_name = str(m.get("yes_sub_title", "")).strip()
        if side_name:
            title = f"{title} ({side_name})"
        return MarketCandidate(
            ticker=str(m["ticker"]),
            title=title,
            yes_bid=yes_bid,
            yes_ask=yes_ask or (100 - no_bid if no_bid else 0),
            no_bid=no_bid,
            no_ask=no_ask or (100 - yes_bid if yes_bid else 0),
            volume=volume,
            close_ts=close_ts,
            open_interest=oi,
        )
    except (KeyError, ValueError, TypeError):
        return None
