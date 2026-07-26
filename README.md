# SportsBet Pro — Dual-Panel Trading Bot (Polymarket + Kalshi)

A Windows desktop trading bot with **two independent panels**, each with its
own ON/OFF (START/STOP) button, settings, balance, trades, statistics, and logs.
Both can run at the same time.

| Panel | Strategy | Markets | Currency |
|---|---|---|---|
| **Polymarket** | Mean Reversion ("Rubber Band") | Daily / 4h / 1h / 15m BTC Up/Down | USDC (Polygon) |
| **Kalshi** | Internal Straddle / Box Arbitrage | 50/50 sports moneylines (NBA/NFL/MLB…) | USD |

---

## 🆕 What's New in v1.3.4

The v1.3.x releases focused on the Kalshi live path, correctness, and polish:

- **Wider default scan filters** (v1.3.4) — a higher fill rate without touching
  the **49¢ entry** that preserves the box-arb edge: min volume **3000**, skip
  markets closing sooner than **30 min** / later than **24 h**
- **Correct Polymarket trade details** (v1.3.3) — the trade drill-down now shows
  a **directional** summary (side UP/DOWN, avg entry, cost, net PnL) instead of
  the Kalshi YES/NO straddle template
- **Windows taskbar icon** (v1.3.2) — an explicit AppUserModelID so the app icon
  shows on the taskbar
- **Orphaned-order cleanup on startup** (v1.3.1) — if the app restarts while a
  live straddle is resting, leftover exchange orders are reconciled and
  cancelled on the next START (no untracked real-money exposure)
- **Realized PnL from settlements** (v1.3.0) — Kalshi settlement history is
  imported so closed straddles show their true profit/loss in Trades and
  Statistics; plus a live-market loading state, quieter sync logs, and
  **date + 12-hour AM/PM** trade timestamps

Earlier, **v1.1.0** reworked the Kalshi panel into a **Kalshi.com-style market
view**: live game cards grouped by matchup (team names, sport icons, win %,
volume), a featured-market carousel (`‹ N of M ›` or click any card), team +
matchup search across the whole scanned set, up to **14 sports series**, and an
always-on market feed that stays live even while **STOPPED**.

