import pytest
from src.db.repository import save_trade_signal, save_skip, close_trade
from src.models import TradeSignal
from src.reporting.summary import (
    generate_daily_summary, generate_monthly_summary, generate_yearly_summary,
)


def _make_signal(symbol="SPY", date="2026-05-07", signal="LONG"):
    return TradeSignal(
        symbol=symbol, date=date, signal=signal,
        entry=500.0, stop_loss=498.0, take_profit=504.0,
        risk=2.0, reward=4.0, stop_type="Option B (First Candle)",
        fvg_body_ratio=2.0, volume_ratio=1.8, filters_passed=[],
    )


def _insert_win(symbol="SPY", date="2026-05-07", pnl=40.0):
    tid = save_trade_signal(_make_signal(symbol, date), qty=10, alpaca_order_id="o1")
    close_trade(tid, exit_price=504.0, result="WIN", pnl_dollars=pnl, pnl_percent=pnl / 5000)
    return tid


def _insert_loss(symbol="SPY", date="2026-05-07", pnl=-20.0):
    tid = save_trade_signal(_make_signal(symbol, date), qty=10, alpaca_order_id="o2")
    close_trade(tid, exit_price=498.0, result="LOSS", pnl_dollars=pnl, pnl_percent=pnl / 5000)
    return tid


