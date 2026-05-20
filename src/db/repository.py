import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from src.db.schema import SessionLocal, Trade, DailySummary, Watchlist
from src.models import TradeSignal, TradeResult


def get_session() -> Session:
    return SessionLocal()


def save_trade_signal(signal: TradeSignal, qty: int, alpaca_order_id: str) -> str:
    trade_id = str(uuid.uuid4())
    with get_session() as session:
        trade = Trade(
            id=trade_id,
            date=signal.date,
            symbol=signal.symbol,
            signal=signal.signal,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            stop_type=signal.stop_type,
            qty=qty,
            fvg_body_ratio=signal.fvg_body_ratio,
            volume_ratio=signal.volume_ratio,
            filters_passed=signal.filters_passed,
            alpaca_order_id=alpaca_order_id,
            result="PENDING",
        )
        session.add(trade)
        session.commit()
    return trade_id


def save_skip(symbol: str, date: str, skip_reason: str):
    trade_id = str(uuid.uuid4())
    with get_session() as session:
        trade = Trade(
            id=trade_id,
            date=date,
            symbol=symbol,
            signal="SKIP",
            result="SKIP",
            skip_reason=skip_reason,
            filters_passed=[],
        )
        session.add(trade)
        session.commit()


def close_trade(trade_id: str, exit_price: float, result: str, pnl_dollars: float, pnl_percent: float):
    with get_session() as session:
        trade = session.get(Trade, trade_id)
        if trade:
            trade.exit_price = exit_price
            trade.result = result
            trade.pnl_dollars = pnl_dollars
            trade.pnl_percent = pnl_percent
            trade.closed_at = datetime.utcnow()
            session.commit()


def get_pending_trades(date: str) -> list[Trade]:
    with get_session() as session:
        return session.query(Trade).filter(
            Trade.date == date,
            Trade.result == "PENDING",
        ).all()


def get_trades_for_date(date: str, symbol: Optional[str] = None) -> list[Trade]:
    with get_session() as session:
        query = session.query(Trade).filter(Trade.date == date)
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        return query.all()


def get_trades_for_month(year: int, month: int, symbol: Optional[str] = None) -> list[Trade]:
    prefix = f"{year}-{month:02d}"
    with get_session() as session:
        query = session.query(Trade).filter(Trade.date.like(f"{prefix}%"))
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        return query.all()


def get_trades_for_year(year: int, symbol: Optional[str] = None) -> list[Trade]:
    with get_session() as session:
        query = session.query(Trade).filter(Trade.date.like(f"{year}%"))
        if symbol:
            query = query.filter(Trade.symbol == symbol)
        return query.all()


def get_all_realized_pnl() -> tuple[float, int, int]:
    """Returns (total_pnl, total_wins, total_losses) across all closed trades.
    Win/loss is determined by actual P&L, so a profitable FORCED_CLOSE counts as a win."""
    with get_session() as session:
        trades = session.query(Trade).filter(
            Trade.result.in_(["WIN", "LOSS", "FORCED_CLOSE"])
        ).all()
    total_pnl = sum(t.pnl_dollars or 0 for t in trades)
    wins   = sum(1 for t in trades if (t.pnl_dollars or 0) > 0)
    losses = sum(1 for t in trades if (t.pnl_dollars or 0) <= 0)
    return round(total_pnl, 2), wins, losses


def save_daily_summary(date: str, symbol: str, total: int, wins: int, losses: int,
                       skipped: int, net_pnl: float, net_pnl_pct: float, account_value: float):
    win_rate = (wins / (wins + losses)) if (wins + losses) > 0 else 0.0
    with get_session() as session:
        summary = DailySummary(
            date=date,
            symbol=symbol,
            total_trades=total,
            wins=wins,
            losses=losses,
            skipped=skipped,
            win_rate=win_rate,
            net_pnl_dollars=net_pnl,
            net_pnl_percent=net_pnl_pct,
            account_value=account_value,
        )
        session.add(summary)
        session.commit()


def update_watchlist(symbols_scores: list[dict]):
    with get_session() as session:
        session.query(Watchlist).update({"active": False})
        session.commit()
        for item in symbols_scores:
            existing = session.query(Watchlist).filter(Watchlist.symbol == item["symbol"]).first()
            if existing:
                existing.fvg_score = item["fvg_score"]
                existing.avg_volume = item.get("avg_volume")
                existing.atr_pct = item.get("atr_pct")
                existing.beta = item.get("beta")
                existing.active = True
                existing.updated_at = datetime.utcnow()
            else:
                session.add(Watchlist(**item, active=True))
        session.commit()


def get_active_watchlist() -> list[str]:
    with get_session() as session:
        rows = session.query(Watchlist).filter(Watchlist.active == True).order_by(Watchlist.fvg_score.desc()).all()
        return [r.symbol for r in rows]
