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