class TestGenerateDailySummary:
    def test_empty_day_returns_valid_string(self, clean_db):
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "Portfolio" in result
        assert "100,000.00" in result
        assert "Buys today" in result

    def test_win_trade_appears_in_summary(self, clean_db):
        _insert_win()
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "SPY" in result
        assert "100%" in result  # win rate

    def test_loss_trade_appears_in_summary(self, clean_db):
        _insert_loss()
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "0W / 1L" in result

    def test_skip_record_counted(self, clean_db):
        save_skip("SPY", "2026-05-07", "CPI release day")
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "📊 Stocks" in result
        assert "SPY" in result
        assert "⏭" in result

    def test_win_rate_calculated(self, clean_db):
        _insert_win()
        _insert_loss()
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "50%" in result

    def test_net_pnl_calculated(self, clean_db):
        _insert_win(pnl=40.0)
        _insert_loss(pnl=-20.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "$+20.00" in result

    def test_account_value_shown(self, clean_db):
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "100,000.00" in result

    def test_forced_close_counts_as_loss(self, clean_db):
        tid = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="o3")
        close_trade(tid, exit_price=499.0, result="FORCED_CLOSE", pnl_dollars=-10.0, pnl_percent=-0.002)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "0W / 1L" in result

    def test_cancelled_trade_counts_as_skipped(self, clean_db):
        tid = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="o4")
        close_trade(tid, exit_price=0.0, result="CANCELLED", pnl_dollars=0.0, pnl_percent=0.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "📊 Stocks" in result
        assert "Buys today:      0" in result

    def test_cancelled_trade_shown_with_dashes_not_zero_pnl(self, clean_db):
        tid = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="o5")
        close_trade(tid, exit_price=0.0, result="CANCELLED", pnl_dollars=0.0, pnl_percent=0.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "📊 Stocks" in result
        assert "$0.00" not in result.split("Realized")[1]


class TestGenerateMonthlySummary:
    def test_empty_month(self, clean_db):
        result = generate_monthly_summary(2026, 5, account_value=100_000.0)
        assert "Monthly Summary" in result
        assert "May 2026" in result

    def test_trades_aggregated_by_symbol(self, clean_db):
        _insert_win("SPY", "2026-05-07", pnl=40.0)
        _insert_win("SPY", "2026-05-08", pnl=30.0)
        _insert_loss("QQQ", "2026-05-07", pnl=-20.0)
        result = generate_monthly_summary(2026, 5, account_value=100_000.0)
        assert "SPY" in result
        assert "QQQ" in result

    def test_monthly_total_pnl(self, clean_db):
        _insert_win("SPY", "2026-05-07", pnl=100.0)
        _insert_loss("SPY", "2026-05-08", pnl=-40.0)
        result = generate_monthly_summary(2026, 5, account_value=100_000.0)
        assert "+$60.00" in result

    def test_excludes_other_months(self, clean_db):
        _insert_win("SPY", "2026-04-30", pnl=50.0)
        _insert_win("SPY", "2026-05-07", pnl=40.0)
        result = generate_monthly_summary(2026, 5, account_value=100_000.0)
        # Only May trade should contribute to total
        assert "+$40.00" in result


class TestGenerateYearlySummary:
    def test_empty_year(self, clean_db):
        result = generate_yearly_summary(2026, account_value=100_000.0, initial_account=100_000.0)
        assert "Yearly Summary" in result
        assert "2026" in result

    def test_total_return_percentage(self, clean_db):
        _insert_win("SPY", "2026-05-07", pnl=1000.0)
        result = generate_yearly_summary(2026, account_value=101_000.0, initial_account=100_000.0)
        assert "1.0%" in result or "+$1000.00" in result

    def test_zero_drawdown_when_only_wins(self, clean_db):
        _insert_win("SPY", "2026-01-10", pnl=500.0)
        _insert_win("SPY", "2026-02-10", pnl=300.0)
        result = generate_yearly_summary(2026, account_value=100_800.0, initial_account=100_000.0)
        assert "Max Drawdown: -0.0%" in result

    def test_best_worst_month_shown(self, clean_db):
        _insert_win("SPY", "2026-01-10", pnl=2000.0)
        _insert_loss("SPY", "2026-03-10", pnl=-500.0)
        result = generate_yearly_summary(2026, account_value=101_500.0, initial_account=100_000.0)
        assert "Best month" in result
        assert "Worst" in result


class TestOpenPositions:
    def _make_pos(self, symbol="SPY", qty=10, entry=500.0, current=505.0,
                  total_pl=50.0, total_plpc=0.01, today_pl=50.0, today_plpc=0.01,
                  stop_loss=None):
        return dict(symbol=symbol, qty=qty, entry=entry, current=current,
                    total_pl=total_pl, total_plpc=total_plpc,
                    today_pl=today_pl, today_plpc=today_plpc, stop_loss=stop_loss)

    def test_long_position_shows_long_label(self, clean_db):
        pos = self._make_pos(qty=10)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "SPY LONG 10sh" in result

    def test_short_position_shows_short_label(self, clean_db):
        pos = self._make_pos(qty=-10, total_pl=30.0, today_pl=30.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "SPY SHORT 10sh" in result

    def test_short_qty_shown_as_positive(self, clean_db):
        pos = self._make_pos(qty=-15, total_pl=10.0, today_pl=10.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "15sh" in result
        assert "-15sh" not in result

    def test_profitable_position_shows_green_icon(self, clean_db):
        pos = self._make_pos(total_pl=50.0, today_pl=50.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "🟢" in result

    def test_losing_position_shows_red_icon(self, clean_db):
        pos = self._make_pos(total_pl=-30.0, today_pl=-30.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "🔴" in result

    def test_stop_loss_shown_when_present(self, clean_db):
        pos = self._make_pos(stop_loss=495.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "Stop $495.00" in result

    def test_no_stop_loss_omitted(self, clean_db):
        pos = self._make_pos(stop_loss=None)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=[pos])
        assert "Stop" not in result

    def test_multiple_positions_all_shown(self, clean_db):
        positions = [
            self._make_pos("SPY", qty=10),
            self._make_pos("QQQ", qty=-5, total_pl=20.0, today_pl=20.0),
        ]
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        open_positions=positions)
        assert "SPY LONG" in result
        assert "QQQ SHORT" in result
        assert "2 open" in result

    def test_cash_and_buying_power_shown_when_provided(self, clean_db):
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        cash=80_000.0, buying_power=320_000.0)
        assert "Cash:" in result
        assert "80,000.00" in result
        assert "Buying Power:" in result
        assert "320,000.00" in result

    def test_cash_and_buying_power_omitted_when_zero(self, clean_db):
        result = generate_daily_summary("2026-05-07", account_value=100_000.0,
                                        cash=0.0, buying_power=0.0)
        assert "Cash:" not in result
        assert "Buying Power:" not in result


class TestStocksSection:
    def test_monitored_skip_shows_magnifier(self, clean_db):
        save_skip("SPY", "2026-05-07", "No valid signal by 10:30 AM cutoff")
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "🔍 SPY" in result

    def test_watchlist_symbol_not_in_db_shows_monitoring(self, clean_db):
        from unittest.mock import patch
        with patch("src.reporting.summary.get_active_watchlist", return_value=["AAPL"]):
            result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "🔄 AAPL" in result

    def test_same_symbol_not_duplicated(self, clean_db):
        save_skip("SPY", "2026-05-07", "No valid signal by 10:30 AM cutoff")
        from unittest.mock import patch
        with patch("src.reporting.summary.get_active_watchlist", return_value=["SPY"]):
            result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert result.count("SPY") == 1
