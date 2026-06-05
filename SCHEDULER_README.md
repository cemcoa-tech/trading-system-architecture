# OI Cache Scheduler - Quick Reference

## Files Created

| File | Purpose |
|------|---------|
| `run_oi_cache_update.py` | Main script - updates OI cache from IBKR |
| `run_oi_cache_update.bat` | Windows batch wrapper |
| `setup_oi_cache_scheduler.ps1` | PowerShell script to create Task Scheduler job |
| `SCHEDULE_OI_CACHE.md` | Detailed setup guide |
| `utils/oi_cache.py` | Cache module (created earlier) |

## Quick Setup (3 Steps)

### 1. Run Once Now (Test)

```bash
cd C:\Users\USER\Desktop\trading-system-architecture
C:\Users\USER\anaconda3\python.exe run_oi_cache_update.py
```

Or double-click: `run_oi_cache_update.bat`

### 2. Setup Scheduled Task (Run as Admin)

```powershell
# Right-click PowerShell → Run as Administrator
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
cd C:\Users\USER\Desktop\trading-system-architecture
.\setup_oi_cache_scheduler.ps1
```

### 3. Verify

```bash
# Check cache contents
python -c "from utils.oi_cache import get_cache_status; import json; print(json.dumps(get_cache_status(), indent=2))"
```

## Manual Commands

### Run now (only during market hours)
```bash
python run_oi_cache_update.py
```

### Run with specific symbols
```bash
python run_oi_cache_update.py --symbols RB GC ES
```

### Force run even outside market hours (records 0s)
```bash
python run_oi_cache_update.py --force
```

### Use alternative IBKR account
```bash
python run_oi_cache_update.py --alt-account
```

### View cache status
```bash
python -c "from utils.oi_cache import get_cache_status; import json; print(json.dumps(get_cache_status(), indent=2))"
```

### Clear cache
```bash
python -c "from utils.oi_cache import clear_cache; clear_cache(); print('Cache cleared')"
```

## What It Does

1. **Connects to IBKR** (requires TWS/Gateway running)
2. **Queries OI/Volume** for all configured symbols
3. **Stores in cache** at `data/oi_cache.json`
4. **Available for 24 hours** for strategy runs outside RTH

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot connect to IBKR" | Start TWS/Gateway first |
| "No contracts found" | Market may be closed, use `--force` |
| Task not running | Check Windows Event Viewer → Application logs |
| OI still 0 in strategies | Run cache update during market hours first |

## Schedule

The scheduler runs **3 times daily**:
- **10:30 AM EST** - Post-open liquidity
- **1:00 PM EST** - Mid-day peak volume  
- **3:00 PM EST** - Pre-close final capture

## Cache Expiration

- Cache entries valid for **24 hours**
- After 24 hours, entries ignored but kept
- Running the cache update refreshes all entries

## Symbols Configured

Default symbols (edit in `run_oi_cache_update.py`):
- RB (RBOB Gasoline) - NYMEX
- GC (Gold) - COMEX
- ES (E-mini S&P) - CME
- NQ (E-mini Nasdaq) - CME
- MES (Micro E-mini S&P) - CME
- MNQ (Micro E-mini Nasdaq) - CME
- MGC (Micro Gold) - COMEX
- CL (Crude Oil) - NYMEX
- ZN (10-Year Treasury) - CBOT
- ZB (30-Year Treasury) - CBOT
- MBT (Micro Bitcoin) - CME
- Z (Corn) - CBOT

## Support

- Full guide: `SCHEDULE_OI_CACHE.md`
- Logs: `logs/trading_framework.log`
- Cache file: `data/oi_cache.json`
