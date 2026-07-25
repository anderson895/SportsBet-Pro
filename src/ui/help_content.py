"""Nilalaman ng About / Help page — pure data, walang Qt.

Nakahiwalay sa widget para (a) matestingan nang hindi bumubuo ng UI at
(b) madaling dagdagan nang hindi hinahawakan ang layout code.

Ang mga numero at pangalan ng field dito ay tumutugma sa aktwal na
DEFAULTS sa `kalshi_settings.py` / `poly_settings.py` at sa totoong
behavior ng mga engine — kapag may binago roon, i-update din ito.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Mga tag para sa filter chips at para malaman kung saang panel
# nauukol ang isang seksyon
GENERAL = "General"
KALSHI = "Kalshi"
POLYMARKET = "Polymarket"


@dataclass(frozen=True)
class Section:
    title: str
    tag: str
    body: str
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, query: str) -> bool:
        """Case-insensitive na hanap sa title, body, tag, at keywords."""
        q = query.strip().lower()
        if not q:
            return True
        haystack = " ".join(
            (self.title, self.tag, self.body, " ".join(self.keywords))
        ).lower()
        return all(word in haystack for word in q.split())


SECTIONS: tuple[Section, ...] = (
    # ---------------------------------------------------------- GENERAL
    Section(
        "What this app does",
        GENERAL,
        "SportsBet Pro runs two independent trading bots in one window.\n\n"
        "• Polymarket panel — trades BTC Up/Down markets with a Mean\n"
        "  Reversion strategy. Directional: it profits when price snaps\n"
        "  back toward the period open.\n\n"
        "• Kalshi panel — trades 50/50 sports markets with Box Arbitrage.\n"
        "  Non-directional: it buys BOTH sides and does not care who wins.\n\n"
        "Each panel has its own START/STOP, settings, balance, trades, logs\n"
        "and statistics. Starting one does not start the other.",
        ("overview", "intro", "what is", "two bots", "panels"),
    ),
    Section(
        "Quick start",
        GENERAL,
        "1. Open Settings for the panel you want to use.\n"
        "2. Check the balance shown at the top of the page.\n"
        "3. Click 'Apply Recommended' — it sizes risk to ~10% of your\n"
        "   balance and sets proven strategy defaults.\n"
        "4. Review the values, then click 'Save Settings'.\n"
        "5. Press START BOT at the bottom.\n\n"
        "Start in PAPER mode until you trust the behaviour. Paper uses real\n"
        "live market data but simulated money.",
        ("getting started", "setup", "first time", "how to begin"),
    ),
    Section(
        "Paper vs Live mode",
        GENERAL,
        "PAPER — simulated fills, no real money, no API keys needed. Real\n"
        "market data is still used, so the strategy behaves realistically.\n\n"
        "LIVE — places real orders with real money. Requires API\n"
        "credentials and a funded account.\n\n"
        "The mode is per panel: you can run Kalshi live while Polymarket\n"
        "stays on paper.",
        ("simulation", "demo", "real money", "test mode"),
    ),
    Section(
        "Reading the Trades page",
        GENERAL,
        "Status column:\n"
        "  RESTING (not filled) — the order is queued on the exchange.\n"
        "     No money has been spent yet. Amber.\n"
        "  FILLED — actually executed. Green.\n"
        "  CANCELLED — withdrawn before filling. Grey.\n\n"
        "A row is written when the order is PLACED, so RESTING rows are\n"
        "normal and expected.\n\n"
        "Double-click any row to open the full trade details: decoded\n"
        "matchup, how many YES vs NO contracts, total cost, and net P&L.\n\n"
        "'Sync from exchange' (Kalshi) imports the real fill history and\n"
        "realised P&L straight from your account — useful if the app was\n"
        "restarted mid-trade. It is safe to click repeatedly.\n\n"
        "Times are shown in your local timezone.",
        ("trades", "status", "resting", "filled", "pnl", "sync", "history"),
    ),
    Section(
        "Where credentials are stored",
        GENERAL,
        "API keys and private keys go into Windows Credential Manager, not\n"
        "into files or the database.\n\n"
        "Exception: RSA private keys that exceed Credential Manager's size\n"
        "limit are written to data\\kalshi_key.pem instead, and the path is\n"
        "saved in settings.\n\n"
        "Leave any secret field blank to keep its current value.",
        ("security", "api key", "private key", "keyring", "safety"),
    ),

    # ----------------------------------------------------------- KALSHI
    Section(
        "Kalshi — how Box Arbitrage works",
        KALSHI,
        "The bot buys BOTH sides of the same market at the same time:\n\n"
        "    BUY 10 YES @ 49¢   =  $4.90\n"
        "    BUY 10 NO  @ 49¢   =  $4.90\n"
        "                          ------\n"
        "                   total  $9.80\n\n"
        "Exactly one side must settle at $1.00, so 10 pairs return $10.00 —\n"
        "no matter who wins. Kalshi automatically nets matched YES+NO into\n"
        "the $1.00 credit, often before the game even ends.\n\n"
        "Gross profit is 2¢ per pair. After maker fees the net is roughly\n"
        "+1.1% per completed cycle.\n\n"
        "This is NOT a bet on a team. The market name (e.g. …CHCPIT-CHC)\n"
        "only identifies which side is 'YES' — the bot holds both.",
        ("straddle", "box arb", "arbitrage", "strategy", "how it works",
         "both sides", "yes no"),
    ),
    Section(
        "Kalshi — why the bot sits idle",
        KALSHI,
        "The bot places post-only (maker) orders. It waits in the order\n"
        "book instead of paying the spread — that is where the profit comes\n"
        "from.\n\n"
        "Bidding 49¢ + 49¢ = 98¢ for a $1.00 payout means somebody must\n"
        "sell to you at those prices. In slow pre-game markets that can\n"
        "take a long time, and many cycles end in CANCEL after the 15\n"
        "minute no-fill timeout.\n\n"
        "Long idle periods are normal and correct, not a bug. If the bot\n"
        "chased the market instead, buying immediately would cost about\n"
        "104¢ for a $1.00 payout — a guaranteed loss.",
        ("idle", "waiting", "no fills", "slow", "nothing happening",
         "maker", "post only"),
    ),
    Section(
        "Kalshi — Hedge Sentinel (the real risk control)",
        KALSHI,
        "The only dangerous outcome is a one-sided fill: if YES fills and\n"
        "NO does not, you are holding a genuine bet on the game.\n\n"
        "The Hedge Sentinel handles this:\n"
        "  • After 90 seconds single-sided, it acts.\n"
        "  • It buys the missing side at up to 51¢.\n"
        "  • 49¢ + 51¢ = $1.00 → breakeven; you lose only fees, not the\n"
        "    game outcome.\n"
        "  • If it cannot fill, the cycle becomes UNHEDGED_HOLD, an ERROR\n"
        "    is logged and an alert is shown. Only then is real\n"
        "    directional risk being carried.\n\n"
        "Both the timeout and the maximum hedge price are configurable in\n"
        "Settings.",
        ("hedge", "sentinel", "risk", "one sided", "single sided",
         "unhedged", "protection", "scratch"),
    ),
    Section(
        "Kalshi — settings reference",
        KALSHI,
        "Trading Mode — Paper (simulated) or Live (real money).\n\n"
        "Environment — Production (kalshi.com) or Demo (practice money at\n"
        "demo.kalshi.co).\n\n"
        "Kalshi API Key ID / RSA Private Key — from kalshi.com → Account\n"
        "Settings → API Keys. Paste the PEM text or give a file path.\n\n"
        "Risk Per Straddle (USD) — money committed to ONE straddle, both\n"
        "sides combined. $10 buys about 10 pairs at 49¢+49¢.\n\n"
        "Entry Price — the resting bid on EACH side. Default 49¢. Lower is\n"
        "more profitable but fills less often; keep it near 49¢. Setting it\n"
        "far from 50¢ (e.g. 20¢) means it will essentially never fill.\n\n"
        "Hedge Sentinel — max hedge price — default 51¢, giving breakeven.\n\n"
        "Hedge Sentinel — single-sided timeout — default 90 seconds.\n\n"
        "Minimum Market Volume — only trade games with at least this much\n"
        "volume. Higher is safer and more liquid; lower surfaces more\n"
        "candidates.\n\n"
        "Skip markets closing sooner than — avoids the chaotic final\n"
        "minutes of a game. Default 45 minutes.\n\n"
        "Skip markets closing later than — ignores games still hours away.\n"
        "Default 12 hours.\n\n"
        "Sports to Trade — which leagues to scan. Leave all unchecked to\n"
        "auto-discover whatever is active.\n\n"
        "Paper Starting Balance — the pretend balance used in Paper mode.",
        ("settings", "fields", "configuration", "risk", "entry price",
         "volume", "sports"),
    ),
    Section(
        "Kalshi — fees and the actual maths",
        KALSHI,
        "Kalshi's fee per leg is:\n\n"
        "    fee = ceil( 0.0175 × contracts × P × (1 − P) )   in cents\n\n"
        "At 49¢ this is about 0.44¢ per contract per leg, so a pair costs\n"
        "roughly 0.9¢ in fees against 2¢ of gross profit.\n\n"
        "Worked example from a real completed cycle:\n"
        "    28 pairs traded, cost $27.44\n"
        "    settlement            $28.00\n"
        "    gross profit          +$0.56\n"
        "    fees paid             −$0.2451\n"
        "    net                   +$0.3149\n\n"
        "The margin is thin, which is exactly why the bot must stay a\n"
        "maker: a single taker fill wipes out several winning cycles.",
        ("fees", "maths", "math", "profit", "economics", "example",
         "calculation"),
    ),
    Section(
        "Kalshi — three-way markets (soccer)",
        KALSHI,
        "Soccer has three outcomes: home win, DRAW, away win. Cards for\n"
        "these games therefore show three rows, and the percentages add up\n"
        "to 100% across all three.\n\n"
        "Each individual market is still binary — 'does Tijuana win?' is\n"
        "yes or no — so Box Arbitrage works normally.\n\n"
        "In the featured card the NO side of a three-way market is labelled\n"
        "'Not <team>', because NO means 'draw OR the opponent', not simply\n"
        "the opponent.",
        ("soccer", "football", "draw", "tie", "three way", "3-way",
         "percentages"),
    ),

    # ------------------------------------------------------ POLYMARKET
    Section(
        "Polymarket — how Mean Reversion works",
        POLYMARKET,
        "The 'rubber band' idea: within a fixed period, when BTC stretches\n"
        "far from the period's opening price, it often snaps back.\n\n"
        "The bot watches the BTC price from Binance, waits for a stretch\n"
        "beyond a threshold, then buys the CONTRARIAN side of the\n"
        "Polymarket BTC Up/Down market — cheap shares that pay out if\n"
        "price reverts.\n\n"
        "Unlike the Kalshi strategy this is directional: it can lose. Every\n"
        "filter below exists to avoid entering on days when price trends\n"
        "instead of reverting.",
        ("mean reversion", "rubber band", "strategy", "btc", "bitcoin",
         "how it works"),
    ),
    Section(
        "Polymarket — entry conditions",
        POLYMARKET,
        "All of these must be true at the same time, or no trade is taken:\n\n"
        "  • Inside the entry window (for 15m markets: 2.5–7.5 minutes\n"
        "    into the period).\n"
        "  • Stretch from the period open is at least the Entry Stretch\n"
        "    Band, and no more than the Death Trap Limit.\n"
        "  • Share price is inside the 0.15–0.25 range — cheap enough for\n"
        "    the payoff to be worthwhile.\n"
        "  • Recent volume is not spiking above the Volume Spike Filter.\n"
        "  • Coinbase premium is within the Coinbase Premium Filter.\n"
        "  • Today is not marked as an Economic Data Day.\n\n"
        "The Logs page shows exactly which condition blocked an entry, for\n"
        "example 'stretch +0.01% < 0.153% minimum'. Seeing many of these\n"
        "means the market is quiet, not that the bot is broken.",
        ("entry", "conditions", "filters", "why no trade", "blocked",
         "stretch", "window"),
    ),
    Section(
        "Polymarket — settings reference",
        POLYMARKET,
        "Trading Mode — Paper (simulated) or Live (real USDC).\n\n"
        "Market Timeframe — which BTC Up/Down market to trade: Daily, 4h,\n"
        "1h or 15m. Strategy timings and thresholds scale automatically to\n"
        "the choice, so the 1.5% daily stretch becomes about 0.15% on 15m.\n\n"
        "Polymarket Private Key — your wallet's private key.\n\n"
        "Funder / Proxy Address — your Polymarket 'Address (For API use\n"
        "only)', NOT your plain wallet address. Copy it from\n"
        "polymarket.com → Settings.\n\n"
        "Polymarket Wallet Type — Magic (email/Google), MetaMask (browser\n"
        "wallet), or Deposit Wallet (accounts created after Apr 2026).\n"
        "Choosing the wrong one makes the balance read 0.00 even when the\n"
        "account is funded.\n\n"
        "Risk Per Trade (USDC) — money committed to one trade.\n\n"
        "Entry Stretch Band — minimum move from the open before buying.\n\n"
        "Max Stretch / Death Trap Limit — skip if price has moved MORE than\n"
        "this; that suggests a trending day, not a reverting one.\n\n"
        "Take Profit — sell when the position is up this much.\n\n"
        "Volume Spike Filter — block entry when recent volume is this many\n"
        "times the baseline (sign of institutional momentum).\n\n"
        "Coinbase Premium Filter — block entry when the Coinbase-vs-Binance\n"
        "premium is too large (sign of aggressive US spot buying).\n\n"
        "Economic Data Day — tick to block ALL entries today (Fed meeting,\n"
        "CPI, and similar trend days).\n\n"
        "Paper Starting Balance — the pretend balance used in Paper mode.",
        ("settings", "fields", "configuration", "wallet type", "funder",
         "timeframe", "risk"),
    ),

    # -------------------------------------------------- TROUBLESHOOTING
    Section(
        "Troubleshooting — balance shows 0.00",
        POLYMARKET,
        "Almost always the wrong Polymarket Wallet Type.\n\n"
        "Polymarket accepts any valid key, so a mismatch does not raise an\n"
        "error — it just reports an empty balance. Try each Wallet Type in\n"
        "Settings and save; the one that shows your real balance is the\n"
        "correct one. Accounts created after April 2026 are usually\n"
        "'Deposit Wallet'.\n\n"
        "Also confirm the Funder is your 'Address (For API use only)' and\n"
        "not your plain wallet address.",
        ("zero balance", "0.00", "no funds", "balance wrong", "wallet type"),
    ),
    Section(
        "Troubleshooting — Polymarket orders are rejected",
        POLYMARKET,
        "'the order signer address has to be the address of the API KEY'\n"
        "  → Your Funder is set to your own wallet address. In the deposit\n"
        "    wallet flow the Funder must be the separate Polymarket deposit\n"
        "    address from polymarket.com → Settings → 'Address (For API use\n"
        "    only)'.\n\n"
        "'maker address not allowed, please use the deposit wallet flow'\n"
        "  → Set Wallet Type to 'Deposit Wallet'.\n\n"
        "Orders accepted but nothing settles\n"
        "  → The account may have no exchange approvals yet. Making one\n"
        "    small manual trade on polymarket.com sets them, after which\n"
        "    the bot can trade.\n\n"
        "There is a bundled checker: run test_polymarket_live.py. It places\n"
        "a $1 order far from the market price (so it cannot fill), reports\n"
        "whether the exchange accepted it, then cancels it.",
        ("rejected", "order failed", "signer", "maker address", "approvals",
         "allowance", "cannot trade"),
    ),
    Section(
        "Troubleshooting — Kalshi messages",
        KALSHI,
        "'Market moved … 49¢ bid would cross the book; will retry next scan'\n"
        "  → Harmless. Between the scan and the order the price moved, so a\n"
        "    post-only order would have become a taker and was skipped. The\n"
        "    bot retries with the next candidate.\n\n"
        "'Straddle cancelled … no fills after 15min'\n"
        "  → Normal maker behaviour. Nobody traded against the resting\n"
        "    orders, so they were withdrawn and the bot moved on.\n\n"
        "Balance dropped, then came back higher\n"
        "  → Kalshi reserves collateral while orders rest or one leg is\n"
        "    filled. When the pair nets to $1.00 the collateral returns\n"
        "    along with the profit. A dip mid-cycle is not a loss.\n\n"
        "Statistics show $0.00 even though trades completed\n"
        "  → Click 'Sync from exchange' on the Trades page. Fill history\n"
        "    alone does not contain realised profit; the sync also pulls it\n"
        "    from your positions.",
        ("errors", "cross", "cancelled", "balance dropped", "reserved",
         "statistics zero", "troubleshooting"),
    ),
    Section(
        "Safety notes",
        GENERAL,
        "• Test in Paper mode first, then Live with a small Risk value.\n"
        "  'Apply Recommended' deliberately sizes risk at about 10% of\n"
        "  your balance.\n\n"
        "• Pressing STOP BOT pauses trading but does NOT cancel orders\n"
        "  already resting on the exchange. Cancel those on kalshi.com or\n"
        "  polymarket.com if you do not want them.\n\n"
        "• Closing the app while a straddle is open leaves the real orders\n"
        "  live on the exchange. Restart and press START to resume\n"
        "  monitoring them, including the Hedge Sentinel.\n\n"
        "• Never share your private keys or PEM files with anyone.",
        ("safety", "warning", "stop", "cancel orders", "risk", "closing"),
    ),
)


def search(query: str) -> list[Section]:
    """Mga seksyon na tumutugma sa query, sa orihinal na pagkakasunod."""
    return [s for s in SECTIONS if s.matches(query)]


def tags() -> list[str]:
    """Mga tag sa pagkakasunod ng unang paglabas (para sa filter chips)."""
    seen: list[str] = []
    for section in SECTIONS:
        if section.tag not in seen:
            seen.append(section.tag)
    return seen
