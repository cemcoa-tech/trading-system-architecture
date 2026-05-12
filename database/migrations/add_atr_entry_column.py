#!/usr/bin/env python3
"""
add_atr_entry_column.py
Migration script to add atr_entry column to trades table.
"""

import sqlite3
import sys
from pathlib import Path

def add_atr_entry_column(db_path: str) -> None:
    """Add atr_entry column to trades table."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Add atr_entry column to trades table
        cursor.execute("""
            ALTER TABLE trades 
            ADD COLUMN atr_entry REAL DEFAULT 0.0
        """)
        
        conn.commit()
        conn.close()
        
        print("✅ Successfully added atr_entry column to trades table")
        return None
        
    except sqlite3.Error as e:
        print(f"❌ Error adding atr_entry column: {e}")
        return e
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return e

if __name__ == "__main__":
    db_path = "data/trading.db"
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    # Convert relative path to absolute
    if not Path(db_path).is_absolute():
        db_path = str(Path(__file__).parent.parent / db_path)
    
    print(f"Adding atr_entry column to: {db_path}")
    result = add_atr_entry_column(db_path)
    
    if result is None:
        sys.exit(0)
    else:
        sys.exit(1)
