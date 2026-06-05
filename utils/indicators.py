"""
utils/indicators.py
───────────────────
Vectorised technical indicators built on pandas.
Every indicator returns a pd.Series aligned with the input index.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Any


def sma(series: pd.Series, length: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=length).mean()


def wilder_rsi(close: pd.Series, length: int) -> pd.Series:
    """
    Relative Strength Index using Wilder's smoothing method (EWM).

    Matches TradeStation's RSI implementation:
        alpha = 1/length   →   equivalent to span = 2*length - 1
    """
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    avg_gain = gains.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = losses.ewm(alpha=1 / length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi

def roc(series: pd.Series, period: int) -> pd.Series:
    """
    Rate of Change (ROC) indicator.
    
    ROC = (Close[0] - Close[n]) / Close[n]
    
    Args:
        series: Price series
        period: Lookback period
        
    Returns:
        Series of ROC values
    """
    return (series - series.shift(period)) / series.shift(period)


def ema(series: pd.Series, span: int) -> pd.Series:
    """
    Exponential Moving Average.
    
    Args:
        series: Price series
        span: EMA period
        
    Returns:
        Series of EMA values
    """
    return series.ewm(span=span, adjust=False).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range (ATR).
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        period: ATR period
        
    Returns:
        Series of ATR values
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def value_lowest(series: pd.Series, window: int) -> pd.Series:
    """
    Rolling minimum (ValueLowest in TradeStation).
    
    Returns the lowest value over the last 'window' bars.
    
    Args:
        series: Price series (typically lows)
        window: Lookback window
        
    Returns:
        Series of rolling minimums
    """
    return series.rolling(window=window, min_periods=window).min()


def value_low(high: pd.Series, low: pd.Series, length: int) -> pd.Series:
    """
    TradeStation ValueLow indicator.
    
    Calculates normalized position of Low relative to average mid-price,
    scaled by average range volatility.
    
    TradeStation formula:
        relative = Average((H + L) / 2, length)
        volUnit = Average(Range, length)
        ValueLow = (Low - relative) / (volUnit * 1/length)  if volUnit * 1/length <> 0
    
    Args:
        high: High prices
        low: Low prices  
        length: Lookback period
        
    Returns:
        Series of ValueLow values (normalized measure)
    """
    # Average mid-price (relative)
    mid_price = (high + low) / 2
    relative = mid_price.rolling(window=length, min_periods=length).mean()
    
    # Average range (volatility unit)
    price_range = high - low
    vol_unit = price_range.rolling(window=length, min_periods=length).mean()
    
    # Denominator: volUnit * 1/length
    denominator = vol_unit / length
    
    # ValueLow = (Low - relative) / (volUnit * 1/length)
    # Avoid division by zero
    value_low = (low - relative) / denominator.replace(0, np.nan)
    
    return value_low


def value_highest(series: pd.Series, window: int) -> pd.Series:
    """
    Rolling maximum (ValueHighest in TradeStation).
    
    Returns the highest value over the last 'window' bars.
    
    Args:
        series: Price series (typically highs)
        window: Lookback window
        
    Returns:
        Series of rolling maximums
    """
    return series.rolling(window=window, min_periods=window).max()


def value_open(series: pd.Series, window: int) -> pd.Series:
    """
    ValueOpen - rolling minimum of Open prices.
    
    In TradeStation, ValueLow/ValueOpen indicator (ratio of rolling min to Open).
    
    Args:
        series: Open price series
        window: Lookback window
        
    Returns:
        Series of rolling minimums of Open
    """
    return series.rolling(window=window, min_periods=window).min()


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """
    Stochastic oscillator.
    
    Args:
        high: High price series
        low: Low price series  
        close: Close price series
        length: Lookback period
        
    Returns:
        Stochastic oscillator values (0-100)
    """
    lowest_low = low.rolling(window=length).min()
    highest_high = high.rolling(window=length).max()
    
    # Avoid division by zero
    denominator = highest_high - lowest_low
    denominator = denominator.replace(0, np.nan)
    
    k_percent = 100 * (close - lowest_low) / denominator
    return k_percent.fillna(50)  # Default to middle when no data


def hurst_exponent(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """
    Simplified Hurst exponent calculation based on price range analysis.
    
    The Hurst exponent measures trend persistence:
    - H > 0.5: Persistent/trending
    - H = 0.5: Random walk
    - H < 0.5: Anti-persistent/mean-reverting
    
    Args:
        high: High price series
        low: Low price series
        close: Close price series
        length: Lookback period
        
    Returns:
        Hurst exponent values (typically 0-1)
    """
    # Use price range as a proxy for volatility
    price_range = high - low
    avg_range = price_range.rolling(window=length).mean()
    
    # Calculate normalized price movement
    price_change = close.diff().abs()
    avg_change = price_change.rolling(window=length).mean()
    
    # Simple Hurst approximation based on range persistence
    # Higher persistent ranges suggest trending behavior (H > 0.5)
    # Lower ranges suggest mean-reversion (H < 0.5)
    
    # Normalize the ratio to get values roughly between 0.3 and 0.7
    hurst = 0.5 + 0.2 * np.tanh((avg_range / avg_change - 2) / 2)
    
    return hurst.fillna(0.5)  # Default to random walk when no data

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
            contract_month=self.contract_month,
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

def adx(high: pd.Series, low: pd.Series, close: pd.Series, 
        length: int = 14) -> pd.Series:
    """
    Average Directional Index (ADX).
    
    Measures trend strength (not direction).
    ADX > 25: strong trend
    ADX < 20: weak trend / ranging
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        length: ADX period
        
    Returns:
        Series of ADX values
    """
    # Calculate directional movement
    up_move = high.diff()
    down_move = -low.diff()
    
    # +DM and -DM
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    # True Range
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    # Smooth ATR
    atr_smooth = tr.rolling(length).mean()
    
    # +DI and -DI
    plus_di = 100 * pd.Series(plus_dm, index=high.index).rolling(length).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=high.index).rolling(length).mean() / atr_smooth
    
    # DX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    
    # ADX (smoothed DX)
    adx_values = dx.rolling(length).mean()
    
    return adx_values

def cube_hlc(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """
    CubeHLC indicator - cube root of (High * Low * Close).
    
    CubeHLC = (H * L * C)^(1/3)
    
    Represents a geometric average of the three price components.
    
    Args:
        high: High prices
        low: Low prices
        close: Close prices
        
    Returns:
        Series of CubeHLC values
    """
    return np.power(high * low * close, 1/3)