import pytest
from unittest.mock import patch
from src.reporting.telegram import TelegramReporter, LOG_OFF, LOG_DEBUG, LOG_INFO, LOG_ERROR


def _reporter():
    return TelegramReporter()


class TestLogLevel:
    def test_default_level_is_info(self):
        assert _reporter().get_level() == LOG_INFO

    def test_set_level_stores_value(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        assert r.get_level() == LOG_DEBUG

    def test_set_level_clamps_below_zero(self):
        r = _reporter()
        r.set_level(-1)
        assert r.get_level() == LOG_OFF

    def test_set_level_clamps_above_three(self):
        r = _reporter()
        r.set_level(99)
        assert r.get_level() == LOG_ERROR

    def test_get_level_label_off(self):
        r = _reporter()
        r.set_level(LOG_OFF)
        assert r.get_level_label() == "OFF"

    def test_get_level_label_debug(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        assert r.get_level_label() == "DEBUG"

    def test_get_level_label_info(self):
        r = _reporter()
        r.set_level(LOG_INFO)
        assert r.get_level_label() == "INFO"

    def test_get_level_label_errors_only(self):
        r = _reporter()
        r.set_level(LOG_ERROR)
        assert r.get_level_label() == "ERRORS ONLY"


class TestLog:
    def _send_calls(self, reporter, msg, msg_level):
        with patch("src.reporting.telegram._send") as mock_send:
            reporter.log(msg, msg_level)
            return mock_send.call_count

    def test_level_off_never_sends(self):
        r = _reporter()
        r.set_level(LOG_OFF)
        for lvl in (LOG_DEBUG, LOG_INFO, LOG_ERROR):
            assert self._send_calls(r, "msg", lvl) == 0

    def test_debug_level_sends_debug_messages(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        assert self._send_calls(r, "msg", LOG_DEBUG) == 1

    def test_debug_level_sends_info_messages(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        assert self._send_calls(r, "msg", LOG_INFO) == 1

    def test_debug_level_sends_error_messages(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        assert self._send_calls(r, "msg", LOG_ERROR) == 1

    def test_info_level_skips_debug_messages(self):
        r = _reporter()
        r.set_level(LOG_INFO)
        assert self._send_calls(r, "msg", LOG_DEBUG) == 0

    def test_info_level_sends_info_messages(self):
        r = _reporter()
        r.set_level(LOG_INFO)
        assert self._send_calls(r, "msg", LOG_INFO) == 1

    def test_info_level_sends_error_messages(self):
        r = _reporter()
        r.set_level(LOG_INFO)
        assert self._send_calls(r, "msg", LOG_ERROR) == 1

    def test_error_level_skips_debug_messages(self):
        r = _reporter()
        r.set_level(LOG_ERROR)
        assert self._send_calls(r, "msg", LOG_DEBUG) == 0

    def test_error_level_skips_info_messages(self):
        r = _reporter()
        r.set_level(LOG_ERROR)
        assert self._send_calls(r, "msg", LOG_INFO) == 0

    def test_error_level_sends_error_messages(self):
        r = _reporter()
        r.set_level(LOG_ERROR)
        assert self._send_calls(r, "msg", LOG_ERROR) == 1

    def test_message_includes_prefix(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log("hello", LOG_INFO)
            sent_text = mock_send.call_args[0][0]
        assert "🔵" in sent_text
        assert "hello" in sent_text

    def test_log_debug_uses_debug_level(self):
        r = _reporter()
        r.set_level(LOG_DEBUG)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log_debug("dbg")
            assert mock_send.call_count == 1
        r.set_level(LOG_INFO)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log_debug("dbg")
            assert mock_send.call_count == 0

    def test_log_info_uses_info_level(self):
        r = _reporter()
        r.set_level(LOG_INFO)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log_info("info")
            assert mock_send.call_count == 1
        r.set_level(LOG_ERROR)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log_info("info")
            assert mock_send.call_count == 0

    def test_log_error_uses_error_level(self):
        r = _reporter()
        r.set_level(LOG_ERROR)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log_error("err")
            assert mock_send.call_count == 1
        r.set_level(LOG_OFF)
        with patch("src.reporting.telegram._send") as mock_send:
            r.log_error("err")
            assert mock_send.call_count == 0
