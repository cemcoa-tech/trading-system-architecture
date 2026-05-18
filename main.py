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
from config.settings import IBKRConfigAlt

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
from utils.notifications import init_notifications, notify_strategy_execution, notify_system
from datetime import datetime


# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM for graceful shutdown."""
    global shutdown_requested
    shutdown_requested = True
    log = get_logger("main")
    log.info("Shutdown signal received, stopping continuous trading...")


def get_strategy_account(strategy_name: str) -> str:
    """Determine which account to use for order placement based on strategy."""
    # Account mapping for order placement
    account_mapping = {
        "U20859646": ["btc2", "zb_stoch", "BTC2_ValueLow_SMA", "Treasury_Stoch_Hurst","gold2"],
        "U22862141": ["mgc", "mnq", "mes", "btc", "zn", "zb", "rb"]
    }
    
    # Check all possible keys for this strategy
    for account, strategies in account_mapping.items():
        if strategy_name in strategies:
            print(f"Strategy {strategy_name} will use account {account} for orders")
            return account
    
    # Default to standard account
    print(f"Strategy {strategy_name} will use default account U22862141")
    return "U22862141"


def get_ibkr_config(strategy_name: str):
    """Return appropriate IBKR config based on strategy name."""
    account = get_strategy_account(strategy_name)
    if account == "U20859646":
        return IBKRConfigAlt()
    return IBKRConfig()


# main.py (UPDATE the build_strategies function)

