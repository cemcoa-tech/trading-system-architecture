"""
database/manager.py
───────────────────
Thin wrapper around SQLite.  No ORM — just parameterised SQL and dicts.
Thread-safe via check_same_thread=False (single-writer model).
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from database.models import SCHEMA_SQL
from utils.logger import get_logger

log = get_logger("db")


class DatabaseManager:
    """SQLite persistence layer for the trading framework."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        log.info("Database ready at %s", db_path)

    # ── Schema bootstrap ─────────────────────────────────────────────────
    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()

    # ── Context helper ───────────────────────────────────────────────────
    @contextmanager
    def _cursor(self):
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ── Strategies ───────────────────────────────────────────────────────
    def upsert_strategy(
        self,
        name: str,
        description: str = "",
        params: Optional[Dict] = None,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO strategies (name, description, params_json)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    params_json = excluded.params_json,
                    updated_at  = datetime('now')
                """,
                (name, description, json.dumps(params or {})),
            )

    def get_strategies(self) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            rows = cur.execute("SELECT * FROM strategies ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    # ── Signals ──────────────────────────────────────────────────────────
    def insert_signal(
        self,
        strategy_name: str,
        signal_date: str,
        signal_type: str,
        close_price: float,
        indicators: Optional[Dict] = None,
        meta: Optional[Dict] = None,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO signals
                    (strategy_name, signal_date, signal_type, close_price,
                     indicator_json, meta_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_name,
                    signal_date,
                    signal_type,
                    close_price,
                    json.dumps(indicators or {}),
                    json.dumps(meta or {}),
                ),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def get_signals(
        self,
        strategy_name: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        q = "SELECT * FROM signals"
        params: list = []
        if strategy_name:
            q += " WHERE strategy_name = ?"
            params.append(strategy_name)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cur:
            return [dict(r) for r in cur.execute(q, params).fetchall()]

    # ── Trades ───────────────────────────────────────────────────────────
    def open_trade(
        self,
        strategy_name: str,
        symbol: str,
        direction: str,
        quantity: int,
        entry_price: float,
        tp_price: Optional[float] = None,
        sl_price: Optional[float] = None,
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO trades
                    (strategy_name, symbol, direction, quantity,
                     entry_price, entry_time, tp_price, sl_price, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')
                """,
                (strategy_name, symbol, direction, quantity,
                 entry_price, now, tp_price, sl_price),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE trades
                SET exit_price = ?, exit_time = ?, pnl = ?,
                    status = 'CLOSED', updated_at = datetime('now')
                WHERE id = ?
                """,
                (exit_price, now, pnl, trade_id),
            )

    def get_trades(
        self,
        strategy_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        q = "SELECT * FROM trades WHERE 1=1"
        params: list = []
        if strategy_name:
            q += " AND strategy_name = ?"
            params.append(strategy_name)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cur:
            return [dict(r) for r in cur.execute(q, params).fetchall()]

    def get_open_trade(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM trades WHERE strategy_name = ? AND status = 'OPEN' "
                "ORDER BY created_at DESC LIMIT 1",
                (strategy_name,),
            ).fetchone()
            return dict(row) if row else None

    # ── Orders ───────────────────────────────────────────────────────────
    def insert_order(
        self,
        strategy_name: str,
        symbol: str,
        action: str,
        order_type: str,
        quantity: int,
        trade_id: Optional[int] = None,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        ib_order_id: Optional[int] = None,
    ) -> int:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO orders
                    (trade_id, strategy_name, symbol, action, order_type,
                     quantity, limit_price, stop_price, ib_order_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED')
                """,
                (trade_id, strategy_name, symbol, action, order_type,
                 quantity, limit_price, stop_price, ib_order_id),
            )
            return cur.lastrowid  # type: ignore[return-value]

    def update_order_status(
        self,
        order_id: int,
        status: str,
        fill_price: Optional[float] = None,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                UPDATE orders
                SET status = ?, fill_price = COALESCE(?, fill_price),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (status, fill_price, order_id),
            )

    def get_orders(
        self,
        strategy_name: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        q = "SELECT * FROM orders WHERE 1=1"
        params: list = []
        if strategy_name:
            q += " AND strategy_name = ?"
            params.append(strategy_name)
        if status:
            q += " AND status = ?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._cursor() as cur:
            return [dict(r) for r in cur.execute(q, params).fetchall()]

    # ── Positions ────────────────────────────────────────────────────────
    def snapshot_position(
        self,
        strategy_name: str,
        symbol: str,
        quantity: int,
        avg_cost: Optional[float] = None,
        market_price: Optional[float] = None,
        unrealized_pnl: Optional[float] = None,
        realized_pnl: Optional[float] = None,
    ) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO positions
                    (strategy_name, symbol, quantity, avg_cost,
                     market_price, unrealized_pnl, realized_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (strategy_name, symbol, quantity, avg_cost,
                 market_price, unrealized_pnl, realized_pnl),
            )

    def get_latest_positions(
        self, strategy_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if strategy_name:
            q = """
                SELECT * FROM positions
                WHERE strategy_name = ?
                ORDER BY snapshot_time DESC LIMIT 1
            """
            params: list = [strategy_name]
        else:
            q = """
                SELECT p.* FROM positions p
                INNER JOIN (
                    SELECT strategy_name, MAX(snapshot_time) AS max_time
                    FROM positions GROUP BY strategy_name
                ) sub ON p.strategy_name = sub.strategy_name
                       AND p.snapshot_time = sub.max_time
            """
            params = []
        with self._cursor() as cur:
            return [dict(r) for r in cur.execute(q, params).fetchall()]

    # ── PnL helpers (for dashboard) ──────────────────────────────────────
    def get_equity_curve(
        self, strategy_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Cumulative PnL over closed trades — drives the equity curve chart."""
        q = """
            SELECT id, strategy_name, exit_time, pnl,
                   SUM(pnl) OVER (ORDER BY exit_time) AS cum_pnl
            FROM trades
            WHERE status = 'CLOSED' AND pnl IS NOT NULL
        """
        params: list = []
        if strategy_name:
            q += " AND strategy_name = ?"
            params.append(strategy_name)
        q += " ORDER BY exit_time"
        with self._cursor() as cur:
            return [dict(r) for r in cur.execute(q, params).fetchall()]

    # ── Teardown ─────────────────────────────────────────────────────────
    def close(self) -> None:
        self._conn.close()
        log.info("Database connection closed")

    def upsert_position_state(
        self,
        strategy_name: str,
        symbol: str,
        entry_bar_date: str = None,
        entry_price: float = None,
        bars_held: int = 0,
        profitable_closes: int = 0,
        tp_price: float = None,
        sl_price: float = None,
        state_json: str = None,
    ) -> None:
        """Update or insert position state for complex strategies."""
        self._conn.execute(
            """
            INSERT INTO position_state (
                strategy_name, symbol, entry_bar_date, entry_price,
                bars_held, profitable_closes, tp_price, sl_price, state_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(strategy_name, symbol) DO UPDATE SET
                entry_bar_date = excluded.entry_bar_date,
                entry_price = excluded.entry_price,
                bars_held = excluded.bars_held,
                profitable_closes = excluded.profitable_closes,
                tp_price = excluded.tp_price,
                sl_price = excluded.sl_price,
                state_json = excluded.state_json,
                updated_at = datetime('now')
            """,
            (
                strategy_name, symbol, entry_bar_date, entry_price,
                bars_held, profitable_closes, tp_price, sl_price, state_json
            ),
        )
        self._conn.commit()

    def get_position_state(self, strategy_name: str, symbol: str) -> Optional[dict]:
        """Retrieve position state for a strategy/symbol."""
        row = self._conn.execute(
            """
            SELECT * FROM position_state
            WHERE strategy_name = ? AND symbol = ?
            """,
            (strategy_name, symbol),
        ).fetchone()
        
        return dict(row) if row else None

    def delete_position_state(self, strategy_name: str, symbol: str) -> None:
        """Delete position state (on exit)."""
        self._conn.execute(
            "DELETE FROM position_state WHERE strategy_name = ? AND symbol = ?",
            (strategy_name, symbol),
        )
        self._conn.commit()