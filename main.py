"""
One Candle Trade — Main Orchestrator
Strategy V3: First 5-min candle ORB + FVG + Volume confirmation
Paper trading via Alpaca. Guided by SAT - Idea 2 V3 document.
"""
import asyncio
import logging
import time
from datetime import datetime

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest

from src.db.schema import init_db
from src.agents.data_retriever import DataRetriever
from src.agents.analyst import Analyst
from src.agents.investor import Investor
from src.reporting.telegram import TelegramReporter
from src.reporting.summary import (
    generate_daily_summary,
    generate_monthly_summary,
    generate_yearly_summary,
)
from src.config import SIGNAL_CUTOFF_HOUR, SIGNAL_CUTOFF_MINUTE, DEFAULT_WATCHLIST, TELEGRAM_BOT_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")

# Initialise components
telegram = TelegramReporter()
retriever = DataRetriever()
analyst = Analyst()
investor = Investor(telegram)

# Track which symbols already have a signal today
_signals_fired: set[str] = set()
_monitoring_active: bool = False


# ──────────────────────────────────────────────
# SCHEDULED JOBS
# ──────────────────────────────────────────────

def job_nightly_screener():
    """8:00 PM EST — update tomorrow's watchlist."""
    logger.info("=== NIGHTLY SCREENER ===")
    retriever.run_nightly_screener()


def job_premarket_check():
    """9:00 AM EST — news/gap filter for each symbol."""
    global _signals_fired, _monitoring_active
    logger.info("=== PRE-MARKET CHECK ===")
    _signals_fired = set()
    _monitoring_active = True
    contexts = retriever.run_premarket_checks()
    for symbol, ctx in contexts.items():
        if not ctx.trade_allowed:
            investor.record_skip(symbol, ctx.date, ctx.skip_reason)
            telegram.send_premarket_skip(symbol, ctx.skip_reason)
        else:
            telegram.send_premarket_clear(symbol, ctx.premarket_gap_pct)


def job_mark_first_candle():
    """9:36 AM EST — mark first candle levels, apply ATR filter."""
    logger.info("=== MARK FIRST CANDLE LEVELS ===")
    retriever.mark_first_candle_levels()
    for symbol, ctx in retriever.get_contexts().items():
        if ctx.trade_allowed and ctx.first_candle:
            telegram.send_candle_levels(symbol, ctx.key_high, ctx.key_low, ctx.candle_range, ctx.atr_14_daily)
        elif not ctx.trade_allowed and ctx.skip_reason:
            investor.record_skip(symbol, ctx.date, ctx.skip_reason)
            telegram.send_premarket_skip(symbol, ctx.skip_reason)


def job_monitor_fvg():
    """
    9:36–10:30 AM EST — runs every 60 seconds.
    Fetches latest 1-min candles and checks for valid FVG + volume confirmation.
    """
    global _monitoring_active
    if not _monitoring_active:
        return

    now_et = datetime.now(ET)
    cutoff = now_et.replace(hour=SIGNAL_CUTOFF_HOUR, minute=SIGNAL_CUTOFF_MINUTE, second=0, microsecond=0)

    if now_et >= cutoff:
        _monitoring_active = False
        for symbol, ctx in retriever.get_contexts().items():
            if ctx.trade_allowed and symbol not in _signals_fired:
                telegram.send_no_signal_cutoff(symbol)
                investor.record_skip(symbol, ctx.date, "No valid signal by 10:30 AM cutoff")
        logger.info("Signal window closed at 10:30 AM")
        return

    contexts = retriever.update_1min_candles()
    for symbol, ctx in contexts.items():
        if not ctx.trade_allowed or symbol in _signals_fired:
            continue
        signal = analyst.analyze(ctx)
        if signal:
            trade_id = investor.execute_signal(signal)
            if trade_id:
                _signals_fired.add(symbol)


def job_monitor_positions():
    """Every 5 minutes during market hours — check if open positions hit TP or SL."""
    investor.monitor_open_positions()


def job_force_close():
    """3:55 PM EST — close all open positions before market closes."""
    logger.info("=== FORCE CLOSE ALL POSITIONS ===")
    investor.force_close_all()


def job_daily_summary():
    """4:05 PM EST — generate and send daily P&L summary."""
    logger.info("=== DAILY SUMMARY ===")
    today = datetime.now(ET).strftime("%Y-%m-%d")
    account_value = investor.get_account_value()
    report = generate_daily_summary(today, account_value)
    logger.info(f"\n{report}")
    telegram.send_daily_summary(report)

    # Send monthly summary on the last trading day of the month
    now = datetime.now(ET)
    tomorrow = now.replace(day=now.day + 1) if now.day < 28 else None
    if tomorrow is None or tomorrow.month != now.month:
        monthly = generate_monthly_summary(now.year, now.month, account_value)
        logger.info(f"\n{monthly}")
        telegram.send_monthly_summary(monthly)

    # Send yearly summary on Dec 31
    if now.month == 12 and now.day == 31:
        initial = 25000.0  # Starting paper account value
        yearly = generate_yearly_summary(now.year, account_value, initial)
        logger.info(f"\n{yearly}")
        telegram.send_yearly_summary(yearly)


# ──────────────────────────────────────────────
# SCHEDULER SETUP
# ──────────────────────────────────────────────

def build_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=ET)

    # Nightly screener — 8:00 PM EST Mon–Fri
    sched.add_job(job_nightly_screener, CronTrigger(day_of_week="mon-fri", hour=20, minute=0))

    # Pre-market check — 9:00 AM EST Mon–Fri
    sched.add_job(job_premarket_check, CronTrigger(day_of_week="mon-fri", hour=9, minute=0))

    # Mark first candle levels — 9:36 AM EST Mon–Fri (bar finalizes at 9:35; give Alpaca 60s)
    sched.add_job(job_mark_first_candle, CronTrigger(day_of_week="mon-fri", hour=9, minute=36))

    # FVG monitoring — every 60s from 9:36 to 10:30 AM EST Mon–Fri
    sched.add_job(job_monitor_fvg, CronTrigger(day_of_week="mon-fri", hour="9-10", minute="*/1"))

    # Position monitoring — every 5 minutes from 9:30 AM to 3:55 PM EST Mon–Fri
    sched.add_job(job_monitor_positions, CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5"))

    # Force close — 3:55 PM EST Mon–Fri
    sched.add_job(job_force_close, CronTrigger(day_of_week="mon-fri", hour=15, minute=55))

    # Daily summary — 4:05 PM EST Mon–Fri
    sched.add_job(job_daily_summary, CronTrigger(day_of_week="mon-fri", hour=16, minute=5))

    return sched


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# TELEGRAM COMMAND HANDLERS
# ──────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — list available commands."""
    await update.message.reply_text(
        "<b>One Candle Trade — Available Commands</b>\n\n"
        "/summary — Send today's P&L summary on demand\n"
        "/help — Show this message",
        parse_mode="HTML",
    )


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/summary — send the daily P&L summary on demand."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, job_daily_summary)


def build_telegram_app() -> Application:
    request = HTTPXRequest(connect_timeout=30, read_timeout=30)
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).request(request).build()
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("summary", cmd_summary))
    return app


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("One Candle Trade V3 — starting up")
    init_db()
    logger.info("Database initialised")

    scheduler = build_scheduler()
    logger.info("Scheduler configured — jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  {job.name} → {job.trigger}")
    scheduler.start()

    tg_app = build_telegram_app()
    logger.info("Telegram bot listening for commands")
    try:
        tg_app.run_polling()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        scheduler.shutdown()
        logger.info("Shutting down gracefully")
