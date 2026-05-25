# utils/calendar_utils.py
"""
utils/calendar_utils.py
──────────────────────
Calendar utilities for trading day calculations.

Handles US Federal Holiday calendar and CME Sunday evening sessions.
"""

import pandas as pd
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

# US Trading Day Calendar
US_BDAY = CustomBusinessDay(calendar=USFederalHolidayCalendar())


def trading_days_before_eom(date) -> int:
    """
    Calculate number of trading days from date to last trading day of month.

    Args:
        date: Date to calculate from (pd.Timestamp or datetime)

    Returns:
        Number of trading days before end of month (0 = last trading day)
        None if calculation fails
    """
    d = pd.Timestamp(date).normalize()
    month_end = (d + pd.offsets.MonthEnd(0)).normalize()

    # Get all business days in range
    rng = pd.date_range(d, month_end, freq=US_BDAY)
    if len(rng) == 0:
        return None

    last_trading_day = rng[-1]
    return len(pd.date_range(d, last_trading_day, freq=US_BDAY)) - 1


def trading_days_before_last_friday_of_month(date) -> int:
    """
    Calculate number of trading days from date to last Friday of the month.

    Args:
        date: Date to calculate from (pd.Timestamp or datetime)

    Returns:
        Number of trading days before last Friday of month (0 = last Friday)
        None if calculation fails
    """
    d = pd.Timestamp(date).normalize()
    month_end = (d + pd.offsets.MonthEnd(0)).normalize()

    # Find last Friday of the month
    # Start from month end and go backwards to find the last Friday
    current = month_end
    last_friday = None

    for i in range(7):  # Check up to 7 days back to find a Friday
        if current.weekday() == 4:  # Friday (weekday 4)
            last_friday = current
            break
        current = current - pd.Timedelta(days=1)

    if last_friday is None:
        return None

    # Get all business days from date to last Friday
    rng = pd.date_range(d, last_friday, freq=US_BDAY)
    if len(rng) == 0:
        return None

    # Debug logging
    print(f"trading_days_before_last_friday: date={d}, last_friday={last_friday}, business_days={list(rng)}, count={len(rng)-1}")

    return len(rng) - 1


def is_first_trading_day_of_month(date) -> bool:
    """
    Check if date is the first trading day of the month.
    
    Args:
        date: Date to check (pd.Timestamp or datetime)
        
    Returns:
        True if date is first trading day of month
    """
    d = pd.Timestamp(date).normalize()
    month_start = d.replace(day=1)
    
    # Get first business day of month
    first_td = pd.date_range(
        month_start,
        month_start + pd.Timedelta(days=10),
        freq=US_BDAY
    )[0]
    
    return d == first_td


def is_last_trading_day_of_month(date) -> bool:
    """
    Check if date is the last trading day of the month.
    
    Args:
        date: Date to check (pd.Timestamp or datetime)
        
    Returns:
        True if date is last trading day of month
    """
    return trading_days_before_eom(date) == 0


def effective_trade_date() -> datetime.date:
    """
    Get effective trade date accounting for pre-market evening runs.

    Evening runs (>= 4pm CT) count as the next trading day's pre-market.
    This aligns with the strategy schedule where evening runs prepare for the next day.

    Returns:
        Effective trade date
    """
    now_utc = datetime.now(timezone.utc)
    ct = now_utc.astimezone(ZoneInfo("America/Chicago"))

    d = ct.date()

    # Evening session (>= 4pm CT) counts as next trading day
    if ct.hour >= 16:
        d = d + timedelta(days=1)

    return d


def get_next_contract_month(current_month: str) -> str:
    """
    Get next quarterly contract month for futures rolling.
    
    Args:
        current_month: Current contract month (YYYYMM format)
        
    Returns:
        Next contract month (YYYYMM format)
        
    Example:
        "202603" -> "202606"
        "202606" -> "202609"
    """
    year = int(current_month[:4])
    month = int(current_month[4:6])
    
    # Quarterly months: Mar(3), Jun(6), Sep(9), Dec(12)
    quarterly_months = [3, 6, 9, 12]
    
    # Find next quarterly month
    next_months = [m for m in quarterly_months if m > month]
    
    if next_months:
        next_month = next_months[0]
        next_year = year
    else:
        next_month = quarterly_months[0]
        next_year = year + 1
    
    return f"{next_year}{next_month:02d}"
