"""
strategies/base_strategy.py
───────────────────────────
Abstract base class that every strategy must subclass.
Enforces a clean 4-step lifecycle:
    1. fetch_data()
    2. compute_indicators()
    3. generate_signal()
    4. get_position_size()

Subclasses implement the specifics; the runner (main.py) calls execute().
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from config.settings import ContractSpec, StrategyParams
from database.manager import DatabaseManager
from execution.broker import Broker
from execution.order_manager import OrderManager
from utils.logger import get_logger


@dataclass
class Signal:
    """Standardised signal emitted by a strategy."""
    signal_type: str        # ENTRY_LONG | EXIT_LONG | ENTRY_SHORT | EXIT_SHORT | NONE
    reason: str
    close_price: float
    indicators: Dict[str, Any]
    meta: Dict[str, Any]


class BaseStrategy(ABC):
    """
    Template-method pattern: execute() orchestrates the workflow;
    subclasses fill in the four abstract hooks.
    """

    def __init__(
        self,
        params: StrategyParams,
        broker: Broker,
        order_mgr: OrderManager,
        db: DatabaseManager,
        account: str,
    ) -> None:
        self.params = params
        self.spec: ContractSpec = params.contract_spec
        self.broker = broker
        self.order_mgr = order_mgr
        self.db = db
        self.account = account
        self.log = get_logger(f"strategy.{params.name}")
        self._df: Optional[pd.DataFrame] = None

    @property
    def name(self) -> str:
        return self.params.name

    # ── Abstract hooks ───────────────────────────────────────────────────

    @abstractmethod
    def fetch_data(self) -> pd.DataFrame:
        """Pull historical bars and return raw DataFrame."""
        ...

    @abstractmethod
    def compute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add indicator columns in-place and return the enriched DataFrame."""
        ...

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, current_pos: int) -> Signal:
        """Inspect the latest row + current position and return a Signal."""
        ...

    def get_position_size(self, signal: Signal) -> int:
        """Return desired contract quantity for an entry signal."""
        # Hard-coded quantities based on contract symbol
        symbol_quantities = {
            "MBT": 10,  # BTC Micro Futures
            "GC": 1,     # Gold Futures
            "ES": 1,     # S&P 500 Micro Futures
            "NQ": 1,     # NASDAQ 100 Micro Futures
            "MNQ": 1,    # NASDAQ 100 Micro Futures (alternative symbol)
            "MES": 1,    # S&P 500 Micro Futures (alternative symbol)
            "MGC": 1,    # Gold Micro Futures
        }
        
        return symbol_quantities.get(self.spec.symbol, 1)

    # ── Template execution ───────────────────────────────────────────────

    def execute(self) -> None:
        """
        Full lifecycle: data → indicators → signal → order placement → DB logging.
        Designed to be called once per scheduling interval (e.g. daily cron).
        """
        self.log.info("=" * 50)
        self.log.info("EXECUTING STRATEGY: %s", self.name)
        self.log.info("=" * 50)

        # 0 — Register strategy
        self.db.upsert_strategy(
            self.name,
            description=f"Strategy: {self.name}",
            params=self.params.params,
        )

        # 1 — Qualify contracts
        self.log.info("[1] Qualifying contracts...")
        trade_ct = self.broker.qualify_contract(self.spec)
        data_ct = self.broker.qualify_data_contract(self.spec)

        # 2 — Fetch data
        self.log.info("[2] Fetching historical data...")
        df = self.fetch_data()

        # 3 — Compute indicators
        self.log.info("[3] Computing indicators...")
        df = self.compute_indicators(df)
        self._df = df

        # 4 — Current position
        current_pos = self.broker.get_position_quantity(trade_ct.conId, account=self.account)
        self.log.info("Current position: %d", current_pos)

        # 5 — Generate signal
        self.log.info("[4] Generating signal...")
        signal = self.generate_signal(df, current_pos)
        self.log.info(
            "Signal: %s  reason=%s", signal.signal_type, signal.reason
        )

        # 6 — Persist signal
        last_row = df.iloc[-1]
        self.db.insert_signal(
            strategy_name=self.name,
            signal_date=str(last_row.get("date", "")),
            signal_type=signal.signal_type,
            close_price=signal.close_price,
            indicators=signal.indicators,
            meta=signal.meta,
        )

        # 7 — Send notification
        from utils.notifications import notify_strategy_execution
        from datetime import datetime
        notify_strategy_execution(
            strategy_name=self.name,
            execution_time=datetime.now(),
            signal=signal.signal_type,
            indicators={
                **signal.indicators,
                'current_pos': current_pos,
                'reason': signal.reason
            }
        )

        # 8 — Execute orders
        self._execute_signal(signal, trade_ct, current_pos)

        # 9 — Snapshot position only if there was a signal (ENTRY or EXIT)
        if signal.signal_type != "NONE":
            new_pos = self.broker.get_position_quantity(trade_ct.conId, account=self.account)
            self.db.snapshot_position(
                strategy_name=self.name,
                symbol=self.spec.symbol,
                quantity=new_pos,
            )

        self.log.info("EXECUTION COMPLETE for %s", self.name)

    # ── Internal order routing ───────────────────────────────────────────

    def _execute_signal(
        self,
        signal: Signal,
        contract,
        current_pos: int,
    ) -> None:
        """Route signal to the appropriate order type."""
        if signal.signal_type == "NONE":
            self.log.info("No order required")
            return

        # Get indicative price
        fallback = signal.close_price
        price, source = self.broker.get_indicative_price(contract, fallback)
        self.log.info("Indicative price: %.2f (%s)", price, source)

        if signal.signal_type == "ENTRY_LONG":
            qty = self.get_position_size(signal)
            limit_px = price + self.spec.price_offset
            bracket_info = self.order_mgr.compute_bracket_prices(
                entry_price=limit_px,
                risk_usd=self.params.risk_usd,
                point_value=self.spec.point_value,
                action="BUY",
                tick_size=self.spec.tick_size,
            )
            result = self.order_mgr.place_bracket(
                contract=contract,
                spec=self.spec,
                action="BUY",
                quantity=qty,
                limit_price=limit_px,
                tp_price=bracket_info["tp"],
                sl_price=bracket_info["sl"],
                account=self.account,
            )
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
                order_type="LIMIT",
                quantity=qty,
                trade_id=trade_id,
                limit_price=result["limit_px"],
            )

        elif signal.signal_type == "EXIT_LONG":
            qty = abs(current_pos)
            limit_px = price - self.spec.price_offset
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
                order_type="LIMIT",
                quantity=qty,
                limit_price=fill_px,
            )
