import logging

from sqlalchemy import (
    create_engine, inspect, text,
    Column, String, Float, Integer, Boolean, DateTime, JSON, Text,
)
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from datetime import datetime
from src.config import DATABASE_URL

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True)
    date = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    strategy = Column(String, default="one_candle_v3")
    signal = Column(String)                 # LONG / SHORT / SKIP
    entry = Column(Float)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    stop_type = Column(String)
    exit_price = Column(Float)
    result = Column(String)                 # WIN / LOSS / SKIP / FORCED_CLOSE
    qty = Column(Integer)
    pnl_dollars = Column(Float)
    pnl_percent = Column(Float)
    fvg_body_ratio = Column(Float)
    volume_ratio = Column(Float)
    filters_passed = Column(JSON)
    skip_reason = Column(Text)
    alpaca_order_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    closed_at = Column(DateTime)

    # Signal-time context, recorded for analysis only (added 2026-10-07).
    # Nullable because rows written before that date never captured them.
    premarket_gap_pct = Column(Float)
    atr_14_daily = Column(Float)
    candle_range = Column(Float)
    key_high = Column(Float)
    key_low = Column(Float)
    fvg_gap_size = Column(Float)


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(String, nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    skipped = Column(Integer, default=0)
    win_rate = Column(Float)
    net_pnl_dollars = Column(Float, default=0.0)
    net_pnl_percent = Column(Float, default=0.0)
    account_value = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    fvg_score = Column(Float, default=0.0)
    avg_volume = Column(Float)
    atr_pct = Column(Float)
    beta = Column(Float)
    active = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


# Columns added to `trades` after the table already existed in production.
# create_all() only creates missing *tables*, never missing columns, so an
# existing database silently keeps the old shape and every INSERT naming a new
# column fails. There is no Alembic here, so reconcile the narrow, explicit way.
_ADDED_TRADE_COLUMNS = {
    "premarket_gap_pct": "FLOAT",
    "atr_14_daily": "FLOAT",
    "candle_range": "FLOAT",
    "key_high": "FLOAT",
    "key_low": "FLOAT",
    "fvg_gap_size": "FLOAT",
}


def _add_missing_trade_columns():
    """Add any of _ADDED_TRADE_COLUMNS the live `trades` table is missing.

    Idempotent: inspects the table first and only adds what is absent, so it is
    safe on every startup. Existing rows get NULL, which is correct — those
    trades genuinely have no recorded context.
    """
    inspector = inspect(engine)
    if "trades" not in inspector.get_table_names():
        return []
    existing = {c["name"] for c in inspector.get_columns("trades")}
    added = []
    for name, sql_type in _ADDED_TRADE_COLUMNS.items():
        if name in existing:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE trades ADD COLUMN {name} {sql_type}"))
        added.append(name)
    return added


def init_db():
    Base.metadata.create_all(engine)
    added = _add_missing_trade_columns()
    if added:
        logger.info(f"Schema: added trades columns {added}")
