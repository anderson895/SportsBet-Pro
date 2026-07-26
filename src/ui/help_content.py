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
        "Double-click any row to open the full trade details: side (UP or\n"
        "DOWN), entry and exit price, size, and net P&L.\n\n"
        "Times are shown in your local timezone.",
        ("trades", "status", "resting", "filled", "pnl", "history"),
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
        "Kalshi — how Mean Reversion works",
        KALSHI,
        "Kalshi runs the SAME 'rubber band' strategy as Polymarket — only\n"
        "the venue differs. Within a fixed period, when BTC stretches far\n"
        "from the period's opening price, it often snaps back.\n\n"
        "Kalshi has no single 'Up or Down' market, so the bot builds one\n"
        "from the KXBTCD 'Above/below' ladder: it pins the strike nearest\n"
        "the period open as the up/down pivot (YES = above = UP, NO = below\n"
        "= DOWN). It then buys the cheap CONTRARIAN side — DOWN when BTC is\n"
        "pumped, UP when dumped — and sells when price reverts.\n\n"
        "This is directional: it can lose. Every filter below exists to\n"
        "avoid entering on days when price trends instead of reverting.",
        ("mean reversion", "rubber band", "strategy", "btc", "bitcoin",
         "how it works", "above below", "kxbtcd", "up down"),
    ),
    Section(
        "Kalshi — entry conditions",
        KALSHI,
        "All of these must be true at the same time, or no trade is taken:\n\n"
        "  • Inside the entry window (for 1h markets: 10–30 minutes into\n"
        "    the period).\n"
        "  • Stretch from the period open is at least the Entry Stretch\n"
        "    Band, and no more than the Death Trap Limit.\n"
        "  • The contrarian contract is cheap enough (0.15–0.25) for the\n"
        "    payoff to be worthwhile.\n"
        "  • Recent volume is not spiking above the Volume Spike Filter.\n"
        "  • Coinbase premium is within the Coinbase Premium Filter.\n"
        "  • Today is not marked as an Economic Data Day.\n\n"
        "The Logs page shows exactly which condition blocked an entry, for\n"
        "example 'stretch +0.01% < 0.31% minimum'. Seeing many of these\n"
        "means the market is quiet, not that the bot is broken.",
        ("entry", "conditions", "filters", "why no trade", "blocked",
         "stretch", "window"),
    ),
    Section(
        "Kalshi — why the bot sits idle",
        KALSHI,
        "The bot only trades when BTC genuinely stretches away from the\n"
        "period open inside the entry window. Most of the time price is\n"
        "quiet and no condition is met — so it waits.\n\n"
        "Long idle periods are normal and correct, not a bug. Forcing a\n"
        "trade with no real stretch would just be a coin-flip bet on BTC.\n"
        "The Logs page names the exact condition it is waiting for.",
        ("idle", "waiting", "slow", "nothing happening", "no trade"),
    ),
    Section(
        "Kalshi — settings reference",
        KALSHI,
        "Trading Mode — Paper (simulated) or Live (real money).\n\n"
        "Market Timeframe — which Kalshi BTC Above/Below market to trade:\n"
        "1 Hour (the reliably-listed KXBTCD ladder) or Daily. Strategy\n"
        "timings and thresholds scale automatically, so the 1.5% daily\n"
        "stretch becomes about 0.31% on 1-hour markets.\n\n"
        "Environment — Production (kalshi.com) or Demo (practice money at\n"
        "demo.kalshi.co).\n\n"
        "Kalshi API Key ID / RSA Private Key — from kalshi.com → Account\n"
        "Settings → API Keys. Paste the PEM text or give a file path.\n\n"
        "Risk Per Trade (USD) — money committed to one trade.\n\n"
        "Entry Stretch Band — minimum move from the open before buying;\n"
        "default 1.5% (daily-calibrated).\n\n"
        "Max Stretch / Death Trap Limit — skip if price has moved MORE than\n"
        "this; that suggests a trending day, not a reverting one.\n\n"
        "Take Profit — sell when the position is up this much; default\n"
        "100%.\n\n"
        "Volume Spike Filter — block entry when recent volume is this many\n"
        "times the baseline (sign of institutional momentum).\n\n"
        "Coinbase Premium Filter — block entry when the Coinbase-vs-Binance\n"
        "premium is too large (sign of aggressive US spot buying).\n\n"
        "Economic Data Day — tick to block ALL entries today (Fed meeting,\n"
        "CPI, and similar trend days).\n\n"
        "Paper Starting Balance — the pretend balance used in Paper mode.",
        ("settings", "fields", "configuration", "risk", "entry price",
         "timeframe", "environment", "api key"),
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
        "'WAITING — resolving Kalshi BTC market…'\n"
        "  → The bot is discovering the KXBTCD above/below strike nearest\n"
        "    the period open. It clears once the order book loads.\n\n"
        "'WAITING — no live order book data yet'\n"
        "  → The chosen strike has no quotes yet this tick; it retries every\n"
        "    few seconds. Common right after a period rollover.\n\n"
        "'No open KXBTCD above/below markets found'\n"
        "  → Kalshi has not listed the BTC ladder for this period yet, or\n"
        "    the Daily timeframe is unavailable — switch to 1 Hour.\n\n"
        "Balance shows '…' in Live mode\n"
        "  → A transient network hiccup; the balance loop retries every\n"
        "    10 seconds and refreshes every 60.",
        ("errors", "no market", "waiting", "balance", "order book",
         "troubleshooting"),
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
        "• Closing the app while a position is open leaves it on the\n"
        "  exchange. Restart and press START to resume monitoring it; the\n"
        "  open position is restored if still within the same period.\n\n"
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
