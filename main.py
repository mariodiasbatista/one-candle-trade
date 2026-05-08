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
    telegram.log_info("🌙 <b>Nightly Screener</b> started")
    try:
        retriever.run_nightly_screener()
        watchlist = retriever._watchlist
        telegram.log_info(f"✅ <b>Nightly Screener</b> complete — watchlist: {', '.join(watchlist)}")
    except Exception as e:
        logger.error(f"Nightly screener error: {e}")
        telegram.log_error(f"❌ <b>Nightly Screener</b> failed: {e}")


def job_premarket_check():
    """9:00 AM EST — news/gap filter for each symbol."""
    global _signals_fired, _monitoring_active
    logger.info("=== PRE-MARKET CHECK ===")
    _signals_fired = set()
    _monitoring_active = True
    watchlist = retriever._watchlist
    telegram.log_info(f"🌅 <b>Pre-market Check</b> started — {len(watchlist)} symbol(s): {', '.join(watchlist)}")
    try:
        contexts = retriever.run_premarket_checks()
        passed = [s for s, c in contexts.items() if c.trade_allowed]
        skipped = [s for s, c in contexts.items() if not c.trade_allowed]
        for symbol, ctx in contexts.items():
            if not ctx.trade_allowed:
                investor.record_skip(symbol, ctx.date, ctx.skip_reason)
                telegram.send_premarket_skip(symbol, ctx.skip_reason)
            else:
                telegram.send_premarket_clear(symbol, ctx.premarket_gap_pct)
        telegram.log_info(
            f"✅ <b>Pre-market Check</b> complete — "
            f"{len(passed)} clear{': ' + ', '.join(passed) if passed else ''} | "
            f"{len(skipped)} skipped{': ' + ', '.join(skipped) if skipped else ''}"
        )
    except Exception as e:
        logger.error(f"Pre-market check error: {e}")
        telegram.log_error(f"❌ <b>Pre-market Check</b> failed: {e}")


def job_mark_first_candle():
    """9:40 AM EST — mark first candle levels, apply ATR filter."""
    logger.info("=== MARK FIRST CANDLE LEVELS ===")
    telegram.log_info("🕯️ <b>First Candle</b> started — fetching 9:30 opening bar")
    try:
        retriever.mark_first_candle_levels()
        for symbol, ctx in retriever.get_contexts().items():
            if ctx.trade_allowed and ctx.first_candle:
                telegram.send_candle_levels(symbol, ctx.key_high, ctx.key_low, ctx.candle_range, ctx.atr_14_daily)
            elif not ctx.trade_allowed and ctx.skip_reason:
                investor.record_skip(symbol, ctx.date, ctx.skip_reason)
                telegram.send_premarket_skip(symbol, ctx.skip_reason)
        active = [s for s, c in retriever.get_contexts().items() if c.trade_allowed]
        if active:
            telegram.log_info(f"✅ <b>First Candle</b> complete — {len(active)} symbol(s) ready for FVG scan")
        else:
            telegram.log_error("❌ <b>First Candle</b> — no symbols passed ATR filter, no trades today")
    except Exception as e:
        logger.error(f"First candle error: {e}")
        telegram.log_error(f"❌ <b>First Candle</b> failed: {e}")


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

    if now_et > cutoff:
        _monitoring_active = False
        for symbol, ctx in retriever.get_contexts().items():
            if ctx.trade_allowed and symbol not in _signals_fired:
                telegram.send_no_signal_cutoff(symbol)
                investor.record_skip(symbol, ctx.date, "No valid signal by 10:30 AM cutoff")
        logger.info("Signal window closed at 10:30 AM")
        telegram.log_info("⏱ <b>FVG Monitor</b> — signal window closed at 10:30 AM")
        return

    active = [s for s, c in retriever.get_contexts().items() if c.trade_allowed and s not in _signals_fired]
    telegram.log_debug(f"<b>FVG scan</b> {now_et.strftime('%H:%M')} — {len(active)} symbol(s) active: {', '.join(active) if active else 'none'}")

    try:
        contexts = retriever.update_1min_candles()
        for symbol, ctx in contexts.items():
            if not ctx.trade_allowed or symbol in _signals_fired:
                continue
            signal = analyst.analyze(ctx)
            if signal:
                trade_id = investor.execute_signal(signal)
                if trade_id:
                    _signals_fired.add(symbol)
            else:
                fvg_status = f"FVG={ctx.fvg.direction}" if ctx.fvg else "no FVG"
                vol_status = f"vol={ctx.volume_ratio:.1f}x" if ctx.volume_ratio else ""
                telegram.log_debug(f"<b>{symbol}</b> — {fvg_status}{' | ' + vol_status if vol_status else ''}")
    except Exception as e:
        logger.error(f"FVG monitor error: {e}")
        telegram.log_error(f"❌ <b>FVG Monitor</b> error: {e}")


