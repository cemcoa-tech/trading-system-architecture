#!/usr/bin/env python3
"""
update_strategy_expiries.py

Automated expiry updater for all trading strategies.

This script:
1. Connects to IBKR and fetches all strategy symbols
2. Retrieves historical volume data for each symbol's available contracts
3. Determines the optimal expiry (highest recent volume) for each symbol
4. Updates settings.py with new expiries for both data and trading contracts
5. Designed to run 1 hour before main trading systems via task scheduler

Usage:
    python update_strategy_expiries.py [--dry-run] [--verbose]

Dependencies:
    - ib_insync
    - pandas
    - datetime
"""

import argparse
import asyncio
import logging
import sys
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import pandas as pd

# Initialize event loop before importing ib_insync
if __name__ == "__main__":
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Future, util

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent))

from config.settings import (
    IBKRConfig, 
    MGC_SPEC, ES_SPEC, MNQ_SPEC,
    MNQCondition1Params, MESCondition1Params, BTCRSIParams, BTC2Params,
    TreasuryEOMParams, Treasury30YEOMParams, TreasuryStochHurstParams,
    RBCombinedParams, Gold2Params, CornVolatilityParams
)
from utils.expiry_selector import resolve_front_month


@dataclass
class SymbolConfig:
    """Configuration for a symbol's expiry update."""
    symbol: str
    exchange: str
    currency: str
    strategy_names: List[str]
    data_symbol: Optional[str] = None
    special_handling: Optional[str] = None  # For special cases like TreasuryStochHurst


