import pytest
from src.core.risk import calculate_stop_loss, calculate_take_profit, calculate_position_size
from src.models import FVGResult
from tests.conftest import make_candle


def _make_fvg(gap_low, gap_high, gap_size=None):
    return FVGResult(
        direction="BULLISH_FVG_BREAK_HIGH",
        gap_high=gap_high,
        gap_low=gap_low,
        gap_size=gap_size if gap_size is not None else round(gap_high - gap_low, 4),
        body_ratio=2.0,
    )


class TestCalculateStopLoss:
    def test_long_stop_below_fvg_gap(self):
        candle = make_candle(99, 100.0, 98.0, 99.5)
        fvg = _make_fvg(gap_low=100.2, gap_high=100.9)
        stop, stop_type = calculate_stop_loss("LONG", candle, fvg)
        assert stop == round(100.2 - 0.02, 2)
        assert "Option A" in stop_type

    def test_long_stop_always_fvg_regardless_of_gap_size(self):
        # Even a tiny gap uses Option A — no threshold fallback
        candle = make_candle(99, 100.0, 98.0, 99.5)
        fvg = _make_fvg(gap_low=100.2, gap_high=100.25, gap_size=0.05)
        stop, stop_type = calculate_stop_loss("LONG", candle, fvg)
        assert stop == round(100.2 - 0.02, 2)
        assert "Option A" in stop_type

    def test_short_stop_above_fvg_gap(self):
        candle = make_candle(97, 97.5, 95.5, 96.5)
        fvg = FVGResult(
            direction="BEARISH_FVG_BREAK_LOW",
            gap_high=96.8, gap_low=95.4, gap_size=1.4, body_ratio=2.0,
        )
        stop, stop_type = calculate_stop_loss("SHORT", candle, fvg)
        assert stop == round(96.8 + 0.02, 2)
        assert "Option A" in stop_type

    def test_short_stop_always_fvg_regardless_of_gap_size(self):
        # Even a tiny gap uses Option A — no threshold fallback
        candle = make_candle(97, 97.5, 95.5, 96.5)
        fvg = FVGResult(
            direction="BEARISH_FVG_BREAK_LOW",
            gap_high=96.8, gap_low=96.75, gap_size=0.05, body_ratio=2.0,
        )
        stop, stop_type = calculate_stop_loss("SHORT", candle, fvg)
        assert stop == round(96.8 + 0.02, 2)
        assert "Option A" in stop_type

    def test_stop_type_label_is_option_a(self):
        candle = make_candle(100, 100, 100, 100)
        fvg = _make_fvg(gap_low=100.2, gap_high=100.5)
        _, stop_type = calculate_stop_loss("LONG", candle, fvg)
        assert stop_type == "Option A (FVG-based)"


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
