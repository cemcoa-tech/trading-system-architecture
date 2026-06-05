# utils/expiry_selector.py
# ───────────────────────────────────────────────────────────────────────────
# Utility functions for selecting optimal futures contract expiry
# based on open interest and liquidity
# ───────────────────────────────────────────────────────────────────────────

from typing import Optional, Tuple
from datetime import datetime, timedelta
import pandas as pd

from ib_insync import IB, Future, ContFuture, ContractDetails
from utils.logger import get_logger

log = get_logger("expiry_selector")


def get_best_expiry(
    ib: IB,
    symbol: str,
    exchange: str = "CME",
    currency: str = "USD",
    min_days_to_expiry: int = 7,
    max_days_to_expiry: int = 365,
    min_volume: int = 100,
) -> Tuple[Optional[Future], Optional[ContractDetails]]:
    """
    Select the best futures contract expiry based on historical trading volume.
    
    Uses reqHistoricalData to get actual volume (works 24/7, unlike OI which is 0 outside RTH).
    
    Process:
    1. Query IBKR for all available contract months for the symbol
    2. Filter by expiry date range (min_days to max_days)
    3. Fetch historical volume data for each contract
    4. Rank by volume
    5. Return the contract with highest liquidity
    
    Args:
        ib: Connected IBKR instance
        symbol: Futures symbol (e.g., "GC", "MES", "ES")
        exchange: Exchange (default: "CME")
        currency: Contract currency (default: "USD")
        min_days_to_expiry: Minimum days until expiry (default: 7)
        max_days_to_expiry: Maximum days until expiry (default: 365)
        min_volume: Minimum daily volume threshold (default: 100)
    
    Returns:
        Tuple of (Future contract, ContractDetails) or (None, None) if no suitable contract found
    """
    log.info("=" * 60)
    log.info("SELECTING BEST EXPIRY FOR %s", symbol)
    log.info("=" * 60)
    
    today = datetime.now()
    min_expiry = today + timedelta(days=min_days_to_expiry)
    max_expiry = today + timedelta(days=max_days_to_expiry)
    
    log.info(f"Date range: {min_expiry.date()} to {max_expiry.date()}")
    log.info(f"Min volume threshold: {min_volume}")
    
    try:
        # Step 1: Get all contract details for the symbol
        log.info("Step 1: Querying available contracts...")
        base_contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        contract_details = ib.reqContractDetails(base_contract)
        
        if not contract_details:
            log.error(f"No contracts found for {symbol}")
            return None, None
        
        log.info(f"Found {len(contract_details)} contracts for {symbol}")
        
        # Step 2: Filter by expiry date and fetch historical volume
        log.info("Step 2: Filtering by expiry and fetching historical volume...")
        valid_contracts = []
        
        for details in contract_details:
            contract = details.contract
            expiry_str = contract.lastTradeDateOrContractMonth
            
            if not expiry_str:
                continue
            
            # Parse expiry date (format: YYYYMM or YYYYMMDD)
            try:
                if len(expiry_str) == 6:
                    expiry_date = datetime.strptime(expiry_str, "%Y%m")
                elif len(expiry_str) == 8:
                    expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
                else:
                    log.warning(f"Unexpected expiry format: {expiry_str}")
                    continue
            except ValueError as e:
                log.warning(f"Failed to parse expiry {expiry_str}: {e}")
                continue
            
            # Check if expiry is within range
            if expiry_date < min_expiry or expiry_date > max_expiry:
                log.debug(f"Skipping {contract.localSymbol}: expiry {expiry_date.date()} out of range")
                continue
            
            # Fetch historical volume (works 24/7)
            try:
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr="2 D",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1
                )
                volume = bars[-1].volume if bars and len(bars) > 0 else 0
            except Exception as e:
                log.warning(f"Error fetching volume for {contract.localSymbol}: {e}")
                volume = 0
            
            # Get OI from contract details (often 0 outside RTH, but we capture it for reference)
            open_interest = details.openInterest if hasattr(details, 'openInterest') else 0
            
            # Log contract info
            log.info(
                f"  {contract.localSymbol}: expiry={expiry_date.date()}, "
                f"Volume={volume:,.0f}, OI={open_interest:,}"
            )
            
            # Filter by minimum volume
            if volume < min_volume:
                log.debug(f"  Skipping {contract.localSymbol}: volume below threshold")
                continue
            
            valid_contracts.append({
                'contract': contract,
                'details': details,
                'expiry_date': expiry_date,
                'volume': volume,
                'open_interest': open_interest,
                'local_symbol': contract.localSymbol,
            })
        
        if not valid_contracts:
            log.warning(f"No contracts meet criteria for {symbol}")
            return None, None
        
        log.info(f"Found {len(valid_contracts)} valid contracts")
        
        # Step 3: Rank by volume (primary)
        log.info("Step 3: Ranking by volume...")
        
        valid_contracts.sort(key=lambda x: x['volume'], reverse=True)
        
        # Step 4: Select the best contract
        best = valid_contracts[0]
        best_contract = best['contract']
        best_details = best['details']
        
        log.info("=" * 60)
        log.info("BEST CONTRACT SELECTED")
        log.info("=" * 60)
        log.info(f"Symbol: {best_contract.localSymbol}")
        log.info(f"Expiry: {best['expiry_date'].date()}")
        log.info(f"Days to expiry: {(best['expiry_date'] - today).days}")
        log.info(f"Volume: {best['volume']:,.0f}")
        log.info(f"Open Interest: {best['open_interest']:,}")
        log.info(f"Contract ID: {best_contract.conId}")
        log.info("=" * 60)
        
        return best_contract, best_details
        
    except Exception as e:
        log.error(f"Error selecting best expiry for {symbol}: {e}", exc_info=True)
        return None, None


