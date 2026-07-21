"""Death-trap filters — pure logic, walang I/O.

Mula sa details.txt: "If the volume profile is drastically increasing as
the price extends, it means institutional buyers are stepping in. The
rubber band is breaking, not stretching." — huwag mag-mean-reversion
entry kapag ganito.
"""
from __future__ import annotations

from statistics import fmean


def is_volume_escalating(
    hourly_volumes: list[float],
    recent_hours: int = 3,
    baseline_hours: int = 20,
    spike_mult: float = 2.0,
) -> tuple[bool, str]:
    """Escalating ba ang volume? (recent avg vs baseline avg).

    `hourly_volumes` ay dapat COMPLETED 1h candles, oldest -> newest.
    Returns (escalating, reason).
    """
    need = recent_hours + baseline_hours
    if len(hourly_volumes) < need:
        # Kulang ang data — huwag mag-block (fail-open), pero i-report
        return False, f"insufficient volume data ({len(hourly_volumes)}/{need}h)"

    recent = hourly_volumes[-recent_hours:]
    baseline = hourly_volumes[-need:-recent_hours]
    baseline_avg = fmean(baseline)
    if baseline_avg <= 0:
        return False, "baseline volume is zero"

    ratio = fmean(recent) / baseline_avg
    if ratio >= spike_mult:
        return True, (
            f"volume escalating: last {recent_hours}h avg is {ratio:.1f}x "
            f"the prior {baseline_hours}h baseline (limit {spike_mult:.1f}x) "
            "— momentum day, rubber band is breaking"
        )
    return False, f"volume normal ({ratio:.1f}x baseline)"


def coinbase_premium_pct(coinbase_price: float, binance_price: float) -> float:
    """% na mas mahal (o mas mura, kung negative) ang Coinbase vs Binance."""
    return (coinbase_price - binance_price) / binance_price * 100.0


def is_premium_exploding(
    premium_pct: float,
    stretch_pct: float,
    threshold_pct: float = 0.15,
) -> tuple[bool, str]:
    """Coinbase premium check — direction-aware.

    Mula sa details.txt: kapag ang Coinbase ay significantly mas mataas sa
    Binance, may aggressive US spot buying — huwag tumaya LABAN dito.

    - Stretch pataas (bibili sana ng DOWN) + malaking POSITIVE premium
      = aggressive buying, huwag bumili ng DOWN.
    - Stretch pababa (bibili sana ng UP) + malaking NEGATIVE premium
      (discount) = aggressive selling, huwag bumili ng UP.
    """
    if stretch_pct > 0 and premium_pct >= threshold_pct:
        return True, (
            f"Coinbase premium {premium_pct:+.2f}% >= {threshold_pct:.2f}% "
            "— aggressive US spot buying, do not bet against it"
        )
    if stretch_pct < 0 and premium_pct <= -threshold_pct:
        return True, (
            f"Coinbase discount {premium_pct:+.2f}% <= -{threshold_pct:.2f}% "
            "— aggressive US spot selling, do not bet against it"
        )
    return False, f"Coinbase premium normal ({premium_pct:+.2f}%)"
