#!/usr/bin/env python3
"""
migrate_all_changes.py
Complete migration script for all database changes made during RB strategy development.
Run this script on your server after pushing code changes.
"""

import sqlite3
import sys
from pathlib import Path

def run_migrations(db_path: str) -> None:
    """Run all database migrations."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"Running migrations on: {db_path}")
        
        # Migration 1: Add atr_entry column to trades table
        try:
            cursor.execute("SELECT atr_entry FROM trades LIMIT 1")
            print("✅ atr_entry column already exists")
        except sqlite3.OperationalError:
            cursor.execute("""
                ALTER TABLE trades 
                ADD COLUMN atr_entry REAL DEFAULT 0.0
            """)
            print("✅ Added atr_entry column to trades table")
        
        # Migration 2: Add bars_held column to trades table  
        try:
            cursor.execute("SELECT bars_held FROM trades LIMIT 1")
            print("✅ bars_held column already exists")
        except sqlite3.OperationalError:
            cursor.execute("""
                ALTER TABLE trades 
                ADD COLUMN bars_held INTEGER DEFAULT 0
            """)
            print("✅ Added bars_held column to trades table")
        
        # Commit all changes
        conn.commit()
        conn.close()
        
        print("🎉 All migrations completed successfully!")
        return None
        
    except sqlite3.Error as e:
        print(f"❌ Migration error: {e}")
        return e
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return e

def verify_migrations(db_path: str) -> None:
    """Verify that all migrations were applied correctly."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check trades table schema
        cursor.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]
        
        required_columns = ['atr_entry', 'bars_held']
        missing_columns = [col for col in required_columns if col not in columns]
        
        if missing_columns:
            print(f"❌ Missing columns: {missing_columns}")
            return False
        else:
            print("✅ All required columns present in trades table")
            
        # Check if we can query the new columns
        cursor.execute("SELECT COUNT(*) FROM trades WHERE atr_entry IS NOT NULL AND bars_held IS NOT NULL")
        count = cursor.fetchone()[0]
        print(f"✅ Successfully queried new columns: {count} trades with non-null values")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Verification error: {e}")
        return False

if __name__ == "__main__":
    db_path = "data/trading.db"
    
    if len(sys.argv) > 1:
        db_path = sys.argv[1]
    
    # Convert relative path to absolute
    if not Path(db_path).is_absolute():
        db_path = str(Path(__file__).parent.parent / db_path)
    
    print(f"Database path: {db_path}")
    
    # Run migrations
    result = run_migrations(db_path)
    
    if result is None:
        # Verify migrations
        if verify_migrations(db_path):
            print("🎯 All migrations verified successfully!")
            sys.exit(0)
        else:
            print("❌ Migration verification failed!")
            sys.exit(1)
    else:
        sys.exit(1)
