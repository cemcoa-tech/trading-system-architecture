# strategies/btc_rsi_meanrev.py
"""
strategies/btc_rsi_meanrev.py
─────────────────────────────
BTC Micro Futures (MBT) RSI Mean-Reversion Strategy

Entry:
    - NOT trending (trending = HH, HL, HL pattern on last 3 bars)
    - RSI(2) Wilder on previous bar between 65 and 75
    → Buy next bar at open

Exits:
    1) Signal Exit: barssinceentry < max_time-1
       AND ValueLowest(low, 5)[0] > ValueLowest(low, 5)[5]
       (rising 5-bar low floor → momentum returning)
       → Sell next bar at open
    
    2) Time Exit: barssinceentry >= max_time-1
       → Sell next bar at open

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
from utils.indicators import wilder_rsi, value_lowest


class BTCRSIMeanRevStrategy(BaseStrategy):
    """
    BTC RSI mean-reversion strategy.
    
    Enters on RSI(2) 65-75 when NOT trending.
    Exits on rising 5-bar low floor or time limit.
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
        self._value_low_window: int = p.get("value_low_window", 5)
        self._max_time: int = p.get("max_time", 10)
        
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
        """Add RSI(2) and ValueLowest(low, 5)."""
        # Wilder RSI(2)
        df["rsi2"] = wilder_rsi(df["close"], self._rsi_length)
        
        # ValueLowest(low, window)
        df["vl5"] = value_lowest(df["low"], self._value_low_window)
        
        # Trending detection components
        df["is_trending"] = self._compute_trending(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.2f  RSI2=%.2f  VL5=%.2f  Trending=%s",
            last["date"],
            last["close"],
            last.get("rsi2", np.nan),
            last.get("vl5", np.nan),
            last.get("is_trending", False),
        )
        
        return df

    def _compute_trending(self, df: pd.DataFrame) -> pd.Series:
        """
        Detect trending pattern: HH, HL, HL on last 3 bars.
        
        At bar i (current):
            high[i-1] > high[i-2]  (higher high)
            low[i] > low[i-1]      (higher low)
            low[i-1] > low[i-2]    (higher low)
        
        Returns:
            Series of boolean trending flags
        """
        trending = pd.Series(False, index=df.index)
        
        for i in range(3, len(df)):
            high_im1 = df["high"].iloc[i - 1]
            high_im2 = df["high"].iloc[i - 2]
            low_i = df["low"].iloc[i]
            low_im1 = df["low"].iloc[i - 1]
            low_im2 = df["low"].iloc[i - 2]
            
            trending.iloc[i] = (
                (high_im1 > high_im2) and
                (low_i > low_im1) and
                (low_im1 > low_im2)
            )
        
        return trending

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic:
        
        Entry (signal on bar i-1, act on bar i):
            - NOT trending at bar i-1
            - RSI(2)[i-2] between rsi_low and rsi_high
            → ENTRY_LONG at bar i open
        
        Exit (while in position):
            1) Signal Exit: bars_held < max_time-1
               AND vl5[i-1] > vl5[i-6]  (rising low floor)
               → EXIT_LONG at bar i open
            
            2) Time Exit: bars_held >= max_time-1
               → EXIT_LONG at bar i open
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
        prev2 = df.iloc[-3] if len(df) >= 3 else prev
        
        close = float(last["close"])
        open_price = float(last["open"])
        
        # Build indicator dict
        indicators = {
            "rsi2_prev": round(float(prev.get("rsi2", np.nan)), 2),
            "rsi2_prev2": round(float(prev2.get("rsi2", np.nan)), 2),
            "vl5_prev": round(float(prev.get("vl5", np.nan)), 2),
            "is_trending_prev": bool(prev.get("is_trending", False)),
            "open": round(open_price, 2),
            "close": round(close, 2),
        }
        
        meta = {"date": str(last["date"])}
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos > 0 or self._position_state["in_position"]:
            state = self._position_state
            state["bars_held"] += 1
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 2)
            
            # Save state update
            self._save_position_state()
            
            # Evaluate exits on PREVIOUS bar (i-1)
            bars_at_prev = state["bars_held"] - 1  # bars held as of prev bar
            
            # Priority 2: Time Exit
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
            
            # Priority 1: Signal Exit (rising low floor)
            # Check: vl5[i-1] > vl5[i-6]
            if bars_at_prev < (self._max_time - 1):
                vl5_prev = prev.get("vl5")
                vl5_6ago = df.iloc[-7].get("vl5") if len(df) >= 7 else None
                
                if vl5_prev is not None and vl5_6ago is not None and not np.isnan(vl5_prev) and not np.isnan(vl5_6ago):
                    if vl5_prev > vl5_6ago:
                        self.log.info(
                            "EXIT: Signal exit (VL5 rising: %.2f > %.2f, bars=%d)",
                            vl5_prev, vl5_6ago, state["bars_held"]
                        )
                        self._reset_position_state()
                        self._delete_position_state()
                        return Signal(
                            signal_type="EXIT_LONG",
                            reason=f"Signal exit: rising low floor (bars={state['bars_held']})",
                            close_price=open_price,
                            indicators={
                                **indicators,
                                "vl5_prev": round(vl5_prev, 2),
                                "vl5_6ago": round(vl5_6ago, 2),
                            },
                            meta={**meta, "exit_type": "SignalX"},
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
        
        # Entry signal evaluated on PREVIOUS bar (i-1)
        # Check: NOT trending AND rsi2[i-2] in [rsi_low, rsi_high]
        
        is_trending_prev = bool(prev.get("is_trending", False))
        rsi_prev2 = float(prev2.get("rsi2", np.nan))
        
        if np.isnan(rsi_prev2):
            return Signal(
                signal_type="NONE",
                reason="RSI not available",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        rsi_in_range = self._rsi_low <= rsi_prev2 <= self._rsi_high
        entry_condition = (not is_trending_prev) and rsi_in_range
        
        if current_pos == 0 and entry_condition:
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
            
            self.log.info(
                "ENTRY: NOT trending, RSI2[prev2]=%.2f in [%.0f, %.0f]",
                rsi_prev2, self._rsi_low, self._rsi_high,
            )
            
            return Signal(
                signal_type="ENTRY_LONG",
                reason=f"RSI({self._rsi_length}) mean-reversion entry",
                close_price=open_price,  # Enter at open
                indicators={
                    **indicators,
                    "entry_condition": "NOT_trending AND RSI_in_range",
                },
                meta=meta,
            )
        
        # No signal
        reason_parts = []
        if is_trending_prev:
            reason_parts.append("trending")
        if not rsi_in_range:
            reason_parts.append(f"RSI={rsi_prev2:.1f} out of range")
        
        reason = "No signal: " + ", ".join(reason_parts) if reason_parts else "No actionable signal"
        
        return Signal(
            signal_type="NONE",
            reason=reason,
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    
    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal.
        
        BTC strategy uses simple limit orders (no bracket).
        Entry at open, exit at open.
        """
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        # Get indicative price (use signal's close_price as it's the open)
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