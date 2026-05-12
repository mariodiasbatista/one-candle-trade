import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from src.agents.investor import Investor
from src.models import TradeSignal
from alpaca.trading.enums import OrderStatus


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
    def test_filled_order_closes_win(self):
        investor, client, telegram = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t1", "order_id": "o1", "signal": signal, "qty": 10}

        mock_order = MagicMock()
        mock_order.status = OrderStatus.FILLED
        mock_order.filled_avg_price = "505.0"  # above TP=504 → WIN
        client.get_order_by_id.return_value = mock_order

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        mock_close.assert_called_once()
        args = mock_close.call_args[0]
        assert args[2] == "WIN"
        assert "SPY" not in investor._open_trades

    def test_filled_order_closes_loss(self):
        investor, client, telegram = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t2", "order_id": "o2", "signal": signal, "qty": 10}

        mock_order = MagicMock()
        mock_order.status = OrderStatus.FILLED
        mock_order.filled_avg_price = "497.0"  # below SL=498 → LOSS
        client.get_order_by_id.return_value = mock_order

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        args = mock_close.call_args[0]
        assert args[2] == "LOSS"

    def test_cancelled_order_recorded(self):
        investor, client, _ = _make_investor()
        signal = _make_signal()
        investor._open_trades["SPY"] = {"trade_id": "t3", "order_id": "o3", "signal": signal, "qty": 10}

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
        investor._open_trades["SPY"] = {"trade_id": "t4", "order_id": "o4", "signal": signal, "qty": 10}
        client.get_order_by_id.side_effect = Exception("Network error")

        investor.monitor_open_positions()  # should not raise
        assert "SPY" in investor._open_trades  # not removed on exception

    def test_filled_avg_price_none_falls_back_to_entry(self):
        investor, client, _ = _make_investor()
        signal = _make_signal()  # entry=500.0
        investor._open_trades["SPY"] = {"trade_id": "t5", "order_id": "o5", "signal": signal, "qty": 10}

        mock_order = MagicMock()
        mock_order.status = OrderStatus.FILLED
        mock_order.filled_avg_price = None
        client.get_order_by_id.return_value = mock_order

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.monitor_open_positions()

        args = mock_close.call_args[0]
        assert args[1] == 500.0  # exit_price == signal.entry, not 0


class TestForceCloseAll:
    def test_current_price_none_falls_back_to_avg_entry_price(self):
        investor, client, _ = _make_investor()
        signal = _make_signal()  # entry=500.0
        investor._open_trades["SPY"] = {"trade_id": "t6", "order_id": "o6", "signal": signal, "qty": 10}

        mock_pos = MagicMock()
        mock_pos.symbol = "SPY"
        mock_pos.current_price = None
        mock_pos.avg_entry_price = "500.0"
        mock_pos.qty = "10"
        client.get_all_positions.return_value = [mock_pos]

        with patch("src.agents.investor.close_trade") as mock_close:
            investor.force_close_all()

        args = mock_close.call_args[0]
        assert args[1] == 500.0  # fell back to avg_entry_price, not crashed


class TestDetermineResult:
    def test_long_at_take_profit_is_win(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()  # TP=504
        assert investor._determine_result(signal, 504.0) == "WIN"
        assert investor._determine_result(signal, 505.0) == "WIN"

    def test_long_below_take_profit_is_loss(self):
        investor, _, _ = _make_investor()
        signal = _make_signal()  # TP=504
        assert investor._determine_result(signal, 500.0) == "LOSS"

    def test_short_at_take_profit_is_win(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        signal.take_profit = 496.0
        assert investor._determine_result(signal, 496.0) == "WIN"
        assert investor._determine_result(signal, 495.0) == "WIN"

    def test_short_above_take_profit_is_loss(self):
        investor, _, _ = _make_investor()
        signal = _make_signal(direction="SHORT")
        signal.take_profit = 496.0
        assert investor._determine_result(signal, 499.0) == "LOSS"


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
