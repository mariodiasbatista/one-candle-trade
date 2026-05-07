import pytest
from src.models import TradeSignal
from src.db.repository import (
    save_trade_signal, save_skip, close_trade,
    get_trades_for_date, get_trades_for_month, get_trades_for_year,
    save_daily_summary, update_watchlist, get_active_watchlist,
)


def _make_signal(symbol="SPY", date="2026-05-07", signal="LONG"):
    return TradeSignal(
        symbol=symbol, date=date, signal=signal,
        entry=500.0, stop_loss=498.0, take_profit=504.0,
        risk=2.0, reward=4.0, stop_type="Option B (First Candle)",
        fvg_body_ratio=2.0, volume_ratio=1.8,
        filters_passed=["news_ok", "gap_ok", "atr_ok", "fvg_ok", "volume_ok"],
    )


class TestSaveTradeSignal:
    def test_returns_trade_id(self, clean_db):
        trade_id = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="order-abc")
        assert trade_id is not None
        assert len(trade_id) == 36  # UUID format

    def test_trade_persisted_in_db(self, clean_db):
        save_trade_signal(_make_signal(), qty=10, alpaca_order_id="order-abc")
        trades = get_trades_for_date("2026-05-07")
        assert len(trades) == 1
        t = trades[0]
        assert t.symbol == "SPY"
        assert t.signal == "LONG"
        assert t.entry == 500.0
        assert t.result == "PENDING"
        assert t.alpaca_order_id == "order-abc"

    def test_qty_stored(self, clean_db):
        save_trade_signal(_make_signal(), qty=15, alpaca_order_id="order-xyz")
        trades = get_trades_for_date("2026-05-07")
        assert trades[0].qty == 15


class TestSaveSkip:
    def test_skip_record_created(self, clean_db):
        save_skip("SPY", "2026-05-07", "Gap too large")
        trades = get_trades_for_date("2026-05-07")
        assert len(trades) == 1
        t = trades[0]
        assert t.signal == "SKIP"
        assert t.result == "SKIP"
        assert t.skip_reason == "Gap too large"

    def test_multiple_skips_stored(self, clean_db):
        save_skip("SPY", "2026-05-07", "Gap too large")
        save_skip("QQQ", "2026-05-07", "CPI day")
        trades = get_trades_for_date("2026-05-07")
        assert len(trades) == 2


class TestCloseTrade:
    def test_close_updates_fields(self, clean_db):
        trade_id = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="order-1")
        close_trade(trade_id, exit_price=504.0, result="WIN", pnl_dollars=40.0, pnl_percent=0.008)
        trades = get_trades_for_date("2026-05-07")
        t = trades[0]
        assert t.result == "WIN"
        assert t.exit_price == 504.0
        assert t.pnl_dollars == 40.0
        assert t.pnl_percent == 0.008
        assert t.closed_at is not None

    def test_close_nonexistent_trade_no_error(self, clean_db):
        close_trade("nonexistent-id", 500.0, "WIN", 0.0, 0.0)

    def test_close_loss(self, clean_db):
        trade_id = save_trade_signal(_make_signal(), qty=10, alpaca_order_id="order-2")
        close_trade(trade_id, exit_price=498.0, result="LOSS", pnl_dollars=-20.0, pnl_percent=-0.004)
        trades = get_trades_for_date("2026-05-07")
        assert trades[0].result == "LOSS"
        assert trades[0].pnl_dollars == -20.0


class TestGetTradesForDate:
    def test_returns_trades_for_date(self, clean_db):
        save_trade_signal(_make_signal(date="2026-05-07"), qty=5, alpaca_order_id="o1")
        save_trade_signal(_make_signal(date="2026-05-08"), qty=5, alpaca_order_id="o2")
        trades = get_trades_for_date("2026-05-07")
        assert len(trades) == 1

    def test_returns_empty_for_missing_date(self, clean_db):
        assert get_trades_for_date("2026-05-07") == []

    def test_filter_by_symbol(self, clean_db):
        save_trade_signal(_make_signal(symbol="SPY"), qty=5, alpaca_order_id="o1")
        save_trade_signal(_make_signal(symbol="QQQ"), qty=5, alpaca_order_id="o2")
        trades = get_trades_for_date("2026-05-07", symbol="SPY")
        assert len(trades) == 1
        assert trades[0].symbol == "SPY"


class TestGetTradesForMonth:
    def test_returns_all_trades_in_month(self, clean_db):
        save_trade_signal(_make_signal(date="2026-05-07"), qty=5, alpaca_order_id="o1")
        save_trade_signal(_make_signal(date="2026-05-15"), qty=5, alpaca_order_id="o2")
        save_trade_signal(_make_signal(date="2026-06-01"), qty=5, alpaca_order_id="o3")
        trades = get_trades_for_month(2026, 5)
        assert len(trades) == 2

    def test_symbol_filter(self, clean_db):
        save_trade_signal(_make_signal(symbol="SPY", date="2026-05-07"), qty=5, alpaca_order_id="o1")
        save_trade_signal(_make_signal(symbol="QQQ", date="2026-05-08"), qty=5, alpaca_order_id="o2")
        trades = get_trades_for_month(2026, 5, symbol="SPY")
        assert len(trades) == 1


class TestGetTradesForYear:
    def test_returns_all_trades_in_year(self, clean_db):
        save_trade_signal(_make_signal(date="2026-01-10"), qty=5, alpaca_order_id="o1")
        save_trade_signal(_make_signal(date="2026-12-20"), qty=5, alpaca_order_id="o2")
        save_trade_signal(_make_signal(date="2025-12-31"), qty=5, alpaca_order_id="o3")
        trades = get_trades_for_year(2026)
        assert len(trades) == 2


class TestWatchlist:
    def test_update_watchlist_adds_symbols(self, clean_db):
        symbols = [
            {"symbol": "SPY", "fvg_score": 0.8, "avg_volume": 1e8, "atr_pct": 0.02, "beta": 1.0},
            {"symbol": "QQQ", "fvg_score": 0.7, "avg_volume": 5e7, "atr_pct": 0.025, "beta": 1.2},
        ]
        update_watchlist(symbols)
        active = get_active_watchlist()
        assert "SPY" in active
        assert "QQQ" in active

    def test_watchlist_ordered_by_fvg_score(self, clean_db):
        symbols = [
            {"symbol": "LOW_SCORE", "fvg_score": 0.3, "avg_volume": 1e8, "atr_pct": 0.02, "beta": 1.0},
            {"symbol": "HIGH_SCORE", "fvg_score": 0.9, "avg_volume": 1e8, "atr_pct": 0.02, "beta": 1.0},
        ]
        update_watchlist(symbols)
        active = get_active_watchlist()
        assert active[0] == "HIGH_SCORE"
        assert active[1] == "LOW_SCORE"

    def test_update_deactivates_previous_symbols(self, clean_db):
        first_batch = [{"symbol": "OLD", "fvg_score": 0.5, "avg_volume": 1e8, "atr_pct": 0.02, "beta": 1.0}]
        update_watchlist(first_batch)
        second_batch = [{"symbol": "NEW", "fvg_score": 0.6, "avg_volume": 1e8, "atr_pct": 0.02, "beta": 1.0}]
        update_watchlist(second_batch)
        active = get_active_watchlist()
        assert "NEW" in active
        assert "OLD" not in active

    def test_empty_watchlist_returns_empty(self, clean_db):
        assert get_active_watchlist() == []
