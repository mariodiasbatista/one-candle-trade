from tests.conftest import make_candle, make_flat_candles
from src.core.fvg import detect_fvg, check_volume_confirmation

KEY_HIGH = 100.0
KEY_LOW = 95.0


def _bullish_sequence():
    """
    5 tiny-body candles + A (high=100.5) + B (large body) + C (low=100.6 > A.high, high=102 > key_high=100).
    Avg body of prior 5 = 0.01. B body = 0.8 >= 1.5 * 0.01.
    """
    prior = make_flat_candles(5)
    A = make_candle(100.0, 100.5, 99.5, 100.2, minute_offset=5)
    B = make_candle(100.2, 101.5, 100.1, 101.0, volume=150_000, minute_offset=6)
    C = make_candle(101.2, 102.0, 100.6, 101.8, volume=200_000, minute_offset=7)
    return prior + [A, B, C]


def _bearish_sequence():
    """
    5 tiny-body candles + A (low=96.8) + B (large body) + C (high=95.4 < A.low, low=94.0 < key_low=95).
    """
    prior = make_flat_candles(5)
    A = make_candle(97.0, 97.5, 96.8, 96.9, minute_offset=5)
    B = make_candle(96.9, 97.0, 95.5, 95.7, volume=150_000, minute_offset=6)
    C = make_candle(95.5, 95.4, 94.0, 94.2, volume=200_000, minute_offset=7)
    return prior + [A, B, C]


class TestDetectFvg:
    def test_not_enough_candles_returns_none(self):
        assert detect_fvg(make_flat_candles(7), KEY_HIGH, KEY_LOW) is None

    def test_exactly_8_candles_processes(self):
        result = detect_fvg(_bullish_sequence(), KEY_HIGH, KEY_LOW)
        assert result is not None

    def test_bullish_fvg_detected(self):
        candles = _bullish_sequence()
        result = detect_fvg(candles, KEY_HIGH, KEY_LOW)
        assert result is not None
        assert result.direction == "BULLISH_FVG_BREAK_HIGH"

    def test_bullish_fvg_gap_values(self):
        candles = _bullish_sequence()
        result = detect_fvg(candles, KEY_HIGH, KEY_LOW)
        # gap_low = A.high = 100.5, gap_high = C.low = 100.6
        assert result.gap_low == 100.5
        assert result.gap_high == 100.6

    def test_bullish_fvg_no_high_break_returns_none(self):
        # C.high < key_high → no level break
        prior = make_flat_candles(5)
        A = make_candle(100.0, 100.5, 99.5, 100.2, minute_offset=5)
        B = make_candle(100.2, 101.5, 100.1, 101.0, minute_offset=6)
        C = make_candle(101.2, 99.5, 100.6, 99.3, minute_offset=7)  # high=99.5 < key_high=100
        result = detect_fvg(prior + [A, B, C], KEY_HIGH, KEY_LOW)
        assert result is None

    def test_bearish_fvg_detected(self):
        candles = _bearish_sequence()
        result = detect_fvg(candles, KEY_HIGH, KEY_LOW)
        assert result is not None
        assert result.direction == "BEARISH_FVG_BREAK_LOW"

    def test_bearish_fvg_gap_values(self):
        candles = _bearish_sequence()
        result = detect_fvg(candles, KEY_HIGH, KEY_LOW)
        # gap_high = A.low = 96.8, gap_low = C.high = 95.4
        assert result.gap_high == 96.8
        assert result.gap_low == 95.4

    def test_bearish_fvg_no_low_break_returns_none(self):
        # C.low > key_low → no level break
        prior = make_flat_candles(5)
        A = make_candle(97.0, 97.5, 96.8, 96.9, minute_offset=5)
        B = make_candle(96.9, 97.0, 95.5, 95.7, minute_offset=6)
        C = make_candle(95.5, 95.4, 95.5, 95.3, minute_offset=7)  # low=95.5 > key_low=95
        result = detect_fvg(prior + [A, B, C], KEY_HIGH, KEY_LOW)
        assert result is None

    def test_small_impulse_body_returns_none(self):
        # Prior candles have large bodies → avg_body is large → B fails threshold
        large_body_prior = [
            make_candle(100.0, 101.5, 98.5, 101.0, minute_offset=i) for i in range(5)
        ]  # body = 1.0 each → avg = 1.0
        A = make_candle(101.0, 101.5, 100.5, 101.2, minute_offset=5)
        B = make_candle(101.2, 101.5, 101.0, 101.1, minute_offset=6)  # body=0.1 < 1.5*1.0
        C = make_candle(101.3, 102.0, 101.6, 101.8, minute_offset=7)
        result = detect_fvg(large_body_prior + [A, B, C], KEY_HIGH, KEY_LOW)
        assert result is None

    def test_body_ratio_computed_correctly(self):
        candles = _bullish_sequence()
        result = detect_fvg(candles, KEY_HIGH, KEY_LOW)
        # B.body = abs(101.0 - 100.2) = 0.8, avg = 0.01 → ratio = 80.0
        assert result.body_ratio == round(0.8 / 0.01, 2)

    def test_no_gap_between_a_and_c_returns_none(self):
        prior = make_flat_candles(5)
        A = make_candle(100.0, 100.5, 99.5, 100.0, minute_offset=5)
        B = make_candle(100.0, 101.5, 99.9, 101.0, minute_offset=6)
        # C.low=100.3 < A.high=100.5 → no bullish gap; C.high=101.5 > A.low=99.5 → no bearish gap
        C = make_candle(101.0, 101.5, 100.3, 101.0, minute_offset=7)
        result = detect_fvg(prior + [A, B, C], KEY_HIGH, KEY_LOW)
        assert result is None


class TestCheckVolumeConfirmation:
    def test_not_enough_candles(self):
        confirmed, ratio = check_volume_confirmation(make_flat_candles(5))
        assert confirmed is False
        assert ratio == 0.0

    def test_volume_above_threshold(self):
        prior = make_flat_candles(5, volume=100_000)
        # C volume = 200_000 → ratio = 2.0 >= 1.5
        C = make_candle(101.0, 102.0, 100.5, 101.5, volume=200_000, minute_offset=5)
        confirmed, ratio = check_volume_confirmation(prior + [C])
        assert confirmed is True
        assert ratio == 2.0

    def test_volume_below_threshold(self):
        prior = make_flat_candles(5, volume=100_000)
        # C volume = 100_000 → ratio = 1.0 < 1.5
        C = make_candle(101.0, 102.0, 100.5, 101.5, volume=100_000, minute_offset=5)
        confirmed, ratio = check_volume_confirmation(prior + [C])
        assert confirmed is False
        assert ratio == 1.0

    def test_zero_avg_volume_returns_false(self):
        prior = make_flat_candles(5, volume=0)
        C = make_candle(101.0, 102.0, 100.5, 101.5, volume=50_000, minute_offset=5)
        confirmed, ratio = check_volume_confirmation(prior + [C])
        assert confirmed is False
        assert ratio == 0.0

    def test_exactly_at_threshold(self):
        prior = make_flat_candles(5, volume=100_000)
        # ratio = 1.5 exactly → should pass (>=)
        C = make_candle(101.0, 102.0, 100.5, 101.5, volume=150_000, minute_offset=5)
        confirmed, ratio = check_volume_confirmation(prior + [C])
        assert confirmed is True
        assert ratio == 1.5
