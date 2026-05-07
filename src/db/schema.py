from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean, DateTime, JSON, Text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from datetime import datetime
from src.config import DATABASE_URL


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


def init_db():
    Base.metadata.create_all(engine)
