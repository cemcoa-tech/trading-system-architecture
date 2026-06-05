# strategies/gold2_atr.py
"""
strategies/gold2_atr.py
───────────────────────
Gold2 (GC) ATR-Based Entry/Exit Strategy

Signal (ab):
    ab = 1 if:
        (Low[0] > Close[5] AND
         Open[3] > Low[9] AND
         Open[7] > Close[8])
    AND
        (Wednesday OR Friday)

    Otherwise ab = 2

Entry:
    - ab = 1 (signal day)
    - Position sized by ATR
    → Buy at open + offset

Exit:
    - BarsSinceEntry = 2 AND ab = 2
    → Sell at open - offset

Direction: Long-only
"""

import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import atr as calc_atr


class Gold2ATRStrategy(BaseStrategy):
    """
    Gold2 strategy using ATR-based position sizing.
    
    Entry based on day-of-week pattern and price relationships.
    Exit based on bars held and signal reversal.
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
        self._atr_mult: float = p.get("atr_mult", 3.0)
        self._risk_dollars: float = p.get("risk_dollars", 20000.0)
        self._stop_loss_usd: float = p.get("stop_loss_usd", 12000.0)
        
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
                "position_size": pos_state.get("position_size", 0),
            }
        
        # Fallback to open_trade table for backward compatibility
        open_trade = self.db.get_open_trade(self.name)
        if not open_trade:
            return {
                "in_position": False,
                "entry_bar_date": None,
                "entry_price": 0.0,
                "bars_held": 0,
                "position_size": 0,
            }
        
        return {
            "in_position": True,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "bars_held": 0,  # Will be incremented
            "position_size": open_trade.get("quantity", 0),
        }

    def _save_position_state(self) -> None:
        """Save position state to database."""
        import json
        self.db.upsert_position_state(
            strategy_name=self.name,
            symbol=self.spec.symbol,
            entry_bar_date=self._position_state["entry_bar_date"],
            entry_price=self._position_state["entry_price"],
            bars_held=self._position_state["bars_held"],
            state_json=json.dumps({"position_size": self._position_state.get("position_size", 0)}),
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
            "position_size": 0,
        }

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from GC contract."""
        data_ct = self.broker.qualify_data_contract(self.spec)
        return self.broker.fetch_historical_bars(data_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add indicators:
        - ATR(14)
        - ab signal
        - Position size calculation
        """
        # ATR for position sizing
        df["atr"] = calc_atr(df["high"], df["low"], df["close"], self._atr_length)
        
        # Day of week (for signal calculation)
        df["day_of_week"] = pd.to_datetime(df["date"]).dt.weekday
        
        # ab signal
        df["ab"] = self._compute_ab_signal(df)
        
        # Position size based on ATR
        df["position_size"] = self._compute_position_size(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.2f  ATR=%.4f  ab=%d  PosSize=%d  DoW=%d",
            last["date"],
            last["close"],
            last.get("atr", np.nan),
            last.get("ab", 2),
            last.get("position_size", 0),
            last.get("day_of_week", -1),
        )
        
        return df

    def _compute_ab_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute ab signal matching TradeStation logic.

        ab = 1 if:
            (Low[0] > Close[5] AND
             Open[3] > Low[9] AND
             Open[7] > Close[8])
        AND
            (Wednesday OR Friday)

        Otherwise ab = 2

        Note: Python weekday: Monday=0, Wednesday=2, Friday=4
        """
        ab = pd.Series(2, index=df.index)  # Default to 2

        for i in range(10, len(df)):  # Need at least 10 bars
            try:
                # Get required bars
                low_0 = df["low"].iloc[i]
                close_5 = df["close"].iloc[i - 5]
                open_3 = df["open"].iloc[i - 3]
                low_9 = df["low"].iloc[i - 9]
                open_7 = df["open"].iloc[i - 7]
                close_8 = df["close"].iloc[i - 8]
                day_of_week = df["day_of_week"].iloc[i]

                # Check for valid values
                if any(pd.isna(v) for v in [low_0, close_5, open_3, low_9, open_7, close_8]):
                    continue

                # Conditions
                cond1 = low_0 > close_5
                cond2 = open_3 > low_9
                cond3 = open_7 > close_8
                is_wednesday = day_of_week == 2
                is_friday = day_of_week == 4

                # TradeStation logic:
                # (cond1 AND cond2 AND cond3) AND (Wednesday OR Friday)
                signal = (cond1 and cond2 and cond3) and (is_wednesday or is_friday)

                ab.iloc[i] = 1 if signal else 2

            except (IndexError, KeyError):
                continue

        return ab

    def _compute_position_size(self, df: pd.DataFrame) -> pd.Series:
        """
        ATR-based position sizing (currently disabled - using fixed qty from base class).
        
        # PositionSize = RiskDollars / (StopDistance * PointValue)
        # StopDistance = ATR * ATR_MULT
        # raw_size = self._risk_dollars / (ATR * self._atr_mult * self.spec.point_value)
        # position_size = min(int(raw_size), self.params.max_position)
        """
        # Fixed at 1 contract - delegated to base class symbol_quantities map (GC=1)
        return pd.Series(1, index=df.index)

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic:
        
        Entry:
            - Flat AND ab = 1
            - Position sized by ATR
            → ENTRY_LONG
        
        Exit:
            - In position AND bars_held = 2 AND ab = 2
            → EXIT_LONG
        """
        if len(df) < 10:
            return Signal(
                signal_type="NONE",
                reason="Insufficient data (need >= 10 bars)",
                close_price=df.iloc[-1]["close"] if len(df) > 0 else 0,
                indicators={},
                meta={"date": str(df.iloc[-1]["date"]) if len(df) > 0 else ""},
            )
        
        last = df.iloc[-1]
        close = float(last["close"])
        ab = int(last.get("ab", 2))
        position_size = int(last.get("position_size", 0))
        atr_val = float(last.get("atr", 0))
        
        # Build indicator dict
        indicators = {
            "ab": ab,
            "position_size": position_size,
            "atr": round(atr_val, 4),
            "stop_distance": round(self._atr_mult * atr_val, 4) if atr_val > 0 else 0,
            "close": round(close, 2),
            "day_of_week": int(last.get("day_of_week", -1)),
        }
        
        # Normalize UTC date to local timezone for consistent storage
        ibkr_date_str = str(last["date"])
        try:
            # IBKR format_date=2 returns "YYYYMMDD HH:mm:ss" in UTC
            if len(ibkr_date_str) >= 14:
                dt_utc = datetime.strptime(ibkr_date_str[:14], "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc)
                dt_local = dt_utc.astimezone()  # Convert to local timezone
                local_date_str = dt_local.strftime("%Y-%m-%d")
            else:
                local_date_str = ibkr_date_str
        except (ValueError, TypeError):
            local_date_str = ibkr_date_str
        
        meta = {"date": local_date_str}
        
        # Use database position state for decision making
        in_position = self._position_state.get("in_position", False)
        bars_held = self._position_state.get("bars_held", 0)
        
        # Log both positions for debugging
        self.log.info(
            "Position check - DB: in_position=%s, bars_held=%d | IBKR: current_pos=%d",
            in_position, bars_held, current_pos
        )
        
        # If there's a mismatch between DB and IBKR, use DB state but warn
        if in_position and current_pos == 0:
            self.log.warning(
                "Position mismatch: DB shows position but IBKR shows 0. Using DB state."
            )
        elif not in_position and current_pos != 0:
            self.log.warning(
                "Position mismatch: IBKR shows position but DB shows none. Syncing to IBKR state."
            )
            # Sync to IBKR state if there's actually a position
            if current_pos > 0:
                in_position = True
                self._position_state["in_position"] = True
                self._position_state["entry_price"] = close
                self._position_state["bars_held"] = 0
                self._save_position_state()
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if in_position:
            state = self._position_state
            state["bars_held"] = bars_held + 1
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 2)
            
            # Save updated bars_held to database for persistence across runs
            self._save_position_state()
            
            # Exit: bars_held = 2 AND ab = 2
            if state["bars_held"] == 2 and ab == 2:
                self.log.info(
                    "EXIT: bars_held=2 and ab=2 (bars=%d, ab=%d)",
                    state["bars_held"], ab
                )
                self._reset_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason="Exit: BarsSinceEntry=2 and ab=2",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "Signal"},
                )
            
            # Continue holding
            self.log.info(
                "HOLD: bars_held=%d, ab=%d",
                state["bars_held"], ab
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding position (bars={state['bars_held']}, ab={ab})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        if not in_position and ab == 1:
            # Initialize position state
            self._position_state = {
                "in_position": True,
                "entry_bar_date": str(last["date"]),
                "entry_price": close,  # Will be updated with actual fill
                "bars_held": 0,
                "position_size": position_size,
            }
            # Persist immediately so reruns don't fire duplicate entries
            self._save_position_state()
            
            self.log.info(
                "ENTRY: ab=1, ATR-sized position=%d (ATR=%.4f, risk=$%.0f)",
                position_size, atr_val, self._risk_dollars
            )
            
            return Signal(
                signal_type="ENTRY_LONG",
                reason=f"Entry: ab=1 signal, ATR-based sizing",
                close_price=close,
                indicators={
                    **indicators,
                    "position_size": position_size,
                },
                meta=meta,
            )
        
        # No signal
        reason_parts = []
        if ab == 2:
            reason_parts.append("ab=2 (no entry signal)")
        if position_size <= 0:
            reason_parts.append("position_size=0 (ATR too high)")
        
        reason = " | ".join(reason_parts) if reason_parts else "No actionable signal"
        
        return Signal(
            signal_type="NONE",
            reason=reason,
            close_price=close,
            indicators=indicators,
            meta=meta,
        )

    def get_position_size(self, signal: Signal) -> int:
        """Fixed position size via base class symbol_quantities map (GC=1)."""
        # ATR-based sizing disabled: return signal.indicators.get("position_size", 1)
        return super().get_position_size(signal)

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal with limit orders.
        
        Entry: open + price_offset
        Exit: open - price_offset
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
            
            # Entry: open + offset
            limit_px = self.order_mgr.round_tick(
                price + self.spec.price_offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing ENTRY order: BUY %d @ %.2f (market=%.2f + offset=%.2f)",
                qty, limit_px, price, self.spec.price_offset
            )
            
            # Update position state with actual entry price
            self._position_state["entry_price"] = limit_px
            self._position_state["position_size"] = qty
            
            # Place limit order
            from ib_insync import LimitOrder
            order = LimitOrder("BUY", qty, limit_px)
            order.account = self.account
            order.tif = "GTC"
            order.outsideRth = True
            
            trade = self.order_mgr._ib.placeOrder(contract, order)
            self.order_mgr._ib.waitOnUpdate()

            # Place stop loss order
            sl_distance = self._stop_loss_usd / self.spec.point_value
            sl_price = self.order_mgr.round_tick(limit_px - sl_distance, self.spec.tick_size)

            from ib_insync import StopOrder
            sl_order = StopOrder("SELL", qty, sl_price)
            sl_order.account = self.account
            sl_order.tif = "GTC"
            sl_order.outsideRth = True

            sl_trade = self.order_mgr._ib.placeOrder(contract, sl_order)
            self.order_mgr._ib.waitOnUpdate()

            self.log.info(
                "Placed STOP LOSS order: SELL %d @ %.2f (stop loss $%.0f/contract)",
                qty, sl_price, self._stop_loss_usd
            )

            # Open trade in database
            trade_id = self.db.open_trade(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                direction="LONG",
                quantity=qty,
                entry_price=limit_px,
                tp_price=None,  # No TP in this strategy
                sl_price=None,  # No SL in this strategy
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
            
            # Persist position state to database
            self._save_position_state()
        
        elif signal.signal_type == "EXIT_LONG":
            qty = abs(current_pos)
            
            # Exit: open - offset
            limit_px = self.order_mgr.round_tick(
                price - self.spec.price_offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing EXIT order: SELL %d @ %.2f (market=%.2f - offset=%.2f)",
                qty, limit_px, price, self.spec.price_offset
            )
            
            # Place exit order (no bracket to cancel)
            fill_px = self.order_mgr.place_exit(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=limit_px,
                account=self.account,
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
            
            # Delete position state from database
            self._delete_position_state()
            self._reset_position_state()