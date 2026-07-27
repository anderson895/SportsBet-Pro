# Change Request — Unify BOTH panels on Box Arbitrage (Arbitrage Betting)

_Logged 2026-07-27, per the user's instruction ("ilagay sa .md file ang
pinapaayos ko para hindi mo makalimutan")._

## The correct direction (what the user actually wants)

**Both panels must run the SAME strategy: Box Arbitrage / "Arbitrage Betting"
(the Internal Straddle) — NOT mean reversion.**

| Panel | Strategy (TARGET) | Markets |
|---|---|---|
| **Polymarket** | **Box Arbitrage** (arbitrage betting) | 50/50 binary markets |
| **Kalshi** | **Box Arbitrage** (arbitrage betting) | 50/50 sports moneylines |

- **Kalshi** should stay the ORIGINAL box-arbitrage straddle (the v1.0.0 sports
  version the user confirmed is correct — screenshot: "Internal Straddle (Box
  Arb)", "Kalshi Sports 50/50").
- **Polymarket** must be CHANGED from Mean Reversion ("Rubber Band") to the
  SAME **Box Arbitrage** strategy — buy YES + NO of a ~50/50 binary market for a
  combined price < $1.00, guaranteed payout $1.00, with a Hedge Sentinel for
  single-sided fills.

## What went wrong (must be undone)

- In **v1.4.0** I mistakenly did the OPPOSITE: I converted the **Kalshi** panel
  to Mean Reversion (to match Polymarket) and deleted the box-arbitrage code.
- That was backwards. The user wants the box-arbitrage strategy on **both**
  panels, and Polymarket switched to box arbitrage.

## Required work

1. **Restore Kalshi Box Arbitrage** — recover the deleted straddle
   implementation and revert the Kalshi mean-reversion rewrite:
   - `src/strategy/straddle.py`, `src/execution/kalshi_paper.py`,
     `src/execution/kalshi_live.py` (straddle version), `src/core/engine_kalshi.py`
     (straddle version), `src/ui/kalshi_dashboard.py` (sports cards),
     `src/ui/kalshi_settings.py` (straddle knobs), `src/ui/kalshi_cards.py`,
     `src/ui/kalshi_chart.py`, and the straddle tests.
   - **Recoverable from git commit `03702a9`** (state right before v1.4.0).
   - Also revert `kalshi_client.create_order` to its box-arb form.
2. **Build Polymarket Box Arbitrage** — a NEW box-arbitrage engine + executor
   + dashboard + settings for the **Polymarket** panel (mirror the Kalshi box-arb
   design), replacing the mean-reversion Polymarket strategy.
   - Polymarket binary markets have YES/NO outcome tokens on the CLOB; buying
     both under $1.00 is the same box-arb lock. Needs a Polymarket market
     scanner for liquid ~50/50 markets + a Hedge Sentinel.
3. **Keep the dual-panel shell** — two independent panels (Polymarket + Kalshi),
   each with its own START/STOP, settings, balance, trades, statistics, logs
   (this part is already correct and stays).
4. **Docs + version** — update README strategy table + What's New; bump version
   (supersede v1.4.0 with a version that documents both panels = box arbitrage).

## Decisions (confirmed 2026-07-27)

- **Polymarket markets for box arb:** **Sports 50/50 markets** (mirror Kalshi —
  NBA/NFL/MLB moneylines). Both panels scan the same kind of market, different
  venue.
- **Versioning:** ship a new **v1.5.0**, and **DELETE the wrong v1.4.0** GitHub
  release + tag.

## Efficient approach (reuse, not long coding)

- **Kalshi:** fast **git recovery** from `03702a9` — restore the deleted box-arb
  files and revert the Kalshi mean-reversion rewrite. No new code.
- **Polymarket box arb:** port the recovered Kalshi box-arb design to Polymarket,
  reusing:
  - `strategy/straddle.py` — pure box-arb logic, already exchange-agnostic.
  - the box-arb `engine_kalshi.py` as the blueprint for a box-arb `engine_poly`.
  - the existing `execution/polymarket.py` CLOB client (add buy-YES + buy-NO +
    orderbook reads) and a Polymarket Gamma-API sports-market scanner.
  - a Polymarket-branded sports dashboard mirroring the Kalshi cards view.
- Keep the dual-panel shell, Clear Trades button, and DB scoping (already good).

## Progress

- ✅ **Kalshi box-arb restored** from git `03702a9` (247 tests green); Clear
  Trades feature preserved.
- ✅ **Polymarket box-arb feasibility verified** — Gamma API returns binary
  markets with Yes/No outcomes, prices, bestBid/bestAsk, clobTokenIds, volume.
  Box arb works the same way: find ~50/50 markets where YES_ask + NO_ask < $1.
- ✅ **DONE — both panels ship as Box Arbitrage (v1.5.0 released).**
- ✅ **Polymarket dashboard display fix** — the reused Kalshi sports-card view
  dropped Polymarket markets (they aren't team matchups → "No candidate games").
  Added `group_markets_flat` (one card per binary market, Yes/No outcomes) and a
  `flat_markets` mode; relabelled "Live Sports Markets" → "Live Markets".
  Verified: Polymarket markets now render, READY 50/50 featured first.

## Polymarket box-arb build plan (files)

Reuse `strategy/straddle.py` (pure logic) unchanged. New venue glue, modeled
1:1 on the Kalshi box-arb files:

- `execution/poly_box.py` — Gamma sports-market scanner → `MarketCandidate`s;
  wraps the existing `polymarket.PolymarketClient` (CLOB) for YES/NO orderbook,
  order placement, fills, balance. Plus `PolyBoxPaperExecutor` /
  `PolyBoxLiveExecutor` (mirror `kalshi_paper` / `kalshi_live`).
- `core/engine_poly_box.py` — box-arb engine (mirror `engine_kalshi.py`),
  scan → place YES+NO → monitor → Hedge Sentinel → record.
- `ui/poly_box_dashboard.py` + `ui/poly_box_settings.py` — sports-cards
  dashboard + box-arb settings with Polymarket creds (mirror the Kalshi UI).
- Wire the **Polymarket panel** to the box-arb engine (replace mean reversion);
  keep `poly_cards` reusing `kalshi_cards.GameCard`.
- ⚠️ Polymarket live box-arb orders (like Kalshi live) can't be fully verified
  without funds — Paper mode fully works.

## Notes / context

- This `sports-betting-bot` is a NEW/separate project from the "first bot"
  (`PolyTradeMonitoring`). Do not conflate them.
- The reference strategy source is
  `reference/High-Yield Kalshi Trading Strategies …` (the Internal Straddle /
  Box Arbitrage sections).
- ⚠️ Security still outstanding: revoke the RSA key exposed in `sportsbet.txt`.
