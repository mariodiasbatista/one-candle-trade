from datetime import date
from src.data.calendar import is_first_friday, is_high_impact_day


class TestIsFirstFriday:
    def test_first_friday_of_may(self):
        # May 1, 2026 is the first Friday of May
        assert is_first_friday(date(2026, 5, 1)) is True

    def test_second_friday_not_first(self):
        # May 8, 2026 is the second Friday (day 8 > 7)
        assert is_first_friday(date(2026, 5, 8)) is False

    def test_first_friday_of_february(self):
        # Feb 6, 2026 is the first Friday of February
        assert is_first_friday(date(2026, 2, 6)) is True

    def test_monday_is_not_friday(self):
        assert is_first_friday(date(2026, 5, 4)) is False

    def test_friday_in_second_week(self):
        # Day 14 > 7, so not first Friday even if it is a Friday
        assert is_first_friday(date(2026, 5, 15)) is False

    def test_friday_day_7(self):
        # Day 7 is the boundary — still first Friday if it's a Friday
        # Jan 2, 2026 is the first Friday of January (day 2 <= 7)
        assert is_first_friday(date(2026, 1, 2)) is True


class TestIsHighImpactDay:
    def test_fomc_day_blocked(self):
        blocked, reason = is_high_impact_day("2026-03-18")
        assert blocked is True
        assert "FOMC" in reason

    def test_another_fomc_day(self):
        blocked, reason = is_high_impact_day("2026-06-17")
        assert blocked is True
        assert "FOMC" in reason

    def test_cpi_day_blocked(self):
        blocked, reason = is_high_impact_day("2026-05-13")
        assert blocked is True
        assert "CPI" in reason

    def test_another_cpi_day(self):
        blocked, reason = is_high_impact_day("2026-01-14")
        assert blocked is True
        assert "CPI" in reason

    def test_nfp_day_blocked(self):
        # May 1, 2026 is first Friday of May = NFP day
        blocked, reason = is_high_impact_day("2026-05-01")
        assert blocked is True
        assert "NFP" in reason

    def test_normal_trading_day_clear(self):
        blocked, reason = is_high_impact_day("2026-05-07")
        assert blocked is False
        assert reason == ""

    def test_normal_wednesday_clear(self):
        blocked, reason = is_high_impact_day("2026-05-06")
        assert blocked is False
        assert reason == ""

    def test_second_friday_not_nfp(self):
        # May 8, 2026 is second Friday — not NFP, not in FOMC/CPI lists
        blocked, _ = is_high_impact_day("2026-05-08")
        assert blocked is False
