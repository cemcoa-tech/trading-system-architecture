"""
execution/broker.py
───────────────────
Abstraction over ib_insync for connection management,
contract qualification, and market data retrieval.
"""

import time
from typing import List, Optional

import pandas as pd
from ib_insync import IB, Contract, Future, util

from config.settings import ContractSpec, IBKRConfig, MarketDataConfig
from utils.logger import get_logger

log = get_logger("broker")


class Broker:
    """
    Manages a single IB gateway connection and exposes helpers
    for contracts, market data, and account queries.
    """

    def __init__(
        self,
        ibkr_cfg: Optional[IBKRConfig] = None,
        mkt_cfg: Optional[MarketDataConfig] = None,
    ) -> None:
        self._cfg = ibkr_cfg or IBKRConfig()
        self._mkt = mkt_cfg or MarketDataConfig()
        self._ib = IB()

    # ── Connection lifecycle ─────────────────────────────────────────────
    def connect(self) -> None:
        """Connect with automatic retries."""
        try:
            util.startLoop()
        except RuntimeError:
            pass

        for attempt in range(1, self._cfg.max_retries + 1):
            try:
                log.info(
                    "Connecting to IBKR %s:%s (attempt %d/%d)",
                    self._cfg.host, self._cfg.port,
                    attempt, self._cfg.max_retries,
                )
                self._ib.connect(
                    self._cfg.host,
                    self._cfg.port,
                    clientId=self._cfg.client_id,
                    timeout=self._cfg.connect_timeout,
                )
                log.info("Connected to IBKR")
                return
            except Exception as exc:
                log.warning("Connection attempt %d failed: %s", attempt, exc)
                if attempt < self._cfg.max_retries:
                    time.sleep(self._cfg.retry_delay)
        raise ConnectionError("Could not connect to IBKR after retries")

    def disconnect(self) -> None:
        try:
            self._ib.disconnect()
            log.info("Disconnected from IBKR")
        except Exception as exc:
            log.warning("Disconnect error (non-fatal): %s", exc)

    @property
    def ib(self) -> IB:
        return self._ib

    @property
    def account(self) -> str:
        return self._cfg.account

    # ── Contract helpers ─────────────────────────────────────────────────
    def qualify_contract(self, spec: ContractSpec) -> Contract:
        """Build + qualify a futures contract from a ContractSpec."""
        kwargs = dict(
            symbol=spec.symbol,
            lastTradeDateOrContractMonth=spec.last_trade_date,
            exchange=spec.exchange,
            currency=spec.currency,
        )
        if spec.trading_class:
            kwargs["tradingClass"] = spec.trading_class
        ct = Future(**kwargs)
        qualified = self._ib.qualifyContracts(ct)
        if not qualified:
            raise ValueError(f"Contract qualification failed for {spec.symbol}")
        log.info(
            "Qualified contract: %s  conId=%s",
            qualified[0].localSymbol, qualified[0].conId,
        )
        return qualified[0]

    def qualify_data_contract(self, spec: ContractSpec) -> Contract:
        """Qualify the data-source contract (may differ from trading contract)."""
        data_spec = ContractSpec(
            symbol=spec.data_symbol,
            last_trade_date=spec.data_last_trade_date,
            exchange=spec.data_exchange,
            currency=spec.currency,
        )
        return self.qualify_contract(data_spec)

    # ── Historical data ──────────────────────────────────────────────────
    def fetch_historical_bars(
        self, contract: Contract
    ) -> pd.DataFrame:
        """Return daily OHLCV as a DataFrame."""
        bars = self._ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr=self._mkt.duration_str,
            barSizeSetting=self._mkt.bar_size,
            whatToShow=self._mkt.what_to_show,
            useRTH=self._mkt.use_rth,
            formatDate=self._mkt.format_date,
        )
        if not bars:
            raise RuntimeError("No historical bars returned")
        df = pd.DataFrame(
            [{"date": b.date, "open": b.open, "high": b.high,
              "low": b.low, "close": b.close, "volume": b.volume}
             for b in bars]
        )
        log.info("Fetched %d historical bars for %s", len(df), contract.localSymbol)
        return df

    # ── Live / delayed mid-price ─────────────────────────────────────────
    def get_mid_price(
        self,
        contract: Contract,
        mkt_type: int = 1,
        wait_seconds: Optional[float] = None,
    ) -> Optional[float]:
        """
        Request streaming snapshot and return mid = (bid+ask)/2.
        mkt_type: 1 = live, 3 = delayed.
        """
        wait = wait_seconds or self._mkt.market_data_wait_s
        self._ib.reqMarketDataType(mkt_type)
        ticker = self._ib.reqMktData(contract, "", False, False)
        deadline = time.monotonic() + wait
        mid = None
        while time.monotonic() < deadline:
            self._ib.waitOnUpdate(0.2)
            bid = getattr(ticker, "bid", None)
            ask = getattr(ticker, "ask", None)
            if (
                isinstance(bid, (int, float))
                and isinstance(ask, (int, float))
                and ask >= bid > 0
            ):
                mid = 0.5 * (ask + bid)
                break
        try:
            self._ib.cancelMktData(contract)
        except Exception:
            pass
        return mid

    def get_indicative_price(
        self,
        contract: Contract,
        fallback_close: float,
    ) -> tuple[float, str]:
        """
        Try live → delayed → fallback close.  Returns (price, source_label).
        """
        mid = self.get_mid_price(contract, mkt_type=1)
        if mid is not None:
            return mid, "LIVE"

        mid = self.get_mid_price(contract, mkt_type=3)
        if mid is not None:
            return mid, "DELAYED"

        return fallback_close, "FALLBACK_CLOSE"

    # ── Account queries ──────────────────────────────────────────────────
    def get_position_quantity(self, con_id: int) -> int:
        """Current net position for a given conId under the configured account."""
        for p in self._ib.positions():
            if p.contract.conId == con_id and p.account == self._cfg.account:
                return int(p.position)
        return 0

    def get_all_positions(self) -> List[dict]:
        return [
            {
                "symbol": p.contract.localSymbol,
                "conId": p.contract.conId,
                "position": int(p.position),
                "avgCost": p.avgCost,
                "account": p.account,
            }
            for p in self._ib.positions()
            if p.account == self._cfg.account
        ]
