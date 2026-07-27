"""Internal Straddle / Box Arbitrage strategy para sa Kalshi — pure logic.

Mula sa reference PDF (High-Yield Kalshi Trading Strategies):
- Maghanap ng high-liquidity ~50/50 sports market (NBA/NFL/MLB moneyline)
- Maglagay ng RESTING limit BUY YES @ 49¢ AT BUY NO @ 49¢ (post-only makers)
- Dahil binary ang market, ang isa ay siguradong magse-settle sa $1.00 —
  guaranteed na ~+1.1% per cycle pagkatapos ng fees
- HEDGE SENTINEL: kapag isang side lang ang na-fill sa loob ng timeout
  (o tumakbo na ang presyo), kanselahin ang lagging order at kunin ang
  kabilang side hanggang 51¢ para ma-lock ang "scratch" (100¢ cost sa
  100¢ payout) — hindi tayo kailanman maiiwang may directional sports bet

Lahat ng presyo dito ay CENTS (integer 1-99) tulad ng Kalshi API.
Walang I/O ang module na ito — fully unit-testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Kalshi general fee formula: fee = ceil(0.07 * C * P * (1-P)) per order
# (taker). Ang MAKER fee ay 0.0175 coefficient at sa select series lamang;
# ginagamit natin ang mas konserbatibong maker coefficient bilang default
# para sa profit estimates — kung 0 pala ang maker fee sa sports, mas
# malaki ang tubo, hindi mas maliit.
MAKER_FEE_COEF = 0.0175
TAKER_FEE_COEF = 0.07


def fee_cents(count: int, price_cents: int, coef: float = MAKER_FEE_COEF) -> int:
    """Kalshi trading fee sa CENTS para sa isang order, rounded UP.

    fee = ceil(coef * C * P * (1-P)), P sa dollars.
    Hal. 100 contracts @ 49¢ maker: 0.0175*100*0.49*0.51 = $0.437 -> 44¢.
    """
    p = price_cents / 100.0
    fee_dollars = coef * count * p * (1.0 - p)
    return math.ceil(fee_dollars * 100.0)


def straddle_sizing(risk_usd: float, yes_cents: int, no_cents: int) -> int:
    """Ilang contract PAIRS ang kaya ng risk budget (kasama ang fees)."""
    pair_cost_cents = yes_cents + no_cents
    if pair_cost_cents <= 0:
        return 0
    budget_cents = int(risk_usd * 100)
    count = budget_cents // pair_cost_cents
    # Ibawas ang fees sa budget — bawasan ang count hanggang kasya
    while count > 0:
        total = (count * pair_cost_cents
                 + fee_cents(count, yes_cents) + fee_cents(count, no_cents))
        if total <= budget_cents:
            break
        count -= 1
    return count


def locked_pnl_cents(count: int, yes_cents: int, no_cents: int) -> int:
    """PnL sa CENTS kapag pareho nang filled (guaranteed $1.00/pair payout)."""
    payout = count * 100
    cost = count * (yes_cents + no_cents)
    fees = fee_cents(count, yes_cents) + fee_cents(count, no_cents)
    return payout - cost - fees


@dataclass(frozen=True)
class MarketCandidate:
    """Isang na-scan na Kalshi market na pwedeng straddle-an."""
    ticker: str
    title: str
    yes_bid: int          # cents
    yes_ask: int
    no_bid: int
    no_ask: int
    volume: int           # contracts traded
    close_ts: float       # unix secs ng expected close/expiration
    open_interest: int = 0


@dataclass(frozen=True)
class ScanConfig:
    min_entry_cents: int = 48       # parehong side dapat nasa band na ito
    max_entry_cents: int = 52
    entry_price_cents: int = 49     # ang resting bid natin per side
    min_volume: int = 5000          # contracts — liquidity gate
    min_secs_to_close: float = 45 * 60    # iwasan ang malapit nang matapos
    max_secs_to_close: float = 12 * 3600  # iwasan din ang sobrang aga


def is_candidate(
    m: MarketCandidate, now_ts: float, cfg: ScanConfig = ScanConfig()
) -> tuple[bool, str]:
    """Pasok ba ang market sa straddle criteria? Returns (ok, reason)."""
    if m.volume < cfg.min_volume:
        return False, f"volume {m.volume:,} < {cfg.min_volume:,} minimum"
    secs_left = m.close_ts - now_ts
    if secs_left < cfg.min_secs_to_close:
        return False, (f"closes in {secs_left / 60:.0f}min — too close, "
                       "late-game risk")
    if secs_left > cfg.max_secs_to_close:
        return False, f"closes in {secs_left / 3600:.1f}h — too far out"
    # Ang 50/50 check: ang MID ng bawat side ay dapat nasa entry band.
    # (yes_ask ang babayaran ng taker; ang resting bid natin ay 49 —
    #  makatotohanang ma-fill lang kung ang market ay talagang ~50/50)
    for side, bid, ask in (("YES", m.yes_bid, m.yes_ask),
                           ("NO", m.no_bid, m.no_ask)):
        if bid <= 0 or ask <= 0:
            return False, f"{side} book empty"
        mid = (bid + ask) / 2.0
        if not (cfg.min_entry_cents <= mid <= cfg.max_entry_cents):
            return False, (f"{side} mid {mid:.1f}¢ outside "
                           f"{cfg.min_entry_cents}-{cfg.max_entry_cents}¢ band")
    return True, "50/50 band, liquid, in time window"


def rank_candidates(
    markets: list[MarketCandidate], now_ts: float,
    cfg: ScanConfig = ScanConfig(),
) -> list[MarketCandidate]:
    """I-filter at i-rank (pinaka-liquid muna) ang mga scan results."""
    ok = [m for m in markets if is_candidate(m, now_ts, cfg)[0]]
    return sorted(ok, key=lambda m: (-m.volume, m.close_ts))


# ------------------------------------------------------------ state machine


class CycleState(Enum):
    RESTING_BOTH = "RESTING_BOTH"    # dalawang resting order, walang fill
    ONE_FILLED = "ONE_FILLED"        # isang side na-fill — sentinel timer on
    HEDGING = "HEDGING"              # kinansela ang lagging, kumukuha ng hedge
    LOCKED = "LOCKED"                # parehong filled @ entry — arb locked
    HEDGED = "HEDGED"                # scratch locked via sentinel (~breakeven)
    UNHEDGED_HOLD = "UNHEDGED_HOLD"  # hedge failed — hawak hanggang settlement
    CANCELLED = "CANCELLED"          # walang na-fill, kinansela pareho


@dataclass(frozen=True)
class SentinelConfig:
    hedge_timeout_secs: float = 90.0   # ONE_FILLED nang ganito katagal -> hedge
    hedge_max_price_cents: int = 51    # max na babayaran para sa hedge side
    hedge_retries: int = 3             # ilang polls susubukan ang hedge
    stale_cancel_secs: float = 15 * 60  # RESTING_BOTH nang walang fill -> cancel


@dataclass(frozen=True)
class CycleDecision:
    """Ano ang dapat gawin ng engine ngayong tick."""
    action: str          # 'WAIT' | 'HEDGE' | 'CANCEL_ALL' | 'DONE' | 'GIVE_UP'
    reason: str = ""


@dataclass
class StraddleCycle:
    """Pure state machine ng isang straddle attempt.

    Ang engine ang nagpapakain ng fill counts + orasan; ang cycle ang
    nagdedesisyon. Walang I/O dito para direct na ma-unit-test ang lahat
    ng transitions (kasama ang Hedge Sentinel).
    """
    ticker: str
    count: int                       # target contracts per side
    entry_cents: int                 # resting price ng bawat side (49)
    started_ts: float                # kailan nailagay ang orders
    cfg: SentinelConfig = field(default_factory=SentinelConfig)

    state: CycleState = CycleState.RESTING_BOTH
    yes_filled: int = 0
    no_filled: int = 0
    one_filled_ts: Optional[float] = None   # kailan nag-simula ang mismatch
    hedge_attempts: int = 0
    hedge_price_cents: Optional[int] = None  # presyo ng na-execute na hedge

    # ------------------------------------------------------------------ API

    @property
    def lagging_side(self) -> Optional[str]:
        """Aling side ang kulang pa (kailangan i-hedge/i-cancel)."""
        if self.yes_filled > self.no_filled:
            return "NO"
        if self.no_filled > self.yes_filled:
            return "YES"
        return None

    def on_tick(
        self, now_ts: float, yes_filled: int, no_filled: int,
        lagging_ask_cents: Optional[int] = None,
    ) -> CycleDecision:
        """Isang polling tick: i-update ang fills, magdesisyon.

        `lagging_ask_cents` = kasalukuyang best ask ng side na kulang pa
        (para sa price-drift trigger ng sentinel); None kung di alam.
        """
        self.yes_filled = yes_filled
        self.no_filled = no_filled

        if self.state in (CycleState.LOCKED, CycleState.HEDGED,
                          CycleState.UNHEDGED_HOLD, CycleState.CANCELLED):
            return CycleDecision("DONE", f"cycle already {self.state.value}")

        # --- parehong buo na ---------------------------------------------
        if yes_filled >= self.count and no_filled >= self.count:
            if self.state is CycleState.HEDGING:
                # Ang pang-kumpleto ay ang HEDGE taker order (hanggang 51¢),
                # hindi ang 49¢ resting order — scratch ito, hindi full arb.
                # Kung hindi pa naitala ng engine ang aktwal na hedge price,
                # gamitin ang max bilang konserbatibong assumption.
                if self.hedge_price_cents is None:
                    self.hedge_price_cents = self.cfg.hedge_max_price_cents
                self.state = CycleState.HEDGED
                return CycleDecision(
                    "DONE",
                    f"hedge filled @ ≤{self.hedge_price_cents}¢ — "
                    "scratch locked",
                )
            self.state = CycleState.LOCKED
            return CycleDecision(
                "DONE",
                f"both sides filled @ {self.entry_cents}¢ — arbitrage locked",
            )

        mismatch = yes_filled != no_filled

        if self.state is CycleState.RESTING_BOTH:
            if mismatch:
                self.state = CycleState.ONE_FILLED
                self.one_filled_ts = now_ts
                return CycleDecision("WAIT", "one side filling — sentinel armed")
            if now_ts - self.started_ts >= self.cfg.stale_cancel_secs:
                self.state = CycleState.CANCELLED
                return CycleDecision(
                    "CANCEL_ALL",
                    f"no fills after {self.cfg.stale_cancel_secs / 60:.0f}min "
                    "— market drifted, cancelling both orders",
                )
            return CycleDecision("WAIT", "resting orders working")

        if self.state is CycleState.ONE_FILLED:
            if not mismatch:
                # Naka-catch up ang lagging side (partial fills equalized)
                self.state = CycleState.RESTING_BOTH
                self.one_filled_ts = None
                return CycleDecision("WAIT", "fills equalized — resting again")

            elapsed = now_ts - (self.one_filled_ts or now_ts)
            timed_out = elapsed >= self.cfg.hedge_timeout_secs
            price_ran = (
                lagging_ask_cents is not None
                and lagging_ask_cents > self.cfg.hedge_max_price_cents
            )
            if timed_out or price_ran:
                self.state = CycleState.HEDGING
                why = (f"single-sided for {elapsed:.0f}s"
                       if timed_out else
                       f"lagging ask ran to {lagging_ask_cents}¢")
                return CycleDecision(
                    "HEDGE",
                    f"HEDGE SENTINEL: {why} — cancel lagging order, take "
                    f"{self.lagging_side} up to "
                    f"{self.cfg.hedge_max_price_cents}¢",
                )
            return CycleDecision(
                "WAIT",
                f"single-sided {elapsed:.0f}s / "
                f"{self.cfg.hedge_timeout_secs:.0f}s before hedge",
            )

        if self.state is CycleState.HEDGING:
            if not mismatch:
                if self.hedge_price_cents is None:
                    self.hedge_price_cents = self.cfg.hedge_max_price_cents
                self.state = CycleState.HEDGED
                return CycleDecision("DONE", "hedge filled — scratch locked")
            self.hedge_attempts += 1
            if self.hedge_attempts >= self.cfg.hedge_retries:
                self.state = CycleState.UNHEDGED_HOLD
                return CycleDecision(
                    "GIVE_UP",
                    f"hedge unfilled after {self.hedge_attempts} attempts — "
                    "holding single side to settlement (max loss = entry cost)",
                )
            return CycleDecision(
                "HEDGE",
                f"hedge attempt {self.hedge_attempts + 1}/"
                f"{self.cfg.hedge_retries}",
            )

        return CycleDecision("WAIT", self.state.value)  # pragma: no cover

    def mark_hedged(self, hedge_price_cents: int) -> None:
        """Tawagin kapag na-fill ang hedge taker order."""
        self.hedge_price_cents = hedge_price_cents
        self.state = CycleState.HEDGED

    # ------------------------------------------------------------------ PnL

    def realized_pnl_cents(self) -> Optional[int]:
        """PnL sa cents kapag tapos na ang cycle; None kung hindi pa final.

        - LOCKED : count * (100 - 2*entry) - fees
        - HEDGED : matched pairs sa (entry + hedge_price) cost
        - CANCELLED : 0
        - UNHEDGED_HOLD : hindi pa alam (settlement ang magpapasya)
        """
        if self.state is CycleState.LOCKED:
            return locked_pnl_cents(self.count, self.entry_cents, self.entry_cents)
        if self.state is CycleState.HEDGED and self.hedge_price_cents is not None:
            pairs = min(self.yes_filled, self.no_filled)
            payout = pairs * 100
            cost = pairs * (self.entry_cents + self.hedge_price_cents)
            fees = (fee_cents(pairs, self.entry_cents)
                    + fee_cents(pairs, self.hedge_price_cents, TAKER_FEE_COEF))
            return payout - cost - fees
        if self.state is CycleState.CANCELLED:
            return 0
        return None

    def settlement_pnl_cents(self, won: bool) -> int:
        """PnL ng UNHEDGED_HOLD position pagkatapos ng settlement."""
        held = max(self.yes_filled, self.no_filled)
        cost = held * self.entry_cents + fee_cents(held, self.entry_cents)
        payout = held * 100 if won else 0
        return payout - cost

    # ----------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "count": self.count,
            "entry_cents": self.entry_cents,
            "started_ts": self.started_ts,
            "state": self.state.value,
            "yes_filled": self.yes_filled,
            "no_filled": self.no_filled,
            "one_filled_ts": self.one_filled_ts,
            "hedge_attempts": self.hedge_attempts,
            "hedge_price_cents": self.hedge_price_cents,
        }

    @classmethod
    def from_dict(cls, d: dict, cfg: SentinelConfig | None = None) -> "StraddleCycle":
        cycle = cls(
            ticker=d["ticker"],
            count=int(d["count"]),
            entry_cents=int(d["entry_cents"]),
            started_ts=float(d["started_ts"]),
            cfg=cfg or SentinelConfig(),
        )
        cycle.state = CycleState(d.get("state", "RESTING_BOTH"))
        cycle.yes_filled = int(d.get("yes_filled", 0))
        cycle.no_filled = int(d.get("no_filled", 0))
        raw_ts = d.get("one_filled_ts")
        cycle.one_filled_ts = float(raw_ts) if raw_ts is not None else None
        cycle.hedge_attempts = int(d.get("hedge_attempts", 0))
        raw_hp = d.get("hedge_price_cents")
        cycle.hedge_price_cents = int(raw_hp) if raw_hp is not None else None
        return cycle
