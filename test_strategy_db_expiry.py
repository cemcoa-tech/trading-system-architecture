#!/usr/bin/env python3
"""
test_strategy_db_expiry.py
──────────────────────────
Demonstration of how strategies can read expiries from the database.

This shows how to modify strategy parameter classes to use database expiries
instead of hardcoded values in settings.py.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent))

from utils.expiry_reader import ExpiryReader
from config.settings import Gold2Params, MESCubeHLCParams


def test_gold2_with_db_expiry():
    """Test Gold2Params with database expiry."""
    print("=== Testing Gold2Params with Database Expiry ===")
    
    # Create original params
    original_params = Gold2Params()
    print(f"Original contract_month: {original_params.contract_month}")
    
    # Update with database expiry
    reader = ExpiryReader()
    success = reader.update_strategy_params(original_params)
    
    if success:
        print(f"Updated contract_month: {original_params.contract_month}")
        print(f"Updated last_trade_date: {original_params.contract_spec.last_trade_date}")
        
        # Verify ContractSpec is also updated
        spec = original_params.contract_spec
        print(f"ContractSpec: {spec.symbol} -> {spec.last_trade_date}")
    else:
        print("Failed to update with database expiry")
    
    return success


def test_mes_with_db_expiry():
    """Test MESCubeHLCParams with database expiry."""
    print("\n=== Testing MESCubeHLCParams with Database Expiry ===")
    
    # Create original params
    original_params = MESCubeHLCParams()
    print(f"Original contract_month: {original_params.contract_month}")
    
    # Update with database expiry
    reader = ExpiryReader()
    success = reader.update_strategy_params(original_params)
    
    if success:
        print(f"Updated contract_month: {original_params.contract_month}")
        print(f"Updated last_trade_date: {original_params.contract_spec.last_trade_date}")
        
        # Verify ContractSpec is also updated
        spec = original_params.contract_spec
        print(f"ContractSpec: {spec.symbol} -> {spec.last_trade_date}")
    else:
        print("Failed to update with database expiry")
    
    return success


def demonstrate_strategy_usage():
    """Demonstrate how strategies would use database expiries in practice."""
    print("\n=== Strategy Usage Example ===")
    
    reader = ExpiryReader()
    
    # Example: Strategy getting its current expiry
    gold_expiry = reader.get_strategy_expiry("Gold2Params")
    if gold_expiry:
        print(f"Gold2 strategy current expiry: {gold_expiry.trade_expiry_yyyymm}")
        print(f"Days to expiry: {gold_expiry.days_to_expiry}")
        print(f"Last updated: {gold_expiry.updated_at}")
    
    # Example: Strategy getting symbol expiry for ContractSpec
    gc_expiry = reader.get_contract_spec_expiry("GC")
    if gc_expiry:
        print(f"GC ContractSpec should use expiry: {gc_expiry}")
    
    # Example: Strategy checking if it needs to roll
    if gold_expiry and gold_expiry.days_to_expiry <= 5:
        print("WARNING: Gold2 strategy needs to roll soon!")
    else:
        print(f"Gold2 strategy has {gold_expiry.days_to_expiry if gold_expiry else 'unknown'} days to expiry")


def main():
    """Main test function."""
    print("Database Expiry Integration Test")
    print("=" * 50)
    
    # Test individual strategies
    gold_success = test_gold2_with_db_expiry()
    mes_success = test_mes_with_db_expiry()
    
    # Demonstrate practical usage
    demonstrate_strategy_usage()
    
    # Summary
    print("\n=== Summary ===")
    print(f"Gold2Params DB update: {'✓' if gold_success else '✗'}")
    print(f"MESCubeHLCParams DB update: {'✓' if mes_success else '✗'}")
    
    if gold_success and mes_success:
        print("\n✓ All strategies can successfully use database expiries!")
        print("✓ Ready to replace hardcoded expiries in settings.py")
    else:
        print("\n✗ Some strategies failed to update with database expiries")
    
    return gold_success and mes_success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
