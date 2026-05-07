# One Candle Trade — V3

Paper trading bot implementing a **First 5-min Candle Opening Range Breakout (ORB)** strategy with FVG and volume confirmation, executed via Alpaca and reported via Telegram.

---

## Schedule

All jobs run Monday–Friday (ET) automatically via APScheduler when `python3 main.py` is running.

| Time (ET) | Job | What it does |
|-----------|-----|--------------|
| 8:00 PM | Nightly Screener | Screens 40 symbols, updates tomorrow's watchlist |
| 9:00 AM | Pre-market Check | News + gap filter per symbol, sends Telegram alert |
| 9:36 AM | Mark First Candle | Fetches opening 5-min candle, applies ATR filter |
| 9:36–10:30 AM (every 60s) | FVG Monitor | Scans 1-min candles for FVG + volume, fires orders |
| 9:30–3:55 PM (every 5 min) | Position Monitor | Checks if open positions hit TP or SL |
| 3:55 PM | Force Close | Closes all open positions before market close |
| 4:05 PM | Daily Summary | Sends P&L report via Telegram |

---

## Full Decision Chain

A trade is only entered when **all conditions pass in sequence**. Any failure stops the chain and records a skip.

### 1. News Filter — 9:00 AM
Skip the day if a high-impact macro event is scheduled (FOMC, CPI, NFP, etc.).

### 2. Gap Filter — 9:00 AM
Two checks on pre-market data:
- Opening gap vs prior close must be **≤ 0.8%** — gaps larger than this indicate an extended move already underway
- Pre-market range must be **≤ 1.5%** of prior close — excessive pre-market volatility increases the chance of a false breakout

### 3. ATR Filter — 9:36 AM
The 9:30 opening 5-min candle range is compared against the 14-day ATR:
- Range must be **≥ 30% of ATR** — too small means no volatility to trade
- Range must be **≤ 120% of ATR** — too large means the move has already happened or risk is unmanageable

### 4. FVG Detection — 9:36–10:30 AM (every 60s)
Looks at the last three 1-min candles (A, B, C) and checks four conditions:

1. **Impulse body** — candle B's body is ≥ 1.5x the average body of the prior 5 candles (strong directional move)
2. **Gap exists** — a price gap between candles A and C (bullish: `C.low > A.high` / bearish: `C.high < A.low`)
3. **Level break** — the breakout direction aligns with the first candle's high or low being taken out
4. **Volume confirmation** — breakout candle C has volume ≥ 1.5x the 5-period average

All four must be true simultaneously for an FVG to be valid.

### 5. Entry
Once all conditions pass:
- **Entry price** — close of the breakout candle (candle C)
- **Stop loss** — two options, chosen automatically:
  - *Option A (FVG-based, tighter)* — used when the FVG gap is ≥ 30% of the first candle range; stop is placed just below/above the FVG gap
  - *Option B (First Candle)* — fallback; stop is placed just below the first candle low (LONG) or above the first candle high (SHORT)
- **Take profit** — 2:1 reward/risk ratio from entry
- **Position size** — risks 1% of account value per trade, capped at 5% of account in position value

### Signal Window
If no valid setup is found by **10:30 AM**, monitoring stops, a "no signal" Telegram notification is sent, and the day is recorded as a skip. No trades are taken after this cutoff.

The 10:30 AM cutoff aligns with the end of the classic Opening Range hour (9:30–10:30 AM). FVG setups after this point tend to have less institutional volume and momentum behind them, making follow-through less reliable and increasing the risk of chasing late breakouts that reverse. The cutoff is configurable via `SIGNAL_CUTOFF_HOUR` and `SIGNAL_CUTOFF_MINUTE` in `.env`.

---

## Setup

```bash
cp .env.example .env
# Fill in ALPACA_API_KEY, ALPACA_SECRET_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
python3 main.py
```

Get Alpaca paper trading keys at [app.alpaca.markets](https://app.alpaca.markets) (switch to Paper Trading mode).

---

## Project Structure

```
main.py                  # Scheduler + job definitions
src/
  config.py              # Env vars and strategy parameters
  models.py              # MarketContext, TradeSignal, FVGResult, Candle
  agents/
    data_retriever.py    # Agent 1 — fetches data, runs pre-market checks
    analyst.py           # Agent 2 — applies filters, detects FVG, generates signal
    investor.py          # Agent 3 — executes orders, monitors positions
  core/
    filters.py           # News, gap, ATR filters
    fvg.py               # FVG detection + volume confirmation
    risk.py              # Stop loss, take profit, position sizing
    screener.py          # Nightly symbol screener
  data/
    alpaca_data.py       # Alpaca market data client
    calendar.py          # High-impact event calendar
  db/
    schema.py            # SQLAlchemy table definitions
    repository.py        # DB read/write helpers
  reporting/
    telegram.py          # Telegram alert sender
    summary.py           # Daily/monthly/yearly P&L reports
```
