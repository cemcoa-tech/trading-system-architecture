# strategies/rb_combined.py
"""
strategies/rb_combined.py
─────────────────────────
RB (RBOB Gasoline) Combined Long/Short Strategy

Long Entry:
    - Open <= Low[5]  (ValueOpen(5)[0] <= ValueLow(5)[5])
    - ADX(20) <= 15  (ranging market)
    - Delayed confirmation
    
Short Entry:
    - Low[2] > High[6]  (gap up pattern)
    - Thursday only
    - Delayed confirmation

Exits:
    - ATR-based stop and target (3x and 6x ATR)
    - Time exits: 9 bars (long) / 3 bars (short)

Direction: Long and Short (two separate systems)
"""

import pandas as pd
import numpy as np
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import atr as calc_atr, adx as calc_adx


class RBCombinedStrategy(BaseStrategy):
    """
    RB combined strategy with both long and short entries.
    
    Long: Mean reversion in ranging markets (low ADX)
    Short: Thursday gap-up fade
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
        self._atr_length: int = p.get("atr_length", 14)
        self._atr_mult_stop: float = p.get("atr_mult_stop", 3.0)
        self._atr_mult_target: float = p.get("atr_mult_target", 6.0)
        self._adx_length: int = p.get("adx_length", 20)
        self._adx_threshold: float = p.get("adx_threshold", 15.0)
        self._entry_delay: int = p.get("entry_delay", 1)
        self._value_lookback: int = p.get("value_lookback", 5)
        self._max_time_long: int = p.get("max_time_long", 9)
        self._max_time_short: int = p.get("max_time_short", 3)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database."""
        open_trade = self.db.get_open_trade(self.name)
        if not open_trade:
            return {
                "in_position": False,
                "side": None,  # "LONG" or "SHORT"
                "entry_bar_date": None,
                "entry_price": 0.0,
                "bars_held": 0,
                "atr_entry": 0.0,
                "stop_price": 0.0,
                "target_price": 0.0,
            }
        
        direction = open_trade.get("direction", "LONG")
        
        return {
            "in_position": True,
            "side": direction,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "bars_held": open_trade.get("bars_held", 0),  # Load from DB
            "atr_entry": open_trade.get("atr_entry", 0.0),  # Load from DB
            "stop_price": open_trade.get("sl_price", 0.0),
            "target_price": open_trade.get("tp_price", 0.0),
        }

    def _reset_position_state(self) -> None:
        """Reset position state after exit."""
        self._position_state = {
            "in_position": False,
            "side": None,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "bars_held": 0,
            "atr_entry": 0.0,
            "stop_price": 0.0,
            "target_price": 0.0,
        }

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from RB contract."""
        trade_ct = self.broker.qualify_contract(self.spec)
        return self.broker.fetch_historical_bars(trade_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add indicators:
        - ATR(14)
        - ADX(20)
        - Long/Short entry conditions
        """
        # ATR
        df["atr"] = calc_atr(df["high"], df["low"], df["close"], self._atr_length)
        
        # ADX
        df["adx"] = calc_adx(df["high"], df["low"], df["close"], self._adx_length)
        
        # Day of week (for Thursday short entries)
        df["is_thursday"] = pd.to_datetime(df["date"]).dt.weekday == 3
        
        # Pre-compute entry conditions
        df["long_condition"] = self._evaluate_long_condition(df)
        df["short_condition"] = self._evaluate_short_condition(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.4f  ATR=%.4f  ADX=%.2f  Thu=%s  LongCond=%s  ShortCond=%s",
            last["date"],
            last["close"],
            last.get("atr", np.nan),
            last.get("adx", np.nan),
            last.get("is_thursday", False),
            last.get("long_condition", False),
            last.get("short_condition", False),
        )
        
        return df

    def _evaluate_long_condition(self, df: pd.DataFrame) -> pd.Series:
        """
        Long condition:
            - Open[0] <= Low[5]  (current open <= low 5 bars ago)
            - ADX(20) <= adx_threshold
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(self._value_lookback + 1, len(df)):
            try:
                open_curr = df["open"].iloc[i]
                low_5ago = df["low"].iloc[i - self._value_lookback]
                adx_curr = df["adx"].iloc[i]
                
                if any(pd.isna(v) for v in [open_curr, low_5ago, adx_curr]):
                    continue
                
                condition.iloc[i] = (
                    (open_curr <= low_5ago) and
                    (adx_curr <= self._adx_threshold)
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def _evaluate_short_condition(self, df: pd.DataFrame) -> pd.Series:
        """
        Short condition:
            - Low[2] > High[6]  (gap up pattern)
            - Thursday only
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(7, len(df)):  # Need at least 7 bars
            try:
                low_2ago = df["low"].iloc[i - 2]
                high_6ago = df["high"].iloc[i - 6]
                is_thursday = df["is_thursday"].iloc[i]
                
                if any(pd.isna(v) for v in [low_2ago, high_6ago]):
                    continue
                
                condition.iloc[i] = (
                    (low_2ago > high_6ago) and
                    is_thursday
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic with delayed entry for both long and short.
        
        Entry (signal on bar i, act on bar i+1):
            - long_condition or short_condition must have been true DELAY bars ago
            → ENTRY_LONG or ENTRY_SHORT
        
        Exit (while in position):
            - Time exits based on side (9 bars long, 3 bars short)
            - Stop/Target managed by bracket orders
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
        close = float(last["close"])
        atr_curr = float(last.get("atr", 0))
        
        # Build indicator dict
        indicators = {
            "atr": round(atr_curr, 4),
            "adx": round(float(last.get("adx", np.nan)), 2),
            "is_thursday": bool(last.get("is_thursday", False)),
            "long_condition": bool(last.get("long_condition", False)),
            "short_condition": bool(last.get("short_condition", False)),
            "close": round(close, 4),
        }
        
        meta = {"date": str(last["date"])}
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos != 0:
            state = self._position_state
            state["bars_held"] += 1
            
            # Save bars_held to database
            open_trade = self.db.get_open_trade(self.name)
            if open_trade:
                self.db.update_trade(open_trade["id"], bars_held=state["bars_held"])
            
            side = state.get("side", "LONG" if current_pos > 0 else "SHORT")
            max_time = self._max_time_long if side == "LONG" else self._max_time_short
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 4)
            indicators["side"] = side
            
            # Time Exit# strategies/rb_combined.py
