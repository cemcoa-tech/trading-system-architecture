# Strategy Expiry Updater

Automated system for updating futures contract expiries across all trading strategies based on historical volume analysis.

## Overview

This system automatically:
1. Connects to IBKR and fetches all strategy symbols
2. Retrieves historical volume data for available contracts
3. Determines optimal expiry (highest recent volume) for each symbol
4. Updates `settings.py` with new expiries for both data and trading contracts
5. Designed to run 1 hour before main trading systems via task scheduler

## Files

- **`update_strategy_expiries_v2.py`** - Main Python script (production version)
- **`update_expiries_production.bat`** - Windows Task Scheduler batch file
- **`update_expiries.bat`** - Development/testing batch file
- **`EXPIRY_UPDATER_README.md`** - This documentation

## Supported Strategies

| Strategy | Symbol | Exchange | Data Symbol | Notes |
|----------|--------|----------|-------------|-------|
| MNQ_Condition1 | NQ | CME | NQ | Micro Nasdaq 100 |
| MES_Condition1 | ES | GLOBEX | ES | Micro S&P 500 |
| BTC_RSI_MeanRev | MBT | CME | MBT | Micro Bitcoin |
| BTC_ValueLow_RSI | MBT | CME | MBT | Micro Bitcoin |
| Treasury_ZN_EOM | ZN | CBOT | ZN | 10-Year Treasury |
| Treasury_30Y_EOM | ZB | CBOT | ZB | 30-Year Treasury |
| Treasury_Stoch_Hurst | MWN | CBOT | ZB | Micro 30-Year Note (trades MWN, signals ZB) |
| RB_Combined | RB | NYMEX | RB | RBOB Gasoline |
| Gold2 | GC | COMEX | GC | Gold futures |
| Corn_Volatility | ZC | CBOT | ZC | Corn futures |
| mgc_pullback | GC | COMEX | GC | Gold futures (standalone) |

## Usage

### Development/Testing
```bash
# Dry run - shows what would be updated without making changes
python update_strategy_expiries_v2.py --dry-run

# Verbose dry run with detailed logging
python update_strategy_expiries_v2.py --dry-run --verbose
```

### Production
```bash
# Live update - actually modifies settings.py
python update_strategy_expiries_v2.py

# Or use the production batch file
update_expiries_production.bat
```

## Windows Task Scheduler Setup

1. **Open Task Scheduler** (taskschd.msc)
2. **Create Basic Task** with these settings:
   - **Name**: "Trading Strategy Expiry Updater"
   - **Trigger**: Daily, 1 hour before trading systems
   - **Action**: Start a program
   - **Program**: `C:\Users\USER\Desktop\trading-system-architecture\update_expiries_production.bat`
   - **Start in**: `C:\Users\USER\Desktop\trading-system-architecture`

3. **Advanced Settings**:
   - ✅ Run whether user is logged on or not
   - ✅ Run with highest privileges
   - ✅ Stop if runs longer than: 10 minutes
   - ✅ If the task is already running: Do not start a new instance

## Prerequisites

1. **IBKR Connection**: Gateway or TWS must be running
2. **Market Data Subscriptions**: Required for all symbols
3. **Python Environment**: All required packages installed
4. **Write Permissions**: Ability to modify `settings.py`

## Safety Features

### Backup System
- Automatic backup of `settings.py` before any changes
- Backup saved as `settings.py.backup`
- Timestamped log files for all runs

### Error Handling
- Connection retry logic (3 attempts with 5s delay)
- Graceful handling of missing symbols/contracts
- Detailed error logging
- Exit codes for batch file integration

### Validation
- Volume-based expiry selection (4-180 days forward)
- Minimum volume thresholds
- Exchange and currency validation
- Contract qualification verification

## Log Files

Logs are saved with timestamp format: `expiry_update_YYYYMMDD_HHMMSS.log`

### Log Levels
- **INFO**: Normal operation, expiry resolutions
- **WARNING**: Non-critical issues, fallbacks used
- **ERROR**: Critical failures, update aborted
- **DEBUG**: Detailed debugging (use --verbose)

### Log Location
- Development: Current directory
- Production: `logs\` subdirectory

## Example Output

```
=== EXPIRY UPDATE SUMMARY ===
MNQCondition1Params (NQ): Trade=20260618, Data=20260618
MESCondition1Params (ES): Trade=20260618, Data=20260618
BTCRSIParams (MBT): Trade=20260626, Data=20260626
TreasuryEOMParams (ZN): Trade=20260921, Data=20260921
Treasury30YEOMParams (ZB): Trade=20260921, Data=20260921
TreasuryStochHurstParams (MWN): Trade=20260828, Data=20260828
RBCombinedParams (RB): Trade=20260630, Data=20260630
Gold2Params (GC): Trade=20260827, Data=20260827
CornVolatilityParams (ZC): Trade=20260714, Data=20260714
MGC_SPEC (GC): Trade=20260827, Data=20260827
MNQ_SPEC (NQ): Trade=20260618, Data=20260618
```

## Troubleshooting

### Common Issues

1. **"No security definition found"**
   - Symbol may not be available on specified exchange
   - Check exchange name (CME vs GLOBEX vs CBOT)
   - Verify market data subscriptions

2. **"Failed to resolve expiry"**
   - No valid contracts found in date range
   - Market data subscription issue
   - Symbol may be delisted or expired

3. **"Could not find pattern"**
   - Settings.py structure has changed
   - Parameter class renamed
   - Contact developer to update regex patterns

### Recovery

If `settings.py` becomes corrupted:
1. Restore from backup: `copy settings.py.backup settings.py`
2. Check log file for what went wrong
3. Run with `--dry-run` to validate fixes
4. Contact support if issues persist

## Configuration

### IBKR Settings
Edit `IBKRConfig` in `config/settings.py`:
```python
@dataclass(frozen=True)
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4001
    client_id: int = 8935
    account: str = "U22862141"
    connect_timeout: float = 15.0
    max_retries: int = 3
    retry_delay: float = 5.0
```

### Expiry Resolution Parameters
Modify in `resolve_front_month()` call:
- `min_days_to_expiry`: 4 (default)
- `max_days_to_expiry`: 180 (default)

## Maintenance

### Monthly
- Review log files for patterns
- Check backup retention
- Validate IBKR subscriptions

### Quarterly
- Update symbol list if new strategies added
- Review exchange changes
- Test disaster recovery

## Support

For issues or questions:
1. Check log files for error details
2. Verify IBKR connection and subscriptions
3. Test with `--dry-run --verbose` first
4. Contact development team with logs and error details

---

**Version**: 2.0  
**Last Updated**: 2026-06-04  
**Compatibility**: Python 3.8+, Windows 10+
