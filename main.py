#!/usr/bin/env python3
"""
main.py
───────
Entry point for the trading framework.

Usage:
    python main.py                    # Run all active strategies once
    python main.py --strategy mgc     # Run only the MGC pullback strategy
    python main.py --dry-run          # Log signals without placing orders

Designed to be called by cron / scheduler once per day after market close.
"""

import argparse
import signal
import sys
import time
from typing import List

from config.settings import (
    DB_PATH,
    IBKRConfig,
    LogConfig,
    MGC_PULLBACK_PARAMS,
    MarketDataConfig,
    StrategyParams,
)
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.mgc_pullback import MGCPullbackStrategy
from strategies.base_strategy import BaseStrategy
from utils.logger import get_logger, setup_logging


# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    global shutdown_requested
    shutdown_requested = True
    log = get_logger("main")
    log.info("Shutdown signal received, stopping continuous trading...")


# main.py (UPDATE the build_strategies function)

from strategies.mgc_pullback import MGCPullbackStrategy
from strategies.mnq_condition1 import MNQCondition1Strategy
from strategies.mes_condition1 import MESCondition1Strategy
from strategies.btc_rsi_meanrev import BTCRSIMeanRevStrategy

# ... (existing imports)

def build_strategies(
    broker: Broker,
    order_mgr: OrderManager,
    db: DatabaseManager,
    filter_name: str = "",
) -> List[BaseStrategy]:
    """
    Strategy registry.  Add new strategies here.
    Each entry maps a short name → (ParamsObject, StrategyClass).
    """
    from config.settings import (
        MGC_PULLBACK_PARAMS,
        MNQ_CONDITION1_PARAMS,
        MES_CONDITION1_PARAMS,
        BTC_RSI_PARAMS,
    )
    
    registry = {
        "mgc": (MGC_PULLBACK_PARAMS, MGCPullbackStrategy),
        "mnq": (MNQ_CONDITION1_PARAMS, MNQCondition1Strategy),
        "mes": (MES_CONDITION1_PARAMS, MESCondition1Strategy),
        "btc": (BTC_RSI_PARAMS, BTCRSIMeanRevStrategy),
    }

    strategies: List[BaseStrategy] = []
    for key, (params, cls) in registry.items():
        if filter_name and key != filter_name:
            continue
        
        # Convert params to StrategyParams if needed
        if not isinstance(params, StrategyParams):
            strategy_params = StrategyParams(
                name=params.name,
                contract_spec=params.contract_spec,
                risk_usd=params.risk_usd,
                max_position=params.max_position,
                params=params.params,
            )
        else:
            strategy_params = params
        
        strategies.append(cls(
            params=strategy_params,
            broker=broker,
            order_mgr=order_mgr,
            db=db
        ))

    return strategies


