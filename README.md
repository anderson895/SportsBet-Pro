# SportsBet Pro — Dual-Panel Trading Bot (Polymarket + Kalshi)

A Windows desktop trading bot with **two independent panels**, each with its
own ON/OFF (START/STOP) button, settings, balance, trades, statistics, and logs.
Both can run at the same time.

| Panel | Strategy | Markets | Currency |
|---|---|---|---|
| **Polymarket** | Mean Reversion ("Rubber Band") | Daily / 4h / 1h / 15m BTC Up/Down | USDC (Polygon) |
| **Kalshi** | Mean Reversion ("Rubber Band") | 1h / Daily BTC Above/Below (KXBTCD) | USD |

Both panels now run the **same** mean-reversion BTC strategy — only the venue
(and the panel branding) differs.

---

## 🆕 What's New in v1.4.0

**The Kalshi panel now runs the same Mean-Reversion BTC strategy as Polymarket.**
The old Internal Straddle / Box-Arbitrage on 50/50 sports markets has been
retired; the reference PDF is now background material only.

- **Kalshi = Mean Reversion** — a Binance BTC feed drives the same
  `strategy/mean_reversion` entry/exit rules and death-trap filters used by
  Polymarket. Kalshi has no single "Up or Down" market, so the bot synthesizes
  one from the **KXBTCD "Above/Below" hourly ladder**: it pins the strike
  nearest the period open as the up/down pivot (**YES = above = UP**,
  **NO = below = DOWN**) and buys the cheap contrarian side.
- **Kalshi timeframes** — **1 Hour** (the reliably-listed KXBTCD ladder) and
  **Daily**. (Kalshi has no 15m/4h BTC up/down market — those stay
  Polymarket-only.)
- **New Kalshi-branded BTC dashboard** — live price chart + stretch %, status
  cards (Internet / Binance / Kalshi), strategy status line, and logs. Distinct
  mint branding from the Polymarket panel.
- **Kalshi settings** — mean-reversion knobs (risk USD, timeframe, stretch band,
  take-profit, volume/premium filters, Economic Data Day) alongside the Kalshi
  API Key ID / RSA key / environment fields.
- **Single-side execution** — `KalshiLiveExecutor` buys to open and sells to
  close one directional position (mirrors the Polymarket executor); the straddle
  Hedge-Sentinel machinery is gone.
- **Clear Trades** — a new button on the Trades page wipes an exchange's local
  trade history (with confirmation); Statistics and balance refresh with it.

