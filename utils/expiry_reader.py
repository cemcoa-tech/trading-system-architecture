#!/usr/bin/env python3
"""
utils/expiry_reader.py
──────────────────────
Utility for strategies to read current expiry information from the database.

This replaces the need for strategies to read expiry dates from settings.py.
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from config.settings import DB_PATH
from database.expiry_manager import ExpiryManager, ExpiryRecord


@dataclass
class StrategyExpiry:
    """Expiry information for a strategy."""
    strategy_name: str
    symbol: str
    exchange: str
    currency: str
    trade_expiry_yyyymm: str
    data_expiry_yyyymm: str
    trade_expiry_yyyymmdd: str
    data_expiry_yyyymmdd: str
    volume: int
    days_to_expiry: int
    updated_at: str


class ExpiryReader:
    """
    Utility class for strategies to read current expiry information from the database.
    
    Usage in strategy:
        from utils.expiry_reader import ExpiryReader
        
        reader = ExpiryReader()
        expiry = reader.get_strategy_expiry("Gold2Params")
        if expiry:
            contract_month = expiry.trade_expiry_yyyymm
    """
    
    def __init__(self, db_path: str = None):
        """Initialize expiry reader with database path."""
        self.db_path = db_path or DB_PATH
        self.manager = ExpiryManager(self.db_path)
    
    def get_strategy_expiry(self, strategy_name: str) -> Optional[StrategyExpiry]:
        """
        Get current expiry information for a specific strategy.
        
        Args:
            strategy_name: Name of the strategy (e.g., "Gold2Params")
            
        Returns:
            StrategyExpiry object or None if not found
        """
        # First try to find the strategy in all expiries to get the symbol
        all_records = self.manager.get_all_expiries()
        for record in all_records:
            if record.strategy_name == strategy_name:
                return StrategyExpiry(
                    strategy_name=record.strategy_name,
                    symbol=record.symbol,
                    exchange=record.exchange,
                    currency=record.currency,
                    trade_expiry_yyyymm=record.trade_expiry_yyyymm,
                    data_expiry_yyyymm=record.data_expiry_yyyymm,
                    trade_expiry_yyyymmdd=record.trade_expiry_full,
                    data_expiry_yyyymmdd=record.data_expiry_full,
                    volume=record.volume,
                    days_to_expiry=record.days_to_expiry,
                    updated_at=record.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                )
        return None
    
    def get_symbol_expiry(self, symbol: str) -> Optional[StrategyExpiry]:
        """
        Get current expiry information for a specific symbol.
        
        Args:
            symbol: Symbol (e.g., "GC", "MES")
            
        Returns:
            StrategyExpiry object or None if not found
        """
        records = self.manager.get_expiries_by_symbol(symbol)
        if not records:
            return None
        
        # Return the first (most recent) record for the symbol
        record = records[0]
        return StrategyExpiry(
            strategy_name=record.strategy_name,
            symbol=record.symbol,
            exchange=record.exchange,
            currency=record.currency,
            trade_expiry_yyyymm=record.trade_expiry_yyyymm,
            data_expiry_yyyymm=record.data_expiry_yyyymm,
            trade_expiry_yyyymmdd=record.trade_expiry_full,
            data_expiry_yyyymmdd=record.data_expiry_full,
            volume=record.volume,
            days_to_expiry=record.days_to_expiry,
            updated_at=record.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
        )
    
    def get_all_expiries(self) -> Dict[str, StrategyExpiry]:
        """
        Get all expiry information from the database.
        
        Returns:
            Dictionary mapping strategy names to StrategyExpiry objects
        """
        records = self.manager.get_all_expiries()
        expiries = {}
        
        for record in records:
            expiry = StrategyExpiry(
                strategy_name=record.strategy_name,
                symbol=record.symbol,
                exchange=record.exchange,
                currency=record.currency,
                trade_expiry_yyyymm=record.trade_expiry_yyyymm,
                data_expiry_yyyymm=record.data_expiry_yyyymm,
                trade_expiry_yyyymmdd=record.trade_expiry_full,
                data_expiry_yyyymmdd=record.data_expiry_full,
                volume=record.volume,
                days_to_expiry=record.days_to_expiry,
                updated_at=record.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
            )
            expiries[record.strategy_name] = expiry
        
        return expiries
    
    def update_strategy_params(self, strategy_params_class) -> bool:
        """
        Update a strategy parameters class with current expiry from database.
        
        This method dynamically updates the contract_month field in the strategy
        parameters class based on the database expiry.
        
        Args:
            strategy_params_class: Strategy parameters class (e.g., Gold2Params)
            
        Returns:
            True if updated successfully, False otherwise
        """
        strategy_name = strategy_params_class.name
        expiry = self.get_strategy_expiry(strategy_name)
        
        if not expiry:
            print(f"Warning: No expiry found for strategy {strategy_name}")
            return False
        
        # Update the contract_month field
        if hasattr(strategy_params_class, 'contract_month'):
            strategy_params_class.contract_month = expiry.trade_expiry_yyyymm
            print(f"Updated {strategy_name}.contract_month to {expiry.trade_expiry_yyyymm}")
            return True
        else:
            print(f"Warning: Strategy {strategy_name} does not have contract_month field")
            return False
    
    def get_contract_spec_expiry(self, symbol: str) -> Optional[str]:
        """
        Get expiry date for ContractSpec objects.
        
        Args:
            symbol: Symbol (e.g., "GC", "NQ")
            
        Returns:
            Expiry date in YYYYMM format or None if not found
        """
        expiry = self.get_symbol_expiry(symbol)
        if expiry:
            return expiry.trade_expiry_yyyymm
        return None


def test_expiry_reader():
    """Test function to verify expiry reader functionality."""
    print("Testing ExpiryReader...")
    
    reader = ExpiryReader()
    
    # Test getting all expiries
    all_expiries = reader.get_all_expiries()
    print(f"Found {len(all_expiries)} expiries in database")
    
    # Test getting specific strategy expiry
    gold_expiry = reader.get_strategy_expiry("Gold2Params")
    if gold_expiry:
        print(f"Gold2Params expiry: {gold_expiry.trade_expiry_yyyymm}")
    
    # Test getting symbol expiry
    gc_expiry = reader.get_symbol_expiry("GC")
    if gc_expiry:
        print(f"GC symbol expiry: {gc_expiry.trade_expiry_yyyymm}")
    
    # Test ContractSpec expiry
    gc_spec_expiry = reader.get_contract_spec_expiry("GC")
    if gc_spec_expiry:
        print(f"GC ContractSpec expiry: {gc_spec_expiry}")
    
    print("ExpiryReader test complete!")


if __name__ == "__main__":
    test_expiry_reader()
