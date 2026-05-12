# strategies/treasury_zn_eom.py
"""
strategies/treasury_zn_eom.py
─────────────────────────────
Treasury ZN End-of-Month Strategy

Entry:
    - N trading days before last trading day of month (e.g., 2 days)
    - Buy at limit: mid + price_offset
    
Exit:
    - First trading day of next month
    - Sell at limit: mid - price_offset

Calendar:
    - Uses US Federal Holiday calendar
    - CME Sunday 5pm ET session counts as Monday
    
Direction: Long-only
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.calendar_utils import (
    trading_days_before_eom,
    is_first_trading_day_of_month,
    effective_trade_date,
)


class TreasuryZNEOMStrategy(BaseStrategy):
    """
    Treasury ZN End-of-Month calendar strategy.
    
    Simple calendar-based entry/exit with no technical indicators.
    Holds position from N days before month-end until first day of next month.
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
        self._days_before_eom: int = p.get("days_before_eom", 2)
        self._price_offset: float = p.get("price_offset", 0.10)
        
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
                "profitable_closes": pos_state.get("profitable_closes", 0),
            }
        
        # Fallback to open_trade table for backward compatibility
        open_trade = self.db.get_open_trade(self.name)
        if not open_trade:
            return {
                "in_position": False,
                "entry_bar_date": None,
                "entry_price": 0.0,
                "bars_held": 0,
                "profitable_closes": 0,
            }
        
        return {
            "in_position": True,
            "entry_bar_date": open_trade.get("entry_time"),
            "entry_price": open_trade.get("entry_price", 0.0),
            "bars_held": 0,  # Will be incremented
            "profitable_closes": 0,
        }

    def _save_position_state(self) -> None:
        """Save current position state to database."""
        self.db.upsert_position_state(
            strategy_name=self.name,
            symbol=self.spec.symbol,
            entry_bar_date=self._position_state["entry_bar_date"],
            entry_price=self._position_state["entry_price"],
            bars_held=self._position_state["bars_held"],
            profitable_closes=self._position_state["profitable_closes"],
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
            "profitable_closes": 0,
        }

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """
        Fetch minimal historical data (not really needed for this strategy).
        Just get last few days to have a DataFrame structure.
        """
        trade_ct = self.broker.qualify_contract(self.spec)
        
        try:
            bars = self.broker.ib.reqHistoricalData(
                trade_ct,
                endDateTime="",
                durationStr="5 D",
                barSizeSetting="1 day",
                whatToShow="TRADES",
                useRTH=False,
                formatDate=2
            )
            
            if bars:
                df = pd.DataFrame([{
                    'date': b.date,
                    'open': float(b.open),
                    'high': float(b.high),
                    'low': float(b.low),
                    'close': float(b.close),
                    'volume': float(b.volume)
                } for b in bars])
                
                return df
            
        except Exception as e:
            self.log.warning(f"Could not fetch historical data: {e}")
        
        # Fallback: create minimal DataFrame with today's date
        return pd.DataFrame([{
            'date': pd.Timestamp.now().normalize(),
            'open': np.nan,
            'high': np.nan,
            'low': np.nan,
            'close': np.nan,
            'volume': 0
        }])

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        No technical indicators needed for calendar-based strategy.
        Just add calendar info.
        """
        today = effective_trade_date()
        
        days_before_eom = trading_days_before_eom(today)
        is_first_td = is_first_trading_day_of_month(today)
        
        self.log.info(
            "Calendar  date=%s  days_before_eom=%s  is_first_td=%s",
            today,
            days_before_eom,
            is_first_td,
        )
        
        # Store calendar info in DataFrame (not really used, but for consistency)
        if len(df) > 0:
            df.loc[df.index[-1], 'days_before_eom'] = days_before_eom
            df.loc[df.index[-1], 'is_first_td'] = is_first_td
        
        return df

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic based on calendar:
        
        Entry:
            - Today is N trading days before end of month
            - Currently flat
            → ENTRY_LONG
        
        Exit:
            - Today is first trading day of next month
            - Currently long
            → EXIT_LONG
        """
        today = effective_trade_date()
        
        days_before_eom = trading_days_before_eom(today)
        is_first_td = is_first_trading_day_of_month(today)
        
        if days_before_eom is None:
            self.log.error("Could not calculate trading days before EOM")
            return Signal(
                signal_type="NONE",
                reason="Calendar calculation error",
                close_price=0.0,
                indicators={},
                meta={"date": str(today)},
            )
        
        # Build indicators dict
        indicators = {
            "date": str(today),
            "days_before_eom": days_before_eom,
            "is_first_trading_day": is_first_td,
            "target_days_before_eom": self._days_before_eom,
        }
        
        meta = {
            "date": str(today),
            "month": today.strftime("%Y-%m"),
        }
        
        # Get current price (we'll need it for order placement)
        close_price = 0.0
        if len(df) > 0 and not pd.isna(df.iloc[-1].get('close')):
            close_price = float(df.iloc[-1]['close'])
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos > 0 or self._position_state["in_position"]:
            state = self._position_state
            
            # Calculate actual bars held based on dates (handles gaps between runs)
            if state["entry_bar_date"]:
                entry_date = pd.to_datetime(state["entry_bar_date"]).date()
                current_date = today
                actual_bars_held = (current_date - entry_date).days
                
                # Only count trading days (weekends excluded)
                trading_days = 0
                for i in range(actual_bars_held + 1):
                    check_date = entry_date + pd.Timedelta(days=i)
                    if check_date.weekday() < 5:  # Monday-Friday
                        trading_days += 1
                
                # Update bars_held with actual trading days
                state["bars_held"] = trading_days - 1  # -1 because entry day counts as day 0
            else:
                state["bars_held"] += 1
            
            # Track profitable closes
            if close_price > state["entry_price"]:
                state["profitable_closes"] = state.get("profitable_closes", 0) + 1
            else:
                state["profitable_closes"] = state.get("profitable_closes", 0)
            
            # Save state update
            self._save_position_state()
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 6)
            indicators["profitable_closes"] = state["profitable_closes"]
            
            if is_first_td:
                self.log.info("EXIT: First trading day of month (bars=%d, prof_x=%d)", state["bars_held"], state["profitable_closes"])
                self._reset_position_state()
                self._delete_position_state()
                return Signal(
                    signal_type="EXIT_LONG",
                    reason=f"Exit: First trading day of month (bars={state['bars_held']}, prof_x={state['profitable_closes']})",
                    close_price=close_price,
                    indicators=indicators,
                    meta={**meta, "exit_type": "first_td"},
                )
            
            # Continue holding
            self.log.info("HOLD: bars=%d prof_x=%d (waiting for first trading day)", state["bars_held"], state["profitable_closes"])
            return Signal(
                signal_type="NONE",
                reason=f"Holding position (bars={state['bars_held']}, prof_x={state['profitable_closes']})",
                close_price=close_price,
                indicators=indicators,
                meta=meta,
            )

        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        print("days_before_eom:", days_before_eom)
        print("self._days_before_eom:", self._days_before_eom)
        if current_pos == 0 and days_before_eom == self._days_before_eom:
            # Safety check: ensure position_state agrees we're flat
            if self._position_state["in_position"]:
                self.log.warning("Skipping entry: position_state shows in_position=True despite current_pos=0")
                return Signal(
                    signal_type="NONE", 
                    reason="Position state conflict",
                    close_price=close_price,
                    indicators=indicators,
                    meta=meta,
                )
            
            # Initialize position state
            self._position_state = {
                "in_position": True,
                "entry_bar_date": str(today),
                "entry_price": close_price,  # Will be updated with actual fill
                "bars_held": 0,
                "profitable_closes": 0,
            }
            
            # Save position state to database
            self._save_position_state()
            
            self.log.info(
                "ENTRY: %d trading days before end of month (target=%d)",
                days_before_eom,
                self._days_before_eom,
            )
            
            return Signal(
                signal_type="ENTRY_LONG",
                reason=f"Entry: {days_before_eom} trading days before month-end",
                close_price=close_price,
                indicators=indicators,
                meta=meta,
            )
        
        # ── NO SIGNAL ────────────────────────────────────────────────────
        
        reason_parts = []
        if current_pos == 0:
            reason_parts.append(f"Waiting for {self._days_before_eom} days before EOM (currently {days_before_eom})")
        else:
            reason_parts.append(f"Holding position until first trading day of next month")
        
        reason = " | ".join(reason_parts) if reason_parts else "No actionable signal"
        
        return Signal(
            signal_type="NONE",
            reason=reason,
            close_price=close_price,
            indicators=indicators,
            meta=meta,
        )

    def get_position_size(self, signal: Signal) -> int:
        """Fixed position size (typically 1 contract for ZN)."""
        return self.params.max_position

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal with limit orders.
        
        Entry: mid + price_offset
        Exit: mid - price_offset
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
        
        self.log.info("Market price: %.6f (%s)", price, source)
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Entry: mid + offset
            limit_px = self.order_mgr.round_tick(
                price + self._price_offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing ENTRY order: BUY %d @ %.6f (mid=%.6f + offset=%.2f)",
                qty, limit_px, price, self._price_offset
            )
            
            # Place limit order
            from ib_insync import LimitOrder
            order = LimitOrder("BUY", qty, limit_px)
            order.account = self.order_mgr._account
            order.tif = "DAY"
            
            trade = self.order_mgr._ib.placeOrder(contract, order)
            self.order_mgr._ib.waitOnUpdate()
            
            # Update position state with actual entry price
            self._position_state["entry_price"] = limit_px
            self._save_position_state()
            
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
                price - self._price_offset,
                self.spec.tick_size
            )
            
            self.log.info(
                "Placing EXIT order: SELL %d @ %.6f (mid=%.6f - offset=%.2f)",
                qty, limit_px, price, self._price_offset
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