"""
execution/order_manager.py
──────────────────────────
Handles order construction and placement logic:
  • bracket orders (entry + TP + SL)
  • flat exit orders
  • tick rounding
  • risk-based position sizing
"""

from typing import Dict, Optional

from ib_insync import IB, Contract, LimitOrder

from config.settings import ContractSpec, IBKRConfig
from utils.logger import get_logger

log = get_logger("orders")


class OrderManager:
    """
    Stateless helper that builds and places orders via a live IB handle.
    All sizing / tick logic is contract-aware through ContractSpec.
    """

    def __init__(self, ib: IB, account: str) -> None:
        self._ib = ib
        self._account = account

    # ── Tick rounding ────────────────────────────────────────────────────
    @staticmethod
    def round_tick(price: float, tick_size: float) -> float:
        """Round *price* to the nearest valid tick increment."""
        return round(price / tick_size) * tick_size

    # ── Risk-based sizing ────────────────────────────────────────────────
    @staticmethod
    def compute_quantity(
        risk_usd: float,
        point_value: float,
        stop_distance_pts: float,
        max_position: int = 1,
    ) -> int:
        """
        Number of contracts sized to risk ≤ risk_usd.
        Floors to max_position as a hard cap.
        """
        if stop_distance_pts <= 0 or point_value <= 0:
            return 1
        raw = risk_usd / (stop_distance_pts * point_value)
        return max(1, min(int(raw), max_position))

    # ── Bracket order ────────────────────────────────────────────────────
    def place_bracket(
        self,
        contract: Contract,
        spec: ContractSpec,
        action: str,
        quantity: int,
        limit_price: float,
        tp_price: float,
        sl_price: float,
    ) -> Dict[str, float]:
        """
        Place a bracket order (parent limit + TP limit + SL stop).
        Returns dict with rounded tp_px and sl_px.
        """
        lp = self.round_tick(limit_price, spec.tick_size)
        tp = self.round_tick(tp_price, spec.tick_size)
        sl = self.round_tick(sl_price, spec.tick_size)

        bracket = self._ib.bracketOrder(action, quantity, lp, tp, sl)

        for o in bracket:
            o.account = self._account
        # TP and SL are GTC; parent only transmits last
        bracket[0].transmit = False
        bracket[1].tif = "GTC"
        bracket[1].transmit = False
        bracket[2].tif = "GTC"
        bracket[2].transmit = True

        parent_trade = self._ib.placeOrder(contract, bracket[0])
        parent_trade.filledEvent += lambda _t: log.info(
            "BRACKET PARENT FILLED @ %s", _t.orderStatus.avgFillPrice
        )
        self._ib.placeOrder(contract, bracket[1])  # TP
        self._ib.placeOrder(contract, bracket[2])  # SL
        self._ib.waitOnUpdate()

        log.info(
            "Bracket placed: %s %d @ %.2f  TP=%.2f  SL=%.2f",
            action, quantity, lp, tp, sl,
        )
        return {"limit_px": lp, "tp_px": tp, "sl_px": sl}

    # ── Flat exit ────────────────────────────────────────────────────────
    def place_exit(
        self,
        contract: Contract,
        spec: ContractSpec,
        action: str,
        quantity: int,
        limit_price: float,
    ) -> float:
        """Place a simple limit order to flatten a position."""
        lp = self.round_tick(limit_price, spec.tick_size)
        order = LimitOrder(action, quantity, lp)
        order.account = self._account
        self._ib.placeOrder(contract, order)
        self._ib.waitOnUpdate()
        log.info("Exit order placed: %s %d @ %.2f", action, quantity, lp)
        return lp

    # ── TP / SL distance helper ──────────────────────────────────────────
    @staticmethod
    def compute_bracket_prices(
        entry_price: float,
        risk_usd: float,
        point_value: float,
        action: str,
        tick_size: float,
    ) -> Dict[str, float]:
        """
        Compute TP and SL prices symmetrically around entry.
        Returns un-rounded values — caller should round_tick().
        """
        dist = risk_usd / point_value
        if action == "BUY":
            tp = entry_price + dist
            sl = entry_price - dist
        else:
            tp = entry_price - dist
            sl = entry_price + dist
        return {"tp": tp, "sl": sl, "distance_pts": dist}
