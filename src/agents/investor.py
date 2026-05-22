import logging
import time
from datetime import datetime
from typing import Optional
import pytz

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass, OrderStatus, QueryOrderStatus

from src.config import (
    ALPACA_API_KEY, ALPACA_SECRET_KEY,
    SLIPPAGE_PER_SHARE, SEC_FEE_RATE, FINRA_TAF_RATE, FINRA_TAF_MAX,
)
from src.models import TradeSignal
from src.core.risk import calculate_position_size
from src.db.repository import save_trade_signal, save_skip, close_trade, get_pending_trades
from src.reporting.telegram import TelegramReporter

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


class Investor:
    """Agent 3 — executes paper trades on Alpaca, monitors positions, records results."""

    def __init__(self, telegram: TelegramReporter):
        self._client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
        self._telegram = telegram
        self._open_trades: dict[str, dict] = {}  # symbol → {trade_id, order_id, signal}

    def recover_open_trades(self):
        """On startup, rebuild _open_trades from any PENDING DB records for today."""
        today = datetime.now(ET).strftime("%Y-%m-%d")
        pending = get_pending_trades(today)
        if not pending:
            return

        logger.info(f"Agent 3: Crash recovery — {len(pending)} pending trade(s) found")
        try:
            positions = {p.symbol: p for p in self._client.get_all_positions()}
        except Exception as e:
            logger.error(f"Agent 3: Recovery failed — could not fetch positions: {e}")
            self._telegram.log_error(f"❌ <b>Crash Recovery</b> failed — could not fetch positions: {e}")
            return

        for trade in pending:
            try:
                if trade.symbol in positions:
                    # Position still open on Alpaca — rebuild in-memory tracking
                    signal = self._signal_from_trade(trade)
                    self._open_trades[trade.symbol] = {
                        "trade_id": trade.id,
                        "order_id": trade.alpaca_order_id,
                        "signal": signal,
                        "qty": trade.qty,
                    }
                    logger.info(f"Agent 3: {trade.symbol} recovered — monitoring resumed")
                    self._telegram.log_info(f"🔄 <b>Crash Recovery</b> — {trade.symbol} open trade recovered, monitoring resumed")
                else:
                    # Position already closed while service was down — record result
                    try:
                        order = self._client.get_order_by_id(trade.alpaca_order_id)
                        exit_price = float(order.filled_avg_price or trade.entry)
                    except Exception:
                        exit_price = trade.entry
                    signal = self._signal_from_trade(trade)
                    result = self._determine_result(signal, exit_price)
                    pnl = self._calculate_pnl(signal, trade.entry, exit_price, trade.qty)
                    pnl_pct = pnl / (trade.entry * trade.qty) if trade.entry > 0 else 0.0
                    close_trade(trade.id, exit_price, result, pnl, round(pnl_pct, 4))
                    logger.info(f"Agent 3: {trade.symbol} closed during downtime — {result} @ {exit_price} | P&L=${pnl:.2f}")
                    self._telegram.log_info(
                        f"⚠️ <b>Crash Recovery</b> — {trade.symbol} closed during downtime\n"
                        f"{result} @ {exit_price} | P&L=${pnl:.2f}"
                    )
            except Exception as e:
                logger.error(f"Agent 3: Recovery error for {trade.symbol}: {e}")
                self._telegram.log_error(f"❌ <b>Crash Recovery</b> failed for {trade.symbol}: {e}")

    def _signal_from_trade(self, trade) -> "TradeSignal":
        """Reconstruct a TradeSignal from a DB Trade record."""
        from src.models import TradeSignal as TS
        return TS(
            symbol=trade.symbol,
            date=trade.date,
            signal=trade.signal,
            entry=trade.entry or 0.0,
            stop_loss=trade.stop_loss or 0.0,
            take_profit=trade.take_profit or 0.0,
            risk=round(abs((trade.entry or 0) - (trade.stop_loss or 0)), 2),
            reward=round(abs((trade.take_profit or 0) - (trade.entry or 0)), 2),
            stop_type=trade.stop_type or "",
            fvg_body_ratio=trade.fvg_body_ratio or 0.0,
            volume_ratio=trade.volume_ratio or 0.0,
            filters_passed=trade.filters_passed or [],
            confidence="HIGH",
        )

    def get_account_value(self) -> float:
        account = self._client.get_account()
        return float(account.portfolio_value)

    def execute_signal(self, signal: TradeSignal) -> Optional[str]:
        """Submit a bracket order to Alpaca. Returns trade_id or None on failure."""
        if signal.symbol in self._open_trades:
            logger.info(f"Agent 3: {signal.symbol} already has an open trade today — skipping duplicate")
            return None

        account_value = self.get_account_value()
        qty = calculate_position_size(account_value, signal.entry, signal.stop_loss)
        if qty <= 0:
            logger.warning(f"Agent 3: Position size 0 for {signal.symbol} — skipping")
            return None

        side = OrderSide.BUY if signal.signal == "LONG" else OrderSide.SELL
        try:
            order = self._client.submit_order(MarketOrderRequest(
                symbol=signal.symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=signal.take_profit),
                stop_loss=StopLossRequest(stop_price=signal.stop_loss),
            ))
            alpaca_order_id = str(order.id)
            trade_id = save_trade_signal(signal, qty, alpaca_order_id)
            self._open_trades[signal.symbol] = {
                "trade_id": trade_id,
                "order_id": alpaca_order_id,
                "signal": signal,
                "qty": qty,
            }
            logger.info(f"Agent 3: Order submitted {signal.signal} {qty}x{signal.symbol} @ market | order_id={alpaca_order_id}")
            self._telegram.send_entry_alert(signal, qty, account_value)
            return trade_id
        except Exception as e:
            logger.error(f"Agent 3: Order submission failed for {signal.symbol}: {e}")
            return None

    def record_skip(self, symbol: str, date: str, reason: str):
        save_skip(symbol, date, reason)
        self._telegram.send_skip_notice(symbol, reason)

    def _find_exit_price(self, symbol: str, fallback: float) -> float:
        """Find actual exit fill price from recent closed orders on Alpaca."""
        try:
            orders = self._client.get_orders(filter=GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                symbols=[symbol],
                limit=5,
            ))
            for o in orders:
                if o.status == OrderStatus.FILLED and o.filled_avg_price:
                    return float(o.filled_avg_price)
        except Exception:
            pass
        return fallback

    def monitor_open_positions(self):
        """Poll Alpaca positions and record result when bracket TP/SL closes them."""
        closed = []
        try:
            open_symbols = {p.symbol for p in self._client.get_all_positions()}
        except Exception as e:
            logger.warning(f"Agent 3: Could not fetch positions: {e}")
            return

        for symbol, info in self._open_trades.items():
            try:
                if symbol not in open_symbols:
                    # Position no longer on Alpaca — bracket TP or SL fired
                    signal = info["signal"]
                    exit_price = self._find_exit_price(symbol, signal.entry)
                    result = self._determine_result(signal, exit_price)
                    pnl_dollars = self._calculate_pnl(signal, signal.entry, exit_price, info["qty"])
                    pnl_pct = pnl_dollars / (signal.entry * info["qty"]) if signal.entry > 0 else 0.0
                    close_trade(info["trade_id"], exit_price, result, pnl_dollars, round(pnl_pct, 4))
                    logger.info(f"Agent 3: {symbol} {result} | exit={exit_price} | P&L=${pnl_dollars:.2f}")
                    self._telegram.send_result_notice(symbol, result, exit_price, pnl_dollars, pnl_pct)
                    closed.append(symbol)
                else:
                    # Still in position — only close if entry was rejected/cancelled
                    order = self._client.get_order_by_id(info["order_id"])
                    if order.status in (OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED):
                        close_trade(info["trade_id"], 0.0, "CANCELLED", 0.0, 0.0)
                        closed.append(symbol)

            except Exception as e:
                logger.warning(f"Agent 3: Monitor error for {symbol}: {e}")

        for symbol in closed:
            del self._open_trades[symbol]

    def force_close_all(self):
        """Close all open positions at market price — called at 3:55 PM EST."""
        for symbol, info in list(self._open_trades.items()):
            try:
                # Cancel all open orders for this symbol (entry + bracket TP/SL legs)
                try:
                    open_orders = self._client.get_orders(
                        filter=GetOrdersRequest(symbols=[symbol], status=QueryOrderStatus.OPEN)
                    )
                    for order in open_orders:
                        try:
                            self._client.cancel_order_by_id(order.id)
                        except Exception:
                            pass
                except Exception:
                    pass
                time.sleep(1.0)

                # Get current price via account positions
                positions = {p.symbol: p for p in self._client.get_all_positions()}
                if symbol in positions:
                    pos = positions[symbol]
                    if not pos.current_price:
                        logger.warning(f"Agent 3: {symbol} current_price unavailable, falling back to avg_entry_price for P&L estimate")
                    exit_price = float(pos.current_price or pos.avg_entry_price)
                    qty = abs(int(pos.qty))
                    signal = info["signal"]
                    side = OrderSide.SELL if signal.signal == "LONG" else OrderSide.BUY
                    self._client.submit_order(MarketOrderRequest(
                        symbol=symbol,
                        qty=qty,
                        side=side,
                        time_in_force=TimeInForce.DAY,
                    ))
                    pnl_dollars = self._calculate_pnl(signal, signal.entry, exit_price, qty)
                    pnl_pct = pnl_dollars / (signal.entry * qty) if signal.entry > 0 else 0.0
                    close_trade(info["trade_id"], exit_price, "FORCED_CLOSE", pnl_dollars, round(pnl_pct, 4))
                    logger.info(f"Agent 3: {symbol} FORCED_CLOSE @ {exit_price} | P&L=${pnl_dollars:.2f}")
            except Exception as e:
                logger.warning(f"Agent 3: Force close error for {symbol}: {e}")
        self._open_trades.clear()

    def _determine_result(self, signal: TradeSignal, exit_price: float) -> str:
        if signal.signal == "LONG":
            if exit_price >= signal.take_profit - 0.01:
                return "WIN"
            elif exit_price <= signal.stop_loss + 0.01:
                return "LOSS"
            else:
                return "FORCED_CLOSE"
        else:
            if exit_price <= signal.take_profit + 0.01:
                return "WIN"
            elif exit_price >= signal.stop_loss - 0.01:
                return "LOSS"
            else:
                return "FORCED_CLOSE"

    def _calculate_fees(self, sell_price: float, qty: int) -> float:
        slippage = 2 * SLIPPAGE_PER_SHARE * qty
        sec_fee  = SEC_FEE_RATE * sell_price * qty
        finra    = min(FINRA_TAF_RATE * qty, FINRA_TAF_MAX)
        return round(slippage + sec_fee + finra, 4)

    def _calculate_pnl(self, signal: TradeSignal, entry: float, exit_price: float, qty: int) -> float:
        if signal.signal == "LONG":
            gross = (exit_price - entry) * qty
            fees  = self._calculate_fees(sell_price=exit_price, qty=qty)
        else:
            gross = (entry - exit_price) * qty
            fees  = self._calculate_fees(sell_price=entry, qty=qty)
        return round(gross - fees, 2)