from strategies.mgc_pullback import MGCPullbackStrategy
from strategies.mnq_condition1 import MNQCondition1Strategy
from strategies.mes_condition1 import MESCondition1Strategy
from strategies.btc_rsi_meanrev import BTCRSIMeanRevStrategy
from strategies.btc2_valuelow_sma import BTC2ValueLowSMAStrategy
from strategies.treasury_zn_eom import TreasuryZNEOMStrategy
from strategies.treasury_30y_eom import Treasury30YEOMStrategy
from strategies.treasury_stoch_hurst import TreasuryStochHurstStrategy
from strategies.rb_combined import RBCombinedStrategy
from strategies.gold2_atr import Gold2ATRStrategy
from strategies.corn_volatility import CornVolatilityStrategy


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
        IBKRConfigAlt,
        MGC_PULLBACK_PARAMS,
        MNQ_CONDITION1_PARAMS,
        MES_CONDITION1_PARAMS,
        BTC_RSI_PARAMS,
        BTC2_PARAMS,
        BTC2_PARAMS_ALT,
        TREASURY_EOM_PARAMS,
        TREASURY_30Y_EOM_PARAMS,
        TREASURY_STOCH_HURST_PARAMS,
        TREASURY_STOCH_HURST_PARAMS_ALT,
        RB_COMBINED_PARAMS,
        GOLD2_PARAMS,
        CORN_VOLATILITY_PARAMS,
    )
    
    registry = {
        "mgc": (MGC_PULLBACK_PARAMS, MGCPullbackStrategy),
        "mnq": (MNQ_CONDITION1_PARAMS, MNQCondition1Strategy),
        "mes": (MES_CONDITION1_PARAMS, MESCondition1Strategy),
        "btc": (BTC_RSI_PARAMS, BTCRSIMeanRevStrategy),
        "btc2": (BTC2_PARAMS_ALT, BTC2ValueLowSMAStrategy),
        "zn": (TREASURY_EOM_PARAMS, TreasuryZNEOMStrategy),
        "zb": (TREASURY_30Y_EOM_PARAMS, Treasury30YEOMStrategy),
        "zb_stoch": (TREASURY_STOCH_HURST_PARAMS_ALT, TreasuryStochHurstStrategy),
        "rb": (RB_COMBINED_PARAMS, RBCombinedStrategy),
        # Additional mappings for U20859646 account
        "BTC2_ValueLow_SMA": (BTC2_PARAMS_ALT, BTC2ValueLowSMAStrategy),
        "Treasury_Stoch_Hurst": (TREASURY_STOCH_HURST_PARAMS_ALT, TreasuryStochHurstStrategy),
        "gold2": (GOLD2_PARAMS, Gold2ATRStrategy),
        "corn": (CORN_VOLATILITY_PARAMS, CornVolatilityStrategy)
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
        
        # Get the account for this strategy
        strategy_account = get_strategy_account(key)
        
        strategies.append(cls(
            params=strategy_params,
            broker=broker,
            order_mgr=order_mgr,
            db=db,
            account=strategy_account
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
                    
                    # Update broker account if needed for U20859646 strategies
                    ibkr_cfg = get_ibkr_config(strat.name)
                    if ibkr_cfg.account != broker.ibkr_cfg.account:
                        log.info("Switching to account %s for strategy %s", ibkr_cfg.account, strat.name)
                        # Reconnect with correct account
                        broker.disconnect()
                        broker.ibkr_cfg = ibkr_cfg
                        broker.connect()
                        order_mgr = OrderManager(broker.ib, ibkr_cfg.account)
                    
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
                        
                        # Send execution notification
                        notify_strategy_execution(
                            strategy_name=strat.name,
                            execution_time=datetime.now(),
                            signal=sig.signal_type,
                            position_size=sig.indicators.get('quantity', new_pos),
                            entry_price=sig.close_price,
                            exit_price=sig.close_price if sig.signal_type.startswith('EXIT') else None,
                            pnl=None,  # Will be calculated on exit
                            bars_held=sig.indicators.get('bars_held'),
                            profitable_closes=sig.indicators.get('profitable_closes'),
                            indicators={
                                **sig.indicators,
                                'current_pos': new_pos,
                                'reason': sig.reason
                            }
                        )
                    else:
                        log.info("No action required")
                        
                        # Send no-action notification
                        notify_strategy_execution(
                            strategy_name=strat.name,
                            execution_time=datetime.now(),
                            signal="NONE",
                            bars_held=sig.indicators.get('bars_held'),
                            indicators={
                                **sig.indicators,
                                'current_pos': pos,
                                'reason': sig.reason
                            }
                        )
                        
                except Exception as e:
                    log.exception("Strategy '%s' failed in continuous mode", strat.name)
                    
                    # Send error notification
                    notify_strategy_execution(
                        strategy_name=strat.name,
                        execution_time=datetime.now(),
                        error=str(e),
                        indicators={}
                    )
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
    
    order_mgr: OrderManager  # declared here, initialised after connect
    current_ibkr_cfg = None  # Track current IBKR config

    try:
        # Connect with default config first
        default_ibkr_cfg = IBKRConfig()
        broker = Broker(ibkr_cfg=default_ibkr_cfg, mkt_cfg=MarketDataConfig())
        broker.connect()
        order_mgr = OrderManager(broker.ib)
        current_ibkr_cfg = default_ibkr_cfg  # Initialize with default config

        # Initialize notification system
        webhook_url = "https://defaulte9b7660d8611412a9331f148b35712.3d.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/5da69da964f24e96bdfb1016be5ad5f1/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=xnRiOwVt5kKd-M-KdWY6owp77CRopnPlMvHqMCRih10"
        init_notifications(webhook_url=webhook_url, enabled=True)
        
        # Send startup notification
        notify_system("Trading framework started - strategies loaded", "INFO")

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
                    # Get the account for this strategy (used only at order placement time)
                    strategy_account = get_strategy_account(strat.name)
                    log.info("Strategy %s will use account %s for order placement", strat.name, strategy_account)
                    
                    # Verify broker connection before strategy execution
                    if not broker.ib.isConnected():
                        log.warning("Broker disconnected, attempting to reconnect...")
                        try:
                            broker.connect()
                            time.sleep(2)
                        except Exception as e:
                            log.error("Failed to reconnect broker: %s", str(e))
                            continue
                    
                    if args.dry_run:
                        log.info("[DRY RUN] Strategy: %s", strat.name)
                        # Partial execution: data + indicators + signal only
                        strat.db.upsert_strategy(strat.name, params=strat.params.params)
                        df = strat.fetch_data()
                        df = strat.compute_indicators(df)
                        try:
                            trade_ct = broker.qualify_contract(strat.spec)
                            pos = broker.get_position_quantity(trade_ct.conId)
                            sig = strat.generate_signal(df, pos)
                            log.info("DRY RUN - Signal: %s  reason=%s", sig.signal_type, sig.reason)
                        except Exception as e:
                            log.error("DRY RUN failed for strategy %s: %s", strat.name, str(e))
                            notify_strategy_execution(
                                strategy_name=strat.name,
                                execution_time=datetime.now(),
                                signal=sig.signal_type,
                                indicators={
                                    **sig.indicators,
                                    'current_pos': pos,
                                    'reason': sig.reason,
                                    'dry_run': True
                                },
                                error=str(e)
                            )
                    else:
                        strat.execute()
                except Exception as e:
                    log.exception("Strategy '%s' failed", strat.name)
                    
                    # Send error notification
                    notify_strategy_execution(
                        strategy_name=strat.name,
                        execution_time=datetime.now(),
                        error=str(e),
                        indicators={}
                    )

    except ConnectionError:
        log.critical("Could not connect to IBKR - aborting")
        sys.exit(1)
    except Exception as e:
        log.exception("Unexpected error in main: %s", str(e))
    finally:
        try:
            broker.disconnect()
        except:
            pass  # Broker might not be initialized
        db.close()

    log.info("ALL STRATEGIES COMPLETE")


if __name__ == "__main__":
    main()
