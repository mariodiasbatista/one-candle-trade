from datetime import datetime
from typing import Optional
from src.db.repository import (
    get_trades_for_date, get_trades_for_month, get_trades_for_year,
    save_daily_summary, get_active_watchlist, get_all_realized_pnl,
)
from src.config import INITIAL_ACCOUNT_VALUE
from src.db.schema import Trade


def _build_trade_stats(trades: list[Trade]) -> dict:
    actual = [t for t in trades if t.result in ("WIN", "LOSS", "FORCED_CLOSE")]
    skipped = [t for t in trades if t.result in ("SKIP", "CANCELLED")]
    wins = [t for t in actual if (t.pnl_dollars or 0) > 0]
    losses = [t for t in actual if (t.pnl_dollars or 0) <= 0]
    net_pnl = sum(t.pnl_dollars or 0 for t in actual)
    win_rate = len(wins) / len(actual) if actual else 0.0
    return {
        "total": len(actual),
        "wins": len(wins),
        "losses": len(losses),
        "skipped": len(skipped),
        "net_pnl": round(net_pnl, 2),
        "win_rate": round(win_rate, 4),
        "trades": actual,
    }


_RESULT_ICON = {
    "WIN": "✅",
    "LOSS": "❌",
    "FORCED_CLOSE": "⚠️",
    "SKIP": "⏭",
    "CANCELLED": "🚫",
}


