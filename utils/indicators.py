"""
utils/indicators.py
───────────────────
Vectorised technical indicators built on pandas.
Every indicator returns a pd.Series aligned with the input index.
"""

import numpy as np
import pandas as pd


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
    
    In TradeStation, ValueOpen(N) is the lowest Open over N bars.
    Equivalent to Lowest(Open, N).
    
    Args:
        series: Open price series
        window: Lookback window
        
    Returns:
        Series of rolling minimums of Open
    """
    return series.rolling(window=window, min_periods=window).min()