> **Scope note:** the Kalshi panel intentionally shows only tradeable **binary
> 50/50 sports games**. Multi-outcome prediction markets (e.g. "LeBron's Next
> Team", elections) are not shown — the box-arbitrage strategy only applies to
> two-outcome games.

Releases: **[v1.3.4 (latest)](https://github.com/anderson895/SportsBet-Pro/releases/tag/v1.3.4)**
· [all releases](https://github.com/anderson895/SportsBet-Pro/releases)

---

## 📌 Progress / Status

### Development Phases — all complete ✅
- [x] **Phase 1: Skeleton** — verbatim reuse, `ScopedDatabase`, dual-panel UI shell, stub engines
- [x] **Phase 2: Polymarket port** — feed / strategy / execution, `PolyEngine`, dashboard + settings, ported tests
- [x] **Phase 3: Kalshi paper** — client, straddle math + state machine, `KalshiEngine`, Kalshi UI, tests
- [x] **Phase 4: Kalshi live** — RSA-PSS auth **validated against the real Kalshi production API** (credential check returns balance)
- [x] **Phase 5: Packaging** — PyInstaller build shipped as `SportsBetPro.exe` (see Releases)

### ✅ Done & verified working
- **App shell** — top exchange switcher (Polymarket / Kalshi), a shared top page
  nav (Dashboard / Settings / Logs / Trades / Statistics / About), per-panel
  START/STOP + uptime, per-exchange accent theme (indigo for Polymarket, mint
  for Kalshi); both bots run independently and concurrently
- **Polymarket panel** — full PolyTradePro port: live BTC chart (line + candles),
  "Price to beat" 12PM-ET strike, mean reversion strategy, death-trap filters,
  paper + live modes, position resume; existing Windows Credential Manager
  credentials carry over
- **Kalshi panel** — always-on market feed (live game cards + probability chart
  even while STOPPED), scanner that groups markets into Kalshi.com-style game
  cards, straddle placement (verified: 101 pairs @ 49¢ on a live MLB game),
  Hedge Sentinel state machine (observed firing on a real 50/50 market),
  settlement tracking, paper balance accounting
- **Kalshi live auth** — RSA-PSS SHA256 request signing validated against the
  real production server; PEM auto-saved to `data/kalshi_key.pem` when it
  exceeds the Windows Credential Manager blob size limit
- **Kalshi 2026 API** — adapted to dollar-string fields (`yes_bid_dollars`,
  `volume_fp`) and `orderbook_fp` (`yes_dollars` / `no_dollars` levels);
  still backwards-compatible with the older integer-cents format
- **Tests** — 247 passing (ported Polymarket suite + Kalshi tests: straddle
  math, hedge sentinel, RSA-PSS signing, paper fills, settlement PnL import,
  startup order reconcile, trade-detail rendering, DB scoping, DoH)
- **DoH resolver** — covers `polymarket.com`, `kalshi.com`, `kalshi.co`

### ✅ Live path exercised
- **Kalshi live orders** — funded production account; live straddles have been
  placed, filled, and settled, with realized PnL imported from the exchange's
  settlement history. The observed bottleneck is **fill rate**, not correctness:
  the 49¢ maker orders fill only on genuinely 50/50 markets, so completed cycles
  are rare (widen the scan filters in Settings to cast a broader net).
- **PyInstaller packaging** — shipped as `SportsBetPro.exe` (see Releases);
  `build.bat` / `SportsBetPro.spec` rebuild it.

### 🔜 Next steps
1. **Fill-rate tuning** — the box-arb edge is proven per cycle (~+1.15%), but
   entire days can pass with no fills. Widen the scan net in Settings (volume,
   time-to-close window) and observe the fill rate before scaling risk.
2. **Optional code signing** — the `.exe` is unsigned, so Windows SmartScreen
   warns on first run ("More info → Run anyway"). An OV/EV certificate would
   remove the warning for distribution.

---

# 📖 Strategy Documentation

This bot implements two independent, well-defined strategies — one per panel.
Both are mechanical (rule-based), fully unit-tested as pure functions, and run
in Paper mode by default.

---

## Strategy 1 — Polymarket: Mean Reversion ("Rubber Band")

Ported from the PolyTradePro project. It trades Polymarket's **daily BTC
Up/Down** markets (and 4h/1h/15m variants).

### The idea
Think of BTC's price as a rubber band anchored to the daily open (the "Price
to Beat"). The further price stretches from that anchor without fundamental
news, the higher the statistical probability it snaps back before the day
ends — over 90% of daily candles have wicks on **both** ends. When retail
panics into the winning side, the losing side's shares get cheap (15¢–25¢),
which is where the edge lives.

### Data feed
- **Binance** WebSocket — read-only BTCUSDT price + 1m klines (no API key
  needed for public market data)
- **Coinbase** spot — for the premium death-trap filter
- The daily market's strike is anchored to the **12:00 PM ET** settlement
  (not 00:00 UTC), matching Polymarket's real settlement rule (DST-aware)

### Entry rules
1. Wait for the **4–12h window** after the period open (skip the opening
   volatility)
2. Look for a **1.5%–2.5% stretch** from the open
   (>2.5% = possible momentum-expansion day → skip)
3. The out-of-the-money share must be priced **15¢–25¢**
4. Buy the mean-reversion side (DOWN if pumped, UP if dumped)
5. **One trade per market period**

### Exit rules
- **Take profit:** +100% of entry price (e.g., 20¢ → 40¢) — you're trading the
  probability shift, not holding to settlement
- **Stop loss:** −50% of entry
- **End-of-period force exit** before settlement — never hold to the close

### Death-trap filters (when to NOT trade)
Mean reversion fails on momentum-expansion days. Three guards veto entries:
1. **Volume escalation** — if recent hourly volume ≥ 2× the baseline,
   institutions are stepping in (the rubber band is breaking, not stretching)
2. **Coinbase premium** — if the US-exchange (Coinbase) price is running
   significantly above/below Binance in the trade's direction, aggressive spot
   flow is present → do not fade it
3. **Economic Data Day** — a manual toggle to block entries on Fed/CPI days
   (structural trend days, not mean-reversion days)

### Timeframe scaling
Daily-calibrated parameters auto-scale to 4h/1h/15m markets: time windows scale
by period fraction; stretch thresholds scale by √(time) (e.g., the 1.5% daily
entry stretch becomes ~0.31% on 1-hour markets).

---

## Strategy 2 — Kalshi: Internal Straddle / Box Arbitrage

From the reference research (`reference/High-Yield Kalshi Trading Strategies`).
This is a **delta-neutral, market-neutral** strategy — the bot does **not**
care who wins the game.

### The idea
Kalshi is a binary exchange: every market settles to exactly **$1.00** for the
winning side and **$0.00** for the losing side. On a high-liquidity **~50/50**
sports market, if you buy **both** YES and NO for a combined price below $1.00,
you are guaranteed a profit at settlement regardless of the outcome.

### Execution
The bot places two **post-only resting limit BUY** orders on the same market:

```
BUY YES @ 49¢   +   BUY NO @ 49¢     →   pair cost = 98¢
one side settles at $1.00            →   payout    = 100¢
```

- **`post_only` is essential** — it forces maker orders. If they would cross
  immediately (become taker), Kalshi rejects them. Taker fees would make the
  strategy unprofitable.
- Contract count = `floor(risk_usd / 0.98)`

### The fee math
Kalshi's fee per order (rounded **up** to the next cent):

```
fee = ceil( 0.0175 · C · P · (1 − P) )        [C = contracts, P = price in $]

Per leg @ 49¢:   0.0175 · 0.49 · 0.51 ≈ $0.0044/contract
Round-trip pair: ≈ $0.0088
Net profit/pair: 100¢ − 98¢ − 0.88¢ ≈ +1.13¢   →  ~+1.15% per completed cycle
```

During Kalshi's 0% maker-fee promotional windows, the edge rises to ~+2%.

### The Hedge Sentinel (single-sided-fill protection)
The one real risk is **execution risk** — one leg fills (say YES @ 49¢) but the
market moves before the NO leg fills, leaving a directional bet. A pure state
machine (`strategy/straddle.py`) guards against this:

```
RESTING_BOTH → ONE_FILLED(t0) → LOCKED                    (both filled — arb locked)
                              ↘ HEDGING → HEDGED           (scratch locked ≈ breakeven)
                                       ↘ UNHEDGED_HOLD     (hedge failed — held to settlement)
             → CANCELLED                                   (no fills — market drifted)
```

The Sentinel fires when a single side has been filled for longer than the
**timeout** (default 90s) **or** the unfilled side's ask runs above the
**hedge cap** (default 51¢). It then cancels the lagging resting order and
places an aggressive crossing BUY (taker) on the missing side up to 51¢:

- **Hedge fills** → `HEDGED`: pair cost ≤ 49¢ + 51¢ = 100¢ for a 100¢ payout →
  loss ≈ fees only (a "scratch")
- **Hedge can't fill** after N retries → `UNHEDGED_HOLD`: the bot holds the
  single side to settlement (worst case −49¢/contract) and records the final
  PnL when the game resolves

### Risk profile
- **Structural risk: ~0%** — you own both sides of a binary market
- **Real-world risk: ~1–2% max** — bounded by the Hedge Sentinel's scratch cost
  or a rare unhedged hold. This is the ~2% figure from the reference backtest.

### Market selection
The scanner discovers live sports **series** (baseball, basketball, football,
hockey, soccer, and more — up to 14) and filters for markets where both YES and
NO mids sit inside the **48–52¢ band**, with sufficient **volume** and a sane
**time-to-close** window (avoids late-game markets that move violently).
Genuine 49/49 markets are rare, so the scanner may sit idle — that is by design,
not a bug.

> **Reference backtest (from the PDF):** starting $2,000, box arbitrage on the
> sports genre, ~15 turnovers/month at +1.14%/cycle compounded to ~$15,975 over
> 12 months (+698.8%) in the 100%-compounding model. Real results depend on
> fill quality and available 50/50 liquidity; this bot's Paper mode lets you
> observe the actual fill rate before risking capital.

---

## Running from source

```powershell
python -m venv venv          # Python 3.13 (NOT 3.10.0 — CPython bug bpo-45757)
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m src.main    # or double-click run.bat
```

Requirements: Windows 10/11, an internet connection.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests -v
```

| Test file | Coverage |
|---|---|
| `test_mean_reversion.py`, `test_timeframes.py`, `test_filters.py`, `test_polymarket.py`, `test_paper_e2e.py`, `test_resume.py` | Full Polymarket side (ported, proven suite) |
| `test_straddle_math.py` | Kalshi fees (ceil per order), pair PnL @49/49, scratch @49+51, sizing, candidate filter |
| `test_hedge_sentinel.py` | `StraddleCycle` state machine — all transitions incl. sentinel triggers and restart persistence |
| `test_kalshi_auth.py` | RSA-PSS SHA256 signing (in-test keypair, verified with the public key) |
| `test_kalshi_paper.py` | Simulated fills from canned orderbook snapshots |
| `test_db_scoping.py` | Isolation of the two exchanges in a single `bot.db` |
| `test_netdns.py` | DoH resolver (polymarket.com + kalshi.com override) |

## Live Mode Setup

### Polymarket (identical to PolyTradePro)
Settings → Trading Mode: Live → Private Key + Funder Address + Wallet Type →
Save. Credentials are verified automatically and the balance is shown. Existing
credentials in Windows Credential Manager carry over (same service name).

### Kalshi
1. kalshi.com (or demo.kalshi.co) → Account Settings → **API Keys** → create a
   key. You get an **API Key ID** and an **RSA private key (.pem)** file.
2. Kalshi panel → Settings → Trading Mode: **Live**
3. Paste the API Key ID; paste the full PEM text **or** enter the .pem file path.
4. Environment: use **Demo** (demo.kalshi.co, practice money) before Production.
5. Save Settings → credentials are verified via `GET /portfolio/balance`.
6. START BOT — it auto-discovers sports series tickers on first run (editable
   in Settings).

> **Paper mode first.** Kalshi paper mode uses **real public market data** with
> simulated fills, so the full scanner + Hedge Sentinel are exercised with no
> real money.

> **Note on secrets:** the API Key ID is stored in Windows Credential Manager.
> A large RSA key that exceeds its size limit is written to
> `data\kalshi_key.pem` (gitignored) instead — this is the standard Kalshi
> `.pem` approach.

## Building the Executable

```powershell
.\venv\Scripts\python.exe -m PyInstaller --noconfirm SportsBetPro.spec
```

Output: `dist/SportsBetPro/`. Same build gotchas as the reference project:
`--collect-submodules finplot` (already in the spec), uninstall PyQt6 from the
build venv, and do not build with Python 3.10.0.

## Troubleshooting

| Problem | Solution |
|---|---|
| Polymarket/Kalshi card shows Disconnected | A built-in DoH resolver (`src/core/netdns.py`) bypasses ISP DNS poisoning of `*.polymarket.com` and `*.kalshi.com` |
| App won't open | Run from a terminal to see the error: `.\venv\Scripts\python.exe -m src.main` |
| Runtime errors | Check **`data\app.log`** — every error has a full traceback |
| Kalshi scanner finds nothing | Normal — exact 49/49 markets are rare. Widen the band or lower the volume threshold in Settings, or wait for game nights |
| `UNHEDGED_HOLD` alert | The hedge couldn't fill — one side is held to settlement (max loss = entry cost). The bot watches for settlement and records the PnL |

## Disclaimer

This software places real-money trades when Live mode is enabled. Use Paper mode
until you have validated the strategy yourself. The `UNHEDGED_HOLD` scenario
carries settlement/directional risk, and the "guaranteed" arbitrage depends on a
successful double-sided fill. Verifying that Polymarket/Kalshi are legal in your
jurisdiction is your responsibility.
