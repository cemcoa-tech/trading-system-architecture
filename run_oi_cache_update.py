#!/usr/bin/env python3
"""
run_oi_cache_update.py
───────────────────────────────────────────────────────────────────────────
Scheduled job to populate OI/Volume cache during market hours.

Run this 1-3 times per day during trading hours:
  - 10:30 AM EST (after open)
  - 1:00 PM EST (mid-day)
  - 3:00 PM EST (before close)

This ensures fresh OI data is available when running strategies outside RTH.

Usage:
    python run_oi_cache_update.py

Windows Task Scheduler Setup:
    1. Open Task Scheduler
    2. Create Basic Task
    3. Name: "Trading OI Cache Update"
    4. Trigger: Daily at 10:30 AM, 1:00 PM, 3:00 PM
    5. Action: Start Program
       - Program: C:\Users\USER\anaconda3\python.exe
       - Arguments: run_oi_cache_update.py
       - Start in: C:\Users\USER\Desktop\trading-system-architecture
"""

import sys
import argparse
from datetime import datetime, time
from typing import List, Dict

from ib_insync import IB, Future, ContractDetails

# Add project to path
sys.path.insert(0, str(__file__).rsplit('\\', 1)[0])

from config.settings import IBKRConfig, IBKRConfigAlt
from utils.oi_cache import update_oi_cache, get_cache_status
from utils.logger import get_logger

log = get_logger("oi_cache_update")

# Symbols to cache OI for (edit this list as needed)
DEFAULT_SYMBOLS = [
    ("RB", "NYMEX"),   # RBOB Gasoline
    ("GC", "COMEX"),   # Gold
    ("ES", "CME"),     # E-mini S&P
    ("NQ", "CME"),     # E-mini Nasdaq
    ("MES", "CME"),    # Micro E-mini S&P
    ("MNQ", "CME"),    # Micro E-mini Nasdaq
    ("MGC", "COMEX"),  # Micro Gold
    ("CL", "NYMEX"),   # Crude Oil
    ("ZN", "CBOT"),    # 10-Year Treasury
    ("ZB", "CBOT"),    # 30-Year Treasury
    ("MBT", "CME"),    # Micro Bitcoin
    ("Z", "CBOT"),     # Corn
]


def is_market_hours() -> bool:
    """Check if currently within typical futures trading hours (9:30 AM - 4:00 PM EST)."""
    now = datetime.now().time()
    market_open = time(9, 30)
    market_close = time(16, 0)  # 4:00 PM
    return market_open <= now <= market_close


def connect_to_ibkr(config) -> IB:
    """Connect to IBKR with given config."""
    ib = IB()
    try:
        ib.connect(
            host=config.host,
            port=config.port,
            clientId=config.client_id,
            timeout=config.connect_timeout
        )
        log.info(f"Connected to IBKR {config.host}:{config.port} (clientId={config.client_id})")
        return ib
    except Exception as e:
        log.error(f"Failed to connect to IBKR: {e}")
        raise


def fetch_contract_oi(ib: IB, symbol: str, exchange: str) -> Dict:
    """
    Fetch OI and Volume for all available expiries of a symbol.
    
    Returns dict of expiry -> {oi, volume, local_symbol}
    """
    results = {}
    
    try:
        log.info(f"Querying {symbol} on {exchange}...")
        base_contract = Future(symbol=symbol, exchange=exchange, currency="USD")
        all_details = ib.reqContractDetails(base_contract)
        
        if not all_details:
            log.warning(f"No contracts found for {symbol}")
            return results
        
        log.info(f"Found {len(all_details)} contracts for {symbol}")
        
        for det in all_details:
            ct = det.contract
            expiry_str = ct.lastTradeDateOrContractMonth
            
            if not expiry_str:
                continue
            
            # Parse expiry date
            try:
                if len(expiry_str) == 6:
                    from datetime import datetime as dt
                    expiry_date = dt.strptime(expiry_str, "%Y%m")
                elif len(expiry_str) == 8:
                    from datetime import datetime as dt
                    expiry_date = dt.strptime(expiry_str, "%Y%m%d")
                else:
                    continue
            except ValueError:
                continue
            
            # Only cache contracts expiring in next 180 days
            from datetime import datetime as dt, timedelta
            if (expiry_date - dt.now()).days > 180:
                continue
            
            # Get OI and Volume
            oi = det.openInterest if hasattr(det, "openInterest") else 0
            volume = det.volume if hasattr(det, "volume") else 0
            
            results[expiry_str] = {
                "symbol": symbol,
                "exchange": exchange,
                "expiry": expiry_str,
                "local_symbol": ct.localSymbol,
                "oi": oi,
                "volume": volume,
            }
            
        log.info(f"Cached OI data for {len(results)} {symbol} contracts")
        
    except Exception as e:
        log.error(f"Error fetching OI for {symbol}: {e}")
    
    return results