def generate_daily_summary(
    date: str,
    account_value: float,
    timestamp: str = "",
    cash: float = 0.0,
    buying_power: float = 0.0,
    day_pnl: float = 0.0,
    open_positions: Optional[list] = None,
) -> str:
    import pytz
    ET = pytz.timezone("America/New_York")
    now_str = timestamp or datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    all_trades = get_trades_for_date(date)
    all_symbols = sorted(set(t.symbol for t in all_trades))
    open_positions = open_positions or []

    lines = [f"📊 Portfolio — {now_str}", ""]

    # ── Account ──────────────────────────────────────
    day_icon = "🟢" if day_pnl >= 0 else "🔴"
    day_sign = "+" if day_pnl >= 0 else ""
    lines.append("💼 Account")
    lines.append(f"Portfolio:    ${account_value:>12,.2f}")
    if cash:
        lines.append(f"Cash:         ${cash:>12,.2f}")
    if buying_power:
        lines.append(f"Buying Power: ${buying_power:>12,.2f}")
    lines.append(f"Day P&L:      {day_icon} ${day_sign}{day_pnl:,.2f}")
    cum_pnl, cum_wins, cum_losses = get_all_realized_pnl()
    cum_pct = cum_pnl / INITIAL_ACCOUNT_VALUE * 100
    cum_icon = "🟢" if cum_pnl >= 0 else "🔴"
    cum_sign = "+" if cum_pnl >= 0 else ""
    lines.append(f"Cumulative:   {cum_icon} ${cum_sign}{cum_pnl:,.2f} ({cum_sign}{cum_pct:.2f}%)  [{cum_wins}W/{cum_losses}L all-time]")

    # ── Open Positions ────────────────────────────────
    if open_positions:
        lines.append("")
        lines.append(f"📈 Positions ({len(open_positions)} open)")
        for pos in open_positions:
            qty   = pos.get("qty", 0)
            entry = pos.get("entry", 0.0)
            cur   = pos.get("current", 0.0)
            sym   = pos.get("symbol", "")
            total_pl   = pos.get("total_pl", 0.0)
            total_plpc = pos.get("total_plpc", 0.0)
            today_pl   = pos.get("today_pl", 0.0)
            today_plpc = pos.get("today_plpc", 0.0)
            stop       = pos.get("stop_loss")

            direction = "LONG" if qty >= 0 else "SHORT"
            pl_icon  = "🟢" if total_pl >= 0 else "🔴"
            pl_sign  = "+" if total_pl >= 0 else ""
            td_sign  = "+" if today_pl >= 0 else ""
            stop_str = f"  Stop ${stop:.2f}" if stop else ""
            lines.append(f"{sym} {direction} {abs(qty)}sh @ ${entry:.2f} → ${cur:.2f}")
            lines.append(
                f"  {pl_icon} Total {pl_sign}${total_pl:.2f} ({pl_sign}{total_plpc:.1%})"
                f"  Today {td_sign}${today_pl:.2f} ({td_sign}{today_plpc:.1%}){stop_str}"
            )

    # ── Today's Activity ──────────────────────────────
    actual  = [t for t in all_trades if t.result in ("WIN", "LOSS", "FORCED_CLOSE")]
    skipped = [t for t in all_trades if t.result in ("SKIP", "CANCELLED")]
    buys    = [t for t in actual if t.signal == "LONG"]
    sells   = [t for t in actual if t.signal == "SHORT" or t.closed_at is not None]
    realized_pnl = sum(t.pnl_dollars or 0 for t in actual)
    wins    = [t for t in actual if (t.pnl_dollars or 0) > 0]
    losses  = [t for t in actual if (t.pnl_dollars or 0) <= 0]

    lines.append("")
    lines.append("📋 Today's Activity")
    lines.append(f"Positions open:  {len(open_positions)}")
    buys_str  = ", ".join(t.symbol for t in buys)  or "none"
    sells_str = ", ".join(t.symbol for t in sells) or "none"
    lines.append(f"Buys today:      {len(buys)} — {buys_str}")
    lines.append(f"Sells today:     {len(sells)} — {sells_str}")
    r_icon = "🟢" if realized_pnl >= 0 else "🔴"
    r_sign = "+" if realized_pnl >= 0 else ""
    lines.append(f"Realized P&L:    {r_icon} ${r_sign}{realized_pnl:.2f}  (after fees & slippage)")
    if wins or losses:
        wr = len(wins) / len(actual) if actual else 0.0
        lines.append(f"Win rate:        {wr:.0%}  ({len(wins)}W / {len(losses)}L)")

    # ── Stocks — all watchlist symbols with their outcome ─
    lines.append("")
    lines.append("📊 Stocks")
    watchlist = get_active_watchlist() or []

    # Only stocks that completed the full FVG window with no signal are "checked"
    MONITORED_REASON = "No valid signal by 10:30 AM cutoff"
    monitored_skips = [t for t in skipped if MONITORED_REASON in (t.skip_reason or "")]
    other_skips     = [t for t in skipped if t not in monitored_skips]

    seen = set()
    # Traded symbols
    for t in actual:
        if t.symbol in seen:
            continue
        seen.add(t.symbol)
        icon = _RESULT_ICON.get(t.result, "•")
        sign = "+" if (t.pnl_dollars or 0) >= 0 else ""
        pnl_str = f"  {sign}${t.pnl_dollars:.2f}" if t.pnl_dollars is not None else ""
        entry_str = f"${t.entry:.2f}" if t.entry else "—"
        exit_str  = f"${t.exit_price:.2f}" if t.exit_price else "—"
        lines.append(f"  {icon} {t.symbol} {t.signal} {entry_str} → {exit_str}{pnl_str}")

    # Monitored through full FVG window — no signal found
    for t in monitored_skips:
        if t.symbol in seen:
            continue
        seen.add(t.symbol)
        lines.append(f"  🔍 {t.symbol} — monitored, no FVG signal")

    # Skipped at any earlier stage (pre-market, ATR filter, no candle data)
    for t in other_skips:
        if t.symbol in seen:
            continue
        seen.add(t.symbol)
        reason = (t.skip_reason or "").split("(")[0].strip()
        lines.append(f"  ⏭ {t.symbol} — {reason}")

    # Watchlist symbols with no DB record yet — currently being monitored
    for symbol in watchlist:
        if symbol not in seen:
            lines.append(f"  🔄 {symbol} — monitoring")

    # Save DB summaries
    for symbol in all_symbols:
        trades = [t for t in all_trades if t.symbol == symbol]
        stats  = _build_trade_stats(trades)
        save_daily_summary(
            date, symbol,
            stats["total"], stats["wins"], stats["losses"], stats["skipped"],
            stats["net_pnl"], stats["win_rate"], account_value,
        )

    return "\n".join(lines)


