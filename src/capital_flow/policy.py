"""Central calculation and display policy for the capital-flow dashboard."""

from __future__ import annotations


ETF_CACHE_SECONDS = 30 * 60
FLOW_WINDOWS: tuple[tuple[str, str, int], ...] = (
    ("1d", "1日", 1),
    ("5d", "5日", 5),
    ("20d", "20日", 20),
    ("60d", "60日", 60),
)
DEFAULT_FLOW_WINDOW = "1d"
FUND_DATE_LOOKBACK_BUFFER = 10
RECENT_SHARE_REQUIRED_LOOKBACK = 3

MIN_INDEX_SCALE_YI = 20.0
HSGT_UNIT_TO_YI = 0.0001
SPLIT_FACTORS = (2, 3, 4, 5, 10)
SPLIT_SHARE_TOLERANCE = 0.12
SPLIT_PRICE_TOLERANCE = 0.18

