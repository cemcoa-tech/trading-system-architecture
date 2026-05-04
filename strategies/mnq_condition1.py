# strategies/mnq_condition1.py
"""
strategies/mnq_condition1.py
────────────────────────────
MNQ Condition1 Strategy - Tony's Exact Rules

Entry:
    - If Condition1[yesterday] = true AND flat → Buy at today's open

Condition1 (all must be true):
    - ROC[0] < ROC[5]
    - Open[0] > EMA3[0]
    - Open[3] <= Close[8]
    - Close[3] <= Close[5]

Exit Priority:
    1) Stop Loss hit (intrabar)
    2) Profit Target hit (intrabar)
    3) Profitable closes count >= threshold
    4) Time exit (max bars held AND no new signal)

Reset/Re-entry:
    - On any exit, if Condition1 still true, re-enter same bar
    - Recalculate PT/SL from previous bar's close + ATR
"""

import pandas as pd
import numpy as np
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import roc, ema, atr


class MNQCondition1Strategy(BaseStrategy):
    """
    MNQ Condition1 strategy with ROC, EMA3, and ATR-based exits.
    
    This strategy tracks position state across executions to maintain:
    - bars_since_entry: Number of bars held
    - profitable_closes: Count of closes >= entry price
    - entry_bar_date: When position was opened
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
        self._roc_lookback: int = p.get("roc_lookback", 5)
        self._ema_span: int = p.get("ema_span", 3)
        self._atr_period: int = p.get("atr_period", 20)
        self._max_time: int = p.get("max_time", 5)
        self._profitable_closes: int = p.get("profitable_closes", 7)
        self._pt_on: int = p.get("pt_on", 1)
        self._sl_on: int = p.get("sl_on", 1)
        self._ptatr: float = p.get("ptatr", 2.0)
        self._slatr: float = p.get("slatr", 4.0)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database or initialize empty."""
        # Try to load from position_state table first
        pos_state = self.db.get_position_state(self.name, self.spec.symbol)
        print("pos_state:", pos_state)
        if pos_state:
            return {
                "in_position": True,
                "entry_bar_date": pos_state.get("entry_bar_date"),
                "entry_price": pos_state.get("entry_price", 0.0),
                "profitable_closes": pos_state.get("profitable_closes", 0),
                "bars_held": pos_state.get("bars_held", 0),
                "tp_price": pos_state.get("tp_price", 0.0),
                "sl_price": pos_state.get("sl_price", 0.0),
            }
        
        # Fallback: check for open trade
        open_trade = self.db.get_open_trade(self.name)
        if not open_trade:
            return {
                "in_position": False,
                "entry_bar_date": None,
                "entry_price": 0.0,
                "profitable_closes": 0,
                "bars_held": 0,
                "tp_price": 0.0,
                "sl_price": 0.0,
            }
        
        # Reconstruct state from open trade
        return {
            "in_position": True,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "profitable_closes": 0,
            "bars_held": 0,
            "tp_price": open_trade.get("tp_price", 0.0),
            "sl_price": open_trade.get("sl_price", 0.0),
        }

    def _save_position_state(self) -> None:
        """Persist position state to database."""
        state = self._position_state
        if state["in_position"]:
            self.db.upsert_position_state(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                entry_bar_date=state["entry_bar_date"],
                entry_price=state["entry_price"],
                bars_held=state["bars_held"],
                profitable_closes=state["profitable_closes"],
                tp_price=state["tp_price"],
                sl_price=state["sl_price"],
            )
        else:
            # Delete state when not in position
            self.db.delete_position_state(self.name, self.spec.symbol)

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from continuous contract."""
        from ib_insync import ContFuture
        
        # Use continuous contract for data
        data_spec = ContFuture(
            symbol=self.spec.data_symbol,
            exchange=self.spec.exchange,
            currency=self.spec.currency,
        )
        
        data_ct = self.broker.ib.qualifyContracts(data_spec)[0]
        return self.broker.fetch_historical_bars(data_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ROC, EMA3, ATR, and Condition1."""
        # Calculate indicators
        df["roc5"] = roc(df["close"], self._roc_lookback)
        df["ema3"] = ema(df["close"], self._ema_span)
        df["atr"] = atr(df["high"], df["low"], df["close"], self._atr_period)
        
        # Evaluate Condition1 for each bar
        df["condition1"] = self._evaluate_condition1(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.2f  ROC5=%.4f  EMA3=%.2f  ATR=%.2f  Cond1=%s",
            last["date"],
            last["close"],
            last["roc5"],
            last["ema3"],
            last["atr"],
            last["condition1"],
        )
        
        return df

    def _evaluate_condition1(self, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate Condition1 for each bar.
        
        Condition1 (all must be true):
        - ROC[0] < ROC[5]
        - Open[0] > EMA3[0]
        - Open[3] <= Close[8]
        - Close[3] <= Close[5]
        """
        condition = pd.Series(False, index=df.index)
        
        min_bars = 10  # Need at least 10 bars of history
        
        for i in range(min_bars, len(df)):
            try:
                roc_0 = df["roc5"].iloc[i]
                roc_5 = df["roc5"].iloc[i - 5] if i >= 5 else np.nan
                open_0 = df["open"].iloc[i]
                ema3_0 = df["ema3"].iloc[i]
                open_3 = df["open"].iloc[i - 3] if i >= 3 else np.nan
                close_8 = df["close"].iloc[i - 8] if i >= 8 else np.nan
                close_3 = df["close"].iloc[i - 3] if i >= 3 else np.nan
                close_5 = df["close"].iloc[i - 5] if i >= 5 else np.nan
                
                # Check for valid values
                vals = [roc_0, roc_5, open_0, ema3_0, open_3, close_8, close_3, close_5]
                if any(pd.isna(v) for v in vals):
                    continue
                
                # Evaluate all conditions
                condition.iloc[i] = (
                    (roc_0 < roc_5) and
                    (open_0 > ema3_0) and
                    (open_3 <= close_8) and
                    (close_3 <= close_5)
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic with position state tracking.
        
        Entry:
            - Condition1[yesterday] = true AND flat → ENTRY_LONG
        
        Exit (priority order):
            1) SL hit → EXIT_LONG (bracket handles this)
            2) PT hit → EXIT_LONG (bracket handles this)
            3) Profitable closes >= threshold → EXIT_LONG (cancel bracket, place market exit)
            4) Bars held > max_time AND Condition1=false → EXIT_LONG (cancel bracket, place market exit)
        """
        if len(df) < 10:
            return Signal(
                signal_type="NONE",
                reason="Insufficient data",
                close_price=df.iloc[-1]["close"],
                indicators={},
                meta={"date": str(df.iloc[-1]["date"])},
            )
        
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        
        close = float(last["close"])
        high = float(last["high"])
        low = float(last["low"])
        open_price = float(last["open"])
        
        # Check yesterday's Condition1
        condition1_yesterday = bool(prev["condition1"])
        condition1_today = bool(last["condition1"])
        
        # Build indicator dict for logging
        indicators = {
            "roc5": round(float(last["roc5"]), 4),
            "ema3": round(float(last["ema3"]), 2),
            "atr": round(float(last["atr"]), 2),
            "condition1_yesterday": condition1_yesterday,
            "condition1_today": condition1_today,
            "open": round(open_price, 2),
            "high": round(high, 2),
            "low": round(low, 2),
        }
        
        meta = {
            "date": str(last["date"]),
            "prev_close": round(float(prev["close"]), 2),
            "prev_atr": round(float(prev["atr"]), 2),
        }
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        print("current_pos BEFORE Exit IF:", current_pos,self._position_state)
        if current_pos > 0 or self._position_state["in_position"]:
            state = self._position_state
            
            # Update bars held
            state["bars_held"] += 1
            
            # Update profitable closes count
            if state["bars_held"] > 0 and close >= state["entry_price"]:
                state["profitable_closes"] += 1
            
            # Add state to indicators for logging
            indicators["bars_held"] = state["bars_held"]
            indicators["profitable_closes"] = state["profitable_closes"]
            indicators["entry_price"] = round(state["entry_price"], 2)
            
            # Priority 1: Stop Loss
            if self._sl_on and state["sl_price"] > 0 and low <= state["sl_price"]:
                self.log.info("EXIT: Stop Loss hit at %.2f", state["sl_price"])
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Stop Loss hit (bars={state['bars_held']}, prof_x={state['profitable_closes']})",
                    close_price=state["sl_price"],  # Exit at SL price
                    indicators=indicators,
                    meta={**meta, "exit_type": "SL", "reset_entry": condition1_today},
                )
            
            # Priority 2: Profit Target
            if self._pt_on and state["tp_price"] > 0 and high >= state["tp_price"]:
                self.log.info("EXIT: Profit Target hit at %.2f", state["tp_price"])
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Profit Target hit (bars={state['bars_held']}, prof_x={state['profitable_closes']})",
                    close_price=state["tp_price"],  # Exit at PT price
                    indicators=indicators,
                    meta={**meta, "exit_type": "PT", "reset_entry": condition1_today},
                )
            
            # Priority 3: Profitable closes threshold
            if state["profitable_closes"] >= self._profitable_closes:
                self.log.info("EXIT: Profitable closes threshold reached (%d)", state["profitable_closes"])
                self._save_position_state()  # Save state before exit
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Profitable closes >= {self._profitable_closes}",
                    close_price=open_price,  # Exit at today's open (simulated)
                    indicators=indicators,
                    meta={**meta, "exit_type": "PROFX", "reset_entry": condition1_today, "cancel_bracket": True},
                )
            
            # Priority 4: Time exit (only if condition1 is false)
            if state["bars_held"] > (self._max_time - 1) and not condition1_yesterday:
                self.log.info("EXIT: Time exit (bars=%d, no signal)", state["bars_held"])
                self._save_position_state()  # Save state before exit
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Time exit after {state['bars_held']} bars",
                    close_price=open_price,
                    indicators=indicators,
                    meta={**meta, "exit_type": "TIMEX", "reset_entry": False, "cancel_bracket": True},
                )
            
            # Continue holding
            self._save_position_state()  # Save state when holding
            self.log.info(
                "HOLD: bars=%d prof_x=%d (max_time=%d prof_thresh=%d)",
                state["bars_held"], state["profitable_closes"],
                self._max_time, self._profitable_closes,
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding position (bars={state['bars_held']}, prof_x={state['profitable_closes']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        if current_pos == 0 and condition1_yesterday:
            # Calculate PT/SL from previous bar
            if self._position_state["in_position"]:
                self.log.warning("Skipping entry: position_state shows in_position=True despite current_pos=0")
                return Signal(signal_type="NONE", reason="Position state conflict", close_price=close, indicators=indicators, meta=meta)
            prev_close = float(prev["close"])
            prev_atr = float(prev["atr"])
            
            tp_price = prev_close + prev_atr * self._ptatr if self._pt_on else 0
            sl_price = prev_close - prev_atr * self._slatr if self._sl_on else 0
            
            # Initialize position state
            self._position_state = {
                "in_position": True,
                "entry_bar_date": str(last["date"]),
                "entry_price": open_price,  # Will be updated with actual fill
                "profitable_closes": 0,
                "bars_held": 0,
                "tp_price": tp_price,
                "sl_price": sl_price,
            }
            
            indicators["tp_price"] = round(tp_price, 2)
            indicators["sl_price"] = round(sl_price, 2)
            
            self.log.info(
                "ENTRY: Condition1 triggered | TP=%.2f SL=%.2f",
                tp_price, sl_price,
            )
            
            self._save_position_state()  # Save state on entry
            
            return Signal(
                signal_type="ENTRY_LONG",
                reason="Condition1 triggered on previous bar",
                close_price=open_price,  # Enter at open
                indicators=indicators,
                meta={**meta, "tp_price": tp_price, "sl_price": sl_price},
            )
        
        # No signal
        return Signal(
            signal_type="NONE",
            reason="No actionable signal",
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def _reset_position_state(self) -> None:
        """Reset position state after exit."""
        self._position_state = {
            "in_position": False,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "profitable_closes": 0,
            "bars_held": 0,
            "tp_price": 0.0,
            "sl_price": 0.0,
        }

        
    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Override to handle PT/SL from signal metadata and reset/re-entry logic.
        """
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        # Get indicative price
        fallback = signal.close_price
        price, source = self.broker.get_indicative_price(contract, fallback)
        self.log.info("Indicative price: %.2f (%s)", price, source)
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Get PT/SL from signal metadata
            tp_price = signal.meta.get("tp_price", 0)
            sl_price = signal.meta.get("sl_price", 0)
            
            # Update position state with actual entry price
            self._position_state["entry_price"] = price
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="BUY",
                quantity=qty,
                limit_price=price,
                tp_price=tp_price,
                sl_price=sl_price,
            )
            
            # Open trade in database
            trade_id = self.db.open_trade(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                direction="LONG",
                quantity=qty,
                entry_price=result["limit_px"],
                tp_price=result["tp_px"],
                sl_price=result["sl_px"],
            )
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="BUY",
                order_type="BRACKET",
                quantity=qty,
                trade_id=trade_id,
                limit_price=result["limit_px"],
            )
        
        elif signal.signal_type == "EXIT_LONG":
            qty = abs(current_pos)
            exit_price = signal.close_price  # Use signal's close_price (might be PT/SL)
            
            # Check if we need to cancel bracket orders (for non-bracket exits)
            if signal.meta.get("cancel_bracket", False):
                self.log.info("Cancelling bracket orders for non-bracket exit")
                self.order_mgr.cancel_open_bracket_legs(contract, include_parent=True)
            
            # Place exit order
            fill_px = self.order_mgr.place_exit(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=exit_price,
            )
            
            # Close the open trade
            open_trade = self.db.get_open_trade(self.name)
            if open_trade:
                pnl = (fill_px - open_trade["entry_price"]) * qty * self.spec.point_value
                self.db.close_trade(open_trade["id"], fill_px, pnl)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="SELL",
                order_type="EXIT",
                quantity=qty,
                limit_price=fill_px,
            )
            
            # Check for reset/re-entry
            if signal.meta.get("reset_entry", False):
                self.log.info("Reset entry condition met - position will re-enter on next signal")
                # The next execution cycle will pick up the entry signal