def job_monitor_positions():
    """Every 5 minutes during market hours — check if open positions hit TP or SL."""
    open_count = len(investor._open_trades)
    if open_count == 0:
        return
    telegram.log_debug(f"<b>Position Monitor</b> {datetime.now(ET).strftime('%H:%M')} — checking {open_count} position(s): {', '.join(investor._open_trades)}")
    try:
        investor.monitor_open_positions()
    except Exception as e:
        logger.error(f"Position monitor error: {e}")
        telegram.log_error(f"❌ <b>Position Monitor</b> error: {e}")


def job_force_close():
    """3:55 PM EST — close all open positions before market closes."""
    logger.info("=== FORCE CLOSE ALL POSITIONS ===")
    open_count = len(investor._open_trades)
    if open_count == 0:
        telegram.log_info("🔒 <b>Force Close</b> — no open positions")
        return
    telegram.log_info(f"🔒 <b>Force Close</b> started — {open_count} open position(s): {', '.join(investor._open_trades)}")
    try:
        investor.force_close_all()
        telegram.log_info("✅ <b>Force Close</b> complete")
    except Exception as e:
        logger.error(f"Force close error: {e}")
        telegram.log_error(f"❌ <b>Force Close</b> failed: {e}")


def job_daily_summary():
    """4:05 PM EST — generate and send daily P&L summary."""
    logger.info("=== DAILY SUMMARY ===")
    telegram.log_info("📊 <b>Daily Summary</b> generating...")
    try:
        today = datetime.now(ET).strftime("%Y-%m-%d")
        account_value = investor.get_account_value()
        report = generate_daily_summary(today, account_value)
        logger.info(f"\n{report}")
        telegram.send_daily_summary(report)
    except Exception as e:
        logger.error(f"Daily summary error: {e}")
        telegram.log_error(f"❌ <b>Daily Summary</b> failed: {e}")

    # Send monthly summary on the last trading day of the month
    now = datetime.now(ET)
    from datetime import timedelta
    tomorrow = now + timedelta(days=1)
    if tomorrow.month != now.month:
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

    # Mark first candle levels — 9:40 AM EST Mon–Fri (bar finalizes at 9:35; extra time for IEX propagation + retries)
    sched.add_job(job_mark_first_candle, CronTrigger(day_of_week="mon-fri", hour=9, minute=40))

    # FVG monitoring — every 60s from 9:36 to 10:30 AM EST Mon–Fri
    sched.add_job(job_monitor_fvg, CronTrigger(day_of_week="mon-fri", hour=9, minute="36-59"))
    sched.add_job(job_monitor_fvg, CronTrigger(day_of_week="mon-fri", hour=10, minute="0-30"))

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
        "/loglevel — Show current Telegram log level\n"
        "/setlevel &lt;0-3&gt; — Set Telegram log level\n"
        "  0 = off | 1 = debug | 2 = info | 3 = errors only\n"
        "/help — Show this message",
        parse_mode="HTML",
    )


async def cmd_loglevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/loglevel — show current Telegram log level."""
    level = telegram.get_level()
    label = telegram.get_level_label()
    await update.message.reply_text(
        f"<b>Telegram log level:</b> {level} — {label}",
        parse_mode="HTML",
    )


async def cmd_setlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setlevel <0-3> — set Telegram log level."""
    try:
        level = int(context.args[0])
        if level not in (0, 1, 2, 3):
            raise ValueError
        telegram.set_level(level)
        label = telegram.get_level_label()
        await update.message.reply_text(
            f"✅ Telegram log level set to <b>{level} — {label}</b>",
            parse_mode="HTML",
        )
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Usage: /setlevel &lt;0-3&gt;\n0=off | 1=debug | 2=info | 3=errors only",
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
    app.add_handler(CommandHandler("loglevel", cmd_loglevel))
    app.add_handler(CommandHandler("setlevel", cmd_setlevel))
    return app


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("One Candle Trade V3 — starting up")
    init_db()
    logger.info("Database initialised")
    investor.recover_open_trades()
    logger.info("Crash recovery check complete")

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
