"""Guards against a second bot instance placing duplicate orders.

A duplicate main.py ran 2026-05-07 to 07-30 and submitted 39 doubled orders at
identical entry prices. The extra legs averaged -$32.57 against -$0.42 for the
legitimate ones — roughly 90% of every loss the strategy has taken. Neither
existing guard could catch it: `_signals_fired` and `_open_trades` are both
per-process memory, so a second copy starts with a clean slate.
"""
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


class TestInstanceLock:
    def _lock_path(self):
        fd, path = tempfile.mkstemp(suffix=".lock")
        os.close(fd)
        return path

    def test_first_caller_acquires(self):
        import main as m
        path = self._lock_path()
        fh = m.acquire_instance_lock(path)
        assert fh is not None
        fh.close()

    def test_second_caller_is_refused_while_first_holds(self):
        import main as m
        path = self._lock_path()
        first = m.acquire_instance_lock(path)
        assert first is not None
        # This is the zombie scenario: a second process starting up.
        assert m.acquire_instance_lock(path) is None, \
            "a second instance must not be able to start"
        first.close()

    def test_lock_is_reusable_once_released(self):
        import main as m
        path = self._lock_path()
        first = m.acquire_instance_lock(path)
        first.close()  # simulates the first process exiting
        second = m.acquire_instance_lock(path)
        assert second is not None, "a restart after a clean exit must succeed"
        second.close()

    def test_fails_closed_when_lock_path_unwritable(self):
        import main as m
        # Never trade unguarded: an unusable lock path must refuse, not proceed.
        assert m.acquire_instance_lock("/nonexistent-dir/x.lock") is None


class TestExecuteSignalDuplicateGuard:
    def _investor(self):
        from src.agents.investor import Investor
        with patch("src.agents.investor.TradingClient"):
            return Investor(MagicMock())

    def _signal(self):
        sig = MagicMock()
        sig.symbol, sig.date, sig.signal = "NVDA", "2026-09-14", "LONG"
        sig.entry, sig.stop_loss, sig.take_profit = 100.0, 99.0, 102.0
        return sig

    def test_blocks_when_db_already_has_a_trade_today(self):
        inv = self._investor()
        existing = MagicMock(result="PENDING", id="abc")
        with patch("src.agents.investor.get_trades_for_date", return_value=[existing]) as g, \
             patch.object(inv, "get_account_value", return_value=100_000.0):
            assert inv.execute_signal(self._signal()) is None
        g.assert_called_once()
        # The order must never reach Alpaca.
        assert inv._client.submit_order.call_count == 0

    def test_skip_rows_do_not_block_a_real_trade(self):
        inv = self._investor()
        skipped = MagicMock(result="SKIP", id="s1")
        with patch("src.agents.investor.get_trades_for_date", return_value=[skipped]), \
             patch("src.agents.investor.calculate_position_size", return_value=10), \
             patch("src.agents.investor.save_trade_signal", return_value="t1"), \
             patch.object(inv, "get_account_value", return_value=100_000.0):
            inv.execute_signal(self._signal())
        assert inv._client.submit_order.call_count == 1, \
            "a prior SKIP means no position was taken, so it must not block"

    def test_allows_the_first_trade_of_the_day(self):
        inv = self._investor()
        with patch("src.agents.investor.get_trades_for_date", return_value=[]), \
             patch("src.agents.investor.calculate_position_size", return_value=10), \
             patch("src.agents.investor.save_trade_signal", return_value="t1"), \
             patch.object(inv, "get_account_value", return_value=100_000.0):
            inv.execute_signal(self._signal())
        assert inv._client.submit_order.call_count == 1

    def test_duplicate_block_alerts_telegram(self):
        inv = self._investor()
        existing = MagicMock(result="WIN", id="abc")
        with patch("src.agents.investor.get_trades_for_date", return_value=[existing]), \
             patch.object(inv, "get_account_value", return_value=100_000.0):
            inv.execute_signal(self._signal())
        assert inv._telegram.log_error.call_count == 1, \
            "a blocked duplicate means a second instance may be live — say so"


class TestLockFilePidIsPreserved:
    """A refused instance must not blank the pid of the holder.

    Opening the lock with "w" truncates *before* flock is attempted, so a second
    instance being correctly refused would still wipe the recorded pid — losing
    the one diagnostic that identifies the live instance.
    """

    def _lock_path(self):
        import os, tempfile
        fd, path = tempfile.mkstemp(suffix=".lock")
        os.close(fd)
        return path

    def test_holder_pid_is_written(self):
        import main as m, os
        path = self._lock_path()
        fh = m.acquire_instance_lock(path)
        assert m.read_instance_lock_pid(path) == str(os.getpid())
        fh.close()

    def test_refused_attempt_does_not_wipe_holder_pid(self):
        import main as m, os
        path = self._lock_path()
        fh = m.acquire_instance_lock(path)
        assert m.acquire_instance_lock(path) is None   # the refused attempt
        assert m.read_instance_lock_pid(path) == str(os.getpid()), \
            "a refused instance must leave the holder's pid intact"
        fh.close()

    def test_stale_pid_is_replaced_on_reacquire(self):
        import main as m, os
        path = self._lock_path()
        with open(path, "w") as f:
            f.write("999999")            # pid from a previous, dead instance
        fh = m.acquire_instance_lock(path)
        assert m.read_instance_lock_pid(path) == str(os.getpid())
        fh.close()
