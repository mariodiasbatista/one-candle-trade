import os
import tempfile

# Create an isolated temp DB file before any src imports
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

# Blank the Telegram credentials before src.config is imported, so the whole
# suite is structurally incapable of sending a real message.
#
# This is not belt-and-braces. main.py builds a module-level
# `telegram = TelegramReporter()`, and the job functions call it directly — so
# any test that exercises a job without patching `main.telegram` sends a real
# alert to the live chat. test_main_jobs.py did exactly that: it patched
# main.logger but not main.telegram, so every suite run fired
# "Force Close failed: API error" at the real bot owner, from the
# Exception("API error") fixture.
#
# Patching each test is the fragile fix — the next job test forgets again.
# src.config reads these with os.getenv(..., ""), and load_dotenv() does not
# override values already in os.environ, so setting them empty here makes
# telegram._send() and send_system_alert() return before any network call.
# Tests that need a configured reporter patch the module attributes directly
# (see test_telegram.py), which still works.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

import pytest
from datetime import datetime, timedelta
import pytz

ET = pytz.timezone("America/New_York")
_BASE_DT = datetime(2026, 5, 7, 9, 35, tzinfo=ET)


def make_candle(open_p, high, low, close, volume=100_000, minute_offset=0):
    from src.models import Candle
    return Candle(
        timestamp=_BASE_DT + timedelta(minutes=minute_offset),
        open=open_p, high=high, low=low, close=close, volume=volume,
    )


def make_flat_candles(n, price=100.0, volume=100_000):
    """n candles with tiny bodies (body=0.01) for avg_body baseline."""
    return [make_candle(price, price + 0.05, price - 0.05, price + 0.01, volume, i) for i in range(n)]


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create the schema once for the whole session.

    Any code path that reads the DB needs the tables to exist, and reads now
    happen in common paths (execute_signal checks for an existing trade before
    submitting). Without this, adding a DB read to shared code breaks unrelated
    tests with "no such table". Creates tables only — it inserts nothing, so
    tests needing a clean slate still use clean_db.
    """
    from src.db.schema import Base, engine
    Base.metadata.create_all(engine)


@pytest.fixture
def clean_db():
    from src.db.schema import Base, engine
    Base.metadata.create_all(engine)
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


def pytest_sessionfinish(session, exitstatus):
    try:
        os.unlink(_db_path)
    except OSError:
        pass
