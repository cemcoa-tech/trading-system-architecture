
"""
Corn (ZC) Volatility Expansion Strategy

Entry:
    Long:
        - BarRange > VolMult * StdDev(BarRange, LookbackVol) + Average(BarRange, LookbackVol)
        - Close > Close[TrendBars]
        → Buy at market (next bar)
    
    Short:
        - BarRange > VolMult * StdDev(BarRange, LookbackVol) + Average(BarRange, LookbackVol)
        - Close < Close[TrendBars]
        → Sell short at market (next bar)

Position Sizing:
    PosSize = StopLimit / (ATR * ATRMult * BigPointValue)

Exits:
    - Profit Target: $2500
    - Stop Loss: $10000
    - Time Exit: 80 bars (forced exit)

Direction: Long and Short
"""

import json
import pandas as pd
import numpy as np
from typing import Optional

from config.settings import StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from strategies.base_strategy import BaseStrategy, Signal
from utils.indicators import atr as calc_atr


class CornVolatilityStrategy(BaseStrategy):
    """
    Corn volatility expansion strategy.
    
    Enters on volatility spikes with trend confirmation.
    Uses ATR-based position sizing and bracket orders.
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
        self._vol_mult: float = p.get("vol_mult", 2.0)
        self._lookback_vol: int = p.get("lookback_vol", 25)
        self._trend_bars: int = p.get("trend_bars", 20)
        self._atr_length: int = p.get("atr_length", 14)
        self._atr_mult: float = p.get("atr_mult", 2.0)
        self._stop_limit_dollars: float = p.get("stop_limit_dollars", 10000.0)
        self._profit_target_dollars: float = p.get("profit_target_dollars", 2500.0)
        self._forced_exit_bars: int = p.get("forced_exit_bars", 80)
        
        # Position state tracking
        self._position_state = self._load_position_state()

    def _load_position_state(self) -> dict:
        """Load position state from database."""
        pos_state = self.db.get_position_state(self.name, self.spec.symbol)
        
        if pos_state:
            # Parse JSON state
            state_json_str = pos_state.get("state_json", "{}")
            extra_state = json.loads(state_json_str) if state_json_str else {}
            
            return {
                "in_position": True,
                "side": extra_state.get("side", "LONG"),
                "entry_bar_date": pos_state.get("entry_bar_date"),
                "entry_price": pos_state.get("entry_price", 0.0),
                "bars_held": pos_state.get("bars_held", 0),
                "position_size": extra_state.get("position_size", 0),
            }
        
        return {
            "in_position": False,
            "side": None,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "bars_held": 0,
            "position_size": 0,
        }
    
    def _save_position_state(self) -> None:
        """Save current position state to database."""
        if not self._position_state["in_position"]:
            return
        
        state_json = json.dumps({
            "side": self._position_state["side"],
            "position_size": self._position_state["position_size"],
        })
        
        self.db.upsert_position_state(
            strategy_name=self.name,
            symbol=self.spec.symbol,
            entry_bar_date=self._position_state["entry_bar_date"],
            entry_price=self._position_state["entry_price"],
            bars_held=self._position_state["bars_held"],
            state_json=state_json,
        )
    
    def _delete_position_state(self) -> None:
        """Delete position state from database on exit."""
        self.db.delete_position_state(self.name, self.spec.symbol)

    def _reset_position_state(self) -> None:
        """Reset position state after exit."""
        self._position_state = {
            "in_position": False,
            "side": None,
            "entry_bar_date": None,
            "entry_price": 0.0,
            "bars_held": 0,
            "position_size": 0,
        }

    # ── Hook implementations ─────────────────────────────────────────────

    def fetch_data(self) -> pd.DataFrame:
        """Pull daily bars from ZC contract."""
        trade_ct = self.broker.qualify_contract(self.spec)
        return self.broker.fetch_historical_bars(trade_ct)

    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add indicators:
        - Bar Range (High - Low)
        - Average Bar Range
        - StdDev of Bar Range
        - Volatility Threshold
        - ATR for position sizing
        - Signal calculation
        """
        # Bar Range
        df["bar_range"] = df["high"] - df["low"]
        
        # Average and StdDev of Bar Range
        df["avg_range"] = df["bar_range"].rolling(self._lookback_vol).mean()
        df["std_range"] = df["bar_range"].rolling(self._lookback_vol).std()
        
        # Volatility Threshold
        df["vol_threshold"] = (
            self._vol_mult * df["std_range"] + df["avg_range"]
        )
        
        # Trend comparison (Close vs Close[TrendBars])
        df["trend_close"] = df["close"].shift(self._trend_bars)
        
        # ATR for position sizing
        df["atr"] = calc_atr(df["high"], df["low"], df["close"], self._atr_length)
        
        # Compute signal and position size
        df["signal"] = self._compute_signal(df)
        df["position_size"] = self._compute_position_size(df)
        
        last = df.iloc[-1]
        self.log.info(
            "Last bar  date=%s  close=%.4f  BarRange=%.4f  VolThreshold=%.4f  ATR=%.4f  Signal=%d  PosSize=%d",
            last["date"],
            last["close"],
            last.get("bar_range", np.nan),
            last.get("vol_threshold", np.nan),
            last.get("atr", np.nan),
            last.get("signal", 0),
            last.get("position_size", 0),
        )
        
        return df

    def _compute_signal(self, df: pd.DataFrame) -> pd.Series:
        """
        Compute entry signal.
        
        Long (1):
            - BarRange > VolThreshold
            - Close > Close[TrendBars]
        
        Short (-1):
            - BarRange > VolThreshold
            - Close < Close[TrendBars]
        
        None (0): Otherwise
        """
        signal = pd.Series(0, index=df.index)
        
        for i in range(self._trend_bars + self._lookback_vol, len(df)):
            try:
                bar_range = df["bar_range"].iloc[i]
                vol_threshold = df["vol_threshold"].iloc[i]
                close_curr = df["close"].iloc[i]
                close_trend = df["trend_close"].iloc[i]
                
                if any(pd.isna(v) for v in [bar_range, vol_threshold, close_curr, close_trend]):
                    continue
                
                # Volatility expansion condition
                vol_trigger = bar_range > vol_threshold
                
                if vol_trigger and close_curr > close_trend:
                    signal.iloc[i] = 1  # Long
                elif vol_trigger and close_curr < close_trend:
                    signal.iloc[i] = -1  # Short
                
            except (IndexError, KeyError):
                continue
        
        return signal

    def _compute_position_size(self, df: pd.DataFrame) -> pd.Series:
        """
        Calculate position size based on ATR.
        
        PosSize = StopLimit / (ATR * ATRMult * BigPointValue)
        
        Returns integer position size (contracts).
        """
        position_sizes = pd.Series(0, index=df.index)
        
        for i in range(len(df)):
            atr_val = df["atr"].iloc[i]
            
            if pd.isna(atr_val) or atr_val <= 0:
                continue
            
            stop_distance = self._atr_mult * atr_val
            
            if stop_distance <= 0:
                continue
            
            # Calculate raw size
            raw_size = self._stop_limit_dollars / (stop_distance * self.spec.point_value)
            
            # Floor to integer
            position_size = int(raw_size)
            
            # Cap at max position
            position_size = min(position_size, self.params.max_position)
            
            # Ensure non-negative
            position_size = max(0, position_size)
            
            position_sizes.iloc[i] = position_size
        
        return position_sizes

    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """
        Decision logic:
        
        Entry:
            - Flat AND signal = 1 or -1
            - Position sized by ATR
            → ENTRY_LONG or ENTRY_SHORT
        
        Exit:
            - In position AND bars_held >= forced_exit_bars
            → EXIT_LONG or EXIT_SHORT
        """
        if len(df) < max(self._trend_bars, self._lookback_vol) + 10:
            return Signal(
                signal_type="NONE",
                reason="Insufficient data",
                close_price=df.iloc[-1]["close"] if len(df) > 0 else 0,
                indicators={},
                meta={"date": str(df.iloc[-1]["date"]) if len(df) > 0 else ""},
            )
        
        last = df.iloc[-1]
        close = float(last["close"])
        signal = 1 #int(last.get("signal", 0))
        position_size = int(last.get("position_size", 0))
        atr_val = float(last.get("atr", 0))
        bar_range = float(last.get("bar_range", 0))
        vol_threshold = float(last.get("vol_threshold", 0))
        
        # Build indicator dict
        indicators = {
            "signal": signal,
            "position_size": position_size,
            "atr": round(atr_val, 4),
            "bar_range": round(bar_range, 4),
            "vol_threshold": round(vol_threshold, 4),
            "close": round(close, 4),
            "trend_close": round(float(last.get("trend_close", 0)), 4),
        }
        
        meta = {"date": str(last["date"])}
        
        # Check for position mismatch between IBKR and DB state
        db_in_position = self._position_state["in_position"]
        if current_pos == 0 and db_in_position:
            self.log.warning(
                "Position mismatch: IBKR shows flat but DB has %s position. "
                "Assuming position from DB state.",
                self._position_state.get("side", "UNKNOWN")
            )
            # Force current_pos to match DB for logic purposes
            side = self._position_state.get("side", "LONG")
            current_pos = 1 if side == "LONG" else -1
        elif current_pos != 0 and not db_in_position:
            self.log.warning(
                "Position mismatch: IBKR shows position but DB is flat. "
                "Syncing to IBKR position."
            )
            # Sync DB to match IBKR
            self._position_state["in_position"] = True
            self._position_state["side"] = "LONG" if current_pos > 0 else "SHORT"
            self._position_state["bars_held"] = 0
            self._save_position_state()
        
        # ── EXIT LOGIC (if in position) ──────────────────────────────────
        
        if current_pos != 0:
            state = self._position_state
            # TradeStation: BarsSinceEntry increments each bar while in position
            # We increment on each signal generation (runs once per bar)
            state["bars_held"] += 1
            
            side = state.get("side", "LONG" if current_pos > 0 else "SHORT")
            
            indicators["bars_held"] = state["bars_held"]
            indicators["entry_price"] = round(state["entry_price"], 4)
            indicators["side"] = side
            
            # Save state update each bar
            self._save_position_state()
            
            # Forced Time Exit
            if state["bars_held"] >= self._forced_exit_bars:
                exit_type = "EXIT_LONG" if side == "LONG" else "EXIT_SHORT"
                self.log.info(
                    "EXIT: Forced time exit (side=%s, bars=%d)",
                    side, state["bars_held"]
                )
                self._reset_position_state()
                self._delete_position_state()
                return Signal(
                    signal_type=exit_type,
                    reason=f"Forced time exit after {state['bars_held']} bars",
                    close_price=close,
                    indicators=indicators,
                    meta={**meta, "exit_type": "TimeX"},
                )
            
            # Continue holding (PT/SL managed by bracket orders)
            self.log.info(
                "HOLD: side=%s bars=%d (forced_exit=%d)",
                side, state["bars_held"], self._forced_exit_bars,
            )
            return Signal(
                signal_type="NONE",
                reason=f"Holding {side} position (bars={state['bars_held']})",
                close_price=close,
                indicators=indicators,
                meta=meta,
            )
        
        # ── ENTRY LOGIC (if flat) ────────────────────────────────────────
        
        if current_pos == 0 and signal != 0 and position_size > 0:
            # Determine direction
            if signal == 1:
                signal_type = "ENTRY_LONG"
                side = "LONG"
                reason = "Volatility expansion + uptrend"
            else:  # signal == -1
                signal_type = "ENTRY_SHORT"
                side = "SHORT"
                reason = "Volatility expansion + downtrend"
            
            # Initialize position state
            # TradeStation: BarsSinceEntry starts at 0 on entry bar
            self._position_state = {
                "in_position": True,
                "side": side,
                "entry_bar_date": str(last["date"]),
                "entry_price": close,  # Will be updated with actual fill
                "bars_held": 0,  # Will be incremented on next bar check
                "position_size": 1,  # Fixed 1 lot for execution
            }
            
            # Save to database for recovery on restart
            self._save_position_state()
            
            self.log.info(
                "ENTRY %s: Fixed 1 lot position (ATR indicator=%.4f, BarRange=%.4f > Threshold=%.4f)",
                side, atr_val, bar_range, vol_threshold
            )
            
            return Signal(
                signal_type=signal_type,
                reason=reason,
                close_price=close,
                indicators={
                    **indicators,
                    "position_size": position_size,
                },
                meta=meta,
            )
        
        # No signal
        reason_parts = []
        if signal == 0:
            reason_parts.append("No volatility expansion signal")
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
        """Fixed position size via base class symbol_quantities map (ZC=1)."""
        return super().get_position_size(signal)

    def _execute_signal(self, signal: Signal, contract, current_pos: int) -> None:
        """
        Execute trading signal with bracket orders.
        
        Entry:
            - Long: BUY at market (mid + offset)
            - Short: SELL at market (mid - offset)
            - Add bracket with PT and SL
        
        Exit:
            - Time exit with limit order
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
        
        # Calculate PT and SL distances (per-contract, matching TradeStation logic)
        # TradeStation: SetProfitTarget(ProfitTarget) - per contract ($2500)
        # TradeStation: SetStopLoss(StopLimit/possize) - per contract ($10000/PosSize)
        qty = self.get_position_size(signal) if signal.signal_type != "NONE" else 1
        
        # Profit Target: $2500 per contract (fixed)
        pt_dist = self._profit_target_dollars / self.spec.point_value
        
        # Stop Loss: StopLimit/PosSize per contract = $10000 / PosSize per contract
        sl_per_contract_dollars = self._stop_limit_dollars / qty if qty > 0 else self._stop_limit_dollars
        sl_dist = sl_per_contract_dollars / self.spec.point_value
        
        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            
            # Entry: market order (TradeStation: "next bar at market")
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
            # Calculate PT and SL (per-contract)
            tp_price = self.order_mgr.round_tick(limit_px + pt_dist, self.spec.tick_size)
            sl_price = self.order_mgr.round_tick(limit_px - sl_dist, self.spec.tick_size)
            
            self.log.info(
                "Placing LONG bracket: BUY %d @ %.4f | PT $%.0f/contract @ %.4f | SL $%.0f/contract @ %.4f",
                qty, limit_px, 
                self._profit_target_dollars, tp_price,
                sl_per_contract_dollars, sl_price
            )
            
            # Update position state with actual fill price
            self._position_state["entry_price"] = limit_px
            self._position_state["position_size"] = qty
            self._save_position_state()
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="BUY",
                quantity=qty,
                limit_price=limit_px,
                tp_price=tp_price,
                sl_price=sl_price,
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
            
            # Entry: market order (TradeStation: "next bar at market")
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
            # Calculate PT and SL (per-contract)
            tp_price = self.order_mgr.round_tick(limit_px - pt_dist, self.spec.tick_size)
            sl_price = self.order_mgr.round_tick(limit_px + sl_dist, self.spec.tick_size)
            
            self.log.info(
                "Placing SHORT bracket: SELL %d @ %.4f | PT $%.0f/contract @ %.4f | SL $%.0f/contract @ %.4f",
                qty, limit_px, 
                self._profit_target_dollars, tp_price,
                sl_per_contract_dollars, sl_price
            )
            
            # Update position state with actual fill price
            self._position_state["entry_price"] = limit_px
            self._position_state["position_size"] = qty
            self._save_position_state()
            
            # Place bracket order
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="SELL",
                quantity=qty,
                limit_price=limit_px,
                tp_price=tp_price,
                sl_price=sl_price,
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
            
            # Exit at market (TradeStation: "next bar at market")
            limit_px = self.order_mgr.round_tick(price, self.spec.tick_size)
            
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
            
            # Delete position state on exit
            self._delete_position_state()
            
            # Close the open trade
            open_trade = self.db.get_open_trade(self.name)
            if open_trade:
                pnl = (fill_px - open_trade["entry_price"]) * qty * self.spec.point_value
                if action == "BUY":  # Short position
                    pnl = -pnl
                self.db.close_trade(open_trade["id"], fill_px, pnl)
            
            self.db.insert_order(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                action=action,
                order_type="EXIT",
                quantity=qty,
                limit_price=fill_px,
            )