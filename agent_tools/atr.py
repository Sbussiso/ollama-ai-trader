# ===============================
# atr.py
# ===============================
from typing import Dict
import logging
import pandas as pd
try:
    from helpers.base_candles import get_coinbase_candles_df
    from helpers.indicators import atr_wilder
except ImportError:
    # Fallback: adjust sys.path when executed from different working directories
    import os, sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from helpers.base_candles import get_coinbase_candles_df  # type: ignore
    from helpers.indicators import atr_wilder  # type: ignore


logger = logging.getLogger(__name__)


def get_latest_atr(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    limit: int = 300,
    period: int = 14,
) -> Dict:
    # Ensure we have enough bars for Wilder ATR smoothing to avoid NaNs
    min_required = max(period + 1, period * 5)
    eff_limit = max(limit, min_required)
    df = get_coinbase_candles_df(product_id, granularity, eff_limit)
    df = df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    n = len(df)

    atr_series = atr_wilder(pd.Series(df["high"].values), pd.Series(df["low"].values), pd.Series(df["close"].values), period)
    s = pd.Series(atr_series)
    if s.notna().any():
        atr_val = float(s[s.notna()].iloc[-1])
    else:
        atr_val = float("nan")
        logger.warning(
            "ATR computation returned all-NaN: product=%s gran=%s limit=%s period=%s bars=%s",
            product_id, granularity, limit, period, n,
        )
    price = float(df["close"].iloc[-1]) if n else float("nan")
    return {
        "product_id": product_id,
        "granularity": granularity,
        "period": period,
        "bars": n,
        "atr": atr_val,
        "price": price,
        "limit": eff_limit  # auto-bumped limit
    }