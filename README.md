# SportsBet Pro — Dual-Panel Trading Bot (Polymarket + Kalshi)

A Windows desktop trading bot with **two independent panels**, each with its
own ON/OFF (START/STOP) button, settings, balance, trades, statistics, and logs.
Both can run at the same time.

| Panel | Strategy | Markets | Currency |
|---|---|---|---|
| **Polymarket** | Mean Reversion ("Rubber Band") | Daily / 4h / 1h / 15m BTC Up/Down | USDC (Polygon) |
| **Kalshi** | Internal Straddle / Box Arbitrage | 50/50 sports moneylines (NBA/NFL/MLB…) | USD |

---

## 📌 Progress / Status (2026-07-22)

### Development Phases
- [x] **Phase 1: Skeleton** — verbatim reuse, `ScopedDatabase`, dual-panel UI shell, stub engines
- [x] **Phase 2: Polymarket port** — feed / strategy / execution, `PolyEngine`, dashboard + settings, ported tests
- [x] **Phase 3: Kalshi paper** — client, straddle math + state machine, `KalshiEngine`, Kalshi UI, tests
- [x] **Phase 4: Kalshi live** — RSA-PSS auth **validated against the real Kalshi production API** (credential check returns balance)
- [ ] **Phase 5: Packaging** — PyInstaller build of `SportsBetPro.exe` *(spec/icon/README ready; build pending)*

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
- **Tests** — 132 passing (ported Polymarket suite + Kalshi tests: straddle
  math, hedge sentinel, RSA-PSS signing, paper fills, DB scoping, DoH)
- **DoH resolver** — covers `polymarket.com`, `kalshi.com`, `kalshi.co`

### 🔜 Next steps
1. **Kalshi live order path** — auth is validated but the production account has
   a $0.00 balance, so orders can't fill yet. To exercise the full live order
   path, either fund the account (small risk) or create a **demo** account
   (demo.kalshi.co, practice money) and set Environment → Demo in Settings.
2. **PyInstaller packaging** — `SportsBetPro.spec` is ready; the `.exe` is not
   built yet.
3. **Paper-mode tuning** — let it run for a while and observe the hedge-sentinel
   timeout (90s) and entry band (48–52¢); adjust in Settings if needed.

---

## The Two Strategies

### Polymarket — Mean Reversion (ported from PolyTradePro)
Binance provides the read-only BTC feed. When BTC stretches 1.5%–2.5% from the
period open inside the 4–12h entry window, the bot buys the out-of-the-money
side at 15¢–25¢ and sells at the profit target — with volume-escalation,
Coinbase-premium, and Economic-Data-Day death-trap filters.

### Kalshi — Internal Straddle / Box Arbitrage
On a high-liquidity ~50/50 sports market, it places two **post-only resting
limit buys**: YES @ 49¢ **and** NO @ 49¢. Because the market is binary, one
side is guaranteed to settle at $1.00 → **~+1.1% per completed cycle** after
maker fees.

**Hedge Sentinel:** if only one side fills within the timeout (default 90s) or
the price runs away, it cancels the lagging order and takes the other side up
to 51¢ to lock a "scratch" (~breakeven) — the bot is never left holding a
directional sports bet.

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
