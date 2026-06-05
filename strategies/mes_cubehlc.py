# strategies/mes_cubhlc.py
"""
strategies/mes_cubhlc.py
────────────────────────
MES (Micro E-mini S&P 500) CubeHLC Strategy

Entry Condition1 (all must be true):
    - high[1] > open[5]
    - low[3] <= high[8]
    - close[0] <= low[5]
    - CubeHLC[0] <= CubeHLC[1]
    - dayofmonth(date) > 1
    - month(date) != 8 (not August)
    - close < average(close, 10)

Position Sizing:
    ATR-based with half position entry

Exits:
    1) Stop Loss: 150 points ($750)
    2) Profit Exit: 10 profitable closes
    3) Time Exit: 10 bars
    4) August Exit: month = 8

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
from utils.indicators import cube_hlc, atr as calc_atr, sma


class MESCubeHLCStrategy(BaseStrategy):
    """
    MES CubeHLC strategy.
    
    Complex multi-bar pattern with CubeHLC indicator.
    Seasonal filtering (no August) and half-position entry.
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
        self._avg_days: int = p.get("avg_days", 10)
        self._atr_length: int = p.get("atr_length", 14)
        self._atr_mult: float = p.get("atr_mult", 2.0)
        self._stop_limit_points: float = p.get("stop_limit_points", 150.0)
        self._max_time: int = p.get("max_time", 10)
        self._profitable_closes: int = p.get("profitable_closes", 10)
        
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
                "profitable_closes": 0,
                "position_size": 0,
                "sl_price": 0.0,
            }
        
        return {
            "in_position": True,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "bars_held": 0,
            "profitable_closes": 0,
            "position_size": open_trade.get("quantity", 0),
            "sl_price": open_trade.get("sl_price", 0.0),
        }

    def _reset_position_state(self) -> None:
        """Reset position state after exit."""
        self._position_state = {
            "in_position": False,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "bars_held": 0,
            "profitable_closes": 0,
            "position_size": 0,
            "sl_price": 0.0,
        }

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from MES continuous contract."""
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
        - CubeHLC
        - Close moving average
        - ATR for position sizing
        - Date components (day, month)
        - Condition1 signal
        """
        # CubeHLC
        df["cube_hlc"] = cube_hlc(df["high"], df["low"], df["close"])
        
        # Moving average of close
        df["close_avg"] = sma(df["close"], self._avg_days)
        
        # ATR for position sizing
        df["atr"] = calc_atr(df["high"], df["low"], df["close"], self._atr_length)
        
        # Date components
        df["day"] = pd.to_datetime(df["date"]).dt.day
        df["month"] = pd.to_datetime(df["date"]).dt.month
        
        # Condition1 signal
        df["condition1"] = self._evaluate_condition1(df)
        
        # Position size
        df["position_size"] = self._compute_position_size(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.2f  CubeHLC=%.2f  CloseAvg=%.2f  ATR=%.2f  Cond1=%s  PosSize=%d  Month=%d",
            last["date"],
            last["close"],
            last.get("cube_hlc", np.nan),
            last.get("close_avg", np.nan),
            last.get("atr", np.nan),
            last.get("condition1", False),
            last.get("position_size", 0),
            last.get("month", 0),
        )
        
        return df

    def _evaluate_condition1(self, df: pd.DataFrame) -> pd.Series:
        """
        Evaluate Condition1 for each bar.
        
        All conditions must be true:
            - high[1] > open[5]
            - low[3] <= high[8]
            - close[0] <= low[5]
            - CubeHLC[0] <= CubeHLC[1]
            - dayofmonth(date) > 1
            - month(date) != 8
            - close < average(close, avg_days)
        """
        condition = pd.Series(False, index=df.index)
        
        for i in range(10, len(df)):  # Need at least 10 bars
            try:
                # Price conditions
                high_1 = df["high"].iloc[i - 1]
                open_5 = df["open"].iloc[i - 5]
                low_3 = df["low"].iloc[i - 3]
                high_8 = df["high"].iloc[i - 8]
                close_0 = df["close"].iloc[i]
                low_5 = df["low"].iloc[i - 5]
                
                # CubeHLC
                cube_0 = df["cube_hlc"].iloc[i]
                cube_1 = df["cube_hlc"].iloc[i - 1]
                
                # Date conditions
                day_of_month = df["day"].iloc[i]
                month = df["month"].iloc[i]
                
                # Moving average
                close_avg = df["close_avg"].iloc[i]
                
                # Check for valid values
                vals = [high_1, open_5, low_3, high_8, close_0, low_5, 
                       cube_0, cube_1, close_avg]
                if any(pd.isna(v) for v in vals):
                    continue
                
                # Evaluate all conditions
                price_cond1 = high_1 > open_5
                price_cond2 = low_3 <= high_8
                price_cond3 = close_0 <= low_5
                cube_cond = cube_0 <= cube_1
                day_cond = day_of_month > 1
                month_cond = month != 8
                avg_cond = close_0 < close_avg
                
                condition.iloc[i] = (
                    price_cond1 and price_cond2 and price_cond3 and
                    cube_cond and day_cond and month_cond and avg_cond
                )
                
            except (IndexError, KeyError):
                continue
        
        return condition

    def _compute_position_size(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate position size based on ATR.
        
        PosSize = StopLimit / (ATR * ATRMult * PointValue)
        Entry with half position: PosSize/2
        """
        position_sizes = pd.Series(0, index=df.index)
        
        stop_limit_dollars = self._stop_limit_points * self.spec.point_value
        
        for i in range(len(df)):
            atr_val = df["atr"].iloc[i]
            
            if pd.isna(atr_val) or atr_val <= 0:
                continue
            
            stop_distance = self._atr_mult * atr_val
            
            if stop_distance <= 0:
                continue
            
            # Calculate full position size
            raw_size = stop_limit_dollars / (stop_distance * self.spec.point_value)
            full_size = int(raw_size)
            
            # Half position entry
            half_size = max(1, int(full_size / 2))
            
            # Cap at max position
            position_size = min(half_size, self.params.max_position)
            
            position_sizes.iloc[i] = position_size
        
        return position_sizes

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic:
        
        Entry:
            - Flat AND condition1 = true
            - Position sized by ATR (half position)
            → ENTRY_LONG
        
        Exit:
            1) August exit: month = 8
            2) Stop loss: low <= SL
            3) Profit exit: profitable_closes >= 10
            4) Time exit: bars_held >= 10
        """
        if len(df) < 20:
            return Signal(
                signal_type="NONE",
                reason="Insufficient data",
                close_price=df.iloc[-1]["close"] if len(df) > 0 else 0,
                indicators={},
                meta={"date": str(df.iloc[-1]["date"]) if len(df) > 0 else ""},
            )
        
        last = df.iloc[-1]
        close = float(last["close"])
        condition1 = bool(last.get("condition1", False))
        position_size = int(last.get("position_size", 0))
        month = int(last.get("month", 0))
        
        # Build indicator dict
        indicators = {
            "condition1": condition1,
            "position_size": position_size,
            "cube_hlc": round(float(last.get("cube_hlc", 0)), 2),
            "close_avg": round(float(last.get("close_avg", 0)), 2),
            "atr": round(float(last.get("atr", 0)), 2),
            "close": round(close, 2),
            "month": month,
            "day": int(last.get("day", 0)),
        }
        
        meta = {"date": str(last["date"])}
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos > 0:
            state = self._position_state
            state["bars_held"] += 1
            
            # Update profitable closes count
            if close >= state["entry_price"]:
                state["profitable_closes"] += 1
            
            indicators["bars_held"] = state["bars_held"]
            indicators["profitable_closes"] = state["profitable_closes"]
            indicators["entry_price"] = round(state["entry_price"], 2)
            indicators["sl_price"] = round(state["sl_price"], 2)
            
            # Priority 1: August Exit
            if month == 8:
                self.log.info("EXIT: August seasonal exit")
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason="August seasonal exit",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "AugustX"},
                )
            
            # Priority 2: Stop Loss (intrabar)
            low = float(last["low"])
            if low <= state["sl_price"]:
                self.log.info(
                    "EXIT: Stop loss hit (low=%.2f <= SL=%.2f)",
                    low, state["sl_price"]
                )
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Stop loss hit at {state['sl_price']:.2f}",
                    close_price=state["sl_price"],  # Exit at SL price
                    indicators=indicators,
                    meta={**meta, "exit_type": "SL"},
                )
            
            # Priority 3: Profit Exit
            if state["profitable_closes"] >= self._profitable_closes:
                self.log.info(
                    "EXIT: Profitable closes threshold (count=%d)",
                    state["profitable_closes"]
                )
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Profit exit: {state['profitable_closes']} profitable closes",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "ProfX"},
                )
            
            # Priority 4: Time Exit
            if state["bars_held"] >= self._max_time:
                self.log.info("EXIT: Time limit (bars=%d)", state["bars_held"])
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Time exit after {state['bars_held']} bars",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "TimeX"},
                )
            
            # Continue holding
            self.log.info(
                "HOLD: bars=%d prof_closes=%d",
                state["bars_held"], state["profitable_closes"]
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding position (bars={state['bars_held']}, prof_closes={state['profitable_closes']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        if current_pos == 0 and condition1 and position_size > 0:
            # Calculate stop loss price
            sl_price = close - self._stop_limit_points
            
            # Initialize position state
            self._position_state = {
                "in_position": True,
                "entry_bar_date": str(last["date"]),
                "entry_price": close,  # Will be updated with actual fill
                "bars_held": 0,
                "profitable_closes": 0,
                "position_size": position_size,
                "sl_price": sl_price,
            }
            
            self.log.info(
                "ENTRY: Condition1 met, half position=%d (SL=%.2f, 150 points)",
                position_size, sl_price
            )
            
            return Signal(
                signal_type="ENTRY_LONG",
                reason="Condition1: Multi-bar pattern + CubeHLC + seasonal filter",
                close_price=close,
                indicators={
                    **indicators,
                    "position_size": position_size,
                    "sl_price": round(sl_price, 2),
                },
                meta=meta,
            )
        
        # No signal
        reason_parts = []
        if not condition1:
            reason_parts.append("Condition1 not met")
        if position_size <= 0:
            reason_parts.append("position_size=0")
        if month == 8:
            reason_parts.append("August (no new entries)")
        
        reason = " | ".join(reason_parts) if reason_parts else "No actionable signal"
        
        return Signal(
            signal_type="NONE",
            reason=reason,
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def get_position_size(self, signal: Signal) -> int:
        """Get ATR-calculated half position size from signal."""
        return signal.indicators.get("position_size", 1)

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal.
        
        Entry: Market open with stop loss
        Exit: Market open (or SL price if stop hit)
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
        
        self.log.info("Market price: %.2f (%s)", price, source)
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            sl_price = signal.indicators.get("sl_price", 0)
            
            # Update position state with actual entry price
            self._position_state["entry_price"] = price
            self._position_state["sl_price"] = sl_price
            
            self.log.info(
                "Placing ENTRY order: BUY %d @ %.2f (SL=%.2f)",
                qty, price, sl_price
            )
            
            # Place entry with stop loss
            from ib_insync import LimitOrder, StopOrder
            
            # Entry order
            entry_order = LimitOrder("BUY", qty, price)
            entry_order.account = self.order_mgr._account
            entry_order.tif = "DAY"
            
            entry_trade = self.order_mgr._ib.placeOrder(contract, entry_order)
            self.order_mgr._ib.waitOnUpdate()
            
            # Stop loss order (separate, not bracket)
            sl_order = StopOrder("SELL", qty, sl_price)
            sl_order.account = self.order_mgr._account
            sl_order.tif = "GTC"
            
            self.order_mgr._ib.placeOrder(contract, sl_order)
            
            # Open trade in database
            trade_id = self.db.open_trade(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                direction="LONG",
                quantity=qty,
                entry_price=price,
                tp_price=None,  # No TP in this strategy
                sl_price=sl_price,
            )
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action="BUY",
                order_type="LIMIT",
                quantity=qty,
                trade_id=trade_id,
                limit_price=price,
            )
        
        elif signal.signal_type == "EXIT_LONG":
            qty = abs(current_pos)
            
            # Use signal's close_price (might be SL price)
            exit_price = signal.close_price
            
            self.log.info(
                "Placing EXIT order: SELL %d @ %.2f",
                qty, exit_price
            )
            
            # Place exit order (cancel stop loss)
            fill_px = self.order_mgr.place_exit(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=exit_price,
                cancel_bracket=True,  # Cancel stop loss
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