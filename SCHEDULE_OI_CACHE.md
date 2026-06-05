# OI Cache Scheduler Setup Guide

## Overview

Schedule `run_oi_cache_update.py` to run during market hours to populate the OI/Volume cache. This ensures your strategies always have OI data even when running outside regular trading hours.

## Quick Start (Run Now)

```bash
# Run once during market hours to populate cache
C:\Users\USER\anaconda3\python.exe run_oi_cache_update.py

# Or use the batch file
run_oi_cache_update.bat
```

## Windows Task Scheduler Setup

### Option 1: Create Task via Command Line (PowerShell - Admin)

```powershell
# Run as Administrator
$action = New-ScheduledTaskAction -Execute "C:\Users\USER\anaconda3\python.exe" -Argument "run_oi_cache_update.py" -WorkingDirectory "C:\Users\USER\Desktop\trading-system-architecture"

# Trigger: Daily at 10:30 AM, 1:00 PM, and 3:00 PM EST
$trigger1 = New-ScheduledTaskTrigger -Daily -At "10:30 AM"
$trigger2 = New-ScheduledTaskTrigger -Daily -At "1:00 PM"
$trigger3 = New-ScheduledTaskTrigger -Daily -At "3:00 PM"

# Settings
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Create task
Register-ScheduledTask -TaskName "Trading OI Cache Update" -Action $action -Trigger $trigger1,$trigger2,$trigger3 -Settings $settings -Description "Populates OI/Volume cache for trading strategies"
```

### Option 2: Manual GUI Setup

1. **Open Task Scheduler**
   - Press `Win + R`, type `taskschd.msc`, press Enter

2. **Create Basic Task**
   - Click "Create Basic Task" in right panel
   - Name: `Trading OI Cache Update`
   - Description: `Populates OI/Volume cache for trading strategies`
   - Click Next

3. **Set Triggers**
   - Choose "Daily"
   - Start: Today's date
   - Recur every: 1 days
   - Click Next

4. **Set Action**
   - Choose "Start a program"
   - Program/script: `C:\Users\USER\anaconda3\python.exe`
   - Add arguments: `run_oi_cache_update.py`
   - Start in: `C:\Users\USER\Desktop\trading-system-architecture`
   - Click Next

5. **Add Multiple Triggers** (Important!)
   - After creation, find the task in the list
   - Right-click → Properties
   - Go to "Triggers" tab
   - Click "New" to add additional times:
     - 10:30 AM
     - 1:00 PM
     - 3:00 PM

6. **Configure Settings**
   - Go to "Settings" tab
   - Check: "Allow task to be run on demand"
   - Check: "Run task as soon as possible after a scheduled start is missed"
   - Check: "If the task fails, restart every: 10 minutes"
   - Uncheck: "Stop the task if it runs longer than"

7. **Security Options**
   - Go to "General" tab
   - Select "Run whether user is logged on or not"
   - Check "Run with highest privileges"
   - Click OK, enter your password when prompted

## Schedule Times Explained

| Time | Purpose |
|------|---------|
| **10:30 AM EST** | Post-open liquidity establishment |
| **1:00 PM EST** | Mid-day update (volume peaks around noon) |
| **3:00 PM EST** | Pre-close capture (final OI for day) |

## Verification

### Check if cache is populated:

```bash
# View cache status
python -c "from utils.oi_cache import get_cache_status; import json; print(json.dumps(get_cache_status(), indent=2))"

# Or run a quick test
python run_oi_cache_update.py --symbols RB GC --force
```

### Expected output during market hours:

```
[OI-CACHE] Connected to IBKR 127.0.0.1:4001
[OI-CACHE] Processing RB on NYMEX...
[OI-CACHE] Found 12 contracts for RB
[OI-CACHE]   RBN6 (20260630): OI=15,234, Volume=3,421
[OI-CACHE]   RBQ6 (20260731): OI=8,934, Volume=2,100
...
[OI-CACHE] OI CACHE UPDATE COMPLETE
```

## Troubleshooting

### Task not running?

1. Check Event Viewer: `Windows Logs` → `Application`
2. Verify Python path: `C:\Users\USER\anaconda3\python.exe --version`
3. Test manually: Run `run_oi_cache_update.bat` from command line
4. Check IBKR TWS/Gateway is running and accepting connections

### OI still 0 after running?

- **Problem**: Markets closed when task ran
- **Solution**: Task only updates during market hours (9:30 AM - 4:00 PM EST)
- **Force run**: `python run_oi_cache_update.py --force` (will record 0 values)

### Missing some symbols?

Edit `DEFAULT_SYMBOLS` in `run_oi_cache_update.py`:

```python
DEFAULT_SYMBOLS = [
    ("RB", "NYMEX"),
    ("GC", "COMEX"),
    # Add your symbols here
    ("YOUR_SYMBOL", "EXCHANGE"),
]
```

### Task runs but no cache file created?

Check that `data/` directory exists and is writable:

```bash
# Test write permissions
python -c "from utils.oi_cache import update_oi_cache; update_oi_cache('TEST', '202606', 1000, 500)"

# Should create: data/oi_cache.json
```

## Alternative: Run via Startup Script

If Task Scheduler is problematic, add to your trading startup batch:

```batch
@echo off
REM In your run_morning_trading.bat or similar

cd C:\Users\USER\Desktop\trading-system-architecture

REM Update OI cache first (only runs during market hours)
python run_oi_cache_update.py

REM Then run your strategies
python main.py --strategy rb
python main.py --strategy gold
...
```

## Logs Location

Cache update logs go to: `logs/trading_framework.log`

Filter for OI cache entries:
```bash
type logs\trading_framework.log | findstr "OI-CACHE"
```

## Unschedule / Remove Task

```powershell
Unregister-ScheduledTask -TaskName "Trading OI Cache Update" -Confirm:$false
```

Or via GUI: Task Scheduler → Find task → Right-click → Delete

## Best Practices

1. **Run TWS/Gateway before market open** (9:00 AM) so it's ready
2. **Keep cache fresh**: Don't go more than 24 hours between updates
3. **Monitor logs**: Check weekly that OI data is being captured
4. **Backup cache**: The `data/oi_cache.json` file is portable - back it up

## Cache File Format

The cache is stored in `data/oi_cache.json`:

```json
{
  "RB_20260630": {
    "symbol": "RB",
    "expiry": "20260630",
    "oi": 15234,
    "volume": 3421,
    "timestamp": "2026-06-02T10:30:15"
  },
  ...
}
```

Entries expire after 24 hours. Old entries are ignored but not deleted.
