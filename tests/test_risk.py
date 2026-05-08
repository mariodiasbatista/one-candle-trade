import pytest
from src.core.risk import calculate_stop_loss, calculate_take_profit, calculate_position_size
from src.models import FVGResult
from tests.conftest import make_candle

# Option A threshold: fvg_size >= 0.30 * candle_range


def _make_fvg(gap_low, gap_high, gap_size=None):
    return FVGResult(
        direction="BULLISH_FVG_BREAK_HIGH",
        gap_high=gap_high,
        gap_low=gap_low,
        gap_size=gap_size if gap_size is not None else round(gap_high - gap_low, 4),
        body_ratio=2.0,
    )


class TestCalculateStopLoss:
    def test_long_option_a_fvg_based(self):
        # candle_range=2.0, fvg_size=0.8 → 0.8 >= 0.3*2.0=0.6 → Option A
        candle = make_candle(99, 100.0, 98.0, 99.5)  # range=2.0
        fvg = _make_fvg(gap_low=100.2, gap_high=100.9, gap_size=0.7)
        stop, stop_type = calculate_stop_loss("LONG", candle, fvg)
        assert stop == round(100.2 - 0.02, 2)
        assert "Option A" in stop_type

    def test_long_option_b_first_candle(self):
        # candle_range=2.0, fvg_size=0.3 → 0.3 < 0.6 → Option B
        candle = make_candle(99, 100.0, 98.0, 99.5)  # low=98.0
        fvg = _make_fvg(gap_low=100.2, gap_high=100.5, gap_size=0.3)
        stop, stop_type = calculate_stop_loss("LONG", candle, fvg)
        assert stop == round(98.0 - 0.02, 2)
        assert "Option B" in stop_type

    def test_short_option_a_fvg_based(self):
        # SHORT: stop = gap_high + 0.02 when Option A applies
        candle = make_candle(97, 97.5, 95.5, 96.5)  # range=2.0
        fvg = FVGResult(
            direction="BEARISH_FVG_BREAK_LOW",
            gap_high=96.8, gap_low=95.4, gap_size=1.4, body_ratio=2.0,
        )
        stop, stop_type = calculate_stop_loss("SHORT", candle, fvg)
        assert stop == round(96.8 + 0.02, 2)
        assert "Option A" in stop_type

    def test_short_option_b_first_candle(self):
        # candle_range=2.0, fvg_size=0.1 → 0.1 < 0.6 → Option B, SHORT stop = high + 0.02
        candle = make_candle(97, 97.5, 95.5, 96.5)  # high=97.5
        fvg = FVGResult(
            direction="BEARISH_FVG_BREAK_LOW",
            gap_high=96.8, gap_low=96.7, gap_size=0.1, body_ratio=2.0,
        )
        stop, stop_type = calculate_stop_loss("SHORT", candle, fvg)
        assert stop == round(97.5 + 0.02, 2)
        assert "Option B" in stop_type

    def test_zero_candle_range_uses_option_b(self):
        # candle_range=0 → option B fallback
        candle = make_candle(100, 100, 100, 100)  # range=0
        fvg = _make_fvg(gap_low=100.2, gap_high=100.5, gap_size=0.3)
        stop, stop_type = calculate_stop_loss("LONG", candle, fvg)
        assert "Option B" in stop_type


class TestCalculateTakeProfit:
    def test_long_take_profit(self):
        # entry=101, stop=98.48 → risk=2.52 → TP=101+2*2.52=106.04
        tp = calculate_take_profit("LONG", entry=101.0, stop_loss=98.48)
        assert tp == round(101.0 + 2.0 * abs(101.0 - 98.48), 2)

    def test_short_take_profit(self):
        # entry=94, stop=96.82 → risk=2.82 → TP=94-2*2.82=88.36
        tp = calculate_take_profit("SHORT", entry=94.0, stop_loss=96.82)
        assert tp == round(94.0 - 2.0 * abs(94.0 - 96.82), 2)

    def test_reward_is_2x_risk_long(self):
        entry, stop = 500.0, 498.0
        tp = calculate_take_profit("LONG", entry, stop)
        risk = abs(entry - stop)
        reward = abs(tp - entry)
        assert round(reward / risk, 1) == 2.0

    def test_reward_is_2x_risk_short(self):
        entry, stop = 450.0, 452.0
        tp = calculate_take_profit("SHORT", entry, stop)
        risk = abs(entry - stop)
        reward = abs(tp - entry)
        assert round(reward / risk, 1) == 2.0


class TestCalculatePositionSize:
    def test_normal_case_capped_by_max_position(self):
        # account=100_000, entry=500, stop=498 → risk$=1000, rps=2, size=500 → max=10 → 10
        size = calculate_position_size(account_value=100_000, entry=500.0, stop_loss=498.0)
        assert size == 10

    def test_small_account_uncapped(self):
        # account=10_000, entry=50, stop=49 → risk$=100, rps=1, size=100 → max=10 → 10
        size = calculate_position_size(account_value=10_000, entry=50.0, stop_loss=49.0)
        assert size == 10

    def test_minimum_one_share(self):
        # Very tight stop and large entry → floor at 1
        size = calculate_position_size(account_value=1_000, entry=1000.0, stop_loss=999.9)
        assert size >= 1

    def test_zero_risk_per_share_returns_zero(self):
        size = calculate_position_size(account_value=100_000, entry=500.0, stop_loss=500.0)
        assert size == 0

    def test_risk_scales_with_account(self):
        size_small = calculate_position_size(account_value=10_000, entry=100.0, stop_loss=99.0)
        size_large = calculate_position_size(account_value=100_000, entry=100.0, stop_loss=99.0)
        assert size_large > size_small

    def test_zero_entry_returns_zero(self):
        size = calculate_position_size(account_value=100_000, entry=0.0, stop_loss=0.0)
        assert size == 0
