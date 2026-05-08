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
    Get effective trade date accounting for CME Sunday evening session.
    
    CME markets open Sunday 5pm ET (6pm ET for some products).
    If script runs Sunday >= 5pm ET, count it as Monday's trade date.
    
    Returns:
        Effective trade date
    """
    now_utc = datetime.now(timezone.utc)
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    
    d = et.date()
    
    # Sunday evening session (>= 5pm ET) counts as Monday
    if et.weekday() == 6 and et.hour >= 17:
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
