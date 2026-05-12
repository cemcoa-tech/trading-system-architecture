# strategies/treasury_stoch_hurst.py
"""
strategies/treasury_stoch_hurst.py
──────────────────────────────────
Treasury Stochastic Hurst Strategy

Signal: ZB (30-Year Treasury Bond)
Execution: MWN (Micro 30-Year Note)

Entry:
    - Stochastic(14) crosses below 60 threshold
    - Hurst exponent rising: H[0] > H[5]
    - Condition must be true DELAY bars ago (default 1)
    → Buy at limit (mid + offset)

Exit:
    1) Signal Exit: RSI(2) >= 70
       → Sell at limit (mid - offset)
    
    2) Time Exit: BarsSinceEntry >= max_time - 1
       → Sell at limit (mid - offset)

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
from utils.indicators import hurst_exponent, stochastic, wilder_rsi


class TreasuryStochHurstStrategy(BaseStrategy):
    """
    Treasury strategy using Stochastic and Hurst exponent.
    
    Uses ZB for signals but executes on MWN (micro contract).
    Combines momentum (Stochastic) and trend persistence (Hurst).
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
        self._signal_symbol: str = p.get("signal_symbol", "ZB")
        self._signal_contract_month: str = p.get("signal_contract_month", "202606")
        self._stoch_length: int = p.get("stoch_length", 14)
        self._stoch_threshold: float = p.get("stoch_threshold", 60.0)
        self._hurst_length: int = p.get("hurst_length", 20)
        self._hurst_lookback: int = p.get("hurst_lookback", 5)
        self._rsi_length: int = p.get("rsi_length", 2)
        self._rsi_exit_threshold: float = p.get("rsi_exit_threshold", 70.0)
        self._entry_delay: int = p.get("entry_delay", 1)
        self._max_time: int = p.get("max_time", 9)
        self._price_offset_ticks: int = p.get("price_offset_ticks", 2)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database."""
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
        """
        Fetch historical data from SIGNAL contract (ZB).
        
        This strategy uses ZB for signals but executes on MWN.
        """
        from ib_insync import Future
        
        # Create ZB signal contract
        signal_contract = Future(
            symbol=self._signal_symbol,
            lastTradeDateOrContractMonth=self._signal_contract_month,
            exchange=self.spec.exchange,
            currency=self.spec.currency,
        )
        
        signal_ct = self.broker.ib.qualifyContracts(signal_contract)[0]
        self.log.info(
            "Using signal contract: %s %s (conId=%d)",
            signal_ct.symbol,
            signal_ct.lastTradeDateOrContractMonth,
            signal_ct.conId,
        )
        
        return self.broker.fetch_historical_bars(signal_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add indicators:
        - Stochastic(14)
        - Hurst exponent(20)
        - RSI(2)
        - Entry condition with delay
        """
        # Stochastic oscillator
        df["stoch"] = stochastic(
            df["high"], df["low"], df["close"],
            self._stoch_length
        )
        
        # Hurst exponent
        df["hurst"] = hurst_exponent(
            df["high"], df["low"], df["close"],
            self._hurst_length
        )
        
        # RSI for exit
        df["rsi2"] = wilder_rsi(df["close"], self._rsi_length)
        
        # Pre-compute entry condition for delay
        df["entry_condition"] = self._evaluate_entry_condition(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.6f  Stoch=%.2f  Hurst=%.4f  RSI2=%.2f  EntryCond=%s",
            last["date"],
            last["close"],
            last.get("stoch", np.nan),
            last.get("hurst", np.nan),
            last.get("rsi2", np.nan),
            last.get("entry_condition", False),
        )
        
        return df

    def _evaluate_entry_condition(self, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate entry condition for each bar.
        
        Entry condition:
            - Stochastic crosses below threshold (stoch[i-1] > thresh AND stoch[i] <= thresh)
            - Hurst exponent rising: H[i] > H[i-5]
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(self._hurst_lookback + 2, len(df)):
            try:
                # Stochastic cross
                stoch_prev = df["stoch"].iloc[i - 1]
                stoch_curr = df["stoch"].iloc[i]
                stoch_cross = (
                    stoch_prev > self._stoch_threshold and
                    stoch_curr <= self._stoch_threshold
                )
                
                # Hurst rising
                hurst_curr = df["hurst"].iloc[i]
                hurst_prev = df["hurst"].iloc[i - self._hurst_lookback]
                hurst_rising = hurst_curr > hurst_prev
                
                # Check for valid values
                if any(pd.isna(v) for v in [stoch_prev, stoch_curr, hurst_curr, hurst_prev]):
                    continue
                
                condition.iloc[i] = stoch_cross and hurst_rising
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic with delayed entry.
        
        Entry (signal on bar i, act on bar i+1):
            - entry_condition must have been true DELAY bars ago
            → ENTRY_LONG at bar i+1
        
        Exit (while in position):
            1) Signal Exit: RSI(2) >= rsi_exit_threshold
               → EXIT_LONG
            
            2) Time Exit: bars_held >= max_time - 1
               → EXIT_LONG
        """
        if len(df) < 40:
            return Signal(
                signal_type="NONE",
                reason="Insufficient data",
                close_price=df.iloc[-1]["close"] if len(df) > 0 else 0,
                indicators={},
                meta={"date": str(df.iloc[-1]["date"]) if len(df) > 0 else ""},
            )
        
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else last
        
        close = float(last["close"])
        
        # Build indicator dict
        indicators = {
            "stoch": round(float(last.get("stoch", np.nan)), 2),
            "hurst": round(float(last.get("hurst", np.nan)), 4),
            "rsi2": round(float(last.get("rsi2", np.nan)), 2),
            "entry_condition": bool(last.get("entry_condition", False)),
            "close": round(close, 6),
        }
        
        meta = {"date": str(last["date"])}
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos > 0:
            state = self._position_state
            state["bars_held"] += 1
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 6)
            
            # Priority 1: Time Exit
            if state["bars_held"] >= (self._max_time - 1):
                self.log.info("EXIT: Time limit reached (bars=%d)", state["bars_held"])
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Time exit after {state['bars_held']} bars",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "TimeX"},
                )
            
            # Priority 2: Signal Exit (RSI)
            rsi2_curr = last.get("rsi2")
            if rsi2_curr is not None and not np.isnan(rsi2_curr):
                if rsi2_curr >= self._rsi_exit_threshold:
                    self.log.info(
                        "EXIT: RSI signal (RSI2=%.2f >= %.2f, bars=%d)",
                        rsi2_curr, self._rsi_exit_threshold, state["bars_held"]
                    )
                    self._reset_position_state()
                    return Signal(
                        signal_type="EXIT_LONG",
                        reason=f"Signal exit: RSI(2)={rsi2_curr:.2f} >= {self._rsi_exit_threshold}",
                        close_price=close,
                        indicators=indicators,
                        meta={**meta, "exit_type": "SigX"},
                    )
            
            # Continue holding
            self.log.info(
                "HOLD: bars=%d (max=%d), RSI2=%.2f (thresh=%.2f)",
                state["bars_held"], self._max_time,
                rsi2_curr if rsi2_curr is not None else -1,
                self._rsi_exit_threshold,
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding position (bars={state['bars_held']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        # Entry: condition must have been true DELAY bars ago
        delay_idx = len(df) - 1 - self._entry_delay
        
        if delay_idx >= 0 and delay_idx < len(df):
            condition_delayed = bool(df.iloc[delay_idx].get("entry_condition", False))
            
            if current_pos == 0 and condition_delayed:
                # Initialize position state
                self._position_state = {
                    "in_position": True,
                    "entry_bar_date": str(last["date"]),
                    "entry_price": close,  # Will be updated with actual fill
                    "bars_held": 0,
                }
                
                delay_bar = df.iloc[delay_idx]
                self.log.info(
                    "ENTRY: condition true %d bar(s) ago (date=%s, Stoch=%.2f, Hurst=%.4f)",
                    self._entry_delay,
                    delay_bar["date"],
                    delay_bar.get("stoch", np.nan),
                    delay_bar.get("hurst", np.nan),
                )
                
                return Signal(
                    signal_type="ENTRY_LONG",
                    reason=f"Delayed entry: Stoch cross + Hurst rising {self._entry_delay} bar(s) ago",
                    close_price=close,
                    indicators={
                        **indicators,
                        "delay": self._entry_delay,
                        "condition_delayed": condition_delayed,
                        "delay_bar_date": str(delay_bar["date"]),
                    },
                    meta=meta,
                )
        
        # No signal
        return Signal(
            signal_type="NONE",
            reason="No actionable signal (entry condition not met with delay)",
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def get_position_size(self, signal: Signal) -> int:
        """Fixed position size (1 contract for MWN)."""
        return self.params.max_position

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal with limit orders on MWN.
        
        Entry: mid + offset (in ticks)
        Exit: mid - offset (in ticks)
        """
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        # Get current market price from EXECUTION contract (MWN)
        fallback = signal.close_price if signal.close_price > 0 else None
        price, source = self.broker.get_indicative_price(contract, fallback)
        
        if price is None or not np.isfinite(price) or price <= 0:
            self.log.error("Could not get valid market price")
            return
        
        self.log.info("Market price: %.6f (%s)", price, source)
        
        # Calculate offset from ticks
        offset = self._price_offset_ticks * self.spec.tick_size
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Entry: mid + offset
            limit_px = self.order_mgr.round_tick(
                price + offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing ENTRY order: BUY %d @ %.6f (mid=%.6f + %d ticks)",
                qty, limit_px, price, self._price_offset_ticks
            )
            
            # Update position state with actual entry price
            self._position_state["entry_price"] = limit_px
            
            # Place limit order
            from ib_insync import LimitOrder
            order = LimitOrder("BUY", qty, limit_px)
            order.account = self.order_mgr._account
            order.tif = "DAY"
            
            trade = self.order_mgr._ib.placeOrder(contract, order)
            self.order_mgr._ib.waitOnUpdate()
            
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
            
            # Exit: mid - offset
            limit_px = self.order_mgr.round_tick(
                price - offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing EXIT order: SELL %d @ %.6f (mid=%.6f - %d ticks)",
                qty, limit_px, price, self._price_offset_ticks
            )
            
            # Place exit order (no bracket to cancel)
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