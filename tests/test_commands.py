import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytz

ET = pytz.timezone("America/New_York")


def _make_update():
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    return update


def _et(day_offset=0, hour=10, minute=0):
    """Return a Monday+offset ET datetime at the given time."""
    return ET.localize(datetime(2026, 5, 11 + day_offset, hour, minute, 0))


def _run(coro):
    return asyncio.run(coro)


class TestCmdSchedule:
    def test_weekend_returns_no_jobs_message(self):
        import main as m
        update = _make_update()
        saturday = ET.localize(datetime(2026, 5, 9, 10, 0))
        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "_watchlist", ["SPY"]):
            mock_dt.now.return_value = saturday
            _run(m.cmd_schedule(update, MagicMock()))
        text = update.message.reply_text.call_args[0][0]
        assert "weekend" in text.lower()
        assert "✅" not in text
        assert "⬜" not in text

    def test_weekday_before_all_jobs_shows_all_pending(self):
        import main as m
        update = _make_update()
        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "_watchlist", ["TSLA"]):
            mock_dt.now.return_value = _et(hour=8, minute=0)
            _run(m.cmd_schedule(update, MagicMock()))
        text = update.message.reply_text.call_args[0][0]
        assert text.count("✅") == 0
        assert "TSLA" in text

    def test_weekday_after_premarket_shows_done(self):
        import main as m
        update = _make_update()
        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "_watchlist", ["TSLA"]):
            mock_dt.now.return_value = _et(hour=9, minute=30)
            _run(m.cmd_schedule(update, MagicMock()))
        text = update.message.reply_text.call_args[0][0]
        assert "✅" in text

    def test_fvg_monitor_shows_running_during_window(self):
        import main as m
        update = _make_update()
        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "_watchlist", ["TSLA"]):
            mock_dt.now.return_value = _et(hour=10, minute=0)
            _run(m.cmd_schedule(update, MagicMock()))
        text = update.message.reply_text.call_args[0][0]
        assert "🔄" in text

    def test_fvg_monitor_shows_done_after_cutoff(self):
        import main as m
        update = _make_update()
        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "_watchlist", ["TSLA"]):
            mock_dt.now.return_value = _et(hour=11, minute=0)
            _run(m.cmd_schedule(update, MagicMock()))
        text = update.message.reply_text.call_args[0][0]
        assert "🔄" not in text

    def test_watchlist_shown_in_output(self):
        import main as m
        update = _make_update()
        with patch("main.datetime") as mock_dt, \
             patch.object(m.retriever, "_watchlist", ["META", "AVGO"]):
            mock_dt.now.return_value = _et(hour=10, minute=0)
            _run(m.cmd_schedule(update, MagicMock()))
        text = update.message.reply_text.call_args[0][0]
        assert "META" in text
        assert "AVGO" in text


class TestTelegramErrorHandler:
    """Without a registered error handler, python-telegram-bot dumps a ~28-line
    traceback per failure. A duplicate bot instance produced 79k Conflict errors
    (~2.2M log lines) and filled the disk, so each error must stay on one line."""

    def _ctx(self, err):
        ctx = MagicMock()
        ctx.error = err
        return ctx

    def test_conflict_logged_as_single_line_naming_duplicate_process(self):
        import main as m
        from telegram import error as tg_error
        with patch.object(m.logger, "error") as mock_error:
            _run(m.on_telegram_error(None, self._ctx(tg_error.Conflict("terminated by other getUpdates"))))
        assert mock_error.call_count == 1
        msg = mock_error.call_args[0][0]
        assert "\n" not in msg, "Conflict must not log a multi-line traceback"
        assert "another bot instance" in msg

    def test_transient_error_logged_as_warning_not_error(self):
        import main as m
        from telegram import error as tg_error
        with patch.object(m.logger, "warning") as mock_warn, \
             patch.object(m.logger, "error") as mock_error:
            _run(m.on_telegram_error(None, self._ctx(tg_error.NetworkError("read timeout"))))
        assert mock_error.call_count == 0
        assert mock_warn.call_count == 1
        msg = mock_warn.call_args[0][0]
        assert "\n" not in msg
        assert "NetworkError" in msg

    def test_handler_is_registered_on_the_application(self):
        import main as m
        app = m.build_telegram_app()
        assert m.on_telegram_error in app.error_handlers, \
            "error handler must be registered or PTB logs full tracebacks"

    def test_noisy_third_party_loggers_are_muted(self):
        import logging
        import main  # noqa: F401  — import applies the level configuration
        # httpx at INFO logs every Telegram poll (~8.6k lines/day) and embeds
        # the bot token in the logged URL.
        for name in ("httpx", "httpcore", "telegram.ext.Application"):
            assert logging.getLogger(name).level >= logging.WARNING, \
                f"{name} must be muted to WARNING or higher"

    def test_our_own_loggers_are_not_muted(self):
        import logging
        import main  # noqa: F401
        # Asserting the *effective* level here would test the harness, not the
        # code: under pytest the root logger is already configured, so
        # basicConfig() no-ops and the inherited level is pytest's, not ours.
        # What this module controls is which loggers it explicitly mutes, so
        # assert our own are left untouched (NOTSET = inherit from root).
        for name in ("src.agents.investor", "src.agents.analyst", "__main__"):
            assert logging.getLogger(name).level == logging.NOTSET, \
                f"{name} must inherit the root level, not be muted"
