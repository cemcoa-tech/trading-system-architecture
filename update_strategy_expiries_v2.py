#!/usr/bin/env python3
"""
update_strategy_expiries_v2.py

Simplified expiry updater that directly updates known parameter classes.
This version uses a more targeted approach to update specific parameter classes.
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
    RBCombinedParams, Gold2Params, CornVolatilityParams,
    DB_PATH
)
from utils.expiry_selector import resolve_front_month
from database.expiry_manager import ExpiryManager, ExpiryRecord


@dataclass
class ExpiryUpdate:
    """Configuration for updating a specific parameter class."""
    param_class: type
    symbol_field: str = "symbol"
    expiry_field: str = "contract_month"
    data_expiry_field: Optional[str] = None


class ExpiryUpdaterV2:
    """Simplified expiry updater using targeted parameter class updates."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False):
        self.dry_run = dry_run
        self.verbose = verbose
        self.ib = IB()
        self.settings_path = Path(__file__).parent / "config" / "settings.py"
        self.backup_path = self.settings_path.with_suffix(".py.backup")
        
        # Setup logging
        self.setup_logging()
        
        # Initialize database manager
        self.expiry_manager = ExpiryManager(DB_PATH)
        
        # Define parameter classes to update
        self.param_updates = [
            ExpiryUpdate(MNQCondition1Params),
            ExpiryUpdate(MESCondition1Params),
            ExpiryUpdate(BTCRSIParams),
            ExpiryUpdate(BTC2Params),
            ExpiryUpdate(TreasuryEOMParams),
            ExpiryUpdate(Treasury30YEOMParams),
            ExpiryUpdate(TreasuryStochHurstParams, data_expiry_field="signal_contract_month"),
            ExpiryUpdate(RBCombinedParams),
            ExpiryUpdate(Gold2Params),
            ExpiryUpdate(CornVolatilityParams),
        ]
        
        # Also update standalone specs
        self.spec_updates = [
            ("MGC_SPEC", "GC"),
            ("ES_SPEC", "ES"),
            ("MNQ_SPEC", "NQ"),
        ]
        
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
                    f"expiry_update_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
                )
            ]
        )
        self.log = logging.getLogger(__name__)
        
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
        """Resolve the best expiry for a symbol using volume data."""
        try:
            self.log.debug(f"Resolving expiry for {symbol} on {exchange}")
            
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
            
    def get_param_class_info(self, param_class: type) -> Tuple[str, str, str, Optional[str]]:
        """Extract symbol, exchange, currency from parameter class instance."""
        try:
            params = param_class()
            symbol = getattr(params, 'symbol')
            exchange = getattr(params, 'exchange')
            currency = getattr(params, 'currency')
            data_symbol = getattr(params, 'data_symbol', None)
            return symbol, exchange, currency, data_symbol
        except Exception as e:
            self.log.error(f"Failed to get info from {param_class.__name__}: {e}")
            return None, None, None, None
            
    def save_expiries_to_database(self):
        """Save all resolved expiries to the database."""
        saved_count = 0
        failed_count = 0
        
        for key, expiry_data in self.updates.items():
            try:
                # Get strategy name and symbol info
                if key.endswith('_SPEC'):
                    # Handle ContractSpec updates
                    strategy_name = key.replace('_SPEC', '_spec')
                    symbol = expiry_data['symbol']
                    
                    # Get exchange info from the spec
                    if key == "MGC_SPEC":
                        exchange = MGC_SPEC.exchange
                    elif key == "ES_SPEC":
                        exchange = ES_SPEC.exchange
                    elif key == "MNQ_SPEC":
                        exchange = MNQ_SPEC.exchange
                    else:
                        exchange = "CME"
                else:
                    # Handle parameter class updates
                    strategy_name = key
                    symbol = expiry_data['symbol']
                    
                    # Get exchange from parameter class
                    symbol, exchange, currency, data_symbol = self.get_param_class_info_from_name(key)
                
                # Create expiry record
                record = ExpiryRecord(
                    strategy_name=strategy_name,
                    symbol=symbol,
                    exchange=exchange,
                    currency='USD',  # Default to USD
                    trade_expiry_yyyymm=expiry_data['trade_expiry'][:6] if len(expiry_data['trade_expiry']) == 8 else expiry_data['trade_expiry'],
                    data_expiry_yyyymm=expiry_data['data_expiry'][:6] if len(expiry_data['data_expiry']) == 8 else expiry_data['data_expiry'],
                    trade_expiry_full=expiry_data['trade_expiry'],
                    data_expiry_full=expiry_data['data_expiry'],
                    volume=0,  # Would need to capture this from resolve_front_month
                    days_to_expiry=0,  # Would need to capture this from resolve_front_month
                    updated_at=datetime.now(timezone.utc)
                )
                
                # Save to database
                if self.expiry_manager.save_expiry(record):
                    saved_count += 1
                    self.log.info(f"Saved expiry for {strategy_name} ({symbol}): Trade={record.trade_expiry_yyyymm}, Data={record.data_expiry_yyyymm}")
                else:
                    failed_count += 1
                    self.log.error(f"Failed to save expiry for {strategy_name} ({symbol})")
                    
            except Exception as e:
                failed_count += 1
                self.log.error(f"Error processing {key}: {e}")
                
        self.log.info(f"Database save complete: {saved_count} saved, {failed_count} failed")
        
        # Display summary table
        if not self.dry_run:
            self.expiry_manager.print_summary_table()
            
    def get_param_class_info_from_name(self, class_name: str) -> Tuple[str, str, str, Optional[str]]:
        """Get symbol, exchange, currency from parameter class name."""
        try:
            # Map class names to their actual classes
            class_map = {
                'MNQCondition1Params': MNQCondition1Params,
                'MESCondition1Params': MESCondition1Params,
                'BTCRSIParams': BTCRSIParams,
                'BTC2Params': BTC2Params,
                'TreasuryEOMParams': TreasuryEOMParams,
                'Treasury30YEOMParams': Treasury30YEOMParams,
                'TreasuryStochHurstParams': TreasuryStochHurstParams,
                'RBCombinedParams': RBCombinedParams,
                'Gold2Params': Gold2Params,
                'CornVolatilityParams': CornVolatilityParams,
            }
            
            if class_name in class_map:
                params = class_map[class_name]()
                return getattr(params, 'symbol'), getattr(params, 'exchange'), getattr(params, 'currency'), getattr(params, 'data_symbol', None)
            else:
                return None, None, None, None
                
        except Exception as e:
            self.log.error(f"Failed to get info from {class_name}: {e}")
            return None, None, None, None
            
    # Commented out settings.py methods - now using database instead
    """
    def backup_settings_file(self):
        '''Create backup of settings.py before making changes.'''
        if not self.dry_run:
            try:
                content = self.settings_path.read_text()
                self.backup_path.write_text(content)
                self.log.info(f"Created backup: {self.backup_path}")
            except Exception as e:
                self.log.error(f"Failed to create backup: {e}")
                raise
                
    def read_settings_content(self) -> str:
        '''Read current settings.py content.'''
        try:
            return self.settings_path.read_text()
        except Exception as e:
            self.log.error(f"Failed to read settings.py: {e}")
            raise
            
    def update_parameter_class(self, content: str, class_name: str, expiry: str, data_expiry: Optional[str] = None) -> str:
        '''Update a specific parameter class's expiry fields.'''
        # Implementation commented out - using database instead
        return content
        
    def update_contract_spec(self, content: str, spec_name: str, expiry: str) -> str:
        '''Update a ContractSpec's last_trade_date.'''
        # Implementation commented out - using database instead
        return content
        
    def write_settings_content(self, content: str):
        '''Write updated content to settings.py.'''
        if not self.dry_run:
            self.log.info("DRY RUN: Settings.py updates disabled - using database instead")
        else:
            self.log.info("DRY RUN: Would save to database instead of updating settings.py")
    """
            
    def run(self) -> bool:
        """Main execution method."""
        self.log.info("Starting expiry update process (V2)")
        self.log.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE UPDATE'}")
        
        try:
            # Connect to IBKR
            if not self.connect_to_ibkr():
                return False
                
            # Resolve expiries for parameter classes
            for param_update in self.param_updates:
                symbol, exchange, currency, data_symbol = self.get_param_class_info(param_update.param_class)
                
                if not symbol:
                    continue
                    
                self.log.info(f"Processing {param_update.param_class.__name__} ({symbol})")
                
                # Resolve trade contract expiry
                trade_expiry = self.resolve_symbol_expiry(symbol, exchange, currency)
                
                if not trade_expiry:
                    self.log.error(f"Failed to resolve trade expiry for {symbol}")
                    continue
                    
                # Resolve data contract expiry if different
                data_expiry = trade_expiry
                if data_symbol and data_symbol != symbol:
                    data_expiry = self.resolve_symbol_expiry(data_symbol, exchange, currency)
                    
                    if not data_expiry:
                        self.log.warning(f"Failed to resolve data expiry for {data_symbol}, using trade expiry")
                        data_expiry = trade_expiry
                        
                # Store updates
                self.updates[param_update.param_class.__name__] = {
                    'trade_expiry': trade_expiry,
                    'data_expiry': data_expiry,
                    'symbol': symbol
                }
                
                self.log.info(f"{param_update.param_class.__name__} ({symbol}) -> Trade: {trade_expiry}, Data: {data_expiry}")
                
            # Resolve expiries for standalone specs
            for spec_name, symbol in self.spec_updates:
                self.log.info(f"Processing {spec_name} ({symbol})")
                
                # Get exchange from the spec
                if spec_name == "MGC_SPEC":
                    exchange = MGC_SPEC.exchange
                elif spec_name == "ES_SPEC":
                    exchange = ES_SPEC.exchange
                elif spec_name == "MNQ_SPEC":
                    exchange = MNQ_SPEC.exchange
                else:
                    exchange = "CME"  # default
                    
                expiry = self.resolve_symbol_expiry(symbol, exchange, "USD")
                
                if not expiry:
                    self.log.error(f"Failed to resolve expiry for {spec_name}")
                    continue
                    
                self.updates[spec_name] = {
                    'trade_expiry': expiry,
                    'data_expiry': expiry,
                    'symbol': symbol
                }
                
                self.log.info(f"{spec_name} ({symbol}) -> {expiry}")
                
            # Display summary
            self.log.info("\n=== EXPIRY UPDATE SUMMARY ===")
            for key, data in self.updates.items():
                self.log.info(f"{key} ({data['symbol']}): Trade={data['trade_expiry']}, Data={data['data_expiry']}")
                
            if not self.updates:
                self.log.warning("No updates to apply")
                return True
                
            # Save to database instead of updating settings.py
            self.save_expiries_to_database()
            
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
        description="Update strategy expiries using targeted parameter class updates"
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
    
    updater = ExpiryUpdaterV2(dry_run=args.dry_run, verbose=args.verbose)
    success = updater.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