Releases: **[v1.4.0 (latest)](https://github.com/anderson895/SportsBet-Pro/releases/tag/v1.4.0)**
· [all releases](https://github.com/anderson895/SportsBet-Pro/releases)

---

## 📌 Progress / Status

### Development Phases — all complete ✅
- [x] **Phase 1: Skeleton** — verbatim reuse, `ScopedDatabase`, dual-panel UI shell, stub engines
- [x] **Phase 2: Polymarket port** — feed / strategy / execution, `PolyEngine`, dashboard + settings, ported tests
- [x] **Phase 3: Kalshi paper** — client, RSA-PSS auth, `KalshiEngine`, Kalshi UI, tests
- [x] **Phase 4: Kalshi live** — RSA-PSS auth **validated against the real Kalshi production API** (credential check returns balance)
- [x] **Phase 6: Unify strategy (v1.4.0)** — Kalshi switched to the same Mean-Reversion BTC strategy via the KXBTCD ladder; straddle code removed
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
- **Kalshi panel** — Kalshi-branded BTC dashboard (live price chart + stretch %,
  status cards, strategy line, logs), the shared mean-reversion engine on the
  KXBTCD Above/Below ladder, single-side paper + live execution, position
  resume, paper balance accounting
- **Kalshi market discovery** — resolves the KXBTCD strike nearest the period
  open as the up/down pivot; verified live against the production API (e.g.
  BTC ~$64,718 → `KXBTCD-…-T64699.99`, UP 0.40/0.41 · DOWN 0.59/0.60)
- **Kalshi live auth** — RSA-PSS SHA256 request signing validated against the
  real production server; PEM auto-saved to `data/kalshi_key.pem` when it
  exceeds the Windows Credential Manager blob size limit
- **Kalshi 2026 API** — adapted to dollar-string fields (`yes_bid_dollars`,
  `volume_fp`) and `orderbook_fp` (`yes_dollars` / `no_dollars` levels);
  still backwards-compatible with the older integer-cents format
- **Tests** — 176 passing (shared strategy core + Kalshi market-mapping,
  single-side live executor, and paper buy→sell engine tests; RSA-PSS signing;
  DB scoping; DoH)
- **DoH resolver** — covers `polymarket.com`, `kalshi.com`, `kalshi.co`

### ✅ Live path exercised
- **Kalshi auth + market discovery** — validated against the funded production
  API (credential check returns balance; the KXBTCD pivot resolves with a live
  ~50/50 order book).
- **PyInstaller packaging** — shipped as `SportsBetPro.exe` (see Releases);
  `build.bat` / `SportsBetPro.spec` rebuild it.

> ⚠️ **Kalshi live orders (mean reversion) are implemented against the
> documented v2 order schema but have not yet been exercised on a funded
> account.** Verify with a tiny real order before relying on Live mode. Paper
> mode is fully validated on both panels.

### 🔜 Next steps
1. **Kalshi live-order verification** — place one tiny real BTC order to confirm
   the buy-to-open / sell-to-close path end-to-end before scaling risk.
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

## Strategy 2 — Kalshi: Mean Reversion ("Rubber Band")

Kalshi runs the **same** rubber-band strategy as Polymarket (above) — the shared
`strategy/mean_reversion` rules, the same Binance feed, and the same death-trap
filters. Only the market plumbing differs.

### Synthesizing an Up/Down market
Kalshi has no single "Up or Down" contract. Instead the **KXBTCD** series
("Bitcoin price Above/Below", hourly) is a dense ladder of "BTC above $STRIKE at
the hour's end" markets (~$100 apart). The bot builds an up/down market by
pinning the strike nearest the period **open** ("price to beat") as the pivot:

```
YES (above the pinned strike) = UP        NO (below) = DOWN
```

So when BTC is pumped above the open the bot buys the cheap **NO (= DOWN)**
side; when dumped, the cheap **YES (= UP)** side — the identical mean-reversion
entry, assembled from a threshold ladder. Discovery is verified live
(`execution/kalshi_market.py`).

### Entry / exit / filters
Identical to Strategy 1: enter on a stretch inside the entry window when the
contrarian contract is cheap (0.15–0.25), take profit at +100%, stop at −50%,
force-exit before settlement, one trade per period, with the volume /
Coinbase-premium / Economic-Data-Day vetoes. Thresholds scale by timeframe
(the 1.5% daily entry stretch becomes ~0.31% on the 1-hour market).

### Timeframes
Kalshi's clean up/down ladder is **hourly** (`KXBTCD`), so **1 Hour** is the
default and the reliably-tradeable timeframe; **Daily** is offered when listed.
Kalshi has no 15m/4h BTC up/down market, so those remain Polymarket-only.

### Execution
`KalshiLiveExecutor` holds **one directional position** at a time — buys to open
(post-only maker on the mapped yes/no side) and sells the same side to close
(crossing the book so the exit fills). Share prices come from the pinned
market's live order book. This is directional (it can lose); the filters exist
to avoid trending days.

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
| `test_mean_reversion.py`, `test_timeframes.py`, `test_filters.py`, `test_polymarket.py`, `test_paper_e2e.py`, `test_resume.py` | Shared strategy core + Polymarket side (proven suite) |
| `test_kalshi_market.py` | KXBTCD discovery: nearest-strike pivot, this-period settlement, UP/DOWN↔yes/no mapping, share-price reads |
| `test_kalshi_live.py` | `KalshiLiveExecutor` — buy opens the mapped side, sell closes the held side, dollars→cents |
| `test_kalshi_engine.py` | Full paper buy→sell through `KalshiEngine` (entry gating, profit target, stop loss, one-trade-per-period) |
| `test_kalshi_auth.py` | RSA-PSS SHA256 signing (in-test keypair, verified with the public key) |
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
5. Pick the **Market Timeframe** (1 Hour recommended) and Risk in USD.
6. Save Settings → credentials are verified via `GET /portfolio/balance`.
7. START BOT — it discovers the current KXBTCD Above/Below market automatically.

> **Paper mode first.** Kalshi paper mode estimates the share price from the BTC
> stretch (same model as Polymarket paper), so the full strategy runs with no
> real money. Live Kalshi orders are new in v1.4.0 — verify with a tiny real
> order first.

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
| Kalshi bot never trades | Normal — it waits for a genuine BTC stretch inside the entry window. The strategy status line names the exact condition it is waiting for |
| `WAITING — resolving Kalshi BTC market…` | The bot is discovering the KXBTCD strike nearest the period open; it clears once the order book loads. `No open KXBTCD…` → switch the timeframe to **1 Hour** |

## Disclaimer

This software places real-money trades when Live mode is enabled. Use Paper mode
until you have validated the strategy yourself. Mean reversion is a
**directional** strategy — it can and will lose on trending days; the death-trap
filters reduce but do not eliminate that risk. Verifying that Polymarket/Kalshi
are legal in your jurisdiction is your responsibility.
