#!/usr/bin/env python3
"""
seed_demo_data.py
─────────────────
Populate the SQLite database with realistic demo data so the Streamlit
dashboard can be explored without a live IBKR connection.

Usage:
    cd trading_framework
    python seed_demo_data.py
"""

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config.settings import DB_PATH
from database.manager import DatabaseManager


def seed() -> None:
    db = DatabaseManager(DB_PATH)

    # ── Strategy ─────────────────────────────────────────────────────────
    db.upsert_strategy(
        "mgc_pullback",
        description="MGC Pullback: RSI(2) dip in SMA200 uptrend, exit on SMA37 cross",
        params={
            "trend_length": 200,
            "rsi_length": 2,
            "rsi_threshold": 30,
            "exit_ma_length": 37,
        },
    )

    # ── Generate 30 days of signals + trades ─────────────────────────────
    base_date = datetime(2025, 1, 6)
    price = 2050.0
    cum_pnl = 0.0
    trade_id_counter = 0

    for i in range(60):
        day = base_date + timedelta(days=i)
        if day.weekday() >= 5:
            continue  # skip weekends

        date_str = day.strftime("%Y-%m-%d")
        price += random.uniform(-15, 18)
        close = round(price, 2)

        sma200 = round(close - random.uniform(-30, 50), 2)
        sma37 = round(close - random.uniform(-10, 15), 2)
        rsi2 = round(random.uniform(5, 85), 2)

        uptrend = close > sma200
        pullback = rsi2 < 30
        exit_up = close > sma37

        # Decide signal type — force a regular entry/exit cycle
        cycle_pos = i % 12
        if cycle_pos == 0:
            sig_type = "ENTRY_LONG"
        elif cycle_pos == 6:
            sig_type = "EXIT_LONG"
        else:
            sig_type = "NONE"

        indicators = {
            "SMA200": sma200,
            "SMA37": sma37,
            "RSI2": rsi2,
            "uptrend": uptrend,
            "pullback": pullback,
            "exit_up": exit_up,
        }

        db.insert_signal(
            strategy_name="mgc_pullback",
            signal_date=date_str,
            signal_type=sig_type,
            close_price=close,
            indicators=indicators,
            meta={"source": "demo_seed"},
        )

        # Create trades for entry signals
        if sig_type == "ENTRY_LONG":
            entry_px = round(close + 5.0, 1)
            tp_px = round(entry_px + 110.0, 1)
            sl_px = round(entry_px - 110.0, 1)
            trade_id_counter = db.open_trade(
                strategy_name="mgc_pullback",
                symbol="MGC",
                direction="LONG",
                quantity=1,
                entry_price=entry_px,
                tp_price=tp_px,
                sl_price=sl_px,
            )
            db.insert_order(
                strategy_name="mgc_pullback",
                symbol="MGC",
                action="BUY",
                order_type="LIMIT",
                quantity=1,
                trade_id=trade_id_counter,
                limit_price=entry_px,
            )

        elif sig_type == "EXIT_LONG" and trade_id_counter > 0:
            exit_px = round(close - 2.0, 1)
            pnl = round(random.uniform(-800, 1500), 2)
            cum_pnl += pnl
            db.close_trade(trade_id_counter, exit_px, pnl)
            db.insert_order(
                strategy_name="mgc_pullback",
                symbol="MGC",
                action="SELL",
                order_type="LIMIT",
                quantity=1,
                trade_id=trade_id_counter,
                limit_price=exit_px,
            )

        # Position snapshot every 3rd trading day
        if i % 3 == 0:
            pos_qty = 1 if sig_type == "ENTRY_LONG" else 0
            db.snapshot_position(
                strategy_name="mgc_pullback",
                symbol="MGC",
                quantity=pos_qty,
                market_price=close,
                unrealized_pnl=round(random.uniform(-500, 500), 2) if pos_qty else 0,
                realized_pnl=round(cum_pnl, 2),
            )

    db.close()
    print(f"✅ Demo data seeded into {DB_PATH}")
    print(f"   Run the dashboard:  streamlit run dashboard/app.py")


if __name__ == "__main__":
    seed()
