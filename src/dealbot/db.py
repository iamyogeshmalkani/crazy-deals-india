"""Storage. One SQL dialect-neutral repository over Postgres (prod) or SQLite (dev/tests).

All timestamps are unix-epoch integers so both engines behave identically.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dealbot.models import RawDeal

STATUS_PENDING = "pending_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_POSTED = "posted"
STATUS_EXPIRED = "expired"
STATUS_STALE = "stale"

_DEAL_COLUMNS = {
    "status",
    "review_chat_msg_id",
    "review_msg_kind",
    "channel_msg_id",
    "channel_msg_kind",
    "posted_at",
}


class Db:
    """Thin autocommit wrapper. SQL is written with %s placeholders for both engines."""

    def __init__(self, url: str = ""):
        self.is_postgres = url.startswith(("postgres://", "postgresql://"))
        if self.is_postgres:
            import psycopg
            from psycopg.rows import dict_row

            # prepare_threshold=None keeps this working behind pgbouncer (Supabase pooler).
            self._conn = psycopg.connect(
                url, autocommit=True, row_factory=dict_row, prepare_threshold=None
            )
        else:
            path = url.replace("sqlite:///", "", 1) if url else "dealbot.db"
            self._conn = sqlite3.connect(path or ":memory:", isolation_level=None)
            self._conn.row_factory = sqlite3.Row

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        if not self.is_postgres:
            sql = sql.replace("%s", "?")
        cur = self._conn.execute(sql, tuple(params))
        if cur.description is None:
            return []
        return [dict(row) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


def _schema(is_postgres: bool) -> List[str]:
    pk = "BIGSERIAL PRIMARY KEY" if is_postgres else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        f"""CREATE TABLE IF NOT EXISTS products (
            id {pk},
            store TEXT NOT NULL,
            store_product_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            image TEXT,
            category TEXT,
            first_seen BIGINT NOT NULL,
            UNIQUE (store, store_product_id)
        )""",
        f"""CREATE TABLE IF NOT EXISTS price_history (
            id {pk},
            product_id BIGINT NOT NULL REFERENCES products(id),
            price INTEGER NOT NULL,
            mrp INTEGER,
            fetched_at BIGINT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_price_history_product "
        "ON price_history (product_id, fetched_at)",
        f"""CREATE TABLE IF NOT EXISTS deals (
            id {pk},
            product_id BIGINT NOT NULL REFERENCES products(id),
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            score INTEGER NOT NULL,
            verified INTEGER NOT NULL,
            price INTEGER,
            mrp INTEGER,
            link TEXT NOT NULL,
            image TEXT,
            channel_text TEXT NOT NULL,
            review_text TEXT NOT NULL,
            expired_text TEXT NOT NULL,
            signals TEXT NOT NULL,
            expires_at BIGINT,
            created_at BIGINT NOT NULL,
            review_chat_msg_id BIGINT,
            review_msg_kind TEXT,
            channel_msg_id BIGINT,
            channel_msg_kind TEXT,
            posted_at BIGINT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_deals_status ON deals (status)",
        "CREATE INDEX IF NOT EXISTS idx_deals_product ON deals (product_id)",
        "CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    ]


class Repo:
    # Don't write a new history row for an unchanged price more often than this.
    PRICE_REFRESH_SECONDS = 6 * 3600

    def __init__(self, db: Db):
        self.db = db

    def init(self) -> None:
        for statement in _schema(self.db.is_postgres):
            self.db.query(statement)

    # --- products & prices -------------------------------------------------

    def upsert_product(self, raw: RawDeal, now: int) -> int:
        rows = self.db.query(
            """INSERT INTO products (store, store_product_id, title, url, image, category, first_seen)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (store, store_product_id) DO UPDATE SET
                 title = excluded.title,
                 url = excluded.url,
                 image = COALESCE(excluded.image, products.image),
                 category = COALESCE(excluded.category, products.category)
               RETURNING id""",
            (raw.store, raw.store_product_id, raw.title, raw.url, raw.image, raw.category, now),
        )
        return int(rows[0]["id"])

    def price_history(self, product_id: int, now: int, days: int = 90) -> List[Tuple[int, int]]:
        """(timestamp, price) rows, oldest first, within the last `days`."""
        rows = self.db.query(
            """SELECT fetched_at, price FROM price_history
               WHERE product_id = %s AND fetched_at >= %s ORDER BY fetched_at ASC""",
            (product_id, now - days * 86400),
        )
        return [(int(r["fetched_at"]), int(r["price"])) for r in rows]

    def record_price(self, product_id: int, price: int, mrp: Optional[int], now: int) -> bool:
        """Append a history row if the price changed or the last row is old. Returns True if written."""
        last = self.db.query(
            """SELECT price, fetched_at FROM price_history
               WHERE product_id = %s ORDER BY fetched_at DESC LIMIT 1""",
            (product_id,),
        )
        if last and int(last[0]["price"]) == price and now - int(last[0]["fetched_at"]) < self.PRICE_REFRESH_SECONDS:
            return False
        self.db.query(
            "INSERT INTO price_history (product_id, price, mrp, fetched_at) VALUES (%s, %s, %s, %s)",
            (product_id, price, mrp, now),
        )
        return True

    # --- deals -------------------------------------------------------------

    def has_open_deal(self, product_id: int) -> bool:
        rows = self.db.query(
            "SELECT 1 AS x FROM deals WHERE product_id = %s AND status IN (%s, %s) LIMIT 1",
            (product_id, STATUS_PENDING, STATUS_APPROVED),
        )
        return bool(rows)

    def last_posted(self, product_id: int, now: int, days: int) -> Optional[Dict[str, Any]]:
        rows = self.db.query(
            """SELECT price, posted_at FROM deals
               WHERE product_id = %s AND posted_at IS NOT NULL AND posted_at >= %s
               ORDER BY posted_at DESC LIMIT 1""",
            (product_id, now - days * 86400),
        )
        return rows[0] if rows else None

    def create_deal(self, product_id: int, raw: RawDeal, *, status: str, score: int,
                    verified: bool, link: str, channel_text: str, review_text: str,
                    expired_text: str, signals: Dict[str, Any], now: int) -> int:
        rows = self.db.query(
            """INSERT INTO deals (product_id, kind, status, score, verified, price, mrp, link, image,
                                  channel_text, review_text, expired_text, signals, expires_at, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (product_id, raw.kind, status, score, 1 if verified else 0, raw.price, raw.mrp, link,
             raw.image, channel_text, review_text, expired_text, json.dumps(signals),
             raw.expires_at, now),
        )
        return int(rows[0]["id"])

    def get_deal(self, deal_id: int) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM deals WHERE id = %s", (deal_id,))
        return rows[0] if rows else None

    def deals_by_status(self, status: str) -> List[Dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM deals WHERE status = %s ORDER BY score DESC, id ASC", (status,)
        )

    def update_deal(self, deal_id: int, **fields: Any) -> None:
        unknown = set(fields) - _DEAL_COLUMNS
        if unknown:
            raise ValueError(f"cannot update columns: {sorted(unknown)}")
        if not fields:
            return
        assignments = ", ".join(f"{col} = %s" for col in fields)
        self.db.query(
            f"UPDATE deals SET {assignments} WHERE id = %s", (*fields.values(), deal_id)
        )

    def posted_count_since(self, since_ts: int) -> int:
        rows = self.db.query(
            "SELECT COUNT(*) AS n FROM deals WHERE posted_at IS NOT NULL AND posted_at >= %s",
            (since_ts,),
        )
        return int(rows[0]["n"])

    def mark_stale(self, older_than_ts: int) -> int:
        """Pending/approved deals that never got posted in time are dropped."""
        rows = self.db.query(
            """UPDATE deals SET status = %s
               WHERE status IN (%s, %s) AND created_at < %s RETURNING id""",
            (STATUS_STALE, STATUS_PENDING, STATUS_APPROVED, older_than_ts),
        )
        return len(rows)

    # --- key/value ---------------------------------------------------------

    def get_kv(self, key: str) -> Optional[str]:
        rows = self.db.query("SELECT value FROM kv WHERE key = %s", (key,))
        return rows[0]["value"] if rows else None

    def set_kv(self, key: str, value: str) -> None:
        self.db.query(
            """INSERT INTO kv (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
