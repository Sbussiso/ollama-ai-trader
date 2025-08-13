# ===============================
# ema_crossover.py  (kept for live diagnostics; now uses same rules)
# ===============================
from typing import Dict
import pandas as pd
from base_candles import get_coinbase_candles_df
try:
    from .indicators import ema, resampled_ema_trend
except ImportError:  # allow running as a script
    from indicators import ema, resampled_ema_trend


def get_ema_crossover_signal(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    limit: int = 300,
    buffer_pct: float = 0.004,
    confirm_timeframe: str = "6H",
    confirm_limit: int = 300,
) -> Dict:
    df = get_coinbase_candles_df(product_id, granularity, limit)
    close = pd.Series(df["close"].values)
    e20 = ema(close, 20)
    e50 = ema(close, 50)

    # hysteresis state
    state = 0
    if len(e20) >= 1 and len(e50) >= 1:
        if e20[-1] > e50[-1] * (1 + buffer_pct):
            state = 1
        elif e20[-1] < e50[-1] * (1 - buffer_pct):
            state = -1

    # HTF trend
    idx = pd.to_datetime(df["datetime"].values)
    htf_state = resampled_ema_trend(pd.Series(close.values, index=idx), idx, confirm_timeframe, 20, 50, 0.0)[-1]

    return {
        "price": float(df["close"].iloc[-1]),
        "ema_fast": float(e20[-1]),
        "ema_slow": float(e50[-1]),
        "bullish": bool(state == 1),
        "bearish": bool(state == -1),
        "htf_state": int(htf_state),
    }