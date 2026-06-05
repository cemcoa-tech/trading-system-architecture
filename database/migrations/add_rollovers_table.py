#!/usr/bin/env python3
"""
database/migrations/add_rollovers_table.py
───────────────────────────────────────────
Migration: Add the rollovers audit table introduced with the
automatic contract rollover feature.

Run with:
    python database/migrations/add_rollovers_table.py
    python database/migrations/add_rollovers_table.py data/trading.db
"""

import sqlite3
import sys
from pathlib import Path


def run(db_path: str) -> bool:
    print(f"\nDatabase: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.cursor()

        # ── 1. Create rollovers table if not present ─────────────────────
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rollovers'"
        )
        if cur.fetchone():
            print("✅  rollovers table already exists — skipping creation")
        else:
            cur.executescript("""
                CREATE TABLE rollovers (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name       TEXT    NOT NULL,
                    old_symbol          TEXT    NOT NULL,
                    new_symbol          TEXT    NOT NULL,
                    old_expiry          TEXT    NOT NULL,
                    new_expiry          TEXT    NOT NULL,
                    old_trade_id        INTEGER,
                    new_trade_id        INTEGER,
                    exit_price          REAL,
                    entry_price         REAL,
                    price_spread        REAL,
                    old_pnl             REAL,
                    quantity            INTEGER,
                    old_oi              INTEGER,
                    new_oi              INTEGER,
                    rolled_at           TEXT    NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (strategy_name) REFERENCES strategies(name)
                );
                CREATE INDEX IF NOT EXISTS idx_rollovers_strategy
                    ON rollovers(strategy_name);
            """)
            print("✅  rollovers table created")

        conn.commit()
        conn.close()
        return True

    except sqlite3.Error as e:
        print(f"❌  SQLite error: {e}")
        return False
    except Exception as e:
        print(f"❌  Unexpected error: {e}")
        return False


def verify(db_path: str) -> bool:
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check table exists
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rollovers'"
        )
        if not cur.fetchone():
            print("❌  rollovers table NOT found")
            conn.close()
            return False

        # Check expected columns
        cur.execute("PRAGMA table_info(rollovers)")
        cols = {row[1] for row in cur.fetchall()}
        required = {
            "id", "strategy_name", "old_symbol", "new_symbol",
            "old_expiry", "new_expiry", "old_trade_id", "new_trade_id",
            "exit_price", "entry_price", "price_spread", "old_pnl",
            "quantity", "old_oi", "new_oi", "rolled_at",
        }
        missing = required - cols
        if missing:
            print(f"❌  Missing columns: {missing}")
            conn.close()
            return False

        print(f"✅  rollovers table verified ({len(cols)} columns present)")

        # Check index
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_rollovers_strategy'"
        )
        if cur.fetchone():
            print("✅  idx_rollovers_strategy index present")
        else:
            print("⚠️   idx_rollovers_strategy index missing (non-fatal)")

        conn.close()
        return True

    except Exception as e:
        print(f"❌  Verification error: {e}")
        return False


if __name__ == "__main__":
    # Resolve DB path
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    else:
        db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "trading.db")

    print("=" * 55)
    print("  MIGRATION: add_rollovers_table")
    print("=" * 55)

    ok = run(db_path)
    if ok:
        ok = verify(db_path)

    if ok:
        print("\n🎯  Migration complete and verified.")
        sys.exit(0)
    else:
        print("\n❌  Migration failed.")
        sys.exit(1)
