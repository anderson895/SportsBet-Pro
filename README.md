# SportsBet Pro — Dual-Panel Trading Bot (Polymarket + Kalshi)

Isang Windows desktop trading bot na may DALAWANG independent na panel:

---

## 📌 Progress / Status (as of 2026-07-22)

### Development Phases
- [x] **Phase 1: Skeleton** — copy verbatim files, ScopedDatabase, dual-panel UI shell, stub engines
- [x] **Phase 2: Polymarket port** — feed/strategy/execution, PolyEngine, poly dashboard + settings, port tests
- [x] **Phase 3: Kalshi paper** — client, straddle math/state machine, KalshiEngine, kalshi UI, tests
- [ ] **Phase 4: Kalshi live** — RSA-PSS auth, authed endpoints, live executor, demo-env validation
      *(nakasulat na ang code; ang demo/prod validation na lang ang kulang)*
- [ ] **Phase 5: Packaging** — PyInstaller build ng SportsBetPro.exe
      *(handa na ang spec/icon/README; ang build na lang ang kulang)*

### ✅ Tapos at VERIFIED na gumagana
- **App shell** — dalawang tab (Polymarket | Kalshi), bawat panel may sariling
  START/STOP, sub-navigation (Dashboard/Settings/Logs/Trades/Statistics/About),
  balance card, colored logs, at uptime counter; sabay na tumatakbo nang
  independent
- **Polymarket panel** — buong port ng PolyTradePro: live BTC chart
  (line + candles), "Price to beat" 12PM-ET strike, mean reversion strategy,
  death-trap filters, paper + live modes, position resume; dala pa rin ang
  dating credentials sa Windows Credential Manager
- **Kalshi panel (PAPER mode)** — market scanner (nakahanap ng READY na 50/50
  games sa unang totoong takbo), straddle placement (verified: 101 pairs @ 49¢
  sa MLB game), Hedge Sentinel state machine, settlement tracking, paper
  balance accounting
- **Kalshi API (bagong format)** — na-adapt sa 2026 API: dollar-string fields
  (`yes_bid_dollars`, `volume_fp`) at `orderbook_fp` (`yes_dollars`/
  `no_dollars` levels); backwards-compatible pa rin sa lumang integer-cents
  format
- **Tests** — 132 passed (ported poly suite + bagong Kalshi tests: straddle
  math, hedge sentinel, RSA-PSS signing, paper fills, DB scoping, DoH)
- **DoH resolver** — sakop na ang `polymarket.com`, `kalshi.com`, `kalshi.co`
- **Environment** — venv sa Python 3.13 (HUWAG ang 3.10.0 — may CPython bug),
  assets/icons kopyado mula sa reference project

### 🔜 Susunod na hakbang
1. **Kalshi LIVE mode validation** — nakasulat na ang code (RSA-PSS auth,
   authed endpoints, live executor) pero hindi pa na-te-test sa totoong
   account. Plano: Demo environment muna (practice money), tapos Production
   na maliit na risk ($5–10)
2. **PyInstaller packaging** — handa na ang `SportsBetPro.spec`; hindi pa
   nabu-build ang `SportsBetPro.exe`
3. **Paper-mode tuning** — hayaang tumakbo ng ilang araw; obserbahan ang
   hedge sentinel timeout (90s) at entry band (48–52¢) kung kailangang
   i-adjust sa Settings

### 📝 Mga natutunan sa unang takbo (2026-07-22)
- Ang auto-discovery ng sports series ay inuuna na ang major leagues
  (`KXMLBGAME`, `KXWNBAGAME`, …) — ang alphabetical na una ay puro
  off-season na soccer leagues
- MLB game-day markets: malaki ang volume (100K–500K contracts); ang mga
  2+ araw pa bago maglaro ay manipis (~300) — ang default na 5,000 minimum
  volume ay makatwiran sa game day pero ibaba sa Settings kung nagte-test
- Nahuli (at naayos) ng tests ang isang tunay na PnL bug: ang hedge-completed
  na straddle ay dating naitatala bilang LOCKED (49¢+49¢) imbes na HEDGED
  (49¢+51¢)

---

| Panel | Strategy | Markets | Currency |
|---|---|---|---|
| **Polymarket** | Mean Reversion ("Rubber Band") | Daily/4h/1h/15m BTC Up/Down | USDC (Polygon) |
| **Kalshi** | Internal Straddle / Box Arbitrage | 50/50 sports moneylines (NBA/NFL/MLB…) | USD |

Bawat panel ay may **sariling ON/OFF (START/STOP) button**, settings (risk,
Paper/Live mode, API keys), balance card, trades table, statistics, at logs.
Parehong pwedeng tumakbo nang sabay.

---

## Ang Dalawang Strategy

### Polymarket — Mean Reversion (port ng PolyTradePro)
Binance ang read-only BTC feed; kapag naka-stretch ang BTC ng 1.5%–2.5% mula
sa period open sa loob ng 4–12h entry window, bumibili ng out-of-the-money
side sa 15¢–25¢ at nagbebenta sa profit target — kasama ang volume-escalation,
Coinbase-premium, at Economic-Data-Day na death-trap filters.

