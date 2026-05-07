"""
Force-runs the 9:00 AM → 9:36 AM pipeline against a past trading date.
Usage: python3 force_run.py [YYYY-MM-DD]
"""
import sys
import logging
from unittest.mock import patch
from datetime import datetime
import pytz

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

ET = pytz.timezone("America/New_York")

TARGET_DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-05-06"

# Patch datetime.now in data_retriever and alpaca_data so all internal
# calls to datetime.now(ET) return the target date at 9:36 AM ET.
fake_now = ET.localize(datetime.strptime(f"{TARGET_DATE} 09:36:00", "%Y-%m-%d %H:%M:%S"))

import src.agents.data_retriever as dr_module

with patch.object(dr_module, "datetime") as mock_dt:
    mock_dt.now.return_value = fake_now
    mock_dt.strptime = datetime.strptime  # keep strptime working

    from src.agents.data_retriever import DataRetriever
    from src.agents.analyst import Analyst
    from src.db.schema import init_db

    init_db()

    retriever = DataRetriever()
    analyst = Analyst()

    print(f"\n=== PRE-MARKET CHECK ({TARGET_DATE}) ===")
    contexts = retriever.run_premarket_checks()
    for symbol, ctx in contexts.items():
        status = "PASS" if ctx.trade_allowed else f"SKIP — {ctx.skip_reason}"
        print(f"  {symbol}: {status}")

    print(f"\n=== MARK FIRST CANDLE LEVELS ===")
    retriever.mark_first_candle_levels()
    for symbol, ctx in retriever.get_contexts().items():
        if ctx.first_candle:
            print(f"  {symbol}: HIGH={ctx.key_high} LOW={ctx.key_low} RANGE={ctx.candle_range:.2f} ATR={ctx.atr_14_daily:.2f} range_valid={ctx.candle_range_valid}")
        else:
            print(f"  {symbol}: SKIP — {ctx.skip_reason}")

    print(f"\n=== FVG MONITORING (one cycle) ===")
    contexts = retriever.update_1min_candles()
    for symbol, ctx in contexts.items():
        if not ctx.trade_allowed:
            continue
        signal = analyst.analyze(ctx)
        if signal:
            print(f"  {symbol}: SIGNAL {signal.signal} entry={signal.entry} SL={signal.stop_loss} TP={signal.take_profit}")
        else:
            print(f"  {symbol}: No valid signal")
