"""SAFE PROBE — patunayan na tanggap ng Polymarket ang mga order natin.

Ano ang ginagawa nito:
  1. Bubuo ng API credentials mula sa naka-save na private key + funder
  2. Babasahin ang totoong USDC balance
  3. Hahanapin ang kasalukuyang BTC Up/Down market at ang order book nito
  4. Maglalagay ng $1 limit BUY sa 0.02 — SOBRANG layo sa market price,
     kaya HINDI ito mafi-fill (walang magbebenta ng ganoon kamura)
  5. Ipapakita ang order ID na ibinigay ng Polymarket (= patunay na
     tanggap ang auth + signing + CLOB V2 + signature type)
  6. Kakanselahin agad ang order

Panganib: halos wala — hindi ito mafi-fill at kinakansela kaagad.
Patakbuhin:  .\\venv\\Scripts\\python.exe test_polymarket_live.py
"""
from __future__ import annotations

import datetime as dt
import sys

# Ang Windows console ay cp1252 — pilitin ang UTF-8 para hindi mag-crash
# ang mga tsek/krus na simbolo
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.core import secrets
from src.core.netdns import install_doh_resolver
from src.execution.polymarket import PolymarketClient, find_btc_market
from src.storage.db import Database

PROBE_PRICE = 0.02   # napakalayo sa ~0.50 market -> hindi mafi-fill
PROBE_USDC = 1.0     # pinakamaliit na makabuluhang halaga


def main() -> int:
    install_doh_resolver()
    db = Database()

    pk = secrets.get_secret(secrets.KEY_PM_PRIVATE)
    funder = secrets.get_secret(secrets.KEY_PM_FUNDER)
    sig_type = int(db.get_setting("polymarket.pm_signature_type", "1"))
    timeframe = str(db.get_setting("polymarket.market_timeframe", "daily"))

    if not pk or not funder:
        print("✗ Walang naka-save na Private Key / Funder. Ilagay muna sa "
              "Polymarket Settings.")
        return 1

    print(f"funder         : {funder}")
    print(f"signature type : {sig_type} "
          f"({'Deposit Wallet' if sig_type == 3 else 'Magic/MetaMask'})")
    print(f"timeframe      : {timeframe}\n")

    # --- 1) connect + derive API creds ---------------------------------
    print("[1/5] Kumokonekta at bumubuo ng API credentials…")
    client = PolymarketClient(private_key=pk, funder=funder,
                              signature_type=sig_type)
    client.connect()
    print("      ✓ konektado (nag-derive ng API key mula sa private key)\n")

    # --- 2) balance -----------------------------------------------------
    print("[2/5] Binabasa ang totoong USDC balance…")
    balance = client.get_usdc_balance()
    print(f"      ✓ balance = {balance:,.2f} USDC")
    if balance < PROBE_USDC:
        print(f"      ✗ kulang ang balance para sa ${PROBE_USDC} na probe")
        return 1
    print()

    # --- 3) market + order book ----------------------------------------
    print("[3/5] Hinahanap ang kasalukuyang BTC Up/Down market…")
    market = find_btc_market(timeframe, dt.datetime.now(dt.timezone.utc))
    token = market.token_for("UP")
    bid, ask = client.get_best_prices(token)
    print(f"      ✓ {market.question}")
    print(f"      UP token best bid={bid} ask={ask}")
    if ask is not None and PROBE_PRICE >= ask:
        print(f"      ✗ HUMINTO: ang probe price na {PROBE_PRICE} ay "
              f"mafi-fill (ask={ask}). Ayaw nating bumili talaga.")
        return 1
    print(f"      ✓ ang {PROBE_PRICE} ay ligtas na mas mababa sa ask "
          f"— hindi mafi-fill\n")

    # --- 4) place the probe order ---------------------------------------
    print(f"[4/5] Naglalagay ng ${PROBE_USDC:.2f} limit BUY @ {PROBE_PRICE}…")
    try:
        order_id = client.buy_limit(token, PROBE_PRICE, PROBE_USDC)
    except Exception as e:
        msg = str(e)
        print(f"      ✗ TINANGGIHAN ang order: {msg}\n")
        print("=" * 62)
        print(" ✗ HINDI PA MAKAKAPAG-TRADE ANG BOT")
        print("=" * 62)
        if "signer address has to be the address of the API KEY" in msg:
            print(
                "\nAng Funder mo ay PAREHO ng wallet address ng private key\n"
                f"({funder}).\n\n"
                "Sa Deposit Wallet flow, ang Funder ay dapat ang HIWALAY na\n"
                "deposit address ng Polymarket — hindi ang MetaMask wallet mo.\n\n"
                "GAWIN: polymarket.com -> Settings -> kopyahin ang\n"
                "       'Address (For API use only)' at ilagay iyon sa\n"
                "       Funder / Proxy Address sa Polymarket Settings."
            )
        elif "maker address not allowed" in msg:
            print(
                "\nHinihingi ng Polymarket ang deposit wallet flow.\n"
                "GAWIN: itakda ang Wallet Type sa 'Deposit Wallet' sa Settings."
            )
        else:
            print("\nSuriin ang Wallet Type at Funder address sa Settings.")
        print(
            "\nTANDAAN din: 0 ang lahat ng allowances (approvals) ng account\n"
            "mo sa exchange contracts. Kadalasan naaayos ito kapag gumawa ka\n"
            "ng ISANG manual na trade sa polymarket.com — pagkatapos noon,\n"
            "makakapag-trade na rin ang bot."
        )
        return 1
    print(f"      ✓ TINANGGAP! order ID = {order_id}\n")

    # --- 5) cancel -------------------------------------------------------
    print("[5/5] Kinakansela ang probe order…")
    client.cancel_all()
    print("      ✓ kinansela\n")

    print("=" * 62)
    print(" ✓ GUMAGANA ANG POLYMARKET LIVE TRADING")
    print("   Napatunayan: credentials, order signing, CLOB V2,")
    print(f"   signature type {sig_type}, at pagtanggap ng order.")
    print("   Makakapag-trade ang bot kapag umabot sa entry conditions.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
