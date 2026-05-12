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
        account: str,
    ) -> None:
        super().__init__(params, broker, order_mgr, db, account)
        # Unpack strategy-specific parameters
        p = params.params
        self._trend_len: int = p.get("trend_length", 200)
        self._rsi_len: int = p.get("rsi_length", 2)
        self._rsi_thresh: float = p.get("rsi_threshold", 30)
        self._exit_ma_len: int = p.get("exit_ma_length", 32)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database."""
        # Try to load from position_state table first
        pos_state = self.db.get_position_state(self.name, self.spec.symbol)
        
        if pos_state:
            return {
                "in_position": True,
                "entry_bar_date": pos_state.get("entry_bar_date"),
                "entry_price": pos_state.get("entry_price", 0.0),
                "bars_held": pos_state.get("bars_held", 0),
            }
        
        # Fallback to open_trade table for backward compatibility
        open_trade = self.db.get_open_trade(self.name)
        if not open_trade:
            return {
                "in_position": False,
                "entry_bar_date": None,
                "entry_price": 0.0,
                "bars_held": 0,
            }
        
        return {
            "in_position": True,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "bars_held": 0,  # Will be incremented
        }

    def _save_position_state(self) -> None:
        """Save current position state to database."""
        self.db.upsert_position_state(
            strategy_name=self.name,
            symbol=self.spec.symbol,
            entry_bar_date=self._position_state["entry_bar_date"],
            entry_price=self._position_state["entry_price"],
            bars_held=self._position_state["bars_held"],
        )

    def _delete_position_state(self) -> None:
        """Delete position state from database."""
        self.db.delete_position_state(self.name, self.spec.symbol)

    def _reset_position_state(self) -> None:
        """Reset position state after exit."""
        self._position_state = {
            "in_position": False,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "bars_held": 0,
        }

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

        meta = {"date": str(last["date"])}

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
                meta=meta,
            )

        # No signal
        reason_parts = []
        if not uptrend:
            reason_parts.append("no uptrend")
        if not pullback:
            reason_parts.append(f"RSI2={rsi2:.1f} >= {self._rsi_thresh}")
        
        reason = "No signal: " + ", ".join(reason_parts) if reason_parts else "No actionable signal"
        
        return Signal(
            signal_type="NONE",
            reason=reason,
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    
