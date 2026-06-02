import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.agents.investor import Investor
from src.models import TradeSignal
from alpaca.trading.enums import OrderStatus, OrderSide


def _make_signal(symbol="SPY", direction="LONG"):
    return TradeSignal(
        symbol=symbol, date="2026-05-07", signal=direction,
        entry=500.0, stop_loss=498.0, take_profit=504.0,
        risk=2.0, reward=4.0, stop_type="Option B (First Candle)",
        fvg_body_ratio=2.0, volume_ratio=1.8, filters_passed=[],
    )


def _make_investor():
    with patch("src.agents.investor.TradingClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_telegram = MagicMock()
        investor = Investor(mock_telegram)
        return investor, mock_client, mock_telegram


class TestGetAccountValue:
    def test_returns_portfolio_value(self):
        investor, client, _ = _make_investor()
        mock_account = MagicMock()
        mock_account.portfolio_value = "100000.00"
        client.get_account.return_value = mock_account
        assert investor.get_account_value() == 100000.0


class TestExecuteSignal:
    def test_success_long_returns_trade_id(self):
        investor, client, telegram = _make_investor()
        mock_account = MagicMock()
        mock_account.portfolio_value = "100000"
        client.get_account.return_value = mock_account
        mock_order = MagicMock()
        mock_order.id = "order-xyz"
        client.submit_order.return_value = mock_order

        with patch("src.agents.investor.save_trade_signal", return_value="trade-abc") as mock_save, \
             patch("src.agents.investor.calculate_position_size", return_value=10):
            trade_id = investor.execute_signal(_make_signal())

        assert trade_id == "trade-abc"
        client.submit_order.assert_called_once()
        telegram.send_entry_alert.assert_called_once()
        mock_save.assert_called_once()

    def test_success_short_submits_sell_order(self):
        investor, client, _ = _make_investor()
        mock_account = MagicMock()
        mock_account.portfolio_value = "100000"
        client.get_account.return_value = mock_account
        mock_order = MagicMock()
        mock_order.id = "order-short"
        client.submit_order.return_value = mock_order

        with patch("src.agents.investor.save_trade_signal", return_value="trade-short"), \
             patch("src.agents.investor.calculate_position_size", return_value=5):
            trade_id = investor.execute_signal(_make_signal(direction="SHORT"))

        assert trade_id == "trade-short"
        call_kwargs = client.submit_order.call_args[0][0]
        from alpaca.trading.enums import OrderSide
        assert call_kwargs.side == OrderSide.SELL

    def test_duplicate_symbol_returns_none(self):
        investor, client, _ = _make_investor()
        investor._open_trades["SPY"] = {"trade_id": "existing", "order_id": "o1", "signal": None, "qty": 5}
        result = investor.execute_signal(_make_signal())
        assert result is None
        client.submit_order.assert_not_called()

    def test_zero_position_size_returns_none(self):
        investor, client, _ = _make_investor()
        mock_account = MagicMock()
        mock_account.portfolio_value = "100000"
        client.get_account.return_value = mock_account

        with patch("src.agents.investor.calculate_position_size", return_value=0):
            result = investor.execute_signal(_make_signal())

        assert result is None
        client.submit_order.assert_not_called()

    def test_alpaca_exception_returns_none(self):
        investor, client, _ = _make_investor()
        mock_account = MagicMock()
        mock_account.portfolio_value = "100000"
        client.get_account.return_value = mock_account
        client.submit_order.side_effect = Exception("API error")

        with patch("src.agents.investor.calculate_position_size", return_value=10):
            result = investor.execute_signal(_make_signal())

        assert result is None


class TestMonitorOpenPositions:
    def _no_position(self, client):
        """Position gone from Alpaca — bracket TP/SL fired."""
        client.get_all_positions.return_value = []

    def _position_open(self, client, symbol="SPY"):
        """Position still open on Alpaca."""
        mock_pos = MagicMock()
        mock_pos.symbol = symbol
        client.get_all_positions.return_value = [mock_pos]

    def _closed_order(self, client, fill_price: str, direction: str = "LONG"):
        """Simulate _find_exit_price finding a filled order."""
        from alpaca.trading.enums import OrderSide
        mock_order = MagicMock()
        mock_order.status = OrderStatus.FILLED
        mock_order.filled_avg_price = fill_price
        mock_order.side = OrderSide.SELL if direction == "LONG" else OrderSide.BUY
        client.get_orders.return_value = [mock_order]

    def test_position_gone_closes_win(self):
        investor, client, telegram = _make_investor()
        signal = _make_signal()  # TP=504, SL=498
        investor._open_trades["SPY"] = {"trade_id": "t1", "order_id": "o1", "signal": signal, "qty": 10}
        self._no_position(client)
        self._closed_order(client, "505.0")  # above TP → WIN

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        mock_close.assert_called_once()
        assert mock_close.call_args[0][2] == "WIN"
        assert "SPY" not in investor._open_trades

    def test_position_gone_closes_loss(self):
        investor, client, telegram = _make_investor()
        signal = _make_signal()  # SL=498
        investor._open_trades["SPY"] = {"trade_id": "t2", "order_id": "o2", "signal": signal, "qty": 10}
        self._no_position(client)
        self._closed_order(client, "497.0")  # below SL → LOSS

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        assert mock_close.call_args[0][2] == "LOSS"

    def test_position_still_open_is_not_closed(self):
        # Position still on Alpaca and entry order is not cancelled → no close
        investor, client, _ = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t3", "order_id": "o3", "signal": signal, "qty": 10}
        self._position_open(client)
        mock_order = MagicMock()
        mock_order.status = OrderStatus.FILLED  # entry filled, position still live
        client.get_order_by_id.return_value = mock_order

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        mock_close.assert_not_called()
        assert "SPY" in investor._open_trades

    def test_cancelled_entry_order_recorded(self):
        investor, client, _ = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t4", "order_id": "o4", "signal": signal, "qty": 10}
        self._position_open(client)
        mock_order = MagicMock()
        mock_order.status = OrderStatus.CANCELED
        client.get_order_by_id.return_value = mock_order

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        mock_close.assert_called_once()
        assert "SPY" not in investor._open_trades

    def test_exception_during_monitor_continues(self):
        investor, client, _ = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t5", "order_id": "o5", "signal": signal, "qty": 10}
        client.get_all_positions.side_effect = Exception("Network error")

        investor.monitor_open_positions()  # should not raise
        assert "SPY" in investor._open_trades  # not removed on exception

    def test_no_exit_price_falls_back_to_entry(self):
        # Position gone but get_orders returns nothing → fallback to signal.entry
        investor, client, _ = _make_investor()
        signal = _make_signal()  # entry=500.0
        investor._open_trades["SPY"] = {"trade_id": "t6", "order_id": "o6", "signal": signal, "qty": 10}
        client.get_all_positions.return_value = []
        client.get_orders.return_value = []  # no closed orders found

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        args = mock_close.call_args[0]
        assert args[1] == 500.0  # falls back to signal.entry


class TestForceCloseAll:
    def test_position_confirmed_closed_updates_db(self):
        """close_all_positions is called; DB updated only after position disappears from Alpaca."""
        investor, client, telegram = _make_investor()
        signal = _make_signal()  # entry=500.0
        investor._open_trades["SPY"] = {"trade_id": "t6", "order_id": "o6", "signal": signal, "qty": 10}

        # First poll: still open. Second poll: gone.
        client.get_all_positions.side_effect = [
            [MagicMock(symbol="SPY")],  # still open on first check
            [],                          # gone on second check
        ]
        client.get_orders.return_value = []  # _find_exit_price falls back to entry

        with patch("src.agents.investor.close_trade") as mock_close, \
             patch("src.agents.investor.time.sleep"):
            investor.force_close_all()

        client.close_all_positions.assert_called_once_with(cancel_orders=True)
        mock_close.assert_called_once()
        assert "SPY" not in investor._open_trades

    def test_position_not_closed_stays_in_open_trades(self):
        """If position never disappears after polling, leave in _open_trades (no orphan DB record)."""
        investor, client, telegram = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t7", "order_id": "o7", "signal": signal, "qty": 10}

        # Position never disappears during polling
        client.get_all_positions.return_value = [MagicMock(symbol="SPY")]

        with patch("src.agents.investor.close_trade") as mock_close, \
             patch("src.agents.investor.time.sleep"):
            investor.force_close_all()

        mock_close.assert_not_called()
        assert "SPY" in investor._open_trades  # stays for crash recovery
        telegram.log_error.assert_called()

    def test_empty_open_trades_is_noop(self):
        investor, client, _ = _make_investor()
        with patch("src.agents.investor.time.sleep"):
            investor.force_close_all()
        client.close_all_positions.assert_not_called()

    def test_close_all_positions_failure_does_not_update_db(self):
        investor, client, telegram = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t8", "order_id": "o8", "signal": signal, "qty": 10}
        client.close_all_positions.side_effect = Exception("API error")

        with patch("src.agents.investor.close_trade") as mock_close, \
             patch("src.agents.investor.time.sleep"):
            investor.force_close_all()

        mock_close.assert_not_called()
        telegram.log_error.assert_called()

    def test_get_positions_error_during_poll_assumes_still_open(self):
        """If get_all_positions fails during polling, assume still open and keep trying."""
        investor, client, telegram = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t9", "order_id": "o9", "signal": signal, "qty": 10}

        # First call (close_all_positions itself succeeds), but poll raises
        client.get_all_positions.side_effect = Exception("connection error")

        with patch("src.agents.investor.close_trade") as mock_close, \
             patch("src.agents.investor.time.sleep"):
            investor.force_close_all()

        mock_close.assert_not_called()
        assert "SPY" in investor._open_trades


class TestRecordSkip:
    def test_record_skip_saves_and_notifies(self):
        investor, _, telegram = _make_investor()
        with patch("src.agents.investor.save_skip") as mock_save:
            investor.record_skip("SPY", "2026-05-07", "Gap too large")
        mock_save.assert_called_once_with("SPY", "2026-05-07", "Gap too large")
        telegram.send_skip_notice.assert_called_once_with("SPY", "Gap too large")


class TestMonitorExceptionPerSymbol:
    def test_per_symbol_exception_sends_telegram_error(self):
        """An exception processing one symbol should not crash the whole monitor run."""
        investor, client, telegram = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t10", "order_id": "o10", "signal": signal, "qty": 10}

        # Position is gone but close_trade raises — should log error, not crash
        client.get_all_positions.return_value = []
        client.get_orders.return_value = []  # fallback to entry price

        with patch("src.agents.investor.close_trade", side_effect=Exception("DB error")):
            investor.monitor_open_positions()  # should not raise

        telegram.log_error.assert_called()


class TestFindExitPriceSideFilter:
    def test_long_ignores_buy_side_fill(self):
        """A buy-side fill (entry) must not be returned as exit price for a LONG."""
        investor, client, _ = _make_investor()
        buy_order = MagicMock()
        buy_order.status = OrderStatus.FILLED
        buy_order.filled_avg_price = "500.0"
        buy_order.side = OrderSide.BUY
        client.get_orders.return_value = [buy_order]

        price = investor._find_exit_price("SPY", fallback=123.0, direction="LONG")
        assert price == 123.0  # buy fill ignored, falls back

    def test_long_returns_sell_side_fill(self):
        """A sell-side fill must be returned as exit price for a LONG."""
        investor, client, _ = _make_investor()
        sell_order = MagicMock()
        sell_order.status = OrderStatus.FILLED
        sell_order.filled_avg_price = "510.0"
        sell_order.side = OrderSide.SELL
        client.get_orders.return_value = [sell_order]

        price = investor._find_exit_price("SPY", fallback=123.0, direction="LONG")
        assert price == 510.0

    def test_short_ignores_sell_side_fill(self):
        """A sell-side fill (entry) must not be returned as exit price for a SHORT."""
        investor, client, _ = _make_investor()
        sell_order = MagicMock()
        sell_order.status = OrderStatus.FILLED
        sell_order.filled_avg_price = "500.0"
        sell_order.side = OrderSide.SELL
        client.get_orders.return_value = [sell_order]

        price = investor._find_exit_price("SPY", fallback=123.0, direction="SHORT")
        assert price == 123.0  # sell fill ignored, falls back

    def test_short_returns_buy_side_fill(self):
        """A buy-side fill (cover) must be returned as exit price for a SHORT."""
        investor, client, _ = _make_investor()
        buy_order = MagicMock()
        buy_order.status = OrderStatus.FILLED
        buy_order.filled_avg_price = "490.0"
        buy_order.side = OrderSide.BUY
        client.get_orders.return_value = [buy_order]

        price = investor._find_exit_price("SPY", fallback=123.0, direction="SHORT")
        assert price == 490.0

    def test_skips_unfilled_orders(self):
        """Orders that are not FILLED must be skipped regardless of side."""
        investor, client, _ = _make_investor()
        canceled_order = MagicMock()
        canceled_order.status = OrderStatus.CANCELED
        canceled_order.filled_avg_price = "500.0"
        canceled_order.side = OrderSide.SELL
        client.get_orders.return_value = [canceled_order]

        price = investor._find_exit_price("SPY", fallback=999.0, direction="LONG")
        assert price == 999.0


class TestDetermineResult:
    def test_long_at_take_profit_is_win(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()  # entry=500, SL=498, TP=504
        assert investor._determine_result(signal, 504.0) == "WIN"
        assert investor._determine_result(signal, 505.0) == "WIN"

    def test_long_at_stop_loss_is_loss(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()  # SL=498
        assert investor._determine_result(signal, 498.0) == "LOSS"
        assert investor._determine_result(signal, 497.0) == "LOSS"

    def test_long_between_sl_and_tp_is_forced_close(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()  # SL=498, TP=504
        # exit at 501 — above SL, below TP → FORCED_CLOSE (may have positive P&L)
        assert investor._determine_result(signal, 501.0) == "FORCED_CLOSE"

    def test_long_forced_close_with_profit(self):
        # real case: AVGO entry=433.18, exit=434.17, SL=416.20, TP=467.14
        investor, _, _ = _make_investor()
        signal = _make_signal()
        signal.entry = 433.18
        signal.stop_loss = 416.20
        signal.take_profit = 467.14
        assert investor._determine_result(signal, 434.17) == "FORCED_CLOSE"

    def test_short_at_take_profit_is_win(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        signal.take_profit = 496.0
        signal.stop_loss = 502.0
        assert investor._determine_result(signal, 496.0) == "WIN"
        assert investor._determine_result(signal, 495.0) == "WIN"

    def test_short_at_stop_loss_is_loss(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        signal.take_profit = 496.0
        signal.stop_loss = 502.0
        assert investor._determine_result(signal, 502.0) == "LOSS"
        assert investor._determine_result(signal, 503.0) == "LOSS"

    def test_short_between_sl_and_tp_is_forced_close(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        signal.take_profit = 496.0
        signal.stop_loss = 502.0
        assert investor._determine_result(signal, 499.0) == "FORCED_CLOSE"

    def test_short_near_sl_slippage_is_loss(self):
        # Real case: AMZN SHORT SL=272.29, fill=272.27 (2¢ slippage) → should be LOSS not FORCED_CLOSE
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        signal.take_profit = 261.67
        signal.stop_loss = 272.29
        assert investor._determine_result(signal, 272.27) == "LOSS"

    def test_long_near_tp_slippage_is_win(self):
        # fill 4¢ below TP → still WIN
        investor, _, _ = _make_investor()
        signal = _make_signal()  # SL=498, TP=504
        assert investor._determine_result(signal, 503.96) == "WIN"


class TestCalculatePnl:
    def test_long_win_pnl(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()
        pnl = investor._calculate_pnl(signal, entry=500.0, exit_price=504.0, qty=10)
        fees = investor._calculate_fees(sell_price=504.0, qty=10)
        assert pnl == round((504.0 - 500.0) * 10 - fees, 2)

    def test_long_loss_pnl(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()
        pnl = investor._calculate_pnl(signal, entry=500.0, exit_price=497.0, qty=10)
        fees = investor._calculate_fees(sell_price=497.0, qty=10)
        assert pnl == round((497.0 - 500.0) * 10 - fees, 2)

    def test_short_win_pnl(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        pnl = investor._calculate_pnl(signal, entry=500.0, exit_price=496.0, qty=10)
        fees = investor._calculate_fees(sell_price=500.0, qty=10)
        assert pnl == round((500.0 - 496.0) * 10 - fees, 2)

    def test_short_loss_pnl(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        pnl = investor._calculate_pnl(signal, entry=500.0, exit_price=503.0, qty=10)
        fees = investor._calculate_fees(sell_price=500.0, qty=10)
        assert pnl == round((500.0 - 503.0) * 10 - fees, 2)
