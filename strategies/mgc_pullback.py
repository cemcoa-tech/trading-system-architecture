"""
strategies/mgc_pullback.py
──────────────────────────
MGC Pullback Strategy (converted from single-file live script).

Rules:
    ENTRY_LONG  →  Close > SMA(200)  AND  RSI(2) < 30
    EXIT_LONG   →  Close > SMA(32)
    Direction   →  Long-only
"""

import pandas as pd

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import sma, wilder_rsi


class MGCPullbackStrategy(BaseStrategy):
    """
    Mean-reversion pullback on Micro Gold futures.
    Enters on RSI(2) dips within an uptrend; exits on SMA(32) cross.
    """

    def __init__(
        self,
        params: StrategyParams,
        broker: Broker,
        order_mgr: OrderManager,
        db: DatabaseManager,
    ) -> None:
        super().__init__(params, broker, order_mgr, db)
        # Unpack strategy-specific parameters
        p = params.params
        self._trend_len: int = p.get("trend_length", 200)
        self._rsi_len: int = p.get("rsi_length", 2)
        self._rsi_thresh: float = p.get("rsi_threshold", 30)
        self._exit_ma_len: int = p.get("exit_ma_length", 32)

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from the data contract (GC for MGC)."""
        data_ct = self.broker.qualify_data_contract(self.spec)
        return self.broker.fetch_historical_bars(data_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add SMA200, SMA32, RSI(2)."""
        df["SMA200"] = sma(df["close"], self._trend_len)
        df["SMA32"] = sma(df["close"], self._exit_ma_len)
        df["RSI2"] = wilder_rsi(df["close"], self._rsi_len)
        self.log.info(
            "Last bar  date=%s  close=%.2f  SMA200=%.2f  SMA32=%.2f  RSI2=%.2f",
            df.iloc[-1]["date"],
            df.iloc[-1]["close"],
            df.iloc[-1]["SMA200"],
            df.iloc[-1]["SMA32"],
            df.iloc[-1]["RSI2"],
        )
        return df

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic:
            Flat + uptrend + pullback  →  ENTRY_LONG
            Long + close > SMA32      →  EXIT_LONG
            Otherwise                  →  NONE
        """
        last = df.iloc[-1]
        close = float(last["close"])
        sma200 = float(last["SMA200"])
        sma32 = float(last["SMA32"])
        rsi2 = float(last["RSI2"])

        uptrend = close > sma200
        pullback = rsi2 < self._rsi_thresh
        exit_up = close > sma32

        indicators = {
            "SMA200": round(sma200, 2),
            "SMA32": round(sma32, 2),
            "RSI2": round(rsi2, 2),
            "uptrend": uptrend,
            "pullback": pullback,
            "exit_up": exit_up,
        }

        self.log.info(
            "States  uptrend=%s  pullback=%s  exit_up=%s  pos=%d",
            uptrend, pullback, exit_up, current_pos,
        )

        if current_pos == 0 and uptrend and pullback:
            return Signal(
                signal_type="ENTRY_LONG",
                reason="UpTrend & Pullback (RSI2 < 30)",
                close_price=close,
                indicators=indicators,
                meta={"date": str(last["date"])},
            )

        if current_pos > 0 and exit_up:
            return Signal(
                signal_type="EXIT_LONG",
                reason="Close > SMA32",
                close_price=close,
                indicators=indicators,
                meta={"date": str(last["date"])},
            )

        return Signal(
            signal_type="NONE",
            reason="No actionable signal",
            close_price=close,
            indicators=indicators,
            meta={"date": str(last["date"])},
        )

    def get_position_size(self, signal: Signal) -> int:
        """Risk-based sizing capped by max_position."""
        dist = self.params.risk_usd / self.spec.point_value
        return OrderManager.compute_quantity(
            risk_usd=self.params.risk_usd,
            point_value=self.spec.point_value,
            stop_distance_pts=dist,
            max_position=self.params.max_position,
        )