class ExpiryUpdater:
    """Main class for updating strategy expiries based on volume data."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.ib = IB()
        self.settings_path = Path(__file__).parent / "config" / "settings.py"
        self.backup_path = self.settings_path.with_suffix(".py.backup")
        
        # Setup logging
        self.setup_logging()
        
        # Define all symbols to update
        self.symbols = self._get_all_symbols()
        
        # Results storage
        self.updates: Dict[str, Dict[str, str]] = {}
        
    def setup_logging(self):
        """Setup logging configuration."""
        log_level = logging.DEBUG if self.verbose else logging.INFO
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s | %(levelname)-8s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(
                    f"expiry_update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                )
            ]
        )
        self.log = logging.getLogger(__name__)
        
    def _get_all_symbols(self) -> List[SymbolConfig]:
        """Extract all unique symbols from strategy parameters."""
        symbols = []
        
        # Strategy parameter classes
        strategy_classes = [
            (MNQCondition1Params, ["MNQ_Condition1"]),
            (MESCondition1Params, ["MES_Condition1"]),
            (BTCRSIParams, ["BTC_RSI_MeanRev"]),
            (BTC2Params, ["BTC_ValueLow_RSI"]),
            (TreasuryEOMParams, ["Treasury_ZN_EOM"]),
            (Treasury30YEOMParams, ["Treasury_30Y_EOM"]),
            (TreasuryStochHurstParams, ["Treasury_Stoch_Hurst"]),
            (RBCombinedParams, ["RB_Combined"]),
            (Gold2Params, ["Gold2"]),
            (CornVolatilityParams, ["Corn_Volatility"]),
        ]
        
        # Also check standalone specs
        standalone_specs = [
            (MGC_SPEC, ["mgc_pullback"]),
            (ES_SPEC, []),  # ES is used in multiple places, handled below
            (MNQ_SPEC, []),  # MNQ is used in multiple places, handled below
        ]
        
        for strategy_class, strategy_names in strategy_classes:
            try:
                params = strategy_class()
                symbol = params.symbol
                
                # Skip if already processed
                if any(s.symbol == symbol for s in symbols):
                    existing = next(s for s in symbols if s.symbol == symbol)
                    existing.strategy_names.extend(strategy_names)
                    continue
                    
                # Handle special cases
                data_symbol = getattr(params, 'data_symbol', symbol)
                special_handling = None
                
                if strategy_class == TreasuryStochHurstParams:
                    special_handling = "treasury_dual_contract"
                    data_symbol = params.signal_symbol  # ZB for signals
                    
                symbols.append(SymbolConfig(
                    symbol=symbol,
                    exchange=params.exchange,
                    currency=params.currency,
                    strategy_names=strategy_names,
                    data_symbol=data_symbol,
                    special_handling=special_handling
                ))
                
            except Exception as e:
                self.log.warning(f"Failed to process {strategy_class.__name__}: {e}")
                
        # Add standalone specs
        for spec, strategy_names in standalone_specs:
            if strategy_names:  # Only add if actually used
                symbols.append(SymbolConfig(
                    symbol=spec.symbol,
                    exchange=spec.exchange,
                    currency=spec.currency,
                    strategy_names=strategy_names,
                    data_symbol=getattr(spec, 'data_symbol', spec.symbol)
                ))
                
        self.log.info(f"Found {len(symbols)} unique symbols to update")
        for sym in symbols:
            self.log.debug(f"  {sym.symbol}: {sym.strategy_names} (data: {sym.data_symbol})")
            
        return symbols
        
    def connect_to_ibkr(self) -> bool:
        """Connect to IBKR with retry logic."""
        config = IBKRConfig()
        
        for attempt in range(config.max_retries):
            try:
                self.log.info(f"Connecting to IBKR (attempt {attempt + 1}/{config.max_retries})")
                self.ib.connect(
                    host=config.host,
                    port=config.port,
                    clientId=config.client_id,
                    timeout=config.connect_timeout
                )
                
                # Wait for connection to be ready
                util.sleep(1)
                if self.ib.isConnected():
                    self.log.info("Successfully connected to IBKR")
                    return True
                    
            except Exception as e:
                self.log.warning(f"Connection attempt {attempt + 1} failed: {e}")
                if attempt < config.max_retries - 1:
                    util.sleep(config.retry_delay)
                    
        self.log.error("Failed to connect to IBKR after all attempts")
        return False
        
    def resolve_symbol_expiry(self, symbol: str, exchange: str, currency: str) -> Optional[str]:
        """
        Resolve the best expiry for a symbol using volume data.
        
        Returns expiry in YYYYMMDD format or None if failed.
        """
        try:
            self.log.debug(f"Resolving expiry for {symbol} on {exchange}")
            
            # Use existing resolve_front_month function
            expiry = resolve_front_month(
                ib=self.ib,
                symbol=symbol,
                exchange=exchange,
                currency=currency,
                min_days_to_expiry=4,
                max_days_to_expiry=180
            )
            
            if expiry:
                self.log.info(f"Resolved {symbol} expiry: {expiry}")
                return expiry
            else:
                self.log.warning(f"Failed to resolve expiry for {symbol}")
                return None
                
        except Exception as e:
            self.log.error(f"Error resolving expiry for {symbol}: {e}")
            return None
            
    def backup_settings_file(self):
        """Create backup of settings.py before making changes."""
        if not self.dry_run:
            try:
                content = self.settings_path.read_text()
                self.backup_path.write_text(content)
                self.log.info(f"Created backup: {self.backup_path}")
            except Exception as e:
                self.log.error(f"Failed to create backup: {e}")
                raise
                
    def read_settings_content(self) -> str:
        """Read current settings.py content."""
        try:
            return self.settings_path.read_text()
        except Exception as e:
            self.log.error(f"Failed to read settings.py: {e}")
            raise
            
    def update_settings_content(self, content: str, updates: Dict[str, Dict[str, str]]) -> str:
        """Update settings.py content with new expiries."""
        updated_content = content
        
        for symbol, expiry_data in updates.items():
            new_expiry = expiry_data['trade_expiry']
            
            # Try to update contract_month in parameter classes first
            pattern_contract_month = r'(symbol:\s*=\s*["\']' + symbol + r'["\'][\s\S]*?contract_month:\s*["\'])\d{6}(["\'])'
            replacement_contract_month = r'\1' + new_expiry + r'\2'
            
            updated_contract_month = False
            if re.search(pattern_contract_month, updated_content, re.DOTALL):
                updated_content = re.sub(pattern_contract_month, replacement_contract_month, updated_content, flags=re.DOTALL)
                self.log.debug(f"Updated {symbol} contract_month to {new_expiry}")
                updated_contract_month = True
            
            # Also try to update last_trade_date in ContractSpec definitions
            pattern_last_trade_date = r'(symbol:\s*=\s*["\']' + symbol + r'["\'][\s\S]*?last_trade_date:\s*["\'])\d{6}(["\'])'
            replacement_last_trade_date = r'\1' + new_expiry + r'\2'
            
            updated_last_trade_date = False
            if re.search(pattern_last_trade_date, updated_content, re.DOTALL):
                updated_content = re.sub(pattern_last_trade_date, replacement_last_trade_date, updated_content, flags=re.DOTALL)
                self.log.debug(f"Updated {symbol} last_trade_date to {new_expiry}")
                updated_last_trade_date = True
            
            if not updated_contract_month and not updated_last_trade_date:
                self.log.warning(f"Could not find contract_month or last_trade_date pattern for {symbol}")
                
            # Update data_last_trade_date if different (for ContractSpec usage)
            if 'data_expiry' in expiry_data and expiry_data['data_expiry'] != new_expiry:
                data_expiry = expiry_data['data_expiry']
                # Look for data_last_trade_date in the same block as the symbol
                pattern_data = r'(symbol:\s*=\s*["\']' + symbol + r'["\'][\s\S]*?data_last_trade_date:\s*["\'])\d{6}(["\'])'
                replacement_data = r'\1' + data_expiry + r'\2'
                
                if re.search(pattern_data, updated_content, re.DOTALL):
                    updated_content = re.sub(pattern_data, replacement_data, updated_content, flags=re.DOTALL)
                    self.log.debug(f"Updated {symbol} data_last_trade_date to {data_expiry}")
                    
        return updated_content
        
    def write_settings_content(self, content: str):
        """Write updated content to settings.py."""
        if not self.dry_run:
            try:
                self.settings_path.write_text(content)
                self.log.info("Successfully updated settings.py")
            except Exception as e:
                self.log.error(f"Failed to write settings.py: {e}")
                raise
        else:
            self.log.info("DRY RUN: Would write updated settings.py")
            
    def run(self) -> bool:
        """Main execution method."""
        self.log.info("Starting expiry update process")
        self.log.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE UPDATE'}")
        
        try:
            # Connect to IBKR
            if not self.connect_to_ibkr():
                return False
                
            # Resolve expiries for all symbols
            for symbol_config in self.symbols:
                self.log.info(f"Processing {symbol_config.symbol}")
                
                # Resolve trade contract expiry
                trade_expiry = self.resolve_symbol_expiry(
                    symbol_config.symbol,
                    symbol_config.exchange,
                    symbol_config.currency
                )
                
                if not trade_expiry:
                    self.log.error(f"Failed to resolve trade expiry for {symbol_config.symbol}")
                    continue
                    
                # Resolve data contract expiry if different
                data_expiry = trade_expiry
                if symbol_config.data_symbol != symbol_config.symbol:
                    data_expiry = self.resolve_symbol_expiry(
                        symbol_config.data_symbol,
                        symbol_config.exchange,
                        symbol_config.currency
                    )
                    
                    if not data_expiry:
                        self.log.warning(f"Failed to resolve data expiry for {symbol_config.data_symbol}, using trade expiry")
                        data_expiry = trade_expiry
                        
                # Store updates
                self.updates[symbol_config.symbol] = {
                    'trade_expiry': trade_expiry,
                    'data_expiry': data_expiry,
                    'strategies': symbol_config.strategy_names
                }
                
                self.log.info(f"{symbol_config.symbol} -> Trade: {trade_expiry}, Data: {data_expiry}")
                
            # Display summary
            self.log.info("\n=== EXPIRY UPDATE SUMMARY ===")
            for symbol, data in self.updates.items():
                strategies_str = ", ".join(data['strategies']) if data['strategies'] else "Standalone"
                self.log.info(f"{symbol}: Trade={data['trade_expiry']}, Data={data['data_expiry']} ({strategies_str})")
                
            if not self.updates:
                self.log.warning("No updates to apply")
                return True
                
            # Update settings file
            if not self.dry_run:
                self.backup_settings_file()
                
            content = self.read_settings_content()
            updated_content = self.update_settings_content(content, self.updates)
            self.write_settings_content(updated_content)
            
            self.log.info("Expiry update process completed successfully")
            return True
            
        except Exception as e:
            self.log.error(f"Expiry update process failed: {e}")
            return False
            
        finally:
            if self.ib.isConnected():
                self.ib.disconnect()
                self.log.info("Disconnected from IBKR")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Update strategy expiries based on volume data"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    updater = ExpiryUpdater(dry_run=args.dry_run, verbose=args.verbose)
    success = updater.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
