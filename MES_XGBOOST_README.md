# MES XGBoost Ensemble Strategy

## Overview

This strategy implements a sophisticated machine learning ensemble approach for trading MES (Micro E-mini S&P 500) futures. It uses 30 pre-trained XGBoost models that vote on market direction based on 840+ engineered features from multiple asset classes.

## Strategy Architecture

### Data Sources

The strategy fetches and processes data from multiple sources:

1. **Futures Contracts**
   - MES (Micro E-mini S&P 500) - Primary trading instrument
   - GC (Gold) - Commodity correlation
   - HG (Copper) - Economic indicator

2. **Foreign Exchange**
   - EURUSD - Dollar strength indicator
   - USDJPY - Risk sentiment indicator

3. **Sector ETFs**
   - XLV (Healthcare)
   - XLK (Technology)
   - XLP (Consumer Staples)
   - XLF (Financials)
   - XLI (Industrials)

4. **Macro Indicators** (via Investing.com API)
   - 10-Year Treasury Yield
   - 2-Year Treasury Yield
   - 2-10 Year Spread
   - Dollar Index (DXY)
   - VIX (Volatility Index)

### Feature Engineering (840+ Features)

The strategy creates a comprehensive feature set:

1. **ATR Features**
   - ATR(30) - 30-period Average True Range
   - ATR(5) - 5-period Average True Range
   - ATR/Close ratio with RSI and MACD

2. **Lagged Returns** (0-3, 5, 10 periods)
   - Raw returns
   - RSI of returns
   - MACD of returns

3. **Correlated Asset Indicators**
   - Percentage changes for all assets
   - RSI(5) for each asset
   - MACD for each asset

4. **Calendar Features**
   - Day of week (sine/cosine encoding)
   - Week of month (sine/cosine encoding)

5. **Pairwise Price Spreads** (840+ features)
   - Daily OHLC spreads (4 periods)
   - Weekly OHLC spreads (4 periods)
   - Monthly OHLC spreads (2 periods)
   - All pairwise combinations normalized by current close

### Ensemble Voting System

**Model Loading:**
- Loads 30 pre-trained XGBoost models from `simulmodels.pkl`
- Each model was trained on different feature pairs
- Models use multi-class classification (3 classes)

**Prediction Classes:**
- Class 1: SELL signal
- Class 2: HOLD signal
- Class 3: BUY signal

**Voting Process:**
1. For each model:
   - Extract required features from latest data
   - Skip if features are missing or contain NaN
   - Predict class using XGBoost
   - Record vote

2. Count votes:
   - `buy_votes` = count of class 3 predictions
   - `sell_votes` = count of class 1 predictions
   - `hold_votes` = count of class 2 predictions

3. Calculate net signal:
   - `net_votes = buy_votes - sell_votes`
   - Direction: BUY if net > 0, SELL if net < 0, NONE if net == 0

### Position Sizing

**ATR-Based Dynamic Sizing:**

```python
max_lots = round(340 / ATR_30)
target_lots = round(5 * abs(net_votes) / 30 * max_lots)
target_lots = min(target_lots, 50)  # Cap at max_lots
```

**Position Direction:**
- If net_votes > 0: `desired_position = +target_lots` (LONG)
- If net_votes < 0: `desired_position = -target_lots` (SHORT)
- If net_votes == 0: `desired_position = 0` (FLAT)

**Order Execution:**
- Calculate delta: `delta = desired_position - current_position`
- If delta > 0: Place BUY order for delta lots
- If delta < 0: Place SELL order for abs(delta) lots
- If delta == 0: No action required

### Logging

The strategy includes comprehensive logging at every step:

1. **Model Loading**
   - Number of models loaded
   - Features per model
   - Success/failure status

2. **Data Fetching**
   - Each asset fetched with bar counts
   - Date ranges
   - Missing data warnings

3. **Feature Engineering**
   - Shape after each transformation
   - Feature counts
   - NaN handling

4. **Ensemble Voting**
   - Models used vs skipped
   - Vote breakdown (BUY/SELL/HOLD)
   - Net votes

5. **Position Sizing**
   - ATR value
   - Max lots calculation
   - Target lots
   - Current vs desired position
   - Delta to execute

6. **Order Execution**
   - Order type and quantity
   - Limit price
   - Fill confirmation

## File Structure

```
trading-system-architecture/
├── config/
│   └── settings.py                    # MES_XGBOOST_PARAMS configuration
├── strategies/
│   └── mes_xgboost_ensemble.py        # Main strategy implementation
├── run_mes_xgboost.py                 # Strategy runner script
├── run_mes_xgboost_strategy.bat       # Windows batch file
├── requirements.txt                   # Updated with xgboost, investiny
└── MES_XGBOOST_README.md              # This file
```

