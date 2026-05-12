"""
config/settings.py
──────────────────
Central configuration for the trading framework.
All tunables live here — nothing is hard-coded in business logic.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay


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
    account: str = "DUM165609"#"#U22862141
    connect_timeout: float = 15.0
    max_retries: int = 3
    retry_delay: float = 5.0


@dataclass(frozen=True)
class IBKRConfigAlt:
    """Alternative IBKR configuration for U20859646 account."""
    host: str = "127.0.0.1"
    port: int = 4002          # 4002 = IB Gateway paper, 7497 = TWS paper
    client_id: int = 8936  # Different client ID to avoid conflicts
    account: str = "U20859646"
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


# config/settings.py (ADD this section)

# ─────────────────────────────────────────────────────────────────────────────
#  BTC STRATEGY 2: VALUELOW/RSI + SMA EXIT PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class BTC2Params:
    """
    BTC Strategy 2: ValueLow/RSI Entry + SMA Turn-Up Exit
    
    Entry:
        - ValueLow(5)[1] <= ValueOpen(5)[3]
        - RSI(2)[0] between 65 and 75
        - Condition must be true DELAY bars ago
    
    Exit:
        - TimeX: BarsSinceEntry >= max_time - 1
        - SigX: SMA(5)[0] > SMA(5)[2] (SMA turning up)
    """
    
    # Strategy identification
    name: str = "BTC2_ValueLow_SMA"
    
    # Contract specifications
    symbol: str = "MBT"
    data_symbol: str = "MBT"  # Use continuous contract
    contract_month: str = "202606"
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
    rsi_length: int = 2
    rsi_low: float = 65.0  # Entry: RSI >= rsi_low
    rsi_high: float = 75.0  # Entry: RSI <= rsi_high
    vl_window: int = 5  # ValueLow/ValueOpen window
    sma_exit_length: int = 5  # SMA for exit signal
    
    # Entry parameters
    entry_delay: int = 1  # Condition must be true DELAY bars ago
    
    # Exit parameters
    max_time: int = 6  # Max bars to hold position
    
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
            "vl_window": self.vl_window,
            "sma_exit_length": self.sma_exit_length,
            "entry_delay": self.entry_delay,
            "max_time": self.max_time,
        }


# Instantiate default configuration
BTC2_PARAMS = BTC2Params()

# Alternative configuration for U20859646 account
BTC2_PARAMS_ALT = BTC2Params()


# ─────────────────────────────────────────────────────────────────────────────
#  TREASURY ZN END-OF-MONTH STRATEGY PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class TreasuryEOMParams:
    """
    Treasury ZN End-of-Month Strategy
    
    Entry:
        - N trading days before end of month (e.g., 2 days)
        - Buy at limit (mid + offset)
    
    Exit:
        - First trading day of next month
        - Sell at limit (mid - offset)
    
    Calendar:
        - Uses US Federal Holiday calendar for trading day calculations
        - Sunday 5pm ET open counts as Monday trade date
    """
    
    # Strategy identification
    name: str = "Treasury_ZN_EOM"
    
    # Contract specifications
    symbol: str = "ZN"
    data_symbol: str = "ZN"
    contract_month: str = "202606"  # Update quarterly
    exchange: str = "CBOT"
    currency: str = "USD"
    tick_size: float = 1/64  # ZN = 1/64th of a point
    point_value: float = 1000.0  # $1000 per point for ZN
    
    # Data fetching
    duration: str = "1 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Strategy parameters
    days_before_eom: int = 14  # Enter N trading days before end of month
    price_offset: float = 0.10  # Entry: mid + offset, Exit: mid - offset
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    
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
            "days_before_eom": self.days_before_eom,
            "price_offset": self.price_offset,
        }


    # Instantiate default configuration
TREASURY_EOM_PARAMS = TreasuryEOMParams(
    days_before_eom=3,
    price_offset=0.15,
)


# ─────────────────────────────────────────────────────────────────────────────
#  TREASURY 30-YEAR BOND END-OF-MONTH STRATEGY PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Treasury30YEOMParams:
    """
    Treasury 30-Year Bond End-of-Month Strategy
    
    Entry:
        - 6 trading days before end of month
        - Buy at limit (mid + offset)
    
    Exit:
        - First trading day of next month
        - Sell at limit (mid - offset)
    
    Calendar:
        - Uses US Federal Holiday calendar for trading day calculations
        - Sunday 5pm ET open counts as Monday trade date
    """
    
    # Strategy identification
    name: str = "Treasury_30Y_EOM"
    
    # Contract specifications
    symbol: str = "ZB"  # 30-Year Treasury Bond
    data_symbol: str = "ZB"
    contract_month: str = "202606"  # Update quarterly
    exchange: str = "CBOT"
    currency: str = "USD"
    tick_size: float = 1/32  # ZB = 1/32nd of a point
    point_value: float = 1000.0  # $1000 per point for ZB
    
    # Data fetching
    duration: str = "1 Y"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Strategy parameters
    days_before_eom: int = 6  # Enter 6 trading days before end of month
    price_offset: float = 0.20  # Entry: mid + offset, Exit: mid - offset
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    
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
            "days_before_eom": self.days_before_eom,
            "price_offset": self.price_offset,
        }

# Instantiate default configuration
TREASURY_30Y_EOM_PARAMS = Treasury30YEOMParams()
# Calendar helper (shared across framework)
US_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())



# ─────────────────────────────────────────────────────────────────────────────
#  TREASURY STOCHASTIC HURST STRATEGY (ZB → MWN)
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class TreasuryStochHurstParams:
    """
    Treasury Stochastic Hurst Strategy
    
    Signal: ZB (30-Year Treasury)
    Execution: MWN (Micro 30-Year Note)
    
    Entry:
        - Stochastic(14) crosses below 60 threshold
        - Hurst exponent rising (H[0] > H[5])
        - Uses 1-bar delay confirmation
    
    Exit:
        - RSI(2) >= 70 (signal exit)
        - BarsSinceEntry >= max_time - 1 (time exit)
    
    Direction: Long-only
    """
    
    # Strategy identification
    name: str = "Treasury_Stoch_Hurst"
    
    # Signal contract (ZB - 30-Year Bond)
    signal_symbol: str = "ZB"
    signal_contract_month: str = "202606"
    
    # Execution contract (MWN - Micro 30-Year Note)
    symbol: str = "MTN"  # MWN actual symbol is MTN
    data_symbol: str = "MTN"
    contract_month: str = "202606"
    exchange: str = "CBOT"
    currency: str = "USD"
    tick_size: float = 1/64  # Treasury tick
    point_value: float = 100.0  # MWN = $100 per point (1/10 of ZB)
    
    # Data fetching
    duration: str = "120 D"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Indicator parameters
    stoch_length: int = 14
    stoch_threshold: float = 60.0  # Cross below this level
    hurst_length: int = 20
    hurst_lookback: int = 5  # H[0] > H[5]
    rsi_length: int = 2
    rsi_exit_threshold: float = 70.0
    
    # Entry parameters
    entry_delay: int = 1  # Condition must be true DELAY bars ago
    
    # Exit parameters
    max_time: int = 9  # Max bars to hold position
    
    # Execution parameters
    price_offset_ticks: int = 2  # Offset in ticks for limit orders
    price_offset: float = 0.0  # Will be calculated from ticks
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    
    def __post_init__(self):
        """Calculate price_offset from ticks."""
        self.price_offset = self.price_offset_ticks * self.tick_size
    
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
            "signal_symbol": self.signal_symbol,
            "signal_contract_month": self.signal_contract_month,
            "stoch_length": self.stoch_length,
            "stoch_threshold": self.stoch_threshold,
            "hurst_length": self.hurst_length,
            "hurst_lookback": self.hurst_lookback,
            "rsi_length": self.rsi_length,
            "rsi_exit_threshold": self.rsi_exit_threshold,
            "entry_delay": self.entry_delay,
            "max_time": self.max_time,
            "price_offset_ticks": self.price_offset_ticks,
        }


# Instantiate default configuration
TREASURY_STOCH_HURST_PARAMS = TreasuryStochHurstParams()

# Alternative configuration for U20859646 account
TREASURY_STOCH_HURST_PARAMS_ALT = TreasuryStochHurstParams()

# ─────────────────────────────────────────────────────────────────────────────
#  RB COMBINED LONG/SHORT STRATEGY
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class RBCombinedParams:
    """
    RB (RBOB Gasoline) Combined Long/Short Strategy
    
    Long Entry:
        - ValueOpen(5)[0] <= ValueLow(5)[5]  (open <= low 5 bars ago)
        - ADX(20) <= 15  (low ADX = ranging market)
        - Uses DELAY confirmation
    
    Short Entry:
        - Low[2] > High[6]  (gap up)
        - Thursday only
        - Uses DELAY confirmation
    
    Exits:
        - ATR-based stop loss and profit target
        - Stop: entry ± ATR * 3
        - Target: entry ± ATR * 6
        - Time exits: 9 bars (long) / 3 bars (short)
    
    Direction: Long and Short
    """
    
    # Strategy identification
    name: str = "RB_Combined"
    
    # Contract specifications
    symbol: str = "RB"
    data_symbol: str = "RB"
    contract_month: str = "202606"  # Update monthly
    exchange: str = "NYMEX"
    currency: str = "USD"
    tick_size: float = 0.0001  # RB = $0.0001 per gallon
    point_value: float = 42000.0  # 42,000 gallons per contract
    
    # Data fetching
    duration: str = "180 D"
    bar_size: str = "1 day"
    what_to_show: str = "TRADES"
    use_rth: bool = False
    
    # Indicator parameters
    atr_length: int = 14
    atr_mult_stop: float = 3.0  # Stop loss = entry ± ATR * 3
    atr_mult_target: float = 6.0  # Target = entry ± ATR * 6
    adx_length: int = 20
    adx_threshold: float = 15.0  # Long entry when ADX <= 15
    
    # Entry parameters
    entry_delay: int = 1  # Condition must be true DELAY bars ago
    value_lookback: int = 5  # For ValueOpen/ValueLow checks
    
    # Exit parameters
    max_time_long: int = 9  # Max bars to hold long position
    max_time_short: int = 3  # Max bars to hold short position
    
    # Execution parameters
    price_offset: float = 0.10  # Aggressive offset for fills
    
    # Risk management
    risk_usd: float = 1100.0
    max_position: int = 1
    
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
            "atr_length": self.atr_length,
            "atr_mult_stop": self.atr_mult_stop,
            "atr_mult_target": self.atr_mult_target,
            "adx_length": self.adx_length,
            "adx_threshold": self.adx_threshold,
            "entry_delay": self.entry_delay,
            "value_lookback": self.value_lookback,
            "max_time_long": self.max_time_long,
            "max_time_short": self.max_time_short,
        }


# Instantiate default configuration
RB_COMBINED_PARAMS = RBCombinedParams()