### Kalshi — Internal Straddle / Box Arbitrage
Sa high-liquidity ~50/50 sports market, naglalagay ng dalawang **post-only
resting limit buy**: YES @ 49¢ **at** NO @ 49¢. Dahil binary ang market, isang
side ang siguradong magse-settle sa $1.00 → **~+1.1% guaranteed per cycle**
pagkatapos ng maker fees.

**Hedge Sentinel:** kapag isang side lang ang na-fill sa loob ng timeout
(default 90s) o tumakbo ang presyo, kinakansela ang lagging order at kinukuha
ang kabilang side hanggang 51¢ para ma-lock ang "scratch" (~breakeven) —
hindi naiiwang may directional sports bet ang bot.

---

## Pag-run mula source

```powershell
python -m venv venv          # Python 3.13
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m src.main    # o i-double-click ang run.bat
```

Requirements: Windows 10/11, internet connection.

## Tests

```powershell
.\venv\Scripts\python.exe -m pytest tests -v
```

| Test file | Saklaw |
|---|---|
| `test_mean_reversion.py`, `test_timeframes.py`, `test_filters.py`, `test_polymarket.py`, `test_paper_e2e.py`, `test_resume.py` | Buong Polymarket side (ported, proven suite) |
| `test_straddle_math.py` | Kalshi fees (ceil per order), pair PnL @49/49, scratch @49+51, sizing, candidate filter |
| `test_hedge_sentinel.py` | StraddleCycle state machine — lahat ng transitions kasama ang sentinel triggers at restart persistence |
| `test_kalshi_auth.py` | RSA-PSS SHA256 signing (in-test keypair, verified sa public key) |
| `test_kalshi_paper.py` | Simulated fills mula sa canned orderbook snapshots |
| `test_db_scoping.py` | Isolation ng dalawang exchange sa iisang bot.db |
| `test_netdns.py` | DoH resolver (polymarket.com + kalshi.com override) |

## Setup ng Live Mode

### Polymarket (kaparehong-pareho ng dating PolyTradePro)
Settings → Trading Mode: Live → Private Key + Funder Address + Wallet Type →
Save. Awtomatikong vine-verify ang credentials at ipinapakita ang balance.
Ang mga dating creds sa Windows Credential Manager ay dala-dala pa rin
(parehong service name).

### Kalshi
1. kalshi.com → Account Settings → **API Keys** → gumawa ng key. Makukuha mo
   ang **API Key ID** at ang **RSA private key (.pem)** file.
2. Kalshi panel → Settings → Trading Mode: **Live**
3. I-paste ang API Key ID; i-paste ang buong PEM text **o** ilagay ang file
   path ng .pem
4. (Optional) Environment: **Demo** muna (demo.kalshi.co, practice money)
   bago mag-Production
5. Save Settings → awtomatikong vine-verify via `GET /portfolio/balance`
6. START BOT — mag-a-auto-discover ito ng sports series tickers sa unang
   takbo (editable sa Settings)

> **Paper mode muna.** Ang Kalshi paper mode ay gumagamit ng TOTOONG public
> market data na may simulated fills — buong scanner + sentinel ang
> na-e-exercise nang walang pera.

## Building the Executable

```powershell
.\venv\Scripts\python.exe -m PyInstaller --noconfirm SportsBetPro.spec
```

Output: `dist/SportsBetPro/`. Parehong build gotchas ng reference project:
`--collect-submodules finplot` (nasa spec na), i-uninstall ang PyQt6 sa build
venv, at huwag mag-build sa Python 3.10.0.

## Troubleshooting

| Problema | Solusyon |
|---|---|
| Polymarket/Kalshi card Disconnected | May built-in DoH resolver (`src/core/netdns.py`) laban sa ISP DNS poisoning ng `*.polymarket.com` at `*.kalshi.com` |
| Hindi bumubukas ang app | Patakbuhin sa terminal: `.\venv\Scripts\python.exe -m src.main` |
| Runtime errors | Tingnan ang **`data\app.log`** — bawat error may full traceback |
| Kalshi scanner walang nahahanap | Normal — bihira ang eksaktong 49/49 na market. Luwagan ang band o volume threshold sa Settings, o hintayin ang game nights |
| `UNHEDGED_HOLD` alert | Nabigo ang hedge — hawak ang isang side hanggang settlement (max loss = entry cost). Titingnan ng bot ang settlement at ire-record ang PnL |

## Disclaimer

Real-money trades ang ginagawa nito kapag Live mode. Gamitin ang Paper mode
hanggang na-validate mo mismo ang strategy. May settlement/directional risk
ang UNHEDGED_HOLD scenario; ang "guaranteed" na arb ay nakadepende sa
matagumpay na double-sided fill. Responsibilidad mong i-verify na legal ang
Polymarket/Kalshi sa iyong jurisdiction.
