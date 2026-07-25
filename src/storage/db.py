"""SQLite storage: trades, logs, at non-secret settings — scoped per exchange.

Isang bot.db para sa dalawang panel (Polymarket + Kalshi). Ang trades at
logs ay may `exchange` column; ang settings keys ay naka-prefix per
exchange (hal. "polymarket.risk_usdc", "kalshi.risk_usd").

Ang mga engine/UI pages ay tumatanggap ng ``ScopedDatabase`` (galing sa
``Database.scope("polymarket")``) na EKSAKTONG kapareho ng lumang Database
API — kaya near-verbatim ang port ng PolyTradePro code; hindi nila alam na
may kabilang exchange.

Ang secrets (private key, API key) ay HINDI dito naka-store —
nasa Windows Credential Manager sila via core/secrets.py.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from src.core.paths import DATA_DIR

DB_DIR = DATA_DIR
DB_PATH = DB_DIR / "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL DEFAULT 'polymarket',  -- 'polymarket' | 'kalshi'
    ts TEXT NOT NULL,                -- ISO-8601 UTC
    market TEXT NOT NULL,            -- e.g. 'BTC Up/Down 2026-07-10' o Kalshi ticker
    side TEXT NOT NULL,              -- 'UP' | 'DOWN' | 'YES' | 'NO'
    action TEXT NOT NULL,            -- 'BUY' | 'SELL' | 'HEDGE' | 'SETTLE' | 'CANCEL'
    price REAL NOT NULL,             -- share/contract price (0.00-1.00)
    size REAL NOT NULL,              -- dollar amount
    status TEXT NOT NULL,            -- 'OPEN' | 'FILLED' | 'CANCELLED'
    pnl REAL,                        -- realized PnL sa pagsara
    meta TEXT                        -- optional JSON (order IDs, atbp.)
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange TEXT NOT NULL DEFAULT 'polymarket',
    ts TEXT NOT NULL,
    level TEXT NOT NULL,             -- 'INFO' | 'WARN' | 'ERROR' | 'TRADE'
    message TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def scope(self, exchange: str) -> "ScopedDatabase":
        """Ibalik ang per-exchange view ng database (lumang Database API)."""
        return ScopedDatabase(self, exchange)

    # ---------------------------------------------------------------- logs

    def add_log(self, exchange: str, level: str, message: str) -> None:
        self._conn.execute(
            "INSERT INTO logs (exchange, ts, level, message) VALUES (?, ?, ?, ?)",
            (exchange, _utc_now(), level, message),
        )
        self._conn.commit()

    def recent_logs(self, exchange: str, limit: int = 200) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM logs WHERE exchange = ? ORDER BY id DESC LIMIT ?",
            (exchange, limit),
        )
        return cur.fetchall()

    def clear_logs(self, exchange: str) -> None:
        self._conn.execute("DELETE FROM logs WHERE exchange = ?", (exchange,))
        self._conn.commit()

    # -------------------------------------------------------------- trades

    def add_trade(
        self,
        exchange: str,
        market: str,
        side: str,
        action: str,
        price: float,
        size: float,
        status: str = "OPEN",
        pnl: Optional[float] = None,
        meta: Optional[str] = None,
        ts: Optional[str] = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO trades (exchange, ts, market, side, action, price, size,"
            " status, pnl, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (exchange, ts or _utc_now(), market, side, action, price, size,
             status, pnl, meta),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def set_trade_pnl_by_meta(
        self, exchange: str, meta: str, pnl: float, size: float
    ) -> bool:
        """I-update ang PnL/size ng row na may ganitong meta. True kung
        may naapektuhan.

        Kailangan ito dahil puwedeng magbago ang realized PnL ng isang
        market (dagdag na fills) matapos nating maitala — mas tama ang
        i-update kaysa magdagdag ng pangalawang row.
        """
        cur = self._conn.execute(
            "UPDATE trades SET pnl = ?, size = ? WHERE exchange = ?"
            " AND meta = ?",
            (pnl, size, exchange, meta),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def supersede_open_trades(
        self, exchange: str, market: str, side: str
    ) -> int:
        """Markahan ang naka-OPEN na placement rows bilang SUPERSEDED.

        Kapag na-import na ang TOTOONG fills mula sa exchange, ang lumang
        "order placed, resting" na row ay doble na — mas tumpak ang datos
        ng exchange. Hindi ito dinedelete (nasa DB pa rin para sa audit),
        itinatago lang sa Trades table.
        """
        cur = self._conn.execute(
            "UPDATE trades SET status = 'SUPERSEDED' WHERE exchange = ?"
            " AND market = ? AND side = ? AND status = 'OPEN'",
            (exchange, market, side),
        )
        self._conn.commit()
        return int(cur.rowcount)

    def has_trade_meta(self, exchange: str, meta: str) -> bool:
        """May naitala na bang trade na may ganitong meta (hal. fill_id)?

        Ginagamit sa pag-import ng history mula sa exchange para hindi
        madoble ang parehong fill sa tuwing magsi-sync.
        """
        cur = self._conn.execute(
            "SELECT 1 FROM trades WHERE exchange = ? AND meta = ? LIMIT 1",
            (exchange, meta),
        )
        return cur.fetchone() is not None

    def recent_trades(self, exchange: str, limit: int = 100) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM trades WHERE exchange = ? ORDER BY id DESC LIMIT ?",
            (exchange, limit),
        )
        return cur.fetchall()

    def total_pnl(self, exchange: str) -> float:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trades"
            " WHERE exchange = ? AND pnl IS NOT NULL",
            (exchange,),
        )
        return float(cur.fetchone()[0])

    def trade_stats(self, exchange: str) -> dict:
        # Kasama ang lahat ng action na may recorded PnL (SELL sa poly,
        # SETTLE/HEDGE sa kalshi) para tama ang closed/wins/losses.
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n,"
            " SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,"
            " SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losses"
            " FROM trades WHERE exchange = ? AND pnl IS NOT NULL",
            (exchange,),
        )
        row = cur.fetchone()
        return {
            "closed": row["n"] or 0,
            "wins": row["wins"] or 0,
            "losses": row["losses"] or 0,
        }

    # ------------------------------------------------------------ settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        cur = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row is not None else default

    def set_setting(self, key: str, value: Any) -> None:
        self._conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
        self._conn.commit()


class ScopedDatabase:
    """Per-exchange view ng Database — kapareho ng lumang PolyTradePro API.

    Lahat ng trades/logs queries ay naka-filter sa exchange, at lahat ng
    settings keys ay awtomatikong napi-prefix ("{exchange}.{key}").
    """

    POSITION_KEY = "open_position"

    def __init__(self, db: Database, exchange: str) -> None:
        self._db = db
        self.exchange = exchange

    # ---------------------------------------------------------------- logs

    def add_log(self, level: str, message: str) -> None:
        self._db.add_log(self.exchange, level, message)

    def recent_logs(self, limit: int = 200) -> list[sqlite3.Row]:
        return self._db.recent_logs(self.exchange, limit)

    def clear_logs(self) -> None:
        self._db.clear_logs(self.exchange)

    # -------------------------------------------------------------- trades

    def add_trade(
        self,
        market: str,
        side: str,
        action: str,
        price: float,
        size: float,
        status: str = "OPEN",
        pnl: Optional[float] = None,
        meta: Optional[str] = None,
        ts: Optional[str] = None,
    ) -> int:
        return self._db.add_trade(
            self.exchange, market, side, action, price, size, status, pnl,
            meta, ts,
        )

    def has_trade_meta(self, meta: str) -> bool:
        return self._db.has_trade_meta(self.exchange, meta)

    def supersede_open_trades(self, market: str, side: str) -> int:
        return self._db.supersede_open_trades(self.exchange, market, side)

    def set_trade_pnl_by_meta(
        self, meta: str, pnl: float, size: float
    ) -> bool:
        return self._db.set_trade_pnl_by_meta(
            self.exchange, meta, pnl, size
        )

    def recent_trades(self, limit: int = 100) -> list[sqlite3.Row]:
        return self._db.recent_trades(self.exchange, limit)

    def total_pnl(self) -> float:
        return self._db.total_pnl(self.exchange)

    def trade_stats(self) -> dict:
        return self._db.trade_stats(self.exchange)

    # ------------------------------------------------------- open position

    def save_open_position(
        self,
        mode: str,
        market: str,
        side: str,
        entry_price: float,
        shares: float,
        entry_ts: dt.datetime,
    ) -> None:
        """I-persist ang open position para ma-restore pagkatapos ng restart."""
        self.set_setting(
            self.POSITION_KEY,
            json.dumps({
                "mode": mode,
                "market": market,
                "side": side,
                "entry_price": entry_price,
                "shares": shares,
                "entry_ts": entry_ts.isoformat(timespec="seconds"),
            }),
        )

    def load_open_position(self) -> Optional[dict]:
        raw = self.get_setting(self.POSITION_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def clear_open_position(self) -> None:
        self.set_setting(self.POSITION_KEY, "")

    # ------------------------------------------------------------ settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._db.get_setting(f"{self.exchange}.{key}", default)

    def set_setting(self, key: str, value: Any) -> None:
        self._db.set_setting(f"{self.exchange}.{key}", value)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
