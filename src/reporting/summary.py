from datetime import datetime
from typing import Optional
from src.db.repository import (
    get_trades_for_date, get_trades_for_month, get_trades_for_year,
    save_daily_summary,
)
from src.db.schema import Trade


def _build_trade_stats(trades: list[Trade]) -> dict:
    actual = [t for t in trades if t.result in ("WIN", "LOSS", "FORCED_CLOSE")]
    skipped = [t for t in trades if t.result == "SKIP"]
    wins = [t for t in actual if t.result == "WIN"]
    losses = [t for t in actual if t.result in ("LOSS", "FORCED_CLOSE")]
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


def generate_daily_summary(date: str, account_value: float) -> str:
    all_symbols = set()
    all_trades = get_trades_for_date(date)
    for t in all_trades:
        all_symbols.add(t.symbol)

    lines = [f"ONE CANDLE TRADE — Daily Summary {date}", "=" * 50]
    header = f"{'Symbol':<8} {'Signal':<7} {'Entry':>7} {'Exit':>7} {'P&L$':>8} {'P&L%':>7} {'Result':<12}"
    lines.append(header)
    lines.append("-" * 50)

    total_pnl = 0.0
    total_wins = 0
    total_losses = 0
    total_skipped = 0

    for symbol in sorted(all_symbols):
        trades = [t for t in all_trades if t.symbol == symbol]
        for t in trades:
            if t.result == "SKIP":
                lines.append(f"{symbol:<8} {'SKIP':<7} {'—':>7} {'—':>7} {'—':>8} {'—':>7} {t.skip_reason or 'skip':<12}")
                total_skipped += 1
            else:
                sign = "+" if (t.pnl_dollars or 0) >= 0 else ""
                pnl_str = f"{sign}${t.pnl_dollars:.2f}" if t.pnl_dollars is not None else "—"
                pnl_pct_str = f"{sign}{t.pnl_percent:.2%}" if t.pnl_percent is not None else "—"
                entry_str = f"{t.entry:.2f}" if t.entry else "—"
                exit_str = f"{t.exit_price:.2f}" if t.exit_price else "—"
                lines.append(f"{symbol:<8} {(t.signal or '—'):<7} {entry_str:>7} {exit_str:>7} {pnl_str:>8} {pnl_pct_str:>7} {(t.result or '—'):<12}")
                total_pnl += t.pnl_dollars or 0
                if t.result == "WIN":
                    total_wins += 1
                elif t.result in ("LOSS", "FORCED_CLOSE"):
                    total_losses += 1

        # Save per-symbol daily summary to DB
        stats = _build_trade_stats(trades)
        save_daily_summary(
            date, symbol,
            stats["total"], stats["wins"], stats["losses"], stats["skipped"],
            stats["net_pnl"], stats["win_rate"], account_value,
        )

    lines.append("-" * 50)
    total_traded = total_wins + total_losses
    win_rate = (total_wins / total_traded) if total_traded > 0 else 0.0
    sign = "+" if total_pnl >= 0 else ""
    lines.append(f"Total trades: {total_traded} | Wins: {total_wins} | Losses: {total_losses} | Skipped: {total_skipped}")
    lines.append(f"Net P&L today: {sign}${total_pnl:.2f} | Win rate: {win_rate:.0%} ({total_wins}/{total_traded})")
    lines.append(f"Account value: ${account_value:,.2f}")
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
