#!/usr/bin/env python3
"""
run_mes_xgboost.py
──────────────────
Runner script for MES XGBoost Ensemble Strategy
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from config.settings import IBKRConfig, MES_XGBOOST_PARAMS
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.mes_xgboost_ensemble import MESXGBoostEnsembleStrategy
from utils.logger import get_logger

log = get_logger("main.mes_xgboost")


def main():
    """Execute MES XGBoost Ensemble strategy."""
    log.info("=" * 70)
    log.info("MES XGBOOST ENSEMBLE STRATEGY - EXECUTION START")
    log.info("=" * 70)
    
    ibkr_cfg = IBKRConfig()
    db = DatabaseManager()
    broker = Broker(ibkr_cfg)
    order_mgr = OrderManager(broker.ib, db)
    
    try:
        log.info("Connecting to IBKR...")
        broker.connect()
        log.info(f"✅ Connected to IBKR (account: {ibkr_cfg.account})")
        
        strategy = MESXGBoostEnsembleStrategy(
            params=MES_XGBOOST_PARAMS,
            broker=broker,
            order_mgr=order_mgr,
            db=db,
            account=ibkr_cfg.account,
        )
        
        log.info(f"Executing strategy: {strategy.name}")
        strategy.execute()
        
        log.info("=" * 70)
        log.info("MES XGBOOST ENSEMBLE STRATEGY - EXECUTION COMPLETE")
        log.info("=" * 70)
        
    except KeyboardInterrupt:
        log.warning("Execution interrupted by user")
    except Exception as e:
        log.error(f"Strategy execution failed: {e}", exc_info=True)
        raise
    finally:
        log.info("Disconnecting from IBKR...")
        broker.disconnect()
        log.info("✅ Disconnected")


if __name__ == "__main__":
    main()