def get_best_expiry_with_contfuture(
    ib: IB,
    symbol: str,
    exchange: str = "CME",
    currency: str = "USD",
) -> Tuple[Optional[Future], Optional[ContractDetails]]:
    """
    Select best expiry using continuous futures approach.
    
    This method uses ContFuture to get the front month, then queries
    nearby contracts to find the one with highest liquidity.
    
    This is useful when you want to stay in the front month but ensure
    you're in the most liquid contract.
    
    Args:
        ib: Connected IBKR instance
        symbol: Futures symbol (e.g., "GC", "MES", "ES")
        exchange: Exchange (default: "CME")
        currency: Contract currency (default: "USD")
    
    Returns:
        Tuple of (Future contract, ContractDetails) or (None, None)
    """
    log.info("=" * 60)
    log.info("SELECTING BEST EXPIRY (CONTINUOUS FUTURES METHOD)")
    log.info("=" * 60)
    
    try:
        # Step 1: Get continuous future to identify front month
        log.info("Step 1: Getting continuous future...")
        cont_future = ContFuture(symbol=symbol, exchange=exchange, currency=currency)
        ib.qualifyContracts(cont_future)
        
        log.info(f"Continuous future: {cont_future.localSymbol}")
        
        # Step 2: Get contract details for the continuous future
        cont_details = ib.reqContractDetails(cont_future)
        
        if not cont_details:
            log.error(f"No details for continuous future {symbol}")
            return None, None
        
        # The continuous future details should point to the front month
        front_month_symbol = cont_details[0].contract.localSymbol
        log.info(f"Front month: {front_month_symbol}")
        
        # Step 3: Get all nearby contracts (front month + next 2-3 months)
        log.info("Step 2: Querying nearby contracts...")
        base_contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        all_details = ib.reqContractDetails(base_contract)
        
        if not all_details:
            log.error(f"No contracts found for {symbol}")
            return None, None
        
        # Filter to nearby contracts (within 3 months of front month)
        today = datetime.now()
        valid_contracts = []
        
        for details in all_details:
            contract = details.contract
            expiry_str = contract.lastTradeDateOrContractMonth
            
            if not expiry_str:
                continue
            
            try:
                if len(expiry_str) == 6:
                    expiry_date = datetime.strptime(expiry_str, "%Y%m")
                elif len(expiry_str) == 8:
                    expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
                else:
                    continue
            except ValueError:
                continue
            
            # Only consider contracts within 90 days
            if (expiry_date - today).days > 90:
                continue
            
            open_interest = details.openInterest if hasattr(details, 'openInterest') else 0
            volume = details.volume if hasattr(details, 'volume') else 0
            
            valid_contracts.append({
                'contract': contract,
                'details': details,
                'expiry_date': expiry_date,
                'open_interest': open_interest,
                'volume': volume,
                'local_symbol': contract.localSymbol,
            })
        
        if not valid_contracts:
            log.warning(f"No nearby contracts found for {symbol}")
            return None, None
        
        # Sort by open interest
        valid_contracts.sort(key=lambda x: x['open_interest'], reverse=True)
        
        # Select best
        best = valid_contracts[0]
        
        log.info("=" * 60)
        log.info("BEST CONTRACT SELECTED (CONTINUOUS METHOD)")
        log.info("=" * 60)
        log.info(f"Symbol: {best['contract'].localSymbol}")
        log.info(f"Expiry: {best['expiry_date'].date()}")
        log.info(f"Open Interest: {best['open_interest']:,}")
        log.info(f"Volume: {best['volume']:,}")
        log.info("=" * 60)
        
        return best['contract'], best['details']
        
    except Exception as e:
        log.error(f"Error selecting best expiry (continuous method): {e}", exc_info=True)
        return None, None


