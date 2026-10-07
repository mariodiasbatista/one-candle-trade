"""
Tests for main.py job functions covering the 4 recent changes:
1. Signal spam fix — _signals_fired populated before execute_signal
2. EOD cleanup job — monitor_open_positions called after force close window
3. Force close job — delegates to investor.force_close_all
4. Option A SL — verified via risk module (covered in test_risk.py)
"""
import pytest
from unittest.mock import MagicMock, patch, call
import main as m


@pytest.fixture(autouse=True)
def reset_globals():
    """Reset main.py global state before each test."""
    original_fired = m._signals_fired.copy()
    original_active = m._monitoring_active
    yield
    m._signals_fired = original_fired
    m._monitoring_active = original_active


# ── job_monitor_fvg — signal spam fix ─────────────────────────────────────────

class TestJobMonitorFvgSignalSpam:
    def _make_ctx(self, trade_allowed=True, has_signal=True):
        ctx = MagicMock()
        ctx.trade_allowed = trade_allowed
        ctx.fvg = MagicMock(direction="BULLISH_FVG_BREAK_HIGH") if has_signal else None
        ctx.volume_ratio = 2.0
        return ctx

    def test_symbol_added_to_fired_before_execute_signal(self):
        """_signals_fired must be populated even if execute_signal returns None."""
        m._monitoring_active = True
        ctx = self._make_ctx()
        signal = MagicMock()

        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "get_contexts", return_value={"SPY": ctx}), \
             patch.object(m.retriever, "update_1min_candles", return_value={"SPY": ctx}), \
             patch.object(m.analyst, "analyze", return_value=signal), \
             patch.object(m.investor, "execute_signal", return_value=None) as mock_exec:

            mock_dt.now.return_value.replace.return_value = MagicMock()
            mock_dt.now.return_value.__gt__ = lambda s, o: False
            mock_dt.now.return_value.strftime.return_value = "09:45"

            m.job_monitor_fvg()

        assert "SPY" in m._signals_fired
        mock_exec.assert_called_once_with(signal)

    def test_symbol_not_re_evaluated_once_fired(self):
        """If symbol already in _signals_fired, analyst.analyze must not be called."""
        m._monitoring_active = True
        m._signals_fired.add("SPY")
        ctx = self._make_ctx()

        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "get_contexts", return_value={"SPY": ctx}), \
             patch.object(m.retriever, "update_1min_candles", return_value={"SPY": ctx}), \
             patch.object(m.analyst, "analyze") as mock_analyze:

            mock_dt.now.return_value.replace.return_value = MagicMock()
            mock_dt.now.return_value.__gt__ = lambda s, o: False
            mock_dt.now.return_value.strftime.return_value = "09:45"

            m.job_monitor_fvg()

        mock_analyze.assert_not_called()

    def test_no_signal_does_not_add_to_fired(self):
        """If analyst returns None, symbol must not be added to _signals_fired."""
        m._monitoring_active = True
        ctx = self._make_ctx()

        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "get_contexts", return_value={"SPY": ctx}), \
             patch.object(m.retriever, "update_1min_candles", return_value={"SPY": ctx}), \
             patch.object(m.analyst, "analyze", return_value=None):

            mock_dt.now.return_value.replace.return_value = MagicMock()
            mock_dt.now.return_value.__gt__ = lambda s, o: False
            mock_dt.now.return_value.strftime.return_value = "09:45"

            m.job_monitor_fvg()

        assert "SPY" not in m._signals_fired

    def test_inactive_monitoring_is_noop(self):
        """If _monitoring_active is False, nothing should be called."""
        m._monitoring_active = False

        with patch.object(m.retriever, "update_1min_candles") as mock_update:
            m.job_monitor_fvg()

        mock_update.assert_not_called()


# ── job_eod_cleanup ───────────────────────────────────────────────────────────

