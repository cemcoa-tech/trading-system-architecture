# utils/oi_cache.py
# ───────────────────────────────────────────────────────────────────────────
# Caches Open Interest and Volume data from IBKR for use outside RTH
# ───────────────────────────────────────────────────────────────────────────

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

# Cache file location
CACHE_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_FILE = CACHE_DIR / "oi_cache.json"

def _ensure_cache_dir():
    """Ensure cache directory exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def load_oi_cache() -> Dict:
    """Load cached OI data from file."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}

def save_oi_cache(cache: Dict):
    """Save OI data to cache file."""
    _ensure_cache_dir()
    with open(CACHE_FILE, 'w') as f:
        json.dump(cache, f, indent=2, default=str)

def get_cached_oi_volume(symbol: str, expiry: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Get cached OI and Volume for a symbol/expiry.
    
    Returns (oi, volume) tuple or (None, None) if not cached.
    """
    cache = load_oi_cache()
    key = f"{symbol}_{expiry}"
    
    if key not in cache:
        return None, None
    
    entry = cache[key]
    cached_time = datetime.fromisoformat(entry.get('timestamp', '2000-01-01'))
    
    # Cache valid for 24 hours
    if datetime.now() - cached_time > timedelta(hours=24):
        return None, None
    
    return entry.get('oi'), entry.get('volume')

def update_oi_cache(symbol: str, expiry: str, oi: int, volume: int):
    """
    Update cache with new OI/Volume data.
    Called when markets are open and we get real data from IBKR.
    """
    cache = load_oi_cache()
    key = f"{symbol}_{expiry}"
    
    cache[key] = {
        'symbol': symbol,
        'expiry': expiry,
        'oi': oi,
        'volume': volume,
        'timestamp': datetime.now().isoformat()
    }
    
    save_oi_cache(cache)

def get_oi_with_fallback(
    symbol: str,
    expiry: str,
    current_oi: int,
    current_volume: int
) -> Tuple[int, int, str]:
    """
    Get OI/Volume with fallback to cache when current data is 0.
    
    Args:
        symbol: Futures symbol (e.g., "RB", "GC")
        expiry: Expiry string (e.g., "20260630")
        current_oi: Current OI from IBKR (may be 0 outside RTH)
        current_volume: Current Volume from IBKR (may be 0 outside RTH)
    
    Returns:
        Tuple of (oi, volume, source)
        where source is "live", "cached", or "zero"
    """
    # If we have live data, cache it and return
    if current_oi > 0 or current_volume > 0:
        update_oi_cache(symbol, expiry, current_oi, current_volume)
        return current_oi, current_volume, "live"
    
    # Try to get from cache
    cached_oi, cached_vol = get_cached_oi_volume(symbol, expiry)
    
    if cached_oi is not None or cached_vol is not None:
        # Use cached values (default to 0 if one is missing)
        return cached_oi or 0, cached_vol or 0, "cached"
    
    # No data available
    return 0, 0, "zero"

def clear_cache():
    """Clear all cached OI data."""
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()

def get_cache_status() -> Dict:
    """Get status of all cached entries."""
    cache = load_oi_cache()
    result = {}
    now = datetime.now()
    
    for key, entry in cache.items():
        cached_time = datetime.fromisoformat(entry.get('timestamp', '2000-01-01'))
        age_hours = (now - cached_time).total_seconds() / 3600
        result[key] = {
            'symbol': entry.get('symbol'),
            'expiry': entry.get('expiry'),
            'oi': entry.get('oi'),
            'volume': entry.get('volume'),
            'age_hours': round(age_hours, 1),
            'valid': age_hours <= 24
        }
    
    return result

if __name__ == "__main__":
    # Test the cache
    print("Testing OI Cache...")
    
    # Update with dummy data
    update_oi_cache("RB", "20260630", 15000, 2500)
    update_oi_cache("GC", "202606", 80000, 12000)
    
    # Read back
    oi, vol, source = get_oi_with_fallback("RB", "20260630", 0, 0)
    print(f"RB (simulated outside RTH): OI={oi}, Volume={vol}, Source={source}")
    
    # Live data simulation
    oi, vol, source = get_oi_with_fallback("RB", "20260630", 15500, 2800)
    print(f"RB (simulated live): OI={oi}, Volume={vol}, Source={source}")
    
    # Show cache status
    print("\nCache Status:")
    for key, status in get_cache_status().items():
        print(f"  {key}: OI={status['oi']}, Vol={status['volume']}, Age={status['age_hours']}h, Valid={status['valid']}")