def compare_liquidity(
    ib: IB,
    symbol: str,
    contract1: Future,
    contract2: Future,
) -> dict:
    """
    Compare liquidity between two contracts.
    
    Args:
        ib: Connected IBKR instance
        symbol: Futures symbol
        contract1: First contract to compare
        contract2: Second contract to compare
    
    Returns:
        Dictionary with liquidity metrics for both contracts
    """
    log.info(f"Comparing liquidity for {symbol}: {contract1.localSymbol} vs {contract2.localSymbol}")
    
    try:
        details1 = ib.reqContractDetails(contract1)
        details2 = ib.reqContractDetails(contract2)
        
        if not details1 or not details2:
            log.error("Could not get contract details for comparison")
            return {}
        
        d1 = details1[0]
        d2 = details2[0]
        
        oi1 = d1.openInterest if hasattr(d1, 'openInterest') else 0
        oi2 = d2.openInterest if hasattr(d2, 'openInterest') else 0
        
        vol1 = d1.volume if hasattr(d1, 'volume') else 0
        vol2 = d2.volume if hasattr(d2, 'volume') else 0
        
        result = {
            'contract1': {
                'symbol': contract1.localSymbol,
                'expiry': contract1.lastTradeDateOrContractMonth,
                'open_interest': oi1,
                'volume': vol1,
            },
            'contract2': {
                'symbol': contract2.localSymbol,
                'expiry': contract2.lastTradeDateOrContractMonth,
                'open_interest': oi2,
                'volume': vol2,
            },
            'recommendation': contract1.localSymbol if oi1 > oi2 else contract2.localSymbol,
        }
        
        log.info(f"Contract 1 OI: {oi1:,}, Volume: {vol1:,}")
        log.info(f"Contract 2 OI: {oi2:,}, Volume: {vol2:,}")
        log.info(f"Recommended: {result['recommendation']}")
        
        return result
        
    except Exception as e:
        log.error(f"Error comparing liquidity: {e}", exc_info=True)
        return {}


