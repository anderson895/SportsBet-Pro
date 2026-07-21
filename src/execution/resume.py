"""Position resume pagkatapos ng app restart — pure decision logic.

Ang open position ay naka-persist sa SQLite (db.save_open_position) tuwing
BUY at binubura tuwing SELL. Sa pag-START ng bot, dinedesisyunan dito kung
ire-restore ito sa executor:

- Mas luma sa kasalukuyang PERIOD START -> STALE: settled na ang market
  ng position, huwag i-restore (gumagana sa lahat ng timeframes —
  ang daily ay tanghali-ET anchored, ang 15m/1h/4h ay UTC-aligned)
- Ibang mode        -> huwag i-restore (pero kung LIVE ang naiwan, i-ERROR
                       nang malakas — may totoong pera pang nakalagay doon)
- Same period + mode -> i-restore
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from src.strategy.mean_reversion import Position


def decide_restore(
    saved: Optional[dict], mode: str, period_start: dt.datetime
) -> tuple[Optional[Position], str, str]:
    """Ibinabalik ang (position | None, log_level, log_message).

    Ang `period_start` ay ang simula (UTC) ng KASALUKUYANG market period —
    stale ang anumang position na pumasok bago iyon.

    Kapag None ang position, dapat i-clear ng caller ang saved record
    (maliban kung walang saved talaga — blanko rin ang message doon).
    """
    if not saved:
        return None, "", ""

    try:
        entry_ts = dt.datetime.fromisoformat(saved["entry_ts"])
        position = Position(
            side=saved["side"],
            entry_price=float(saved["entry_price"]),
            shares=float(saved["shares"]),
            entry_ts=entry_ts,
        )
        saved_mode = saved["mode"]
        market = saved.get("market", "?")
    except (KeyError, ValueError, TypeError) as e:
        return None, "WARN", f"Corrupt saved position discarded ({e})"

    if entry_ts < period_start:
        return None, "WARN", (
            f"Stale open position from {entry_ts.isoformat(timespec='minutes')} "
            f"discarded — its market period has already settled ({market})"
        )

    if saved_mode != mode:
        if saved_mode == "LIVE":
            # May TOTOONG position pa sa Polymarket na hindi natin mata-track
            # sa paper mode — ipaalam nang malakas sa user.
            return None, "ERROR", (
                f"A LIVE position is still open on Polymarket ({position.side} "
                f"{position.shares:,.1f} shares @ {position.entry_price:.2f}, "
                f"{market}) but the bot is now in PAPER mode — it cannot be "
                "tracked. Manage it manually on polymarket.com or switch "
                "back to Live mode."
            )
        return None, "WARN", (
            f"Paper position discarded — the bot is now in {mode} mode "
            f"(was PAPER: {position.side} @ {position.entry_price:.2f})"
        )

    return position, "INFO", (
        f"Restored open position after restart: {position.side} "
        f"{position.shares:,.1f} shares @ {position.entry_price:.2f} ({market})"
    )
