"""
config/settings.py
──────────────────
Central configuration for the trading framework.
All tunables live here — nothing is hard-coded in business logic.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any


# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "trading.db"
LOG_DIR = BASE_DIR / "logs"


# ── IBKR Connection ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class IBKRConfig:
    """Interactive Brokers gateway / TWS connection parameters."""
    host: str = "127.0.0.1"
    port: int = 4001          # 4002 = IB Gateway paper, 7497 = TWS paper
    client_id: int = 8935
    account: str = "U22862141"
    connect_timeout: float = 15.0
    max_retries: int = 3
    retry_delay: float = 5.0


# ── Market Data ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class MarketDataConfig:
    """Historical / live data request parameters."""
    duration_str: str = "20 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    format_date: int = 2
    market_data_wait_s: float = 3.0


# ── Contract Specs ───────────────────────────────────────────────────────────
@dataclass
class ContractSpec:
    """Defines a futures contract for trading and its data source contract."""
    symbol: str
    last_trade_date: str
    exchange: str
    currency: str = "USD"
    trading_class: str = ""

    # Data contract may differ (e.g. MGC trades, GC provides deeper history)
    data_symbol: str = ""
    data_last_trade_date: str = ""
    data_exchange: str = ""

    # Contract-level constants
    tick_size: float = 0.1
    point_value: float = 10.0
    price_offset: float = 5.0

    def __post_init__(self) -> None:
        if not self.data_symbol:
            self.data_symbol = self.symbol
        if not self.data_last_trade_date:
            self.data_last_trade_date = self.last_trade_date
        if not self.data_exchange:
            self.data_exchange = self.exchange


# ── Pre-built contract specs ────────────────────────────────────────────────
MGC_SPEC = ContractSpec(
    symbol="MGC",
    last_trade_date="202606",
    exchange="COMEX",
    tick_size=0.1,
    point_value=10.0,
    price_offset=5.0,
    data_symbol="GC",
    data_last_trade_date="202606",
    data_exchange="COMEX",
)

ES_SPEC = ContractSpec(
    symbol="ES",
    last_trade_date="202606",
    exchange="GLOBEX",
    trading_class="ES",
    tick_size=0.25,
    point_value=50.0,
    price_offset=2.0,
)

MNQ_SPEC = ContractSpec(
    symbol="MNQ",
    last_trade_date="202606",
    exchange="CME",
    tick_size=0.25,
    point_value=2.0,
    price_offset=5.0,
)


# ── Strategy Parameters ─────────────────────────────────────────────────────
@dataclass
class StrategyParams:
    """Parameters for a single strategy instance."""
    name: str
    contract_spec: ContractSpec
    params: Dict[str, Any] = field(default_factory=dict)
    risk_usd: float = 1100.0
    max_position: int = 1


MGC_PULLBACK_PARAMS = StrategyParams(
    name="mgc_pullback",
    contract_spec=MGC_SPEC,
    risk_usd=1100.0,
    max_position=1,
    params={
        "trend_length": 200,
        "rsi_length": 2,
        "rsi_threshold": 30,
        "exit_ma_length": 37,
    },
)


# ── Logging ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class LogConfig:
    log_dir: Path = LOG_DIR
    max_bytes: int = 10 * 1024 * 1024   # 10 MB per file
    backup_count: int = 5
    console_level: str = "INFO"
    file_level: str = "DEBUG"


# ── Dashboard ────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DashboardConfig:
    refresh_interval_ms: int = 5000      # auto-refresh every 5s
    max_signal_rows: int = 200
    max_trade_rows: int = 500
