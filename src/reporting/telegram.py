import logging
import requests
from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from src.models import TradeSignal

logger = logging.getLogger(__name__)
BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def _send(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug(f"Telegram not configured — message: {text}")
        return
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
        }, timeout=10)
    except Exception as e:
        logger.warning(f"Telegram send error: {e}")


class TelegramReporter:

    def send_premarket_clear(self, symbol: str, gap_pct: float):
        _send(f"[Agent 1] <b>{symbol}</b> pre-market clear ✓\nGap={gap_pct:.2%} | No high-impact news | Ready to trade")

    def send_premarket_skip(self, symbol: str, reason: str):
        _send(f"[Agent 1] <b>{symbol}</b> SKIP today\nReason: {reason}")

    def send_candle_levels(self, symbol: str, high: float, low: float, candle_range: float, atr: float):
        _send(
            f"[Agent 1] <b>{symbol}</b> 5-min candle marked ✓\n"
            f"HIGH={high} | LOW={low} | Range=${candle_range:.2f} | ATR=${atr:.2f}\n"
            f"Monitoring 1-min for FVG..."
        )

    def send_entry_alert(self, signal: TradeSignal, qty: int, account_value: float):
        emoji = "📈" if signal.signal == "LONG" else "📉"
        _send(
            f"{emoji} [Agent 2] <b>SIGNAL: {signal.signal} {signal.symbol}</b>\n"
            f"Entry: {signal.entry} | SL: {signal.stop_loss} | TP: {signal.take_profit}\n"
            f"RR: 2:1 | Qty: {qty} shares\n"
            f"FVG ratio: {signal.fvg_body_ratio}x | Volume: {signal.volume_ratio}x ✓\n"
            f"Stop: {signal.stop_type}"
        )

    def send_skip_notice(self, symbol: str, reason: str):
        _send(f"[Agent 2] <b>{symbol}</b> — No valid signal\nReason: {reason}")

    def send_result_notice(self, symbol: str, result: str, exit_price: float, pnl_dollars: float, pnl_pct: float):
        emoji = "✅" if result == "WIN" else ("⚠️" if result == "FORCED_CLOSE" else "❌")
        sign = "+" if pnl_dollars >= 0 else ""
        _send(
            f"{emoji} [Agent 3] <b>{symbol} {result}</b>\n"
            f"Exit: {exit_price} | P&L: {sign}${pnl_dollars:.2f} ({sign}{pnl_pct:.2%})"
        )

    def send_daily_summary(self, report: str):
        _send(f"📊 [Agent 3] <b>Daily Summary</b>\n\n{report}")

    def send_monthly_summary(self, report: str):
        _send(f"📅 [Agent 3] <b>Monthly Summary</b>\n\n{report}")

    def send_yearly_summary(self, report: str):
        _send(f"🏆 [Agent 3] <b>Yearly Summary</b>\n\n{report}")

    def send_no_signal_cutoff(self, symbol: str):
        _send(f"[Agent 1] <b>{symbol}</b> — 10:30 AM cutoff reached. No trade today.")
