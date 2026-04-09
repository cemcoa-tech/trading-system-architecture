# Trading Framework

Production-grade, modular trading system built on IBKR (ib_insync) with clean architecture, SQLite persistence, and a Streamlit monitoring dashboard.

## Architecture

```
trading_framework/
├── config/
│   ├── __init__.py
│   └── settings.py          # All tunables: IBKR, contracts, strategy params
├── database/
│   ├── __init__.py
│   ├── models.py             # SQLite DDL (5 tables)
│   └── manager.py            # CRUD operations — no ORM
├── strategies/
│   ├── __init__.py
│   ├── base_strategy.py      # Abstract base — template method pattern
│   └── mgc_pullback.py       # MGC Pullback (RSI2 + SMA200/37)
├── execution/
│   ├── __init__.py
│   ├── broker.py             # IBKR connection, contracts, market data
│   └── order_manager.py      # Bracket orders, exits, tick rounding, sizing
├── utils/
│   ├── __init__.py
│   ├── logger.py             # Rotating file + console logging
│   └── indicators.py         # Vectorised SMA, Wilder RSI
├── dashboard/
│   ├── __init__.py
│   └── app.py                # Streamlit dashboard (5 tabs)
├── main.py                   # Entry point — runs strategies via CLI
├── seed_demo_data.py         # Populate DB with demo data for dashboard testing
└── requirements.txt
```

## Quick Start

### 1. Install

```bash
cd trading_framework
pip install -r requirements.txt
```

### 2. Run Live (requires IBKR Gateway/TWS)

```bash
# All strategies
python main.py

# Single strategy
python main.py --strategy mgc

# Dry run (signals only, no orders)
python main.py --dry-run
```

### 3. Dashboard (works standalone)

```bash
# Seed demo data first (no IBKR needed)
python seed_demo_data.py

# Launch dashboard
streamlit run dashboard/app.py
```

## Strategy: MGC Pullback

| Rule       | Condition              |
|------------|------------------------|
| Trend      | Close > SMA(200)       |
| Entry      | RSI(2) < 30            |
| Exit       | Close > SMA(37)        |
| Direction  | Long only              |
| Sizing     | Risk-based (default $1100) |

## Adding a New Strategy

1. Create `strategies/my_strategy.py` subclassing `BaseStrategy`
2. Implement 4 hooks: `fetch_data`, `compute_indicators`, `generate_signal`, `get_position_size`
3. Add a `StrategyParams` config in `config/settings.py`
4. Register in `main.py` → `build_strategies()` registry dict

## Database Tables

| Table      | Purpose                          |
|------------|----------------------------------|
| strategies | Strategy registry + params       |
| signals    | Every signal generated           |
| trades     | Entry → exit lifecycle with PnL  |
| orders     | Individual order legs            |
| positions  | Periodic position snapshots      |

## Dashboard Tabs

- **Overview** — Positions, open trades, KPIs
- **Trades** — Full history with entry/exit/PnL
- **PnL** — Equity curve, drawdown, distribution
- **Orders** — Status breakdown (submitted/filled/cancelled)
- **Signals** — Live feed with auto-refresh
# trading-system-architecture
