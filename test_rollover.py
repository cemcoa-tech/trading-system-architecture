#!/usr/bin/env python3
"""
test_rollover.py
────────────────
Dry-run test for the rollover system WITHOUT placing real orders.

Tests:
  1. DB migration — rollovers table exists and is queryable
  2. check_rollover_needed() — connects to IBKR and checks OI for a symbol
  3. db.rollover_trade()     — simulates the atomic DB rollover operation
  4. db.get_rollover_history() — reads it back

Usage:
    python test_rollover.py                   # full test (needs IBKR running)
    python test_rollover.py --db-only         # skip IBKR, only test DB layer
"""

import argparse
import sys
from pathlib import Path

from config.settings import DB_PATH, IBKRConfig, MarketDataConfig
from database.manager import DatabaseManager
from utils.logger import setup_logging, LogConfig, get_logger

setup_logging(LogConfig())
log = get_logger("test_rollover")


# ─────────────────────────────────────────────────────────────────────────────
# 1. DB-layer tests (always run)
# ─────────────────────────────────────────────────────────────────────────────

def test_db_layer(db: DatabaseManager) -> bool:
    log.info("=" * 55)
    log.info("TEST 1: DB layer — rollovers table")
    log.info("=" * 55)

    # Ensure a dummy strategy exists (FK requirement)
    db.upsert_strategy("_test_rollover_strategy", description="Rollover unit test")

    # Open a fake trade on the old contract
    old_trade_id = db.open_trade(
        strategy_name="_test_rollover_strategy",
        symbol="GCM6",
        direction="LONG",
        quantity=1,
        entry_price=3300.00,
        tp_price=3400.00,
        sl_price=3200.00,
    )
    log.info("Opened fake old trade: id=%d  entry=3300.00  TP=3400.00  SL=3200.00", old_trade_id)

    # Simulate rollover: exit GCM6 @ 3310, enter GCQ6 @ 3315 (spread=5)
    new_trade_id = db.rollover_trade(
        strategy_name="_test_rollover_strategy",
        old_trade_id=old_trade_id,
        old_symbol="GCM6",
        new_symbol="GCQ6",
        old_expiry="202606",
        new_expiry="202608",
        exit_price=3310.00,
        entry_price=3315.00,
        quantity=1,
        direction="LONG",
        tp_price=3405.00,   # 3400 + spread(5)
        sl_price=3205.00,   # 3200 + spread(5)
        point_value=100.0,
        old_oi=45000,
        new_oi=72000,
    )
    log.info("rollover_trade() returned new_trade_id=%d", new_trade_id)

    # Verify old trade is CLOSED
    old_trades = db.get_trades(strategy_name="_test_rollover_strategy", status="CLOSED")
    old_closed = [t for t in old_trades if t["id"] == old_trade_id]
    if old_closed:
        t = old_closed[0]
        log.info("[PASS] Old trade CLOSED: exit_price=%.2f  pnl=%.2f", t["exit_price"], t["pnl"])
    else:
        log.error("[FAIL] Old trade NOT closed")
        return False

    # Verify new trade is OPEN
    new_open = db.get_open_trade("_test_rollover_strategy")
    if new_open and new_open["id"] == new_trade_id:
        log.info(
            "[PASS] New trade OPEN: symbol=%s  entry=%.2f  TP=%.2f  SL=%.2f",
            new_open["symbol"], new_open["entry_price"],
            new_open["tp_price"], new_open["sl_price"],
        )
    else:
        log.error("[FAIL] New trade NOT open or wrong id")
        return False

    # Verify rollover audit record
    history = db.get_rollover_history(strategy_name="_test_rollover_strategy")
    if history:
        r = history[0]
        log.info(
            "[PASS] Rollover record: %s -> %s  spread=%.2f  old_oi=%d  new_oi=%d  old_pnl=%.2f",
            r["old_symbol"], r["new_symbol"], r["price_spread"],
            r["old_oi"], r["new_oi"], r["old_pnl"],
        )
    else:
        log.error("[FAIL] No rollover record found")
        return False

    # Cleanup test data
    with db._cursor() as cur:
        cur.execute("DELETE FROM rollovers WHERE strategy_name='_test_rollover_strategy'")
        cur.execute("DELETE FROM trades WHERE strategy_name='_test_rollover_strategy'")
        cur.execute("DELETE FROM strategies WHERE name='_test_rollover_strategy'")
    log.info("Cleaned up test data")

    log.info("TEST 1 PASSED")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# 2. IBKR OI check (only when --db-only is NOT set)
# ─────────────────────────────────────────────────────────────────────────────

def test_ibkr_oi_check(symbol: str, exchange: str, currency: str = "USD") -> bool:
    log.info("=" * 55)
    log.info("TEST 2: check_rollover_needed() for %s on %s", symbol, exchange)
    log.info("=" * 55)

    from ib_insync import IB, Future, util
    from utils.expiry_selector import check_rollover_needed
    from config.settings import IBKRConfig

    cfg = IBKRConfig()
    util.startLoop()
    ib = IB()

    try:
        log.info("Connecting to IBKR %s:%s ...", cfg.host, cfg.port)
        ib.connect(cfg.host, cfg.port, clientId=cfg.client_id)
        log.info("Connected")

        # Build a stub current contract (first available)
        base = Future(symbol=symbol, exchange=exchange, currency=currency)
        all_details = ib.reqContractDetails(base)
        if not all_details:
            log.error("No contracts found for %s", symbol)
            return False

        # Use the soonest-expiry as "current"
        all_details.sort(key=lambda d: d.contract.lastTradeDateOrContractMonth)
        current_ct = all_details[0].contract
        log.info("Using current contract: %s  expiry=%s", current_ct.localSymbol, current_ct.lastTradeDateOrContractMonth)

        should_roll, next_ct, cur_oi, nxt_oi = check_rollover_needed(
            ib=ib,
            current_contract=current_ct,
            symbol=symbol,
            exchange=exchange,
            currency=currency,
        )

        log.info("should_roll=%s  current_OI=%d  next_OI=%d", should_roll, cur_oi, nxt_oi)
        if next_ct:
            log.info("Next contract: %s", next_ct.localSymbol)

        log.info("TEST 2 PASSED (result is informational only)")
        return True

    except Exception as e:
        log.error("TEST 2 FAILED: %s", e, exc_info=True)
        return False
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-only", action="store_true", help="Skip IBKR connection tests")
    parser.add_argument("--symbol", default="GC", help="Symbol to test OI check on (default: GC)")
    parser.add_argument("--exchange", default="COMEX", help="Exchange (default: COMEX)")
    args = parser.parse_args()

    db = DatabaseManager(DB_PATH)
    results = []

    # Test 1: DB layer
    results.append(("DB layer", test_db_layer(db)))

    # Test 2: IBKR OI check
    if not args.db_only:
        results.append(("IBKR OI check", test_ibkr_oi_check(args.symbol, args.exchange)))
    else:
        log.info("Skipping IBKR test (--db-only)")

    db.close()

    log.info("=" * 55)
    log.info("RESULTS")
    log.info("=" * 55)
    all_passed = True
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        log.info("  %s  --  %s", status, name)
        if not passed:
            all_passed = False

    sys.exit(0 if all_passed else 1)
