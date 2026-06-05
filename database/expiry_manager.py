"""
database/expiry_manager.py

Database manager for strategy contract expiries.
Stores and retrieves optimal contract expiries based on volume analysis.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExpiryRecord:
    """Record for a strategy's contract expiry information."""
    strategy_name: str
    symbol: str
    exchange: str
    currency: str
    trade_expiry_yyyymm: str
    data_expiry_yyyymm: str
    trade_expiry_full: str  # YYYYMMDD format
    data_expiry_full: str   # YYYYMMDD format
    volume: int
    days_to_expiry: int
    updated_at: datetime
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for database operations."""
        return {
            'strategy_name': self.strategy_name,
            'symbol': self.symbol,
            'exchange': self.exchange,
            'currency': self.currency,
            'trade_expiry_yyyymm': self.trade_expiry_yyyymm,
            'data_expiry_yyyymm': self.data_expiry_yyyymm,
            'trade_expiry_full': self.trade_expiry_full,
            'data_expiry_full': self.data_expiry_full,
            'volume': self.volume,
            'days_to_expiry': self.days_to_expiry,
            'updated_at': self.updated_at.isoformat()
        }


class ExpiryManager:
    """Database manager for strategy expiries."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
        
    def init_database(self):
        """Initialize the expiries table if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS strategy_expiries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    trade_expiry_yyyymm TEXT NOT NULL,
                    data_expiry_yyyymm TEXT NOT NULL,
                    trade_expiry_full TEXT NOT NULL,
                    data_expiry_full TEXT NOT NULL,
                    volume INTEGER NOT NULL,
                    days_to_expiry INTEGER NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    UNIQUE(strategy_name, symbol)
                )
            ''')
            
            # Create indexes for performance
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_strategy_symbol 
                ON strategy_expiries(strategy_name, symbol)
            ''')
            
            conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_updated_at 
                ON strategy_expiries(updated_at)
            ''')
            
            conn.commit()
            
    def save_expiry(self, record: ExpiryRecord) -> bool:
        """Save or update an expiry record."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT OR REPLACE INTO strategy_expiries 
                    (strategy_name, symbol, exchange, currency, 
                     trade_expiry_yyyymm, data_expiry_yyyymm,
                     trade_expiry_full, data_expiry_full,
                     volume, days_to_expiry, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.strategy_name,
                    record.symbol,
                    record.exchange,
                    record.currency,
                    record.trade_expiry_yyyymm,
                    record.data_expiry_yyyymm,
                    record.trade_expiry_full,
                    record.data_expiry_full,
                    record.volume,
                    record.days_to_expiry,
                    record.updated_at.isoformat()
                ))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving expiry record: {e}")
            return False
            
    def get_expiry(self, strategy_name: str, symbol: str) -> Optional[ExpiryRecord]:
        """Get a specific expiry record."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM strategy_expiries 
                    WHERE strategy_name = ? AND symbol = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                ''', (strategy_name, symbol))
                
                row = cursor.fetchone()
                if row:
                    return ExpiryRecord(
                        strategy_name=row['strategy_name'],
                        symbol=row['symbol'],
                        exchange=row['exchange'],
                        currency=row['currency'],
                        trade_expiry_yyyymm=row['trade_expiry_yyyymm'],
                        data_expiry_yyyymm=row['data_expiry_yyyymm'],
                        trade_expiry_full=row['trade_expiry_full'],
                        data_expiry_full=row['data_expiry_full'],
                        volume=row['volume'],
                        days_to_expiry=row['days_to_expiry'],
                        updated_at=datetime.fromisoformat(row['updated_at'])
                    )
                return None
        except Exception as e:
            print(f"Error getting expiry record: {e}")
            return None
            
    def get_all_expiries(self) -> List[ExpiryRecord]:
        """Get all expiry records."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM strategy_expiries 
                    ORDER BY strategy_name, symbol
                ''')
                
                records = []
                for row in cursor.fetchall():
                    records.append(ExpiryRecord(
                        strategy_name=row['strategy_name'],
                        symbol=row['symbol'],
                        exchange=row['exchange'],
                        currency=row['currency'],
                        trade_expiry_yyyymm=row['trade_expiry_yyyymm'],
                        data_expiry_yyyymm=row['data_expiry_yyyymm'],
                        trade_expiry_full=row['trade_expiry_full'],
                        data_expiry_full=row['data_expiry_full'],
                        volume=row['volume'],
                        days_to_expiry=row['days_to_expiry'],
                        updated_at=datetime.fromisoformat(row['updated_at'])
                    ))
                return records
        except Exception as e:
            print(f"Error getting all expiry records: {e}")
            return []
            
    def get_expiries_by_symbol(self, symbol: str) -> List[ExpiryRecord]:
        """Get all expiry records for a specific symbol."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM strategy_expiries 
                    WHERE symbol = ?
                    ORDER BY updated_at DESC
                ''', (symbol,))
                
                records = []
                for row in cursor.fetchall():
                    records.append(ExpiryRecord(
                        strategy_name=row['strategy_name'],
                        symbol=row['symbol'],
                        exchange=row['exchange'],
                        currency=row['currency'],
                        trade_expiry_yyyymm=row['trade_expiry_yyyymm'],
                        data_expiry_yyyymm=row['data_expiry_yyyymm'],
                        trade_expiry_full=row['trade_expiry_full'],
                        data_expiry_full=row['data_expiry_full'],
                        volume=row['volume'],
                        days_to_expiry=row['days_to_expiry'],
                        updated_at=datetime.fromisoformat(row['updated_at'])
                    ))
                return records
        except Exception as e:
            print(f"Error getting expiries by symbol: {e}")
            return []
            
    def delete_old_records(self, days_to_keep: int = 30) -> int:
        """Delete old expiry records beyond the specified days."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('''
                    DELETE FROM strategy_expiries 
                    WHERE updated_at < datetime('now', '-{} days')
                '''.format(days_to_keep))
                
                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count
        except Exception as e:
            print(f"Error deleting old records: {e}")
            return 0
            
    def export_to_csv(self, file_path: str) -> bool:
        """Export all expiry records to CSV file."""
        try:
            import csv
            
            records = self.get_all_expiries()
            
            with open(file_path, 'w', newline='') as csvfile:
                fieldnames = [
                    'strategy_name', 'symbol', 'exchange', 'currency',
                    'trade_expiry_yyyymm', 'data_expiry_yyyymm',
                    'trade_expiry_full', 'data_expiry_full',
                    'volume', 'days_to_expiry', 'updated_at'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for record in records:
                    writer.writerow(record.to_dict())
                    
            return True
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return False
            
    def print_summary_table(self):
        """Print a formatted summary table of all expiries."""
        records = self.get_all_expiries()
        
        if not records:
            print("No expiry records found.")
            return
            
        print("\n" + "="*100)
        print("STRATEGY EXPIRY SUMMARY TABLE")
        print("="*100)
        print(f"{'Strategy':<25} {'Symbol':<8} {'Exchange':<8} {'Trade Exp':<8} {'Data Exp':<8} {'Volume':<10} {'Days':<6} {'updatedOn':<20}")
        print("-"*100)
        
        for record in records:
            print(f"{record.strategy_name:<25} {record.symbol:<8} {record.exchange:<8} "
                  f"{record.trade_expiry_yyyymm:<8} {record.data_expiry_yyyymm:<8} "
                  f"{record.volume:<10,} {record.days_to_expiry:<6} "
                  f"{record.updated_at.strftime('%Y-%m-%d %H:%M'):<20}")
                  
        print("="*100)
        print(f"Total records: {len(records)}")
        print("="*100 + "\n")