def generate_monthly_summary(year: int, month: int, account_value: float) -> str:
    month_label = datetime(year, month, 1).strftime("%B %Y")
    all_trades = get_trades_for_month(year, month)
    symbols = sorted(set(t.symbol for t in all_trades))

    lines = [f"ONE CANDLE TRADE — Monthly Summary {month_label}", "=" * 60]
    header = f"{'Symbol':<8} {'Trades':>7} {'Wins':>5} {'Losses':>7} {'Skipped':>8} {'Win%':>6} {'Net P&L':>10}"
    lines.append(header)
    lines.append("-" * 60)

    total_pnl = 0.0
    all_daily_pnls = []

    for symbol in symbols:
        trades = [t for t in all_trades if t.symbol == symbol]
        stats = _build_trade_stats(trades)
        sign = "+" if stats["net_pnl"] >= 0 else ""
        lines.append(
            f"{symbol:<8} {stats['total']:>7} {stats['wins']:>5} {stats['losses']:>7} "
            f"{stats['skipped']:>8} {stats['win_rate']:>6.0%} {sign}${stats['net_pnl']:>9.2f}"
        )
        total_pnl += stats["net_pnl"]
        for t in stats["trades"]:
            all_daily_pnls.append((t.date, t.pnl_dollars or 0))

    lines.append("-" * 60)
    daily_totals: dict[str, float] = {}
    for date, pnl in all_daily_pnls:
        daily_totals[date] = daily_totals.get(date, 0) + pnl

    best_day = max(daily_totals.items(), key=lambda x: x[1]) if daily_totals else ("—", 0)
    worst_day = min(daily_totals.items(), key=lambda x: x[1]) if daily_totals else ("—", 0)
    sign = "+" if total_pnl >= 0 else ""
    lines.append(f"Net P&L: {sign}${total_pnl:.2f} | Account: ${account_value:,.2f}")
    lines.append(f"Best day: {best_day[0]} (+${best_day[1]:.2f}) | Worst day: {worst_day[0]} (${worst_day[1]:.2f})")
    return "\n".join(lines)


def generate_yearly_summary(year: int, account_value: float, initial_account: float) -> str:
    all_trades = get_trades_for_year(year)
    symbols = sorted(set(t.symbol for t in all_trades))

    lines = [f"ONE CANDLE TRADE — Yearly Summary {year}", "=" * 65]
    header = f"{'Symbol':<8} {'Trades':>7} {'Win%':>6} {'Net P&L':>10} {'Return%':>9}"
    lines.append(header)
    lines.append("-" * 65)

    total_pnl = 0.0
    monthly_pnls: dict[str, float] = {}

    for symbol in symbols:
        trades = [t for t in all_trades if t.symbol == symbol]
        stats = _build_trade_stats(trades)
        ret_pct = (stats["net_pnl"] / initial_account) * 100 if initial_account > 0 else 0.0
        sign = "+" if stats["net_pnl"] >= 0 else ""
        lines.append(
            f"{symbol:<8} {stats['total']:>7} {stats['win_rate']:>6.0%} "
            f"{sign}${stats['net_pnl']:>9.2f} {sign}{ret_pct:>8.1f}%"
        )
        total_pnl += stats["net_pnl"]
        for t in stats["trades"]:
            month_key = t.date[:7]  # YYYY-MM
            monthly_pnls[month_key] = monthly_pnls.get(month_key, 0) + (t.pnl_dollars or 0)

    # Max drawdown
    equity_curve = [initial_account]
    running = initial_account
    for m in sorted(monthly_pnls):
        running += monthly_pnls[m]
        equity_curve.append(running)
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    best_month = max(monthly_pnls.items(), key=lambda x: x[1]) if monthly_pnls else ("—", 0)
    worst_month = min(monthly_pnls.items(), key=lambda x: x[1]) if monthly_pnls else ("—", 0)
    total_return = (total_pnl / initial_account) * 100 if initial_account > 0 else 0.0
    sign = "+" if total_pnl >= 0 else ""
    lines.append("-" * 65)
    lines.append(f"Portfolio Net P&L: {sign}${total_pnl:.2f} | Total Return: {sign}{total_return:.1f}%")
    lines.append(f"Max Drawdown: -{max_dd:.1%} | Account: ${account_value:,.2f}")
    lines.append(f"Best month: {best_month[0]} (+${best_month[1]:.2f}) | Worst: {worst_month[0]} (${worst_month[1]:.2f})")
    return "\n".join(lines)