def update_cache_for_symbols(ib: IB, symbols: List[tuple]) -> Dict:
    """
    Update OI cache for all specified symbols.
    
    Returns summary of what was updated.
    """
    total_updated = 0
    total_skipped = 0
    summary = {}
    
    for symbol, exchange in symbols:
        log.info(f"\n{'='*50}")
        log.info(f"Processing {symbol} on {exchange}")
        log.info(f"{'='*50}")
        
        contracts = fetch_contract_oi(ib, symbol, exchange)
        
        if not contracts:
            log.warning(f"No OI data retrieved for {symbol}")
            total_skipped += 1
            summary[symbol] = {"status": "no_data", "contracts": 0}
            continue
        
        updated_count = 0
        for expiry, data in contracts.items():
            # Only cache if we have some data (or it's zero but we want to record it)
            update_oi_cache(symbol, expiry, data["oi"], data["volume"])
            log.info(f"  {data['local_symbol']} ({expiry}): OI={data['oi']:,}, Volume={data['volume']:,}")
            updated_count += 1
        
        total_updated += updated_count
        summary[symbol] = {
            "status": "updated",
            "contracts": updated_count,
            "total_oi": sum(c["oi"] for c in contracts.values()),
            "total_volume": sum(c["volume"] for c in contracts.values()),
        }
    
    return {
        "total_symbols": len(symbols),
        "symbols_updated": sum(1 for s in summary.values() if s["status"] == "updated"),
        "symbols_skipped": sum(1 for s in summary.values() if s["status"] == "no_data"),
        "total_contracts_updated": total_updated,
        "details": summary,
    }


def main():
    parser = argparse.ArgumentParser(description="Update OI/Volume cache from IBKR")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even outside market hours (for testing)"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        help="Specific symbols to update (e.g., RB GC ES)"
    )
    parser.add_argument(
        "--alt-account",
        action="store_true",
        help="Use alternative IBKR account (U20859646)"
    )
    
    args = parser.parse_args()
    
    log.info("=" * 60)
    log.info("OI CACHE UPDATE JOB STARTING")
    log.info("=" * 60)
    log.info(f"Timestamp: {datetime.now().isoformat()}")
    
    # Check market hours (unless forced)
    if not args.force and not is_market_hours():
        log.warning("Outside market hours (9:30 AM - 4:00 PM EST)")
        log.warning("Use --force to run anyway, or wait for market hours")
        log.info("Exiting - cache not updated")
        return 1
    
    # Determine symbols to update
    if args.symbols:
        # Map symbols to their exchanges
        symbol_map = {s: e for s, e in DEFAULT_SYMBOLS}
        symbols = [(s, symbol_map.get(s, "CME")) for s in args.symbols]
    else:
        symbols = DEFAULT_SYMBOLS
    
    log.info(f"Will update OI cache for {len(symbols)} symbols: {[s[0] for s in symbols]}")
    
    # Connect to IBKR
    config = IBKRConfigAlt() if args.alt_account else IBKRConfig()
    ib = connect_to_ibkr(config)
    
    try:
        # Update cache
        summary = update_cache_for_symbols(ib, symbols)
        
        # Show final cache status
        log.info("\n" + "=" * 60)
        log.info("CACHE UPDATE COMPLETE - SUMMARY")
        log.info("=" * 60)
        log.info(f"Symbols processed: {summary['total_symbols']}")
        log.info(f"Symbols updated: {summary['symbols_updated']}")
        log.info(f"Symbols skipped (no data): {summary['symbols_skipped']}")
        log.info(f"Total contracts cached: {summary['total_contracts_updated']}")
        
        # Show per-symbol details
        log.info("\nPer-symbol details:")
        for sym, data in summary["details"].items():
            if data["status"] == "updated":
                log.info(f"  {sym}: {data['contracts']} contracts, "
                        f"Total OI={data['total_oi']:,}, Total Vol={data['total_volume']:,}")
            else:
                log.info(f"  {sym}: No data retrieved")
        
        # Show current cache status
        log.info("\nCurrent cache entries:")
        cache_status = get_cache_status()
        for key, entry in sorted(cache_status.items()):
            log.info(f"  {key}: OI={entry['oi']:,}, Vol={entry['volume']:,}, "
                    f"Age={entry['age_hours']:.1f}h, Valid={entry['valid']}")
        
        log.info("\n" + "=" * 60)
        log.info("OI CACHE UPDATE COMPLETE")
        log.info("=" * 60)
        
        return 0
        
    except Exception as e:
        log.error(f"Error during cache update: {e}", exc_info=True)
        return 1
        
    finally:
        if ib.isConnected():
            ib.disconnect()
            log.info("Disconnected from IBKR")


if __name__ == "__main__":
    sys.exit(main())