def resolve_front_month(
    ib: IB,
    symbol: str,
    exchange: str = "CME",
    currency: str = "USD",
    min_days_to_expiry: int = 4,
    max_days_to_expiry: int = 180,
) -> Optional[str]:
    """
    Resolve the active front-month expiry for a futures symbol at runtime.

    Strategy:
      1. Query all contracts from IBKR for the symbol.
      2. Filter to those expiring >= min_days_to_expiry and <= max_days_to_expiry from today.
      3. Fetch historical volume data (works 24/7, unlike OI which is 0 outside RTH)
      4. Pick contract with highest recent volume.

    Returns the expiry string in YYYYMMDD format, or None on failure.
    Caller should fall back to the hard-coded settings.py value on None.
    """
    log.info("[AUTO-EXPIRY] Resolving front month for %s on %s", symbol, exchange)
    today = datetime.now()
    today_str = today.strftime("%Y%m%d")
    min_expiry = today + timedelta(days=min_days_to_expiry)
    max_expiry = today + timedelta(days=max_days_to_expiry)

    try:
        # Step 1: Get all available contracts
        base_contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        all_details = ib.reqContractDetails(base_contract)

        if not all_details:
            log.warning("[AUTO-EXPIRY] No contracts returned for %s — keeping configured expiry", symbol)
            return None

        # Step 2: Filter to non-expired contracts (preserve OI from already-fetched details)
        contracts = []
        for det in all_details:
            ct = det.contract
            expiry_str = ct.lastTradeDateOrContractMonth
            if not expiry_str:
                continue
            
            # Skip expired contracts
            if expiry_str < today_str[:len(expiry_str)]:
                continue
            
            # Parse expiry date for min_days check
            try:
                if len(expiry_str) == 6:
                    expiry_date = datetime.strptime(expiry_str, "%Y%m")
                elif len(expiry_str) == 8:
                    expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
                else:
                    continue
            except ValueError:
                continue
            
            if expiry_date < min_expiry or expiry_date > max_expiry:
                continue
            
            oi = getattr(det, "openInterest", 0) or 0
            contracts.append((ct, oi))

        if not contracts:
            log.warning("[AUTO-EXPIRY] No valid contracts for %s — keeping configured expiry", symbol)
            return None

        log.info("[AUTO-EXPIRY] Found %d valid contracts for %s (date range: %s to %s)", 
                 len(contracts), symbol, min_expiry.date(), max_expiry.date())

        # Step 3: Fetch historical volume for each contract (no extra reqContractDetails calls)
        candidates = []
        for ct, oi in contracts:
            try:
                # Fetch last 2 days of daily bars to get recent volume
                bars = ib.reqHistoricalData(
                    ct,
                    endDateTime="",
                    durationStr="2 D",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1
                )

                # Retry once if empty (transient HMDS warm-up)
                # if not bars:
                #     ib.sleep(5)
                #     bars = ib.reqHistoricalData(
                #         ct,
                #         endDateTime="",
                #         durationStr="2 D",
                #         barSizeSetting="1 day",
                #         whatToShow="TRADES",
                #         useRTH=False,
                #         formatDate=1
                #     )

                # Get volume from most recent bar
                volume = bars[-1].volume if bars and len(bars) > 0 else 0

                candidates.append({
                    "contract": ct,
                    "local_symbol": ct.localSymbol,
                    "expiry_str": ct.lastTradeDateOrContractMonth,
                    "expiry_date": datetime.strptime(ct.lastTradeDateOrContractMonth, "%Y%m" if len(ct.lastTradeDateOrContractMonth) == 6 else "%Y%m%d"),
                    "volume": volume,
                    "oi": oi,
                })

                # Small pause to avoid IBKR pacing violations between requests
                # ib.sleep(1)

            except Exception as e:
                log.warning(f"[AUTO-EXPIRY] Error fetching volume for {ct.localSymbol}: {e}")
                continue

        if not candidates:
            log.warning("[AUTO-EXPIRY] No volume data retrieved for %s", symbol)
            return None

        # Step 4: Log all candidates
        print(f"\n[AUTO-EXPIRY] ===== CANDIDATE LIST START for {symbol} =====")
        print(f"[AUTO-EXPIRY] {symbol}: All {len(candidates)} candidate contracts considered (using historical volume):")
        print(f"[AUTO-EXPIRY] {symbol}: {'Symbol':<12} | {'Expiry':<12} | {'Volume':<12} | {'OI':<10} | Days")
        print(f"[AUTO-EXPIRY] {symbol}: {'-'*65}")
        
        for c in sorted(candidates, key=lambda x: x["expiry_date"]):
            days_to_exp = (c["expiry_date"] - today).days
            print(f"[AUTO-EXPIRY] {symbol}: {c['local_symbol']:<12} | {c['expiry_date'].date():<12} | {c['volume']:<12,.0f} | {c['oi']:<10,} | {days_to_exp}")
            log.info(
                "[AUTO-EXPIRY] %s: %-12s | %-12s | Volume=%-12.0f | OI=%-10d | days=%d",
                symbol, c["local_symbol"], c["expiry_date"].date(), c["volume"], c["oi"], days_to_exp
            )

        # Step 5: Select best contract by volume
        candidates.sort(key=lambda x: x["volume"], reverse=True)
        best = candidates[0]
        
        total_vol = sum(c["volume"] for c in candidates)
        
        if best["volume"] > 0:
            selection_reason = f"highest volume ({best['volume']:,.0f})"
        else:
            # All volumes are 0 - fall back to nearest expiry
            candidates.sort(key=lambda x: x["expiry_date"])
            best = candidates[0]
            selection_reason = f"nearest expiry (volume=0 fallback)"

        days_to_exp = (best["expiry_date"] - today).days
        
        print(f"[AUTO-EXPIRY] ===== CANDIDATE LIST END =====")
        print(f"[AUTO-EXPIRY] {symbol} -> SELECTED: {best['local_symbol']} | expiry={best['expiry_date'].date()} | Volume={best['volume']:,.0f} | OI={best['oi']:,} | days_to_exp={days_to_exp} | reason={selection_reason}")
        
        log.info(
            "[AUTO-EXPIRY] %s -> SELECTED: %s | expiry=%s | Volume=%.0f | OI=%d | days_to_exp=%d | reason=%s",
            symbol, best["local_symbol"], best["expiry_date"].date(),
            best["volume"], best["oi"], days_to_exp, selection_reason
        )

        return best["expiry_str"]

    except Exception as exc:
        log.error("[AUTO-EXPIRY] Failed for %s: %s", symbol, exc, exc_info=True)
        return None


