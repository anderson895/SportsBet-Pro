"""Polymarket bot engine — Internal Straddle / Box Arbitrage.

Same strategy as the Kalshi box-arb engine (`engine_kalshi.py`), but on
Polymarket: scan Gamma for liquid ~50/50 binary markets, place two resting BUY
limit orders (YES + NO) on the CLOB, monitor fills, and run the Hedge Sentinel
(`strategy/straddle.py`) for single-sided fills.

- PAPER: reuses the exchange-agnostic paper executor (simulated fills from real
  Gamma order-book snapshots).
- LIVE: real CLOB orders via `PolymarketClient` (documented but unverified on a
  funded account — validate with a tiny real order first).

Emits the same Qt signals as the Kalshi box-arb engine so the sports-cards
dashboard wiring is identical.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import re
import time
from enum import Enum
from typing import Optional

import httpx
from PySide6.QtCore import QObject, Signal

from src.core import secrets as secret_store
from src.core.applog import Outage, err_text
from src.core.status import ConnectionMonitor
from src.execution.poly_box import (
    PolyBoxLiveExecutor,
    PolyBoxPaperExecutor,
    PolyMarketRef,
    best_prices_for_ref,
    fetch_market_prices,
    scan_markets,
)
from src.execution.polymarket import PolymarketClient, PolymarketError
from src.storage.db import ScopedDatabase
from src.strategy.straddle import (
    CycleState,
    ScanConfig,
    SentinelConfig,
    StraddleCycle,
    is_candidate,
    rank_candidates,
    straddle_sizing,
)

filelog = logging.getLogger("sportsbet.engine_poly_box")

SCAN_INTERVAL_SECS = 30
FILL_POLL_SECS = 3
SETTLE_POLL_SECS = 60
STRADDLE_KEY = "open_straddle"
# A single straddle may not risk more than this share of the account.
MAX_STRADDLE_FRACTION = 0.25

DEFAULTS = {
    "risk_usdc": 100.0,
    "entry_price_cents": 49,
    "hedge_timeout_secs": 90.0,
    "hedge_max_price": 51,
    "hedge_retries": 3,
    "min_volume_usd": 10000,     # USD traded (Gamma volumeNum)
    "min_close_mins": 30.0,
    "max_close_hours": 24.0,
    "paper_start_usdc": 1000.0,
}


def _iso_ts(raw: object) -> Optional[str]:
    """Polymarket trade time -> ISO string the Trades table can format.

    The CLOB returns `match_time` as a UNIX timestamp (seconds), e.g.
    "1783857399" — passing that through raw makes the Trades table show the
    bare number. Already-ISO values are kept as-is.
    """
    if raw in (None, ""):
        return None
    text = str(raw).strip()
    try:
        secs = float(text)
    except ValueError:
        return text  # already ISO (or something we shouldn't touch)
    return dt.datetime.fromtimestamp(secs, dt.timezone.utc).isoformat()


class BotState(Enum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"


class PolyBoxEngine(QObject):
    stateChanged = Signal(str)
    strategyStatus = Signal(str)
    straddleStatus = Signal(str)
    marketsScanned = Signal(list)
    marketTick = Signal(str, str, float, float)   # (ticker, title, yes%, no%)
    tradeExecuted = Signal()
    logAdded = Signal(str, str)
    modeChanged = Signal(str)
    liveBalance = Signal(float)
    connectionChanged = Signal(str, bool)         # unused (shared monitor)

    def __init__(self, db: ScopedDatabase) -> None:
        super().__init__()
        self._db = db
        self.state = BotState.STOPPED
        self.executor: PolyBoxPaperExecutor | PolyBoxLiveExecutor = \
            PolyBoxPaperExecutor()
        self._http: Optional[httpx.AsyncClient] = None
        self._live: Optional[PolymarketClient] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._balance_task: Optional[asyncio.Task] = None
        self._chart_task: Optional[asyncio.Task] = None
        self._session_ready = False
        self._cycle: Optional[StraddleCycle] = None
        self._cycle_title = ""
        self._cycle_ref: Optional[PolyMarketRef] = None
        self._refs: dict[str, PolyMarketRef] = {}   # ticker -> market ref
        self._traded: set[str] = set()
        self._chart_focus: Optional[tuple[str, str]] = None
        self._chart_focus_user = False
        self._watch_log_key = ""   # dedup key for "Watching:" log lines
        self._outage = Outage()    # quiet + slower retries while offline
        self._last_balance: Optional[float] = None  # last from the live API
        # Shared connection monitor (internet / binance / polymarket / kalshi);
        # fanned out to both dashboards by main_window.
        self._monitor = ConnectionMonitor(
            on_status=lambda name, up: self.connectionChanged.emit(name, up))

    # ------------------------------------------------------------------ API

    def set_chart_focus(self, ticker: str, title: str) -> None:
        self._chart_focus = (ticker, title)
        self._chart_focus_user = True
        try:
            asyncio.create_task(self._chart_poll_once(ticker, title))
        except RuntimeError:
            pass

    async def _chart_poll_once(self, ticker: str, title: str) -> None:
        prices = await self._prices_for(ticker)
        self._emit_tick(ticker, title, prices)

    def start_monitors(self) -> None:
        self._monitor.start()
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._loop(), name="polybox-loop")

    def start(self) -> None:
        if self.state is BotState.RUNNING:
            return
        self.state = BotState.RUNNING
        self._session_ready = False
        mode = str(self._db.get_setting("trading_mode", "paper")).lower()
        asyncio.create_task(self._begin_session(mode), name="polybox-session")
        self.stateChanged.emit(self.state.value)
        self.log("INFO", f"Bot STARTED [{mode.upper()} MODE] — Internal "
                         "Straddle (box arbitrage) on 50/50 Polymarket markets")

    async def stop(self) -> None:
        if self.state is BotState.STOPPED:
            return
        self.state = BotState.STOPPED
        self._session_ready = False
        if self._balance_task is not None:
            self._balance_task.cancel()
            self._balance_task = None
        self.stateChanged.emit(self.state.value)
        self.straddleStatus.emit("—")
        self.log("INFO", "Bot STOPPED — trading paused; live market feed stays "
                         "on. LIVE resting orders (if any) remain on Polymarket; "
                         "cancel them on polymarket.com if unwanted")

    def log(self, level: str, message: str) -> None:
        self._db.add_log(level, message)
        self.logAdded.emit(level, message)
        py_level = {"WARN": logging.WARNING, "ERROR": logging.ERROR}.get(
            level, logging.INFO)
        filelog.log(py_level, message)

    # ------------------------------------------------------------- sessions

    async def _begin_session(self, mode: str) -> None:
        try:
            await self._setup(mode)
        except Exception as e:
            filelog.exception("Polymarket box-arb live setup failed:")
            self.log("ERROR", f"Live setup failed: {e} — falling back to PAPER")
            self.executor = PolyBoxPaperExecutor()
            self.modeChanged.emit("PAPER")
        self._restore_cycle()
        self._session_ready = True

    async def _setup(self, mode: str) -> None:
        if mode == "live":
            pk = secret_store.get_secret(secret_store.KEY_PM_PRIVATE)
            funder = secret_store.get_secret(secret_store.KEY_PM_FUNDER)
            if not pk or not funder:
                raise PolymarketError(
                    "Polymarket Private Key / Funder Address not set in Settings")
            sig = int(self._db.get_setting("pm_signature_type", 1))
            client = PolymarketClient(private_key=pk, funder=funder,
                                      signature_type=sig)
            await asyncio.to_thread(client.connect)
            balance = await asyncio.to_thread(client.get_usdc_balance)
            self._live = client
            self.executor = PolyBoxLiveExecutor(client)
            self.modeChanged.emit("LIVE")
            self._last_balance = balance
            self.liveBalance.emit(balance)
            self._balance_task = asyncio.create_task(self._balance_loop())
            self.log("INFO", f"LIVE mode ready — balance ${balance:,.2f}")
        else:
            self.executor = PolyBoxPaperExecutor()
            self.modeChanged.emit("PAPER")
            self.log("INFO", "PAPER mode — simulated fills on real Polymarket "
                             "market data")

    # ------------------------------------------------------------- main loop

    async def _loop(self) -> None:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=20)
        while True:
            try:
                trading = self.state is BotState.RUNNING and self._session_ready
                if trading and self._cycle is None:
                    await self._scan_and_place(place=True)
                    await asyncio.sleep(
                        self._outage.delay(self._scan_interval()))
                elif trading and self._cycle.state is CycleState.UNHEDGED_HOLD:
                    await self._scan_and_place(place=False)
                    await self._watch_settlement()
                    await asyncio.sleep(SETTLE_POLL_SECS)
                elif trading:
                    await self._monitor_cycle()
                    await asyncio.sleep(FILL_POLL_SECS)
                else:
                    await self._scan_and_place(place=False)
                    await asyncio.sleep(
                        self._outage.delay(self._scan_interval()))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                filelog.exception("Poly box-arb loop error:")
                self.log("WARN", f"Loop error: {e} — retrying in 10s")
                await asyncio.sleep(10)

    # ------------------------------------------------------------------ scan

    def _scan_config(self) -> ScanConfig:
        g = self._db.get_setting
        return ScanConfig(
            entry_price_cents=int(float(g("entry_price_cents",
                                          DEFAULTS["entry_price_cents"]))),
            min_volume=int(float(g("min_volume_usd",
                                   DEFAULTS["min_volume_usd"]))),
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
        return float(self._db.get_setting("scan_interval_secs", SCAN_INTERVAL_SECS))

    def _account_balance(self) -> Optional[float]:
        """Balance to size-check against; None when it is not known yet."""
        if self.executor is not None and self.executor.MODE == "PAPER":
            start = float(self._db.get_setting("paper_start_usdc",
                                               DEFAULTS["paper_start_usdc"]))
            return start + self._db.total_pnl()
        return self._last_balance

    def _leagues(self) -> list[str]:
        """Selected "Sports to Trade" labels; empty = every sport."""
        raw = str(self._db.get_setting("sport_leagues", "") or "")
        return [s.strip() for s in raw.split("|") if s.strip()]

    def _watch(self, reason: str) -> None:
        """Show WHY no straddle was placed — on screen AND in the log.

        Box arb legitimately sits idle for long stretches, and until now the
        reason only went to the UI status line: the log could not answer "why
        didn't it trade?". Logged deduped (digits stripped from the key) so a
        30s scan loop doesn't spam the file.
        """
        self.strategyStatus.emit(reason)
        key = re.sub(r"[0-9.,+-]+", "#", reason)
        if key != self._watch_log_key:
            self._watch_log_key = key
            self.log("INFO", f"Watching: {reason}")

    async def _scan_and_place(self, place: bool = True) -> None:
        cfg = self._scan_config()
        now = time.time()
        try:
            cands, refs = await scan_markets(self._http, self._leagues())
        except Exception as e:
            msg = self._outage.fail(f"Market scan failed: {err_text(e)}")
            if msg:
                self.log("WARN", msg)
            return
        back = self._outage.recover()
        if back:
            self.log("INFO", back)
        self._refs.update(refs)
        rows: list[dict] = []
        found = []
        for c in cands:
            ok, reason = is_candidate(c, now, cfg)
            rows.append({
                "ticker": c.ticker, "title": c.title,
                "yes_bid": c.yes_bid, "yes_ask": c.yes_ask,
                "no_bid": c.no_bid, "no_ask": c.no_ask,
                "volume": c.volume, "status": "READY" if ok else reason,
            })
            if ok and c.ticker not in self._traded:
                found.append(c)
        rows.sort(key=lambda r: -r["volume"])
        self.marketsScanned.emit(rows[:400])

        if rows and self._cycle is None:
            if (self._chart_focus_user and self._chart_focus is not None
                    and not any(r["ticker"] == self._chart_focus[0] for r in rows)):
                self._chart_focus_user = False
            if not self._chart_focus_user:
                ready = [r for r in rows if r.get("status") == "READY"]
                focus = ready[0] if ready else rows[0]
                self._chart_focus = (focus["ticker"], focus["title"])
                self._emit_tick_row(focus)

        if not place:
            if self.state is BotState.RUNNING:
                self.strategyStatus.emit(f"PREPARING… ({len(rows)} live markets)")
            else:
                self.strategyStatus.emit(
                    f"MONITORING {len(rows)} live markets — press START BOT")
            return

        ranked = rank_candidates(found, now, cfg)
        if not ranked:
            self._watch(
                f"SCANNING — {len(rows)} markets, none in the "
                f"{cfg.min_entry_cents}-{cfg.max_entry_cents}¢ 50/50 band yet")
            return

        risk = float(self._db.get_setting("risk_usdc", DEFAULTS["risk_usdc"]))
        entry = cfg.entry_price_cents
        target = next((c for c in ranked
                       if entry < c.yes_ask and entry < c.no_ask), None)
        if target is None:
            self._watch(
                f"WAITING — {len(ranked)} candidate(s) but a {entry}¢ bid would "
                "cross the book; waiting for a wider spread")
            return
        count = straddle_sizing(risk, entry, entry)
        if count < 1:
            self._watch(
                f"WAITING — risk ${risk:.2f} too small for one "
                f"{entry}¢+{entry}¢ pair")
            return

        # Last line of defence against a mistyped Risk Per Straddle — see the
        # matching guard in engine_kalshi.
        cost = count * entry * 2 / 100.0
        balance = self._account_balance()
        if balance and cost > balance * MAX_STRADDLE_FRACTION:
            self._watch(
                f"BLOCKED — ${cost:,.2f} straddle is over "
                f"{MAX_STRADDLE_FRACTION:.0%} of the ${balance:,.2f} balance. "
                f"Lower Risk Per Straddle (currently ${risk:,.2f})")
            return

        ref = self._refs.get(target.ticker)
        if isinstance(self.executor, PolyBoxLiveExecutor) and ref is not None:
            self.executor.set_market(ref)
        try:
            await self.executor.place_straddle(target.ticker, entry, count)
        except Exception as e:
            filelog.exception("Straddle placement failed:")
            self.log("ERROR", f"Straddle placement failed on {target.title}: {e}")
            return
        self._cycle = StraddleCycle(ticker=target.ticker, count=count,
                                    entry_cents=entry, started_ts=now,
                                    cfg=self._sentinel_config())
        self._cycle_title = target.title
        self._cycle_ref = ref
        self._traded.add(target.ticker)
        self._persist_cycle()
        for side in ("YES", "NO"):
            self._db.add_trade(market=target.ticker, side=side, action="BUY",
                               price=entry / 100.0, size=count * entry / 100.0,
                               status="OPEN")
        self.tradeExecuted.emit()
        self.log("TRADE", f"[{self.executor.MODE}] STRADDLE placed on "
                          f"{target.title}: BUY {count} YES @ {entry}¢ + "
                          f"{count} NO @ {entry}¢ "
                          f"(${cost:,.2f} from ${risk:,.2f} risk)")
        self.strategyStatus.emit(
            f"STRADDLE WORKING — {target.title} ({count} pairs @ {entry}¢)")

    # --------------------------------------------------------------- monitor

    async def _prices_for(self, ticker: str) -> Optional[dict]:
        """Best yes/no bid/ask (cents) for a market — CLOB if live, else Gamma."""
        ref = self._refs.get(ticker)
        if isinstance(self.executor, PolyBoxLiveExecutor) and self._live and ref:
            try:
                return await asyncio.to_thread(
                    best_prices_for_ref, self._live, ref)
            except Exception as e:
                filelog.warning("Live price fetch failed: %s", e)
                return None
        return await fetch_market_prices(ticker, self._http)

    def _emit_tick(self, ticker: str, title: str, prices: Optional[dict]) -> None:
        if not prices or not prices.get("yes_bid") or not prices.get("yes_ask"):
            return
        ymid = (prices["yes_bid"] + prices["yes_ask"]) / 2.0
        nmid = (prices["no_bid"] + prices["no_ask"]) / 2.0
        self.marketTick.emit(ticker, title, ymid, nmid)

    def _emit_tick_row(self, row: dict) -> None:
        ymid = (row["yes_bid"] + row["yes_ask"]) / 2.0
        nmid = (row["no_bid"] + row["no_ask"]) / 2.0
        self.marketTick.emit(row["ticker"], row["title"], ymid, nmid)

    async def _monitor_cycle(self) -> None:
        cycle = self._cycle
        assert cycle is not None
        prices = await self._prices_for(cycle.ticker) or {}
        self._chart_focus = (cycle.ticker, self._cycle_title or cycle.ticker)
        self._emit_tick(cycle.ticker, self._cycle_title or cycle.ticker, prices)

        if isinstance(self.executor, PolyBoxPaperExecutor) and prices:
            self.executor.on_book(prices)
        yes_filled, no_filled = await self.executor.get_fills(cycle.ticker)

        lagging = cycle.lagging_side
        lag_ask = None
        if lagging is not None and prices:
            lag_ask = prices.get("yes_ask" if lagging == "YES" else "no_ask")
        decision = cycle.on_tick(time.time(), yes_filled, no_filled, lag_ask)
        self._persist_cycle()
        self.straddleStatus.emit(
            f"{self._cycle_title[:32]}: {cycle.state.value} — YES {yes_filled}/"
            f"{cycle.count}, NO {no_filled}/{cycle.count} — {decision.reason}")

        if decision.action == "WAIT":
            return
        if decision.action == "CANCEL_ALL":
            await self.executor.cancel_all(cycle.ticker)
            self._db.add_trade(market=cycle.ticker, side="PAIR", action="CANCEL",
                               price=cycle.entry_cents / 100.0, size=0.0,
                               status="CANCELLED")
            self.log("INFO", f"Straddle cancelled — {decision.reason}")
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
                prices=prices)
            if filled >= need:
                cycle.mark_hedged(cycle.cfg.hedge_max_price_cents)
                self._record_completed()
            return
        if decision.action == "GIVE_UP":
            self.log("ERROR", f"{self._cycle_title}: {decision.reason}")
            self._persist_cycle()
            return
        if decision.action == "DONE":
            self._record_completed()

    def _record_completed(self) -> None:
        cycle = self._cycle
        assert cycle is not None
        pnl_cents = cycle.realized_pnl_cents()
        if pnl_cents is None:
            return
        pnl = pnl_cents / 100.0
        if cycle.state is CycleState.LOCKED:
            action, note = "SETTLE", "both sides filled — $1.00/pair locked"
            price = cycle.entry_cents / 100.0
        else:
            action = "HEDGE"
            note = f"scratch via sentinel @ {cycle.hedge_price_cents or 0}¢"
            price = (cycle.hedge_price_cents or 0) / 100.0
        pairs = min(cycle.yes_filled, cycle.no_filled)
        self._db.add_trade(market=cycle.ticker, side="PAIR", action=action,
                           price=price, size=pairs * 1.0, status="FILLED", pnl=pnl)
        self.log("TRADE", f"[{self.executor.MODE}] {self._cycle_title} "
                          f"{cycle.state.value} — {pairs} pairs, PnL "
                          f"{pnl:+,.2f} USDC ({note})")
        self.tradeExecuted.emit()
        self.strategyStatus.emit(
            f"FLAT — last cycle {cycle.state.value}, PnL {pnl:+,.2f} USDC")
        if isinstance(self.executor, PolyBoxLiveExecutor):
            asyncio.create_task(self._refresh_balance())
        self._finish_cycle()

    async def _watch_settlement(self) -> None:
        cycle = self._cycle
        assert cycle is not None
        prices = await fetch_market_prices(cycle.ticker, self._http)
        # A resolved Polymarket market prices one side at ~$1.00 and the other
        # ~$0.00; until then, keep holding.
        self.straddleStatus.emit(
            f"{self._cycle_title[:32]}: UNHEDGED_HOLD — waiting for resolution")
        if not prices:
            return
        yes_mid = (prices["yes_bid"] + prices["yes_ask"]) / 2.0
        if 3 < yes_mid < 97:
            return  # not resolved yet
        result = "yes" if yes_mid >= 97 else "no"
        held = "YES" if cycle.yes_filled > cycle.no_filled else "NO"
        won = held.lower() == result
        pnl = cycle.settlement_pnl_cents(won) / 100.0
        held_count = max(cycle.yes_filled, cycle.no_filled)
        self._db.add_trade(market=cycle.ticker, side=held, action="SETTLE",
                           price=1.0 if won else 0.0, size=held_count * 1.0,
                           status="FILLED", pnl=pnl)
        self.log("TRADE", f"[{self.executor.MODE}] {self._cycle_title} resolved "
                          f"{result.upper()} — held {held}, PnL {pnl:+,.2f} USDC")
        self.tradeExecuted.emit()
        self._finish_cycle()

    # -------------------------------------------------------------- balance

    async def _balance_loop(self) -> None:
        failed = False
        while True:
            try:
                bal = await self.executor.get_balance()
                if bal is not None:
                    self._last_balance = bal
                    self.liveBalance.emit(bal)
                failed = False
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if not failed:
                    self.log("WARN", f"Balance fetch failed: {e} — retry 10s")
                    failed = True
                await asyncio.sleep(10)

    async def _refresh_balance(self) -> None:
        try:
            bal = await self.executor.get_balance()
            if bal is not None:
                self._last_balance = bal
                self.liveBalance.emit(bal)
        except Exception as e:
            filelog.warning("Balance refresh failed: %s", e)

    # ----------------------------------------------------------- history sync

    async def _authed_client(self) -> tuple[PolymarketClient, bool]:
        """(client, owned) — an authenticated Polymarket client.

        Reuses the live session's client when running; otherwise builds a
        temporary one from saved credentials so the sync works even while the
        bot is STOPPED (it is a read-only account query).
        """
        if self._live is not None:
            return self._live, False
        pk = secret_store.get_secret(secret_store.KEY_PM_PRIVATE)
        funder = secret_store.get_secret(secret_store.KEY_PM_FUNDER)
        if not pk or not funder:
            raise PolymarketError(
                "Add your Polymarket Private Key and Funder Address in "
                "Settings first — they are needed to read your account history."
            )
        sig = int(self._db.get_setting("pm_signature_type", 1))
        client = PolymarketClient(private_key=pk, funder=funder,
                                  signature_type=sig)
        await asyncio.to_thread(client.connect)
        return client, True

    async def sync_fills_from_polymarket(self) -> tuple[int, int]:
        """Import the REAL fill history from Polymarket into the local DB.

        Local rows are written when an order is PLACED, so a restart or a
        missed fill leaves the Trades table out of step with the account. This
        pulls ground truth from the CLOB and adds only new fills (deduped by
        trade id).

        Returns (imported, total seen). Read-only — never places an order.
        """
        client, _owned = await self._authed_client()
        trades = await asyncio.to_thread(client.get_trades)

        imported = 0
        filled_keys: set[tuple[str, str]] = set()
        for t in trades:
            if not isinstance(t, dict):
                t = getattr(t, "__dict__", {}) or {}
            market = str(t.get("market") or t.get("condition_id") or "")
            outcome = str(t.get("outcome") or "").upper() or "?"
            filled_keys.add((market, outcome))

            trade_id = str(t.get("id") or t.get("trade_id") or "")
            if not trade_id:
                continue
            meta = f"poly_fill:{trade_id}"
            if self._db.has_trade_meta(meta):
                continue
            try:
                price = float(t.get("price") or 0.0)
                size = float(t.get("size") or 0.0)
            except (TypeError, ValueError):
                continue
            action = "SELL" if str(t.get("side", "")).upper() == "SELL" else "BUY"
            self._db.add_trade(
                market=market, side=outcome, action=action, price=price,
                size=size * price, status="FILLED", meta=meta,
                ts=_iso_ts(t.get("match_time")),
            )
            imported += 1

        # The exchange is ground truth: hide local "resting" placement rows
        # that real fills have superseded.
        superseded = 0
        for market, side in filled_keys:
            superseded += self._db.supersede_open_trades(market, side)

        # Realized PnL. Unlike Kalshi (which exposes /portfolio/settlements),
        # the Polymarket CLOB has no PnL endpoint — so derive it from the
        # fills: match SELLs against BUYs per market+side at average cost.
        # Without this the Statistics page stays at 0 even after trading.
        closed = self._record_realized_pnl(trades)

        if imported or superseded or closed:
            self.tradeExecuted.emit()
            bits = [f"Synced {imported} new fill(s) from Polymarket "
                    f"({len(trades)} in history)"]
            if superseded:
                bits.append(f"replaced {superseded} placeholder row(s)")
            if closed:
                bits.append(f"recorded PnL for {closed} closed position(s)")
            self.log("INFO", " — ".join(bits))
        else:
            filelog.info("Polymarket sync: already up to date (%d trades in "
                         "history, nothing new)", len(trades))
        await self._refresh_balance()
        return imported, len(trades)

    def _record_realized_pnl(self, trades: list) -> int:
        """Derive realized PnL per market+side from the fills and record it.

        Average-cost method: for each (market, outcome) total the BUY cost and
        the SELL proceeds, then

            realized = sell_proceeds − avg_buy_price × matched_shares

        Only positions with at least one SELL are booked (an open position has
        no realized PnL yet). Idempotent — one row per market+side, updated in
        place on later syncs.
        """
        legs: dict[tuple[str, str], dict[str, float]] = {}
        for t in trades:
            if not isinstance(t, dict):
                t = getattr(t, "__dict__", {}) or {}
            market = str(t.get("market") or t.get("condition_id") or "")
            outcome = str(t.get("outcome") or "").upper() or "?"
            try:
                price = float(t.get("price") or 0.0)
                shares = float(t.get("size") or 0.0)
            except (TypeError, ValueError):
                continue
            if not market or shares <= 0 or price <= 0:
                continue
            leg = legs.setdefault((market, outcome), {
                "buy_shares": 0.0, "buy_cost": 0.0,
                "sell_shares": 0.0, "sell_proceeds": 0.0})
            if str(t.get("side", "")).upper() == "SELL":
                leg["sell_shares"] += shares
                leg["sell_proceeds"] += shares * price
            else:
                leg["buy_shares"] += shares
                leg["buy_cost"] += shares * price

        recorded = 0
        for (market, outcome), leg in legs.items():
            sold, bought = leg["sell_shares"], leg["buy_shares"]
            if sold <= 0 or bought <= 0:
                continue  # still open (or sell-only) — nothing realized yet
            avg_cost = leg["buy_cost"] / bought
            matched = min(sold, bought)
            cost = avg_cost * matched
            proceeds = leg["sell_proceeds"] * (matched / sold)
            pnl = round(proceeds - cost, 4)
            meta = f"poly_realized:{market}:{outcome}"
            if self._db.has_trade_meta(meta):
                self._db.set_trade_pnl_by_meta(meta, pnl, round(cost, 4))
                continue
            self._db.add_trade(
                market=market, side=outcome, action="CLOSE",
                price=round(proceeds / matched, 4), size=round(cost, 4),
                status="FILLED", pnl=pnl, meta=meta,
            )
            recorded += 1
        return recorded

    # ---------------------------------------------------------- persistence

    def _persist_cycle(self) -> None:
        if self._cycle is None:
            self._db.set_setting(STRADDLE_KEY, "")
        else:
            payload = self._cycle.to_dict()
            payload["mode"] = self.executor.MODE
            payload["title"] = self._cycle_title
            self._db.set_setting(STRADDLE_KEY, json.dumps(payload))

    def _finish_cycle(self) -> None:
        self._cycle = None
        self._cycle_ref = None
        self._db.set_setting(STRADDLE_KEY, "")

    def _restore_cycle(self) -> None:
        raw = self._db.get_setting(STRADDLE_KEY, "")
        if not raw:
            return
        try:
            saved = json.loads(raw)
        except (ValueError, TypeError):
            self._db.set_setting(STRADDLE_KEY, "")
            return
        saved_mode = saved.pop("mode", "PAPER")
        self._cycle_title = saved.pop("title", "")
        if saved_mode != self.executor.MODE:
            level = "ERROR" if saved_mode == "LIVE" else "WARN"
            self.log(level, f"A {saved_mode} straddle on {saved.get('ticker')} "
                            f"was left open but the bot is now {self.executor.MODE} "
                            "— manage it on polymarket.com.")
            self._db.set_setting(STRADDLE_KEY, "")
            return
        try:
            self._cycle = StraddleCycle.from_dict(saved, cfg=self._sentinel_config())
        except (KeyError, ValueError, TypeError) as e:
            self.log("WARN", f"Corrupt saved straddle discarded ({e})")
            self._db.set_setting(STRADDLE_KEY, "")
            return
        self._traded.add(self._cycle.ticker)
        self.log("INFO", f"Restored open straddle after restart: "
                         f"{self._cycle_title or self._cycle.ticker} "
                         f"({self._cycle.state.value})")
        if saved_mode == "PAPER":
            asyncio.create_task(self.executor.place_straddle(
                self._cycle.ticker, self._cycle.entry_cents, self._cycle.count))
