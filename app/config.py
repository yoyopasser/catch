from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = DATA_DIR / "cache"
HISTORY_DIR = CACHE_DIR / "history"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "stock_tool.db"

for path in (DATA_DIR, CACHE_DIR, HISTORY_DIR, EXPORT_DIR):
    path.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class StrategyDefaults:
    history_days: int = 260
    min_history_rows: int = 90
    pivot_window: int = 2
    volume_ratio_stock: float = 1.30
    volume_ratio_etf: float = 1.15
    red_body_stock: float = 0.02
    red_body_etf: float = 0.008
    max_extension_atr_stock: float = 2.0
    max_extension_atr_etf: float = 1.8
    min_risk_reward: float = 1.5
    preferred_risk_reward: float = 2.0
    default_risk_per_trade_pct: float = 0.01
    max_position_pct: float = 0.20
    liquidity_percentile_cutoff: float = 0.30
    max_workers: int = 8
    request_timeout_seconds: int = 18
    history_cache_hours: int = 8
    snapshot_cache_minutes: int = 5


DEFAULTS = StrategyDefaults()

TWSE_DAILY_ALL_URL = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_DAILY_ALL_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