def check_rollover_needed(
    ib: IB,
    current_contract: Future,
    symbol: str,
    exchange: str = "CME",
    currency: str = "USD",
    force_rollover: bool = False,
) -> Tuple[bool, Optional[Future], int, int]:
    """
    Primary rollover trigger: rollover when the next contract's open interest
    exceeds the current contract's open interest.

    This is the standard market convention used by most institutional desks —
    when volume/OI migrates to the next month, follow it.

    Args:
        ib: Connected IBKR instance
        current_contract: The contract currently held/traded
        symbol: Futures symbol (e.g. "GC", "MES")
        exchange: Exchange (e.g. "COMEX", "CME")
        currency: Contract currency (default "USD")

    Returns:
        Tuple of:
          - should_rollover (bool)
          - next_contract (Future or None)
          - current_oi (int)
          - next_oi (int)
    """
    log.info("-" * 50)
    log.info("ROLLOVER CHECK: %s (%s)", current_contract.localSymbol, symbol)
    log.info("-" * 50)

    try:
        today = datetime.now()

        # ── Step 1: Parse current contract expiry ───────────────────────
        expiry_str = current_contract.lastTradeDateOrContractMonth
        try:
            if len(expiry_str) == 6:
                current_expiry = datetime.strptime(expiry_str, "%Y%m")
            elif len(expiry_str) == 8:
                current_expiry = datetime.strptime(expiry_str, "%Y%m%d")
            else:
                log.error("Unrecognised expiry format: %s", expiry_str)
                return False, None, 0, 0
        except ValueError as e:
            log.error("Could not parse expiry %s: %s", expiry_str, e)
            return False, None, 0, 0

        days_to_expiry = (current_expiry - today).days
        log.info("Current contract expiry: %s  (%d days away)", current_expiry.date(), days_to_expiry)

        # ── Step 2: Fetch all contract details for the symbol ───────────
        base = Future(symbol=symbol, exchange=exchange, currency=currency)
        all_details = ib.reqContractDetails(base)

        if not all_details:
            log.error("No contracts returned for %s on %s", symbol, exchange)
            return False, None, 0, 0

        log.info("Found %d contracts for %s", len(all_details), symbol)

        # ── Step 3: Find current and next contract volume ─────────────
        # Use historical volume (works 24/7) instead of OI (often 0 outside RTH)
        current_vol = 0
        candidates = []   # contracts with expiry AFTER current_expiry

        def get_contract_volume(ct):
            """Fetch historical volume for a contract."""
            try:
                bars = ib.reqHistoricalData(
                    ct,
                    endDateTime="",
                    durationStr="2 D",
                    barSizeSetting="1 day",
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1
                )
                return bars[-1].volume if bars and len(bars) > 0 else 0
            except Exception as e:
                log.warning(f"Error fetching volume for {ct.localSymbol}: {e}")
                return 0

        for details in all_details:
            ct = details.contract
            exp_str = ct.lastTradeDateOrContractMonth
            try:
                if len(exp_str) == 6:
                    exp_date = datetime.strptime(exp_str, "%Y%m")
                elif len(exp_str) == 8:
                    exp_date = datetime.strptime(exp_str, "%Y%m%d")
                else:
                    continue
            except ValueError:
                continue

            # Match current contract by conId or expiry
            is_current = (
                ct.conId == current_contract.conId
                or exp_str == expiry_str
            )
            if is_current:
                current_vol = get_contract_volume(ct)
                log.info("Current  %s: Volume=%.0f", ct.localSymbol, current_vol)
                continue

            # Only consider contracts with future expiry (within 18 months)
            if exp_date > current_expiry and (exp_date - today).days <= 540:
                vol = get_contract_volume(ct)
                candidates.append({
                    "contract": ct,
                    "expiry_date": exp_date,
                    "volume": vol,
                })
                log.info("Candidate %s: Volume=%.0f  expiry=%s", ct.localSymbol, vol, exp_date.date())

        if not candidates:
            log.info("No next-month candidates found — no rollover needed")
            return False, None, int(current_vol), 0

        # Pick the nearest next expiry with the highest volume
        candidates.sort(key=lambda x: (x["expiry_date"], -x["volume"]))
        # Among the nearest expiry month, pick highest volume
        nearest_expiry = candidates[0]["expiry_date"]
        nearest_candidates = [c for c in candidates if c["expiry_date"] == nearest_expiry]
        nearest_candidates.sort(key=lambda x: -x["volume"])
        best_next = nearest_candidates[0]

        next_vol = best_next["volume"]
        next_contract = best_next["contract"]

        log.info(
            "Best next contract: %s  Volume=%.0f  (current Volume=%.0f)",
            next_contract.localSymbol, next_vol, current_vol,
        )

        # ── Step 4: Trigger rollover if next volume > current volume ───
        if force_rollover:
            log.warning(
                "ROLLOVER FORCED (force_rollover=True): skipping volume comparison  "
                "current Vol=%.0f  next Vol=%.0f",
                current_vol, next_vol,
            )
            return True, next_contract, int(current_vol), int(next_vol)

        if next_vol > current_vol:
            log.info(
                "ROLLOVER TRIGGERED: next Volume (%.0f) > current Volume (%.0f)",
                next_vol, current_vol,
            )
            return True, next_contract, int(current_vol), int(next_vol)

        log.info(
            "No rollover needed: current Volume (%.0f) >= next Volume (%.0f)",
            current_vol, next_vol,
        )
        return False, None, int(current_vol), int(next_vol)

    except Exception as e:
        log.error("Error in check_rollover_needed: %s", e, exc_info=True)
        return False, None, 0, 0