class TestJobEodCleanup:
    def test_no_open_trades_is_noop(self):
        """If no open trades, monitor_open_positions must not be called."""
        m.investor._open_trades = {}
        with patch.object(m.investor, "monitor_open_positions") as mock_monitor:
            m.job_eod_cleanup()
        mock_monitor.assert_not_called()

    def test_calls_monitor_when_trades_open(self):
        """With open trades, monitor_open_positions must be called once."""
        m.investor._open_trades = {"SPY": {}}
        with patch.object(m.investor, "monitor_open_positions") as mock_monitor:
            m.job_eod_cleanup()
        mock_monitor.assert_called_once()

    def test_logs_warning_if_still_unconfirmed(self):
        """If trades remain after monitor, a warning should be logged."""
        m.investor._open_trades = {"SPY": {}}

        def _noop(): pass

        with patch.object(m.investor, "monitor_open_positions", side_effect=_noop), \
             patch("main.logger") as mock_logger:
            m.job_eod_cleanup()

        mock_logger.warning.assert_called_once()
        assert "SPY" in mock_logger.warning.call_args[0][0]

    def test_exception_is_caught_and_logged(self):
        """An exception in monitor_open_positions must be caught, not raised."""
        m.investor._open_trades = {"SPY": {}}
        with patch.object(m.investor, "monitor_open_positions", side_effect=Exception("boom")), \
             patch("main.logger") as mock_logger:
            m.job_eod_cleanup()  # must not raise

        mock_logger.error.assert_called_once()


# ── job_force_close ───────────────────────────────────────────────────────────

class TestJobForceClose:
    def test_no_open_trades_skips_force_close(self):
        """If no open trades, force_close_all must not be called."""
        m.investor._open_trades = {}
        with patch.object(m.investor, "force_close_all") as mock_fc:
            m.job_force_close()
        mock_fc.assert_not_called()

    def test_calls_force_close_all_when_trades_open(self):
        """With open trades, force_close_all must be called."""
        m.investor._open_trades = {"SPY": {}}
        with patch.object(m.investor, "force_close_all") as mock_fc:
            m.job_force_close()
        mock_fc.assert_called_once()

    def test_exception_is_caught_and_logged(self):
        """An exception in force_close_all must be caught, not raised."""
        m.investor._open_trades = {"SPY": {}}
        with patch.object(m.investor, "force_close_all", side_effect=Exception("API error")), \
             patch("main.logger") as mock_logger:
            m.job_force_close()  # must not raise

        mock_logger.error.assert_called_once()


class TestJobsNeverSendRealTelegram:
    """The job functions call main.py's module-level `telegram` reporter directly.

    TestJobForceClose.test_exception_is_caught_and_logged patches main.logger but
    not main.telegram, so before conftest blanked the credentials every suite run
    delivered a real "Force Close failed: API error" alert to the live chat — the
    Exception("API error") fixture reaching a real reporter. These tests pin the
    guard so a future job test that forgets to patch cannot reach the network.
    """

    def test_credentials_are_blank_in_the_test_environment(self):
        from src.reporting import telegram as tg
        assert tg.TELEGRAM_BOT_TOKEN == "", "a real token in tests can page the owner"
        assert tg.TELEGRAM_CHAT_ID == ""

    def test_force_close_failure_reaches_no_network_call(self):
        from src.reporting import telegram as tg
        m.investor._open_trades = {"SPY": {}}
        with patch.object(tg, "requests") as mock_req, \
             patch.object(m.investor, "force_close_all", side_effect=Exception("API error")), \
             patch("main.logger"):
            m.job_force_close()
        assert mock_req.post.call_count == 0, \
            "job_force_close must not post to Telegram during tests"

    def test_force_close_success_path_also_sends_nothing(self):
        from src.reporting import telegram as tg
        m.investor._open_trades = {"SPY": {}}
        with patch.object(tg, "requests") as mock_req, \
             patch.object(m.investor, "force_close_all"):
            m.job_force_close()
        assert mock_req.post.call_count == 0

    def test_system_alert_is_also_inert_in_tests(self):
        from src.reporting import telegram as tg
        with patch.object(tg, "requests") as mock_req:
            assert tg.send_system_alert("disk nearly full") is False
        assert mock_req.post.call_count == 0
