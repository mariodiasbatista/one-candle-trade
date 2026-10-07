"""Signal-time context must be recorded, and the migration must be safe.

Before 2026-10-07 the only features ever stored were fvg_body_ratio and
volume_ratio, and both test null against chance — so there was nothing else to
analyse even though the bot computed several other features on every signal and
threw them away. These are recorded for later analysis only; nothing reads them
back to make a trading decision.
"""
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

CONTEXT_FIELDS = ("premarket_gap_pct", "atr_14_daily", "candle_range",
                  "key_high", "key_low", "fvg_gap_size")


class TestSignalCarriesContext:
    def test_analyst_populates_every_context_field(self):
        from src.models import MarketContext, Candle, FVGResult
        from src.agents.analyst import Analyst
        from datetime import datetime
        import pytz
        ET = pytz.timezone("America/New_York")

        candle = Candle(timestamp=ET.localize(datetime(2026, 10, 6, 9, 35)),
                        open=100.0, high=101.0, low=99.0, close=100.5, volume=500_000)
        fvg = FVGResult(direction="BULLISH_FVG_BREAK_HIGH", gap_high=100.8,
                        gap_low=100.2, gap_size=0.6, body_ratio=2.4)
        ctx = MarketContext(
            symbol="NVDA", date="2026-10-06", trade_allowed=True, skip_reason=None,
            premarket_gap_pct=0.82, atr_14_daily=3.45, first_candle=candle,
            key_high=101.0, key_low=99.0, candle_range=2.0, candle_range_valid=True,
            fvg=fvg, volume_ratio=1.9, volume_confirmed=True,
            candles_1min=[candle],   # analyst reads entry from the latest 1-min close
        )
        sig = Analyst().analyze(ctx)
        assert sig is not None, "a confirmed FVG should produce a signal"
        assert sig.premarket_gap_pct == 0.82
        assert sig.atr_14_daily == 3.45
        assert sig.candle_range == 2.0
        assert sig.key_high == 101.0
        assert sig.key_low == 99.0
        assert sig.fvg_gap_size == 0.6

    def test_fields_default_so_existing_callers_keep_working(self):
        from src.models import TradeSignal
        sig = TradeSignal(symbol="SPY", date="2026-10-06", signal="LONG", entry=500.0,
                          stop_loss=499.0, take_profit=502.0, risk=1.0, reward=2.0,
                          stop_type="Option A (FVG-based)", fvg_body_ratio=2.0,
                          volume_ratio=1.5)
        for f in CONTEXT_FIELDS:
            assert getattr(sig, f) == 0.0


class TestMigration:
    def test_columns_are_added_to_a_pre_existing_table(self):
        """The real upgrade path: a DB whose trades table predates these columns."""
        from sqlalchemy import create_engine, inspect, text
        import src.db.schema as schema

        fd_path = tempfile.mkstemp(suffix=".db")[1]
        eng = create_engine(f"sqlite:///{fd_path}")
        # Old-shape table: just enough columns to stand in for the live one.
        with eng.begin() as c:
            c.execute(text("CREATE TABLE trades (id VARCHAR PRIMARY KEY, date VARCHAR, symbol VARCHAR)"))
        with patch.object(schema, "engine", eng):
            added = schema._add_missing_trade_columns()
        assert set(added) == set(CONTEXT_FIELDS)
        cols = {c["name"] for c in inspect(eng).get_columns("trades")}
        assert set(CONTEXT_FIELDS) <= cols

    def test_migration_is_idempotent(self):
        from sqlalchemy import create_engine, text
        import src.db.schema as schema

        fd_path = tempfile.mkstemp(suffix=".db")[1]
        eng = create_engine(f"sqlite:///{fd_path}")
        with eng.begin() as c:
            c.execute(text("CREATE TABLE trades (id VARCHAR PRIMARY KEY)"))
        with patch.object(schema, "engine", eng):
            first = schema._add_missing_trade_columns()
            second = schema._add_missing_trade_columns()
        assert len(first) == len(CONTEXT_FIELDS)
        assert second == [], "a second run must add nothing"

    def test_no_table_yet_is_not_an_error(self):
        from sqlalchemy import create_engine
        import src.db.schema as schema
        eng = create_engine("sqlite:///" + tempfile.mkstemp(suffix=".db")[1])
        with patch.object(schema, "engine", eng):
            assert schema._add_missing_trade_columns() == []


class TestPersisted:
    def test_context_reaches_the_database(self, clean_db):
        from src.models import TradeSignal
        from src.db.repository import save_trade_signal, get_trades_for_date
        sig = TradeSignal(symbol="AMD", date="2026-10-06", signal="SHORT", entry=200.0,
                          stop_loss=200.5, take_profit=199.0, risk=0.5, reward=1.0,
                          stop_type="Option A (FVG-based)", fvg_body_ratio=2.2,
                          volume_ratio=1.7, premarket_gap_pct=-1.3, atr_14_daily=5.1,
                          candle_range=2.8, key_high=202.0, key_low=199.2,
                          fvg_gap_size=0.45)
        save_trade_signal(sig, qty=10, alpaca_order_id="o-1")
        t = [x for x in get_trades_for_date("2026-10-06") if x.symbol == "AMD"][0]
        assert t.premarket_gap_pct == -1.3
        assert t.atr_14_daily == 5.1
        assert t.candle_range == 2.8
        assert t.key_high == 202.0
        assert t.key_low == 199.2
        assert t.fvg_gap_size == 0.45
