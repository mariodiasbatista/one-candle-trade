from datetime import datetime, date
import calendar

# Known FOMC decision dates for 2026 (8 per year, ~6 weeks apart)
FOMC_DATES_2026 = {
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
}

# Known CPI release dates 2026 (monthly, usually 2nd or 3rd week)
CPI_DATES_2026 = {
    "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-10",
    "2026-05-13", "2026-06-10", "2026-07-14", "2026-08-12",
    "2026-09-11", "2026-10-13", "2026-11-12", "2026-12-10",
}

HIGH_IMPACT_DATES = FOMC_DATES_2026 | CPI_DATES_2026


def is_first_friday(d: date) -> bool:
    """Returns True if date is the first Friday of the month (NFP release day)."""
    if d.weekday() != 4:  # 4 = Friday
        return False
    return d.day <= 7


def is_high_impact_day(trade_date: str) -> tuple[bool, str]:
    """
    Returns (True, reason) if today is a high-impact news day to skip.
    Returns (False, "") if safe to trade.
    """
    d = datetime.strptime(trade_date, "%Y-%m-%d").date()

    if trade_date in FOMC_DATES_2026:
        return True, "FOMC interest rate decision day"

    if trade_date in CPI_DATES_2026:
        return True, "CPI release day"

    if is_first_friday(d):
        return True, "NFP (Non-Farm Payrolls) release day"

    return False, ""
