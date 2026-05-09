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