"""
strategies/rb_combined.py
─────────────────────────
RB (RBOB Gasoline) Combined Long/Short Strategy

Long Entry:
    - Open <= Low[5]  (ValueOpen(5)[0] <= ValueLow(5)[5])
    - ADX(20) <= 15  (ranging market)
    - Delayed confirmation
    
Short Entry:
    - Low[2] > High[6]  (gap up pattern)
    - Thursday only
    - Delayed confirmation

Exits:
    - ATR-based stop and target (3x and 6x ATR)
    - Time exits: 9 bars (long) / 3 bars (short)

Direction: Long and Short (two separate systems)
"""

import pandas as pd
import numpy as np
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import atr as calc_atr, adx as calc_adx


class RBCombinedStrategy(BaseStrategy):
    """
    RB combined strategy with both long and short entries.
    
    Long: Mean reversion in ranging markets (low ADX)
    Short: Thursday gap-up fade
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
        self._atr_length: int = p.get("atr_length", 14)
        self._atr_mult_stop: float = p.get("atr_mult_stop", 3.0)
        self._atr_mult_target: float = p.get("atr_mult_target", 6.0)
        self._adx_length: int = p.get("adx_length", 20)
        self._adx_threshold: float = p.get("adx_threshold", 15.0)
        self._entry_delay: int = p.get("entry_delay", 1)
        self._value_lookback: int = p.get("value_lookback", 5)
        self._max_time_long: int = p.get("max_time_long", 9)
        self._max_time_short: int = p.get("max_time_short", 3)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database."""
        open_trade = self.db.get_open_trade(self.name)
        if not open_trade:
            return {
                "in_position": False,
                "side": None,  # "LONG" or "SHORT"
                "entry_bar_date": None,
                "entry_price": 0.0,
                "bars_held": 0,
                "atr_entry": 0.0,
                "stop_price": 0.0,
                "target_price": 0.0,
            }
        
        direction = open_trade.get("direction", "LONG")
        
        return {
            "in_position": True,
            "side": direction,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "bars_held": open_trade.get("bars_held", 0),  # Load from DB
            "atr_entry": open_trade.get("atr_entry", 0.0),  # Load from DB
            "stop_price": open_trade.get("sl_price", 0.0),
            "target_price": open_trade.get("tp_price", 0.0),
        }

    def _reset_position_state(self) -> None:
        """Reset position state after exit."""
        self._position_state = {
            "in_position": False,
            "side": None,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "bars_held": 0,
            "atr_entry": 0.0,
            "stop_price": 0.0,
            "target_price": 0.0,
        }

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from RB contract."""
        trade_ct = self.broker.qualify_contract(self.spec)
        return self.broker.fetch_historical_bars(trade_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add indicators:
        - ATR(14)
        - ADX(20)
        - Long/Short entry conditions
        """
        # ATR
        df["atr"] = calc_atr(df["high"], df["low"], df["close"], self._atr_length)
        
        # ADX
        df["adx"] = calc_adx(df["high"], df["low"], df["close"], self._adx_length)
        
        # Day of week (for Thursday short entries)
        df["is_thursday"] = pd.to_datetime(df["date"]).dt.weekday == 3
        
        # Pre-compute entry conditions
        df["long_condition"] = self._evaluate_long_condition(df)
        df["short_condition"] = self._evaluate_short_condition(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.4f  ATR=%.4f  ADX=%.2f  Thu=%s  LongCond=%s  ShortCond=%s",
            last["date"],
            last["close"],
            last.get("atr", np.nan),
            last.get("adx", np.nan),
            last.get("is_thursday", False),
            last.get("long_condition", False),
            last.get("short_condition", False),
        )
        
        return df

    def _evaluate_long_condition(self, df: pd.DataFrame) -> pd.Series:
        """
        Long condition:
            - Open[0] <= Low[5]  (current open <= low 5 bars ago)
            - ADX(20) <= adx_threshold
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(self._value_lookback + 1, len(df)):
            try:
                open_curr = df["open"].iloc[i]
                low_5ago = df["low"].iloc[i - self._value_lookback]
                adx_curr = df["adx"].iloc[i]
                
                if any(pd.isna(v) for v in [open_curr, low_5ago, adx_curr]):
                    continue
                
                condition.iloc[i] = (
                    (open_curr <= low_5ago) and
                    (adx_curr <= self._adx_threshold)
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def _evaluate_short_condition(self, df: pd.DataFrame) -> pd.Series:
        """
        Short condition:
            - Low[2] > High[6]  (gap up pattern)
            - Thursday only
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(7, len(df)):  # Need at least 7 bars
            try:
                low_2ago = df["low"].iloc[i - 2]
                high_6ago = df["high"].iloc[i - 6]
                is_thursday = df["is_thursday"].iloc[i]
                
                if any(pd.isna(v) for v in [low_2ago, high_6ago]):
                    continue
                
                condition.iloc[i] = (
                    (low_2ago > high_6ago) and
                    is_thursday
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic with delayed entry for both long and short.
        
        Entry (signal on bar i, act on bar i+1):
            - long_condition or short_condition must have been true DELAY bars ago
            → ENTRY_LONG or ENTRY_SHORT
        
        Exit (while in position):
            - Time exits based on side (9 bars long, 3 bars short)
            - Stop/Target managed by bracket orders
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
        close = float(last["close"])
        atr_curr = float(last.get("atr", 0))
        
        # Build indicator dict
        indicators = {
            "atr": round(atr_curr, 4),
            "adx": round(float(last.get("adx", np.nan)), 2),
            "is_thursday": bool(last.get("is_thursday", False)),
            "long_condition": bool(last.get("long_condition", False)),
            "short_condition": bool(last.get("short_condition", False)),
            "close": round(close, 4),
        }
        
        meta = {"date": str(last["date"])}
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos != 0:
            state = self._position_state
            state["bars_held"] += 1
            
            # Save bars_held to database
            open_trade = self.db.get_open_trade(self.name)
            if open_trade:
                self.db.update_trade(open_trade["id"], bars_held=state["bars_held"])
            
            side = state.get("side", "LONG" if current_pos > 0 else "SHORT")
            max_time = self._max_time_long if side == "LONG" else self._max_time_short
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 4)
            indicators["side"] = side
            
            # Time Exit
            if state["bars_held"] >= (max_time - 1):
                exit_type = "EXIT_LONG" if side == "LONG" else "EXIT_SHORT"
                self.log.info(
                    "EXIT: Time limit reached (side=%s, bars=%d, max=%d)",
                    side, state["bars_held"], max_time
                )
                self._reset_position_state()
                return Signal(
                    signal_type=exit_type,
                    reason=f"Time exit after {state['bars_held']} bars ({side})",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "TimeX"},
                )
            
            # Continue holding (stop/target managed by bracket orders)
            self.log.info(
                "HOLD: side=%s bars=%d (max=%d)",
                side, state["bars_held"], max_time,
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding {side} position (bars={state['bars_held']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        # Check delayed conditions
        delay_idx = len(df) - 1 - self._entry_delay
        
        if delay_idx >= 0 and delay_idx < len(df):
            delay_bar = df.iloc[delay_idx]
            long_delayed =  bool(delay_bar.get("long_condition", False))
            short_delayed = bool(delay_bar.get("short_condition", False))
            
            # Priority: Long entry first
            if current_pos == 0 and long_delayed:
                # Initialize position state
                self._position_state = {
                    "in_position": True,
                    "side": "LONG",
                    "entry_bar_date": str(last["date"]),
                    "entry_price": close,  # Will be updated with actual fill
                    "bars_held": 0,
                    "atr_entry": atr_curr,
                    "stop_price": 0.0,  # Will be calculated
                    "target_price": 0.0,  # Will be calculated
                }
                
                self.log.info(
                    "ENTRY LONG: condition true %d bar(s) ago (ADX=%.2f)",
                    self._entry_delay,
                    delay_bar.get("adx", np.nan),
                )
                
                return Signal(
                    signal_type="ENTRY_LONG",
                    reason=f"Long entry: Low ADX mean reversion ({self._entry_delay} bar delay)",
                    close_price=close,
                    indicators={
                        **indicators,
                        "delay": self._entry_delay,
                        "delay_bar_date": str(delay_bar["date"]),
                        "atr_entry": round(atr_curr, 4),
                    },
                    meta=meta,
                )
            
            # Check short entry
            elif current_pos == 0 and short_delayed:
                # Initialize position state
                self._position_state = {
                    "in_position": True,
                    "side": "SHORT",
                    "entry_bar_date": str(last["date"]),
                    "entry_price": close,  # Will be updated with actual fill
                    "bars_held": 0,
                    "atr_entry": atr_curr,
                    "stop_price": 0.0,
                    "target_price": 0.0,
                }
                
                self.log.info(
                    "ENTRY SHORT: Thursday gap-up fade %d bar(s) ago",
                    self._entry_delay,
                )
                
                return Signal(
                    signal_type="ENTRY_SHORT",
                    reason=f"Short entry: Thursday gap-up fade ({self._entry_delay} bar delay)",
                    close_price=close,
                    indicators={
                        **indicators,
                        "delay": self._entry_delay,
                        "delay_bar_date": str(delay_bar["date"]),
                        "atr_entry": round(atr_curr, 4),
                    },
                    meta=meta,
                )
        
        # No signal
        return Signal(
            signal_type="NONE",
            reason="No actionable signal (conditions not met with delay)",
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def get_position_size(self, signal: Signal) -> int:
        """Fixed position size (1 contract for RB)."""
        return self.params.max_position

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal with ATR-based bracket orders.
        
        Long:
            Entry: mid + offset
            Stop: entry - ATR * atr_mult_stop
            Target: entry + ATR * atr_mult_target
        
        Short:
            Entry: mid - offset
            Stop: entry + ATR * atr_mult_stop
            Target: entry - ATR * atr_mult_target
        """
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        # Get current market price
        fallback = signal.close_price if signal.close_price > 0 else None
        price, source = self.broker.get_indicative_price(contract, fallback)
        
        if price is None or not np.isfinite(price) or price <= 0:
            self.log.error("Could not get valid market price")
            return
        
        self.log.info("Market price: %.4f (%s)", price, source)
        
        # Get ATR from signal
        atr_entry = signal.indicators.get("atr_entry", signal.indicators.get("atr", 0))
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Entry: mid + offset
            limit_px = self.order_mgr.round_tick(
                price + self.spec.price_offset,
                self.spec.tick_size
            )
            
            # Calculate stop and target
            stop_dist = atr_entry * self._atr_mult_stop
            target_dist = atr_entry * self._atr_mult_target
            
            stop_px = self.order_mgr.round_tick(limit_px - stop_dist, self.spec.tick_size)
            target_px = self.order_mgr.round_tick(limit_px + target_dist, self.spec.tick_size)
            
            self.log.info(
                "Placing LONG bracket: BUY %d @ %.4f | Stop %.4f | Target %.4f (ATR=%.4f)",
                qty, limit_px, stop_px, target_px, atr_entry
            )
            
            # Update position state
            self._position_state["entry_price"] = limit_px
            self._position_state["stop_price"] = stop_px
            self._position_state["target_price"] = target_px
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="BUY",
                quantity=qty,
                limit_price=limit_px,
                tp_price=target_px,
                sl_price=stop_px,
                account=self.account,
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
            
            # Save atr_entry to database
            self.db.update_trade(trade_id, atr_entry=atr_entry)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="BUY",
                order_type="BRACKET",
                quantity=qty,
                trade_id=trade_id,
                limit_price=result["limit_px"],
            )
        
        elif signal.signal_type == "ENTRY_SHORT":
            qty = self.get_position_size(signal)
            
            # Entry: mid - offset
            limit_px = self.order_mgr.round_tick(
                price - self.spec.price_offset,
                self.spec.tick_size
            )
            
            # Calculate stop and target
            stop_dist = atr_entry * self._atr_mult_stop
            target_dist = atr_entry * self._atr_mult_target
            
            stop_px = self.order_mgr.round_tick(limit_px + stop_dist, self.spec.tick_size)
            target_px = self.order_mgr.round_tick(limit_px - target_dist, self.spec.tick_size)
            
            self.log.info(
                "Placing SHORT bracket: SELL %d @ %.4f | Stop %.4f | Target %.4f (ATR=%.4f)",
                qty, limit_px, stop_px, target_px, atr_entry
            )
            
            # Update position state
            self._position_state["entry_price"] = limit_px
            self._position_state["stop_price"] = stop_px
            self._position_state["target_price"] = target_px
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=limit_px,
                tp_price=target_px,
                sl_price=stop_px,
                account=self.account,
            )
            
            # Open trade in database
            trade_id = self.db.open_trade(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                direction="SHORT",
                quantity=qty,
                entry_price=result["limit_px"],
                tp_price=result["tp_px"],
                sl_price=result["sl_px"],
            )
            
            # Save atr_entry to database
            self.db.update_trade(trade_id, atr_entry=atr_entry)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="SELL",
                order_type="BRACKET",
                quantity=qty,
                trade_id=trade_id,
                limit_price=result["limit_px"],
            )
        
        elif signal.signal_type in ("EXIT_LONG", "EXIT_SHORT"):
            qty = abs(current_pos)
            action = "SELL" if signal.signal_type == "EXIT_LONG" else "BUY"
            
            limit_px = self.order_mgr.round_tick(
                price - self.spec.price_offset if action == "SELL" else price + self.spec.price_offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing TIME EXIT: %s %d @ %.4f",
                action, qty, limit_px
            )
            
            # Place exit order (cancel existing brackets)
            fill_px = self.order_mgr.place_exit(
                contract=contract,
                spec=self.spec,
                action=action,
                quantity=qty,
                limit_price=limit_px,
                account=self.account,
            )
            
            # Close the open trade
            open_trade = self.db.get_open_trade(self.name)
            if open_trade:
                pnl = (fill_px - open_trade["entry_price"]) * qty * self.spec.point_value
                if action == "BUY":  # Short position
                    pnl = -pnl  # Reverse sign for shorts
                self.db.close_trade(open_trade["id"], fill_px, pnl)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action=action,
                order_type="EXIT",
                quantity=qty,
                limit_price=fill_px,
            )
            if state["bars_held"] >= (max_time - 1):
                exit_type = "EXIT_LONG" if side == "LONG" else "EXIT_SHORT"
                self.log.info(
                    "EXIT: Time limit reached (side=%s, bars=%d, max=%d)",
                    side, state["bars_held"], max_time
                )
                self._reset_position_state()
                return Signal(
                    signal_type=exit_type,
                    reason=f"Time exit after {state['bars_held']} bars ({side})",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "TimeX"},
                )
            
            # Continue holding (stop/target managed by bracket orders)
            self.log.info(
                "HOLD: side=%s bars=%d (max=%d)",
                side, state["bars_held"], max_time,
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding {side} position (bars={state['bars_held']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        # Check delayed conditions
        delay_idx = len(df) - 1 - self._entry_delay
        
        if delay_idx >= 0 and delay_idx < len(df):
            delay_bar = df.iloc[delay_idx]
            long_delayed = bool(delay_bar.get("long_condition", False))
            short_delayed = bool(delay_bar.get("short_condition", False))
            
            # Priority: Long entry first
            if current_pos == 0 and long_delayed:
                # Initialize position state
                self._position_state = {
                    "in_position": True,
                    "side": "LONG",
                    "entry_bar_date": str(last["date"]),
                    "entry_price": close,  # Will be updated with actual fill
                    "bars_held": 0,
                    "atr_entry": atr_curr,
                    "stop_price": 0.0,  # Will be calculated
                    "target_price": 0.0,  # Will be calculated
                }
                
                self.log.info(
                    "ENTRY LONG: condition true %d bar(s) ago (ADX=%.2f)",
                    self._entry_delay,
                    delay_bar.get("adx", np.nan),
                )
                
                return Signal(
                    signal_type="ENTRY_LONG",
                    reason=f"Long entry: Low ADX mean reversion ({self._entry_delay} bar delay)",
                    close_price=close,
                    indicators={
                        **indicators,
                        "delay": self._entry_delay,
                        "delay_bar_date": str(delay_bar["date"]),
                        "atr_entry": round(atr_curr, 4),
                    },
                    meta=meta,
                )
            
            # Check short entry
            elif current_pos == 0 and short_delayed:
                # Initialize position state
                self._position_state = {
                    "in_position": True,
                    "side": "SHORT",
                    "entry_bar_date": str(last["date"]),
                    "entry_price": close,  # Will be updated with actual fill
                    "bars_held": 0,
                    "atr_entry": atr_curr,
                    "stop_price": 0.0,
                    "target_price": 0.0,
                }
                
                self.log.info(
                    "ENTRY SHORT: Thursday gap-up fade %d bar(s) ago",
                    self._entry_delay,
                )
                
                return Signal(
                    signal_type="ENTRY_SHORT",
                    reason=f"Short entry: Thursday gap-up fade ({self._entry_delay} bar delay)",
                    close_price=close,
                    indicators={
                        **indicators,
                        "delay": self._entry_delay,
                        "delay_bar_date": str(delay_bar["date"]),
                        "atr_entry": round(atr_curr, 4),
                    },
                    meta=meta,
                )
        
        # No signal
        return Signal(
            signal_type="NONE",
            reason="No actionable signal (conditions not met with delay)",
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def get_position_size(self, signal: Signal) -> int:
        """Fixed position size (1 contract for RB)."""
        return self.params.max_position

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal with ATR-based bracket orders.
        
        Long:
            Entry: mid + offset
            Stop: entry - ATR * atr_mult_stop
            Target: entry + ATR * atr_mult_target
        
        Short:
            Entry: mid - offset
            Stop: entry + ATR * atr_mult_stop
            Target: entry - ATR * atr_mult_target
        """
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return
        
        # Get current market price
        fallback = signal.close_price if signal.close_price > 0 else None
        price, source = self.broker.get_indicative_price(contract, fallback)
        
        if price is None or not np.isfinite(price) or price <= 0:
            self.log.error("Could not get valid market price")
            return
        
        self.log.info("Market price: %.4f (%s)", price, source)
        
        # Get ATR from signal
        atr_entry = signal.indicators.get("atr_entry", signal.indicators.get("atr", 0))
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Entry: mid + offset
            limit_px = self.order_mgr.round_tick(
                price + self.spec.price_offset,
                self.spec.tick_size
            )
            
            # Calculate stop and target
            stop_dist = atr_entry * self._atr_mult_stop
            target_dist = atr_entry * self._atr_mult_target
            
            stop_px = self.order_mgr.round_tick(limit_px - stop_dist, self.spec.tick_size)
            target_px = self.order_mgr.round_tick(limit_px + target_dist, self.spec.tick_size)
            
            self.log.info(
                "Placing LONG bracket: BUY %d @ %.4f | Stop %.4f | Target %.4f (ATR=%.4f)",
                qty, limit_px, stop_px, target_px, atr_entry
            )
            
            # Update position state
            self._position_state["entry_price"] = limit_px
            self._position_state["stop_price"] = stop_px
            self._position_state["target_price"] = target_px
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="BUY",
                quantity=qty,
                limit_price=limit_px,
                tp_price=target_px,
                sl_price=stop_px,
                account=self.account,
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
            
            # Save atr_entry to database
            self.db.update_trade(trade_id, atr_entry=atr_entry)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="BUY",
                order_type="BRACKET",
                quantity=qty,
                trade_id=trade_id,
                limit_price=result["limit_px"],
            )
        
        elif signal.signal_type == "ENTRY_SHORT":
            qty = self.get_position_size(signal)
            
            # Entry: mid - offset
            limit_px = self.order_mgr.round_tick(
                price - self.spec.price_offset,
                self.spec.tick_size
            )
            
            # Calculate stop and target
            stop_dist = atr_entry * self._atr_mult_stop
            target_dist = atr_entry * self._atr_mult_target
            
            stop_px = self.order_mgr.round_tick(limit_px + stop_dist, self.spec.tick_size)
            target_px = self.order_mgr.round_tick(limit_px - target_dist, self.spec.tick_size)
            
            self.log.info(
                "Placing SHORT bracket: SELL %d @ %.4f | Stop %.4f | Target %.4f (ATR=%.4f)",
                qty, limit_px, stop_px, target_px, atr_entry
            )
            
            # Update position state
            self._position_state["entry_price"] = limit_px
            self._position_state["stop_price"] = stop_px
            self._position_state["target_price"] = target_px
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=limit_px,
                tp_price=target_px,
                sl_price=stop_px,
                account=self.account,
            )
            
            # Open trade in database
            trade_id = self.db.open_trade(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                direction="SHORT",
                quantity=qty,
                entry_price=result["limit_px"],
                tp_price=result["tp_px"],
                sl_price=result["sl_px"],
            )
            
            # Save atr_entry to database
            self.db.update_trade(trade_id, atr_entry=atr_entry)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="SELL",
                order_type="BRACKET",
                quantity=qty,
                trade_id=trade_id,
                limit_price=result["limit_px"],
            )
        
        elif signal.signal_type in ("EXIT_LONG", "EXIT_SHORT"):
            qty = abs(current_pos)
            action = "SELL" if signal.signal_type == "EXIT_LONG" else "BUY"
            
            limit_px = self.order_mgr.round_tick(
                price - self.spec.price_offset if action == "SELL" else price + self.spec.price_offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing TIME EXIT: %s %d @ %.4f",
                action, qty, limit_px
            )
            
            # Place exit order (cancel existing brackets)
            fill_px = self.order_mgr.place_exit(
                contract=contract,
                spec=self.spec,
                action=action,
                quantity=qty,
                limit_price=limit_px,
                account=self.account,
            )
            
            # Close the open trade
            open_trade = self.db.get_open_trade(self.name)
            if open_trade:
                pnl = (fill_px - open_trade["entry_price"]) * qty * self.spec.point_value
                if action == "BUY":  # Short position
                    pnl = -pnl  # Reverse sign for shorts
                self.db.close_trade(open_trade["id"], fill_px, pnl)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action=action,
                order_type="EXIT",
                quantity=qty,
                limit_price=fill_px,
            )