## Configuration

### Strategy Parameters (`config/settings.py`)

```python
@dataclass
class MESXGBoostParams:
    name: str = "MES_XGBoost_Ensemble"
    symbol: str = "MES"
    contract_month: str = "202606"
    exchange: str = "CME"
    tick_size: float = 0.25
    point_value: float = 5.0
    
    # Model parameters
    model_pickle_path: str = "C:\\Users\\USER\\SP500Triplets\\simulmodels.pkl"
    account: str = "U16668533"
    
    # Position sizing
    atr_period: int = 30
    atr_5_period: int = 5
    risk_per_atr: float = 340.0
    vote_scaling: float = 5.0
    max_lots: int = 50
```

### Customization

**To change the model file location:**
Edit `model_pickle_path` in `config/settings.py`

**To adjust position sizing:**
- `risk_per_atr`: Dollar risk per ATR unit (default: 340)
- `vote_scaling`: Multiplier for vote strength (default: 5.0)
- `max_lots`: Maximum position size cap (default: 50)

**To change the account:**
Edit `account` in `MESXGBoostParams`

## Installation

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Verify model file exists:**
```
C:\Users\USER\SP500Triplets\simulmodels.pkl
```

3. **Ensure IBKR connection:**
- TWS or IB Gateway running on port 4001
- Account U16668533 configured

## Running the Strategy

### Windows (Batch File)
```bash
run_mes_xgboost_strategy.bat
```

### Command Line
```bash
python run_mes_xgboost.py
```

### Output
- Console output with real-time logging
- Log file: `mes_xgboost_strategy_log.txt`
- Database records in `data/trading.db`

## Strategy Workflow

```
1. INITIALIZATION
   ├── Load 30 XGBoost models from pickle
   ├── Connect to IBKR
   └── Initialize database

2. DATA FETCHING
   ├── Fetch MES, Gold, Copper futures (10Y history)
   ├── Fetch EURUSD, USDJPY forex (1Y history)
   ├── Fetch XLV, XLK, XLP, XLF, XLI ETFs (1Y history)
   └── Fetch 10Y/2Y Treasuries, DXY, VIX (macro data)

3. FEATURE ENGINEERING
   ├── Compute ATR(30) and ATR(5)
   ├── Add lagged returns (0-3, 5, 10) with RSI/MACD
   ├── Add correlated asset indicators
   ├── Add calendar features
   └── Add 840+ pairwise spread features

4. ENSEMBLE PREDICTION
   ├── For each of 30 models:
   │   ├── Extract required features
   │   ├── Predict class (1=SELL, 2=HOLD, 3=BUY)
   │   └── Record vote
   ├── Count BUY/SELL/HOLD votes
   └── Calculate net_votes = buy_votes - sell_votes

5. POSITION SIZING
   ├── Calculate max_lots based on ATR
   ├── Calculate target_lots based on vote strength
   ├── Determine desired_position (LONG/SHORT/FLAT)
   └── Calculate delta from current position

6. ORDER EXECUTION
   ├── If delta > 0: Place BUY order
   ├── If delta < 0: Place SELL order
   └── If delta == 0: No action

7. DATABASE LOGGING
   ├── Record signal
   ├── Record orders
   └── Update position snapshot
```

## Example Execution Log

```
==============================================================
MES XGBOOST ENSEMBLE STRATEGY - EXECUTION START
==============================================================
Connecting to IBKR...
✅ Connected to IBKR (account: U16668533)

============================================================
LOADING XGBOOST MODELS
============================================================
Loaded 30 models from pickle
Model ('Low_d1_minus_Close_m1_norm', 'Low_d0_minus_High_m1_norm'): 2 features
...
✅ Successfully loaded 30 XGBoost models

============================================================
FETCHING MULTI-ASSET DATA
============================================================
Step 1: Qualifying futures contracts...
Processing MES (MES @ CME)...
  MES mapped to: MESM6 (expiry 20260618)
Processing Gold (GC @ COMEX)...
  Gold: Selected contract with highest volume
Processing Copper (HG @ COMEX)...
  Copper: Retrieved 479 bars
✅ Qualified 3 futures contracts

Step 2: Downloading 10-year daily OHLC...
  MES: 2500 bars from 2016-05-26 to 2026-05-26
  Gold: 2500 bars from 2016-05-26 to 2026-05-26
  Copper: 479 bars from 2024-06-28 to 2026-05-18

Step 3: Building merged DataFrame...
  Merged shape after futures: (2500, 7)

Step 4: Fetching FX data...
  EURUSD: 259 bars
  USDJPY: 259 bars

Step 5: Fetching sector ETFs...
  XLV: 252 bars
  XLK: 252 bars
  XLP: 252 bars
  XLF: 252 bars
  XLI: 252 bars
  Merged shape after ETFs: (2500, 17)

Step 6: Fetching macro indicators...
  Macro fetch attempt 1/3...
    ✅ Bonds data fetched
    ✅ Dollar Index fetched
    ✅ VIX data fetched
  ✅ All macro data fetched successfully (no NaNs)

✅ Final merged data shape: (250, 21)

============================================================
COMPUTING INDICATORS
============================================================
Step 1: Computing ATR features...
  After ATR: (250, 23)
Step 2: Computing lagged return features...
  After lagged returns: (250, 38)
Step 3: Computing correlated asset features...
  After correlated features: (245, 62)
Step 4: Computing pairwise spread features...
  After pairwise spreads: (231, 840)
✅ Final feature set: (231, 840)

============================================================
GENERATING ENSEMBLE SIGNAL
============================================================
Latest data: Date=2026-05-15, Close=7432.25, ATR_30=86.83

Running predictions on 30 models...

Voting results:
  Models used: 30
  Skipped: 0
  BUY votes: 25
  SELL votes: 5
  HOLD votes: 0
  Net votes: 20

Position sizing:
  Max lots (based on ATR): 3
  Target lots: 13
  Direction: BUY
  Desired position: 13
  Current position: 0
  Delta: +13

✅ ENTRY_LONG signal: Buy 13 lots

============================================================
EXECUTING SIGNAL
============================================================
Indicative price: 7432.25 (last_close)
Placing BUY order: 13 lots @ 7432.25
✅ BUY order placed: 13 lots @ 7432.25

==============================================================
MES XGBOOST ENSEMBLE STRATEGY - EXECUTION COMPLETE
==============================================================
```

## Risk Management

1. **Position Sizing**
   - ATR-based: Automatically adjusts to market volatility
   - Vote strength: Larger positions when consensus is strong
   - Hard cap: Maximum 50 lots regardless of signal

2. **Diversification**
   - 30 independent models reduce overfitting risk
   - Multi-asset features capture market regime changes

3. **No Stop Loss**
   - Strategy relies on model signals for exits
   - Rebalances position on every execution
   - Can reverse from LONG to SHORT instantly

## Monitoring

**Check logs:**
```bash
tail -f mes_xgboost_strategy_log.txt
```

**Database queries:**
```sql
-- Recent signals
SELECT * FROM signals WHERE strategy_name = 'MES_XGBoost_Ensemble' ORDER BY created_at DESC LIMIT 10;

-- Recent orders
SELECT * FROM orders WHERE strategy_name = 'MES_XGBoost_Ensemble' ORDER BY created_at DESC LIMIT 10;

-- Position snapshots
SELECT * FROM position_snapshots WHERE strategy_name = 'MES_XGBoost_Ensemble' ORDER BY snapshot_time DESC LIMIT 10;
```

## Troubleshooting

**Model file not found:**
- Verify path: `C:\Users\USER\SP500Triplets\simulmodels.pkl`
- Update `model_pickle_path` in `config/settings.py`

**Missing features:**
- Check if all data sources are accessible
- Verify IBKR market data subscriptions
- Check investiny API availability

**No votes from models:**
- Verify model pickle file integrity
- Check for NaN values in features
- Review feature engineering logs

**IBKR connection failed:**
- Ensure TWS/Gateway is running
- Check port 4001 is correct
- Verify account U16668533 is active

## Performance Notes

- **Execution time:** ~2-5 minutes (depends on data fetching)
- **Memory usage:** ~500MB (30 models + feature engineering)
- **Recommended schedule:** Daily after market close
- **Data requirements:** IBKR market data subscriptions for all assets

## Future Enhancements

1. **Model Retraining**
   - Periodic retraining on recent data
   - Walk-forward optimization
   - Feature selection refinement

2. **Additional Features**
   - Order flow indicators
   - Sentiment data
   - Options market data

3. **Risk Controls**
   - Maximum drawdown limits
   - Daily loss limits
   - Correlation-based position sizing

## Support

For issues or questions:
1. Check logs: `mes_xgboost_strategy_log.txt`
2. Review database records
3. Verify all dependencies are installed
4. Ensure model file is accessible
