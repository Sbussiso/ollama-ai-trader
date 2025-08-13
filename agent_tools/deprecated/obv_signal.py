# ===============================
# obv signal tool
# ===============================
from typing import Dict
import pandas as pd
from base_candles import get_coinbase_candles_df
try:
    from indicators import obv, sma
except ImportError:  # allow running as a script: python agent_tools/obv_signal.py
    from .indicators import obv, sma


def get_latest_obv(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    limit: int = 300,
    obv_ma_period: int = 20,
) -> Dict:
    df = get_coinbase_candles_df(product_id, granularity, limit)
    close = pd.Series(df["close"].values)
    vol = pd.Series(df["volume"].values)
    _obv = obv(close, vol)
    _ma = sma(pd.Series(_obv), obv_ma_period)
    obv_val = float(_obv[-1])
    obv_ma = float(_ma[-1]) if len(_ma) else float("nan")
    return {
        "obv": obv_val,
        "obv_ma": obv_ma,
        "volume_confirms_trend": bool(obv_val > obv_ma),
        "volume_denies_trend": bool(obv_val < obv_ma),
    }


if __name__ == "__main__":
    print(get_latest_obv(product_id="BTC-USD", granularity="1H", limit=300, obv_ma_period=20))
    