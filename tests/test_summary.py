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
        assert "ONE CANDLE TRADE" in result
        assert "2026-05-07" in result
        assert "Traded: 0" in result

    def test_win_trade_appears_in_summary(self, clean_db):
        _insert_win()
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "✅" in result
        assert "SPY" in result

    def test_loss_trade_appears_in_summary(self, clean_db):
        _insert_loss()
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "❌" in result

    def test_skip_record_counted(self, clean_db):
        save_skip("SPY", "2026-05-07", "CPI day")
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "Skipped: 1" in result

    def test_win_rate_calculated(self, clean_db):
        _insert_win()
        _insert_loss()
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "50%" in result

    def test_net_pnl_calculated(self, clean_db):
        _insert_win(pnl=40.0)
        _insert_loss(pnl=-20.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "+$20.00" in result

    def test_account_value_shown(self, clean_db):
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "100,000.00" in result

    def test_forced_close_counts_as_loss(self, clean_db):
        tid = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="o3")
        close_trade(tid, exit_price=499.0, result="FORCED_CLOSE", pnl_dollars=-10.0, pnl_percent=-0.002)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "1 losses" in result

    def test_cancelled_trade_counts_as_skipped(self, clean_db):
        tid = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="o4")
        close_trade(tid, exit_price=0.0, result="CANCELLED", pnl_dollars=0.0, pnl_percent=0.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "Skipped: 1" in result
        assert "Traded: 0" in result

    def test_cancelled_trade_shown_with_dashes_not_zero_pnl(self, clean_db):
        tid = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="o5")
        close_trade(tid, exit_price=0.0, result="CANCELLED", pnl_dollars=0.0, pnl_percent=0.0)
        result = generate_daily_summary("2026-05-07", account_value=100_000.0)
        assert "CANCELLED" in result
        # trade row must use dashes, not formatted P&L values
        trade_row = [l for l in result.splitlines() if "CANCELLED" in l][0]
        assert "—" in trade_row
        assert "$0.00" not in trade_row


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
