from dotenv import load_dotenv
import os

load_dotenv()

# Alpaca paper trading
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
ALPACA_PAPER = True
INITIAL_ACCOUNT_VALUE = float(os.getenv("INITIAL_ACCOUNT_VALUE", "100000"))

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///one_candle_trade.db")

# Strategy parameters
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "0.05"))
FVG_BODY_RATIO_MIN = float(os.getenv("FVG_BODY_RATIO_MIN", "1.5"))
VOLUME_RATIO_MIN = float(os.getenv("VOLUME_RATIO_MIN", "1.5"))
ATR_MIN_RATIO = float(os.getenv("ATR_MIN_RATIO", "0.2"))
ATR_MAX_RATIO = float(os.getenv("ATR_MAX_RATIO", "1.2"))
GAP_THRESHOLD = float(os.getenv("GAP_THRESHOLD", "0.015"))
PREMARKET_VOLATILITY_THRESHOLD = float(os.getenv("PREMARKET_VOLATILITY_THRESHOLD", "0.015"))
SIGNAL_CUTOFF_HOUR = int(os.getenv("SIGNAL_CUTOFF_HOUR", "10"))
SIGNAL_CUTOFF_MINUTE = int(os.getenv("SIGNAL_CUTOFF_MINUTE", "30"))
REWARD_RISK_RATIO = float(os.getenv("REWARD_RISK_RATIO", "2.0"))

# Trade cost simulation (paper trading treated as real)
SLIPPAGE_PER_SHARE = float(os.getenv("SLIPPAGE_PER_SHARE", "0.01"))
SEC_FEE_RATE   = 0.0000278   # Section 31: $0.0000278 per $ of sale proceeds
FINRA_TAF_RATE = 0.000145    # FINRA TAF: $0.000145/share sold (max $7.27)
FINRA_TAF_MAX  = 7.27

# Watchlist
DEFAULT_WATCHLIST = [s.strip() for s in os.getenv("DEFAULT_WATCHLIST", "SPY,QQQ,NVDA,TSLA,AAPL").split(",")]

# Screener — volume threshold is IEX-feed adjusted (~2-5% of consolidated tape)
SCREENER_MIN_IEX_VOLUME = int(os.getenv("SCREENER_MIN_IEX_VOLUME", "200000"))

TIMEZONE = "America/New_York"
