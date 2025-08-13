# ===============================
# rsi signal tool
# ===============================
from typing import Dict
import pandas as pd
import numpy as np
import logging
from base_candles import get_coinbase_candles_df
try:
    from indicators import rsi_wilder
except ImportError:  # allow running as a script: python agent_tools/rsi_signal.py
    from .indicators import rsi_wilder

logger = logging.getLogger(__name__)


def get_latest_rsi(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    limit: int = 300,
    period: int = 14,
    long_threshold: float = 50.0,
    short_threshold: float = 50.0,
) -> Dict:
    df = get_coinbase_candles_df(product_id, granularity, limit)
    close = pd.Series(df["close"].values)
    rsi = rsi_wilder(close, period)

    # Use the last finite RSI value to avoid trailing NaNs when the latest bucket is incomplete
    if len(rsi) == 0:
        return {"rsi": float("nan"), "momentum_ok_for_long": False, "momentum_ok_for_short": False}

    rsi_series = pd.Series(rsi)
    finite_idx = np.where(~rsi_series.isna().to_numpy())[0]

    if finite_idx.size == 0:
        logger.debug("RSI computation returned all NaN values (insufficient data?)")
        return {"rsi": float("nan"), "momentum_ok_for_long": False, "momentum_ok_for_short": False}

    last_i = int(finite_idx[-1])
    prev_i = int(finite_idx[-2]) if finite_idx.size >= 2 else last_i
    val = float(rsi_series.iloc[last_i])
    prev_val = float(rsi_series.iloc[prev_i])

    momentum_ok_for_long = bool(val > long_threshold and val > prev_val)
    momentum_ok_for_short = bool(val < short_threshold and val < prev_val)

    # Optional debug trace
    logger.debug(f"RSI[{granularity}] {product_id}: last={val:.2f}, prev={prev_val:.2f}, len={len(rsi)}")

    return {"rsi": val, "momentum_ok_for_long": momentum_ok_for_long, "momentum_ok_for_short": momentum_ok_for_short}


if __name__ == "__main__":
    print(get_latest_rsi(product_id="BTC-USD", granularity="1H", limit=300, period=14, long_threshold=50.0, short_threshold=50.0))