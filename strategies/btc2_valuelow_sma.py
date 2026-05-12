# strategies/btc2_valuelow_sma.py
"""
strategies/btc2_valuelow_sma.py
───────────────────────────────
BTC Strategy 2: ValueLow/RSI Entry + SMA Turn-Up Exit

Entry (with delay):
    - condition1 = ValueLow(5)[1] <= ValueOpen(5)[3]
                   AND RSI(2)[0] >= 65
                   AND RSI(2)[0] <= 75
    - Condition must have been true DELAY bars ago
    → Buy next bar at market

Exits:
    1) TimeX: BarsSinceEntry >= max_time - 1
       → Sell next bar at market
    
    2) SigX: BarsSinceEntry < max_time - 1
             AND Average(Close, 5)[0] > Average(Close, 5)[2]
       → Sell next bar at market
       (5-period SMA has turned up)

Direction: Long-only
"""

import pandas as pd
import numpy as np
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import wilder_rsi, value_lowest, value_open, sma


class BTC2ValueLowSMAStrategy(BaseStrategy):
    """
    BTC Strategy 2: ValueLow/RSI entry with SMA turn-up exit.
    
    Uses delayed entry condition and SMA slope for exit timing.
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
        self._rsi_length: int = p.get("rsi_length", 2)
        self._rsi_low: float = p.get("rsi_low", 65.0)
        self._rsi_high: float = p.get("rsi_high", 75.0)
        self._vl_window: int = p.get("vl_window", 5)
        self._sma_exit_length: int = p.get("sma_exit_length", 5)
        self._entry_delay: int = p.get("entry_delay", 1)
        self._max_time: int = p.get("max_time", 6)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database."""
        pos_state = self.db.get_position_state(self.name, self.spec.symbol)
        
        if pos_state:
            return {
                "in_position": True,
                "entry_bar_date": pos_state.get("entry_bar_date"),
                "entry_price": pos_state.get("entry_price", 0.0),
                "bars_held": pos_state.get("bars_held", 0),
            }
        
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

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from continuous MBT contract."""
        from ib_insync import ContFuture
        
        data_spec = ContFuture(
            symbol=self.spec.data_symbol,
            exchange=self.spec.exchange,
            currency=self.spec.currency,
        )
        
        data_ct = self.broker.ib.qualifyContracts(data_spec)[0]
        return self.broker.fetch_historical_bars(data_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add indicators:
        - RSI(2)
        - ValueLow(5)
        - ValueOpen(5)
        - SMA(Close, 5)
        - condition1 (for delayed entry)
        """
        # Wilder RSI(2)
        df["rsi2"] = wilder_rsi(df["close"], self._rsi_length)
        
        # ValueLow(5) - rolling min of Low
        df["vl5"] = value_lowest(df["low"], self._vl_window)
        
        # ValueOpen(5) - rolling min of Open
        df["vo5"] = value_open(df["open"], self._vl_window)
        
        # SMA(Close, 5) for exit signal
        df["sma5"] = sma(df["close"], self._sma_exit_length)
        
        # Pre-compute condition1 for each bar (for delay lookback)
        df["condition1"] = self._evaluate_condition1(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.2f  RSI2=%.2f  VL5=%.2f  VO5=%.2f  SMA5=%.2f  Cond1=%s",
            last["date"],
            last["close"],
            last.get("rsi2", np.nan),
            last.get("vl5", np.nan),
            last.get("vo5", np.nan),
            last.get("sma5", np.nan),
            last.get("condition1", False),
        )
        
        return df

    def _evaluate_condition1(self, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate condition1 for each bar.
        
        condition1 at bar i:
            ValueLow(5)[1] <= ValueOpen(5)[3]
                → vl5 at bar i-1 <= vo5 at bar i-3
            AND RSI(2)[0] >= 65
                → rsi2 at bar i >= 65
            AND RSI(2)[0] <= 75
                → rsi2 at bar i <= 75
        
        TradeStation indexing:
            [0] = current bar
            [1] = 1 bar ago
            [3] = 3 bars ago
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(5, len(df)):  # Need at least 5 bars for lookbacks
            try:
                vl5_1 = df["vl5"].iloc[i - 1]  # ValueLow(5)[1]
                vo5_3 = df["vo5"].iloc[i - 3]  # ValueOpen(5)[3]
                rsi_0 = df["rsi2"].iloc[i]      # RSI(2)[0]
                
                # Check for valid values
                if any(pd.isna(v) for v in [vl5_1, vo5_3, rsi_0]):
                    continue
                
                # Evaluate condition
                condition.iloc[i] = (
                    (vl5_1 <= vo5_3) and
                    (self._rsi_low <= rsi_0 <= self._rsi_high)
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic with delayed entry.
        
        Entry (signal on bar i, act on bar i+1):
            - condition1 must have been true DELAY bars ago
            - Example: if DELAY=1, condition1[i-1] must be true
            → ENTRY_LONG at bar i+1 open
        
        Exit (while in position):
            1) TimeX: bars_held >= max_time - 1
               → EXIT_LONG at next bar open
            
            2) SigX: bars_held < max_time - 1
                     AND SMA(5)[0] > SMA(5)[2]
               → EXIT_LONG at next bar open
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
        open_price = float(last["open"])
        
        # Build indicator dict
        indicators = {
            "rsi2": round(float(last.get("rsi2", np.nan)), 2),
            "vl5": round(float(last.get("vl5", np.nan)), 2),
            "vo5": round(float(last.get("vo5", np.nan)), 2),
            "sma5": round(float(last.get("sma5", np.nan)), 2),
            "condition1": bool(last.get("condition1", False)),
            "open": round(open_price, 2),
            "close": round(close, 2),
        }
        
        meta = {"date": str(last["date"])}
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos > 0 or self._position_state["in_position"]:
            state = self._position_state
            state["bars_held"] += 1
            
            # Save state update
            self._save_position_state()
            
            # Use previous bar's state for exit decisions
            bars_at_prev = state["bars_held"] - 1
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 2)
            
            # Priority 1: Time Exit
            if bars_at_prev >= (self._max_time - 1):
                self.log.info("EXIT: Time limit reached (bars=%d)", state["bars_held"])
                self._reset_position_state()
                self._delete_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Time exit after {state['bars_held']} bars",
                    close_price=open_price,  # Exit at today's open
                    indicators=indicators,
                    meta={**meta, "exit_type": "TimeX"},
                )
            
            # Priority 2: Signal Exit (SMA turning up)
            # Check: SMA(5)[0] > SMA(5)[2]  (at previous bar)
            if bars_at_prev < (self._max_time - 1):
                sma5_0 = prev.get("sma5")
                sma5_2 = df.iloc[-4].get("sma5") if len(df) >= 4 else None  # [i-1-2] = i-3
                
                if sma5_0 is not None and sma5_2 is not None and not np.isnan(sma5_0) and not np.isnan(sma5_2):
                    if sma5_0 > sma5_2:
                        self.log.info(
                            "EXIT: Signal exit (SMA turning up: %.2f > %.2f, bars=%d)",
                            sma5_0, sma5_2, state["bars_held"]
                        )
                        self._reset_position_state()
                        self._delete_position_state()
                        return Signal(
                            signal_type="EXIT_LONG",
                            reason=f"Signal exit: SMA(5) turning up (bars={state['bars_held']})",
                            close_price=open_price,
                            indicators={
                                **indicators,
                                "sma5_0": round(sma5_0, 2),
                                "sma5_2": round(sma5_2, 2),
                            },
                            meta={**meta, "exit_type": "SigX"},
                        )
            
            # Continue holding
            self.log.info(
                "HOLD: bars=%d (max_time=%d)",
                state["bars_held"], self._max_time,
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding position (bars={state['bars_held']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        # Entry: condition1 must have been true DELAY bars ago
        # Signal evaluated on bar i-1 (prev), act on bar i (today)
        # Check condition1 at bar i-1-DELAY
        
        delay_idx = len(df) - 1 - self._entry_delay  # Current bar minus delay
        
        if delay_idx >= 0 and delay_idx < len(df):
            condition1_delayed = bool(df.iloc[delay_idx].get("condition1", False))
            # print("delay_idx :--",delay_idx)
            # print(df.tail(10))
            # print("delay idx",df.iloc[delay_idx])
            # print("Condition1 IS:--->",condition1_delayed)
            if current_pos == 0 and condition1_delayed:
                # Safety check: ensure position_state agrees we're flat
                if self._position_state["in_position"]:
                    self.log.warning("Skipping entry: position_state shows in_position=True despite current_pos=0")
                    return Signal(
                        signal_type="NONE", 
                        reason="Position state conflict",
                        close_price=close,
                        indicators=indicators,
                        meta=meta,
                    )
                
                # Initialize position state
                self._position_state = {
                    "in_position": True,
                    "entry_bar_date": str(last["date"]),
                    "entry_price": open_price,  # Will be updated with actual fill
                    "bars_held": 0,
                }
                
                # Save position state to database
                self._save_position_state()
                
                delay_bar = df.iloc[delay_idx]
                self.log.info(
                    "ENTRY: condition1 was true %d bar(s) ago (date=%s, RSI2=%.2f, VL5=%.2f, VO5=%.2f)",
                    self._entry_delay,
                    delay_bar["date"],
                    delay_bar.get("rsi2", np.nan),
                    delay_bar.get("vl5", np.nan),
                    delay_bar.get("vo5", np.nan),
                )
                
                return Signal(
                    signal_type="ENTRY_LONG",
                    reason=f"Delayed entry: condition1 true {self._entry_delay} bar(s) ago",
                    close_price=open_price,  # Enter at open
                    indicators={
                        **indicators,
                        "delay": self._entry_delay,
                        "condition1_delayed": condition1_delayed,
                        "delay_bar_date": str(delay_bar["date"]),
                    },
                    meta=meta,
                )
        
        # No signal
        return Signal(
            signal_type="NONE",
            reason="No actionable signal (condition1 not met with delay)",
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal.
        
        BTC Strategy 2 uses simple limit orders (no bracket).
        Entry at open, exit at open.
        """
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        # Get indicative price (use signal's close_price as it's for open)
        fallback = signal.close_price
        price, source = self.broker.get_indicative_price(contract, fallback)
        self.log.info("Indicative price: %.2f (%s)", price, source)
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Update position state with actual entry price
            self._position_state["entry_price"] = price
            
            # Place simple limit order (no bracket for this strategy)
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
            from ib_insync import LimitOrder
            order = LimitOrder("BUY", qty, limit_px)
            order.account = self.order_mgr._account
            order.tif = "DAY"
            
            trade = self.order_mgr._ib.placeOrder(contract, order)
            self.order_mgr._ib.waitOnUpdate()
            
            self.log.info(
                "Entry order placed: BUY %d @ %.2f",
                qty, limit_px,
            )
            
            # Open trade in database
            trade_id = self.db.open_trade(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                direction="LONG",
                quantity=qty,
                entry_price=limit_px,
                tp_price=None,  # No TP for this strategy
                sl_price=None,  # No SL for this strategy
            )
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="BUY",
                order_type="LIMIT",
                quantity=qty,
                trade_id=trade_id,
                limit_price=limit_px,
            )
        
        elif signal.signal_type == "EXIT_LONG":
            qty = abs(current_pos)
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
            # Place exit order (no bracket to cancel for this strategy)
            fill_px = self.order_mgr.place_exit(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=limit_px,
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