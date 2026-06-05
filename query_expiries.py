#!/usr/bin/env python3
"""
query_expiries.py

Simple script to query and display strategy expiries from the database.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent))

from config.settings import DB_PATH
from database.expiry_manager import ExpiryManager


def main():
    """Main function to query and display expiries."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Query strategy expiries from database")
    parser.add_argument("--strategy", help="Filter by strategy name")
    parser.add_argument("--symbol", help="Filter by symbol")
    parser.add_argument("--export", help="Export to CSV file")
    parser.add_argument("--table", action="store_true", help="Show formatted table")
    
    args = parser.parse_args()
    
    # Initialize database manager
    manager = ExpiryManager(DB_PATH)
    
    if args.strategy:
        # Query by strategy
        records = [manager.get_expiry(args.strategy, args.symbol)] if args.symbol else []
        if not records or not records[0]:
            print(f"No records found for strategy: {args.strategy}")
            return
    elif args.symbol:
        # Query by symbol
        records = manager.get_expiries_by_symbol(args.symbol)
        if not records:
            print(f"No records found for symbol: {args.symbol}")
            return
    else:
        # Get all records
        records = manager.get_all_expiries()
        if not records:
            print("No expiry records found in database.")
            return
    
    # Export to CSV if requested
    if args.export:
        if manager.export_to_csv(args.export):
            print(f"Exported {len(records)} records to {args.export}")
        else:
            print("Failed to export to CSV")
        return
    
    # Display results
    if args.table or not args.strategy and not args.symbol:
        manager.print_summary_table()
    else:
        # Simple list display
        for record in records:
            print(f"{record.strategy_name} ({record.symbol}): Trade={record.trade_expiry_yyyymm}, Data={record.data_expiry_yyyymm}")


if __name__ == "__main__":
    main()
