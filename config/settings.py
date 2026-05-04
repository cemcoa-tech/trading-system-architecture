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
    port: int = 4002          # 4002 = IB Gateway paper, 7497 = TWS paper
    client_id: int = 8935
    account: str = "U22862141"#"DUM165609
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
    symbol="GC",
    last_trade_date="202606",
    exchange="COMEX",
    tick_size=0.1,
    point_value=100.0,
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
    symbol="NQ",
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
    risk_usd=11000.0,
    max_position=1,
    params={
        "trend_length": 200,
        "rsi_length": 2,
        "rsi_threshold": 30,
        "exit_ma_length": 32,
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



@dataclass
class MNQCondition1Params:
    """MNQ Condition1 strategy configuration."""
    
    # Strategy identification
    name: str = "MNQ_Condition1"
    
    # Contract specifications
    symbol: str = "NQ"
    data_symbol: str = "NQ"  # Use continuous for data
    contract_month: str = "202606"  # June 2026 front-month
    exchange: str = "CME"
    currency: str = "USD"
    tick_size: float = 0.25
    point_value: float = 2.0  # $2 per point
    
    # Data fetching
    duration: str = "2 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Indicator parameters
    roc_lookback: int = 5
    ema_span: int = 3
    atr_period: int = 20
    
    # Exit parameters
    max_time: int = 5  # Max bars to hold
    profitable_closes: int = 7  # Exit after N profitable closes
    pt_on: int = 1  # 1 = profit target active
    sl_on: int = 1  # 1 = stop loss active
    ptatr: float = 2.0  # PT = entry + ATR * PTATR
    slatr: float = 4.0  # SL = entry - ATR * SLATR
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    price_offset: float = 0.0  # Enter at market
    
    @property
    def contract_spec(self) -> "ContractSpec":
        return ContractSpec(
            symbol=self.symbol,
            data_symbol=self.data_symbol,
            last_trade_date=self.contract_month,
            exchange=self.exchange,
            currency=self.currency,
            tick_size=self.tick_size,
            point_value=self.point_value,
            price_offset=self.price_offset,
        )
    
    @property
    def params(self) -> Dict[str, Any]:
        return {
            "roc_lookback": self.roc_lookback,
            "ema_span": self.ema_span,
            "atr_period": self.atr_period,
            "max_time": self.max_time,
            "profitable_closes": self.profitable_closes,
            "pt_on": self.pt_on,
            "sl_on": self.sl_on,
            "ptatr": self.ptatr,
            "slatr": self.slatr,
        }


# ─────────────────────────────────────────────────────────────────────────────
#  MES CONDITION1 STRATEGY PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class MESCondition1Params:
    """MES Condition1 strategy configuration (identical logic to MNQ)."""
    
    # Strategy identification
    name: str = "MES_Condition1"
    
    # Contract specifications
    symbol: str = "ES"
    data_symbol: str = "ES"  # Use continuous for data
    contract_month: str = "202606"  # June 2026 front-month
    exchange: str = "CME"
    currency: str = "USD"
    tick_size: float = 0.25
    point_value: float = 5.0  # $5 per point
    
    # Data fetching
    duration: str = "2 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Indicator parameters
    roc_lookback: int = 5
    ema_span: int = 3
    atr_period: int = 20
    
    # Exit parameters
    max_time: int = 5
    profitable_closes: int = 7
    pt_on: int = 1
    sl_on: int = 1
    ptatr: float = 2.0
    slatr: float = 4.0
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    price_offset: float = 0.0
    
    @property
    def contract_spec(self) -> "ContractSpec":
        return ContractSpec(
            symbol=self.symbol,
            data_symbol=self.data_symbol,
            last_trade_date=self.contract_month,
            exchange=self.exchange,
            currency=self.currency,
            tick_size=self.tick_size,
            point_value=self.point_value,
            price_offset=self.price_offset,
        )
    
    @property
    def params(self) -> Dict[str, Any]:
        return {
            "roc_lookback": self.roc_lookback,
            "ema_span": self.ema_span,
            "atr_period": self.atr_period,
            "max_time": self.max_time,
            "profitable_closes": self.profitable_closes,
            "pt_on": self.pt_on,
            "sl_on": self.sl_on,
            "ptatr": self.ptatr,
            "slatr": self.slatr,
        }


# Instantiate default configurations
MNQ_CONDITION1_PARAMS = MNQCondition1Params()
MES_CONDITION1_PARAMS = MESCondition1Params()


@dataclass
class BTCRSIParams:
    """BTC MBT RSI mean-reversion strategy configuration."""
    
    # Strategy identification
    name: str = "BTC_RSI_MeanRev"
    
    # Contract specifications
    symbol: str = "MBT"
    data_symbol: str = "MBT"  # Use continuous contract
    contract_month: str = "202606"  # Empty for continuous
    exchange: str = "CME"
    currency: str = "USD"
    tick_size: float = 5.0  # MBT = $5 tick
    point_value: float = 0.10  # $0.10 per index point
    
    # Data fetching
    duration: str = "2 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Indicator parameters
    rsi_length: int = 2  # Wilder RSI period
    rsi_low: float = 65.0  # Entry: RSI >= rsi_low
    rsi_high: float = 75.0  # Entry: RSI <= rsi_high
    value_low_window: int = 5  # Lowest-low lookback for exit
    
    # Exit parameters
    max_time: int = 10  # Max bars to hold position
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    price_offset: float = 0.0  # Enter at market open
    
    @property
    def contract_spec(self) -> "ContractSpec":
        return ContractSpec(
            symbol=self.symbol,
            last_trade_date=self.contract_month,
            data_symbol=self.data_symbol,
            exchange=self.exchange,
            currency=self.currency,
            tick_size=self.tick_size,
            point_value=self.point_value,
        )
    
    @property
    def params(self) -> Dict[str, Any]:
        return {
            "rsi_length": self.rsi_length,
            "rsi_low": self.rsi_low,
            "rsi_high": self.rsi_high,
            "value_low_window": self.value_low_window,
            "max_time": self.max_time,
        }


# Instantiate default configuration
BTC_RSI_PARAMS = BTCRSIParams()