def run_continuous_trading(
    broker: Broker,
    order_mgr: OrderManager,
    db: DatabaseManager,
    strategies: List[BaseStrategy],
    check_interval: int = 60,
) -> None:
    """
    Run strategies continuously, checking for signals at regular intervals.
    Keeps IB connection alive and monitors for trading opportunities.
    """
    log = get_logger("main")
    log.info("Starting continuous trading mode (check interval: %d seconds)", check_interval)
    log.info("Press Ctrl+C to stop gracefully")
    
    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        while not shutdown_requested:
            log.info("=" * 60)
            log.info("CONTINUOUS TRADING CYCLE - %s", time.strftime("%Y-%m-%d %H:%M:%S"))
            log.info("=" * 60)
            
            for strat in strategies:
                if shutdown_requested:
                    break
                    
                try:
                    log.info("Checking strategy: %s", strat.name)
                    
                    # Register strategy
                    strat.db.upsert_strategy(strat.name, params=strat.params.params)
                    
                    # Fetch data and compute indicators
                    df = strat.fetch_data()
                    df = strat.compute_indicators(df)
                    
                    # Get current position
                    trade_ct = broker.qualify_contract(strat.spec)
                    pos = broker.get_position_quantity(trade_ct.conId)
                    
                    # Generate signal
                    sig = strat.generate_signal(df, pos)
                    log.info("Signal: %s | Reason: %s", sig.signal_type, sig.reason)
                    
                    # Execute signal if not NONE
                    if sig.signal_type != "NONE":
                        log.info("Executing signal: %s", sig.signal_type)
                        strat._execute_signal(sig, trade_ct, pos)
                        
                        # Update position snapshot
                        new_pos = broker.get_position_quantity(trade_ct.conId)
                        strat.db.snapshot_position(
                            strategy_name=strat.name,
                            symbol=strat.spec.symbol,
                            quantity=new_pos,
                        )
                    else:
                        log.info("No action required")
                        
                except Exception as e:
                    log.exception("Strategy '%s' failed in continuous mode", strat.name)
                    continue
            
            # Wait for next check interval (unless shutdown requested)
            if not shutdown_requested:
                log.info("Waiting %d seconds until next check...", check_interval)
                time.sleep(check_interval)
                
    except KeyboardInterrupt:
        log.info("Keyboard interrupt received")
    finally:
        log.info("Continuous trading stopped")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading Framework Runner")
    parser.add_argument(
        "--strategy", "-s",
        default="",
        help="Run only this strategy (e.g. 'mgc'). Default: run all.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute signals but skip order placement.",
    )
    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run strategies continuously with specified check interval.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Check interval in seconds for continuous mode (default: 60).",
    )
    args = parser.parse_args()

    # ── Logging ──────────────────────────────────────────────────────────
    setup_logging(LogConfig())
    log = get_logger("main")
    log.info("=" * 60)
    log.info("  TRADING FRAMEWORK – STARTING")
    log.info("=" * 60)

    # ── Infrastructure ───────────────────────────────────────────────────
    db = DatabaseManager(DB_PATH)
    ibkr_cfg = IBKRConfig()
    broker = Broker(ibkr_cfg=ibkr_cfg, mkt_cfg=MarketDataConfig())
    order_mgr: OrderManager  # declared here, initialised after connect

    try:
        broker.connect()
        order_mgr = OrderManager(broker.ib, ibkr_cfg.account)

        strategies = build_strategies(
            broker, order_mgr, db, filter_name=args.strategy
        )
        if not strategies:
            log.warning("No strategies matched filter '%s'", args.strategy)
            return

        if args.continuous:
            if args.dry_run:
                log.warning("Dry run mode not supported with continuous trading")
                log.info("Use regular mode for continuous paper trading")
                return
            
            # Run continuous trading
            run_continuous_trading(
                broker, order_mgr, db, strategies, 
                check_interval=args.interval
            )
        else:
            # Original single-run mode
            for strat in strategies:
                try:
                    if args.dry_run:
                        log.info("[DRY RUN] Strategy: %s", strat.name)
                        # Partial execution: data + indicators + signal only
                        strat.db.upsert_strategy(strat.name, params=strat.params.params)
                        df = strat.fetch_data()
                        df = strat.compute_indicators(df)
                        trade_ct = broker.qualify_contract(strat.spec)
                        pos = broker.get_position_quantity(trade_ct.conId)
                        sig = strat.generate_signal(df, pos)
                        log.info("Signal FULL: %s", sig)
                        log.info(
                            "[DRY RUN] Signal: %s | Reason: %s",
                            sig.signal_type, sig.reason,
                        )
                    else:
                        strat.execute()
                except Exception:
                    log.exception("Strategy '%s' failed", strat.name)

    except ConnectionError:
        log.critical("Could not connect to IBKR - aborting")
        sys.exit(1)
    finally:
        broker.disconnect()
        db.close()

    log.info("ALL STRATEGIES COMPLETE")


if __name__ == "__main__":
    main()
