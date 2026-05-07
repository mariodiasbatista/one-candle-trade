import os
import tempfile

# Create an isolated temp DB file before any src imports
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

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
