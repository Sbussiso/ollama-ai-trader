# ===============================
# signal_hub.py
# Unified RSI + EMA crossover + OBV (+ optional ATR)
# ===============================
from typing import Dict, Any
import logging
import json
import numpy as np
import pandas as pd

try:
    from helpers.base_candles import get_coinbase_candles_df
except ImportError:
    import os, sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from helpers.base_candles import get_coinbase_candles_df  # type: ignore
try:
    from helpers.indicators import (
        rsi_wilder,
        ema,
        resampled_ema_trend,
        obv as obv_calc,
        sma,
        atr_wilder,
    )
except ImportError:  # fallback when executed with different CWD
    import os, sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from helpers.indicators import (  # type: ignore
        rsi_wilder,
        ema,
        resampled_ema_trend,
        obv as obv_calc,
        sma,
        atr_wilder,
    )

logger = logging.getLogger(__name__)


def _normalize_granularity(g: str) -> str:
    if not g:
        return "1H"
    m = g.strip().upper()
    aliases = {
        "1MIN": "1M", "1MINUTE": "1M", "ONE_MIN": "1M", "ONE_MINUTE": "1M",
        "5MIN": "5M", "5MINUTE": "5M",
        "15MIN": "15M", "15MINUTE": "15M",
        "1HR": "1H", "1 H": "1H", "ONE_HOUR": "1H",
        "6HR": "6H", "6 H": "6H",
        "1DAY": "1D", "1 D": "1D", "ONE_DAY": "1D",
    }
    if m in aliases:
        return aliases[m]
    if m in {"1M", "5M", "15M", "1H", "6H", "1D"}:
        return m
    return m.replace("MIN", "M").replace("HR", "H").replace("DAY", "D").replace(" ", "")


def _last_finite(series: pd.Series) -> float:
    idx = np.where(~series.isna().to_numpy())[0]
    if idx.size == 0:
        return float("nan")
    return float(series.iloc[int(idx[-1])])


def get_signals_tool(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    limit: int = 300,
    # RSI
    rsi_period: int = 14,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    # EMA crossover
    ema_fast: int = 20,
    ema_slow: int = 50,
    buffer_pct: float = 0.004,
    confirm_timeframe: str = "6H",
    # OBV
    obv_ma_period: int = 20,
    # ATR (optional)
    include_atr: bool = True,
    atr_period: int = 14,
    # Output
    return_format: str = "summary",  # summary | json
) -> str:
    """
    Compute RSI, EMA crossover (with HTF confirmation), OBV trend confirmation,
    and optional ATR using a single candle fetch.

    Returns a concise summary string by default, or JSON when return_format="json".
    """
    try:
        granularity = _normalize_granularity(granularity)
        # resampling rule prefers lowercase (pandas)
        confirm_rule = confirm_timeframe.strip().lower() if confirm_timeframe else "6h"

        df = get_coinbase_candles_df(product_id, granularity, limit)
        if df is None or df.empty:
            return f"Error: No candle data for {product_id} @ {granularity}"

        close = pd.Series(df["close"].values)
        high = pd.Series(df["high"].values)
        low = pd.Series(df["low"].values)
        vol = pd.Series(df["volume"].values)
        idx = pd.to_datetime(df["datetime"].values)

        # --- RSI ---
        rsi_vals = rsi_wilder(close, rsi_period)
        rsi_series = pd.Series(rsi_vals)
        rsi_value = _last_finite(rsi_series)
        if not np.isfinite(rsi_value):
            rsi_state = "unavailable"
        elif rsi_value <= rsi_oversold:
            rsi_state = "oversold"
        elif rsi_value >= rsi_overbought:
            rsi_state = "overbought"
        else:
            rsi_state = "neutral"

        # --- EMA crossover ---
        ef = ema(close, ema_fast)
        es = ema(close, ema_slow)
        ema_fast_val = float(ef[-1]) if len(ef) else float("nan")
        ema_slow_val = float(es[-1]) if len(es) else float("nan")
        ema_state = "neutral"
        if np.isfinite(ema_fast_val) and np.isfinite(ema_slow_val):
            if ema_fast_val > ema_slow_val * (1 + buffer_pct):
                ema_state = "bullish"
            elif ema_fast_val < ema_slow_val * (1 - buffer_pct):
                ema_state = "bearish"
        # HTF confirmation via resample of existing series
        htf_arr = resampled_ema_trend(pd.Series(close.values, index=idx), idx, confirm_rule, ema_fast, ema_slow, 0.0)
        htf_state_val = int(htf_arr[-1]) if len(htf_arr) else 0
        htf_state = "bull" if htf_state_val == 1 else ("bear" if htf_state_val == -1 else "neutral")

        # --- OBV ---
        obv_vals = obv_calc(close, vol)
        obv_last = float(obv_vals[-1]) if len(obv_vals) else float("nan")
        obv_ma_vals = sma(pd.Series(obv_vals), obv_ma_period)
        obv_ma_last = float(obv_ma_vals[-1]) if len(obv_ma_vals) else float("nan")
        obv_state = "neutral"
        if np.isfinite(obv_last) and np.isfinite(obv_ma_last):
            if obv_last > obv_ma_last:
                obv_state = "confirms"
            elif obv_last < obv_ma_last:
                obv_state = "denies"

        # --- ATR (optional) ---
        atr_value = None
        if include_atr:
            atrvals = atr_wilder(high, low, close, atr_period)
            atr_series = pd.Series(atrvals)
            atr_value = _last_finite(atr_series)

        price = float(close.iloc[-1]) if len(close) else float("nan")

        payload: Dict[str, Any] = {
            "product_id": product_id,
            "granularity": granularity,
            "price": price,
            "rsi": {
                "value": round(rsi_value, 2) if np.isfinite(rsi_value) else None,
                "state": rsi_state,
                "period": rsi_period,
                "oversold": rsi_oversold,
                "overbought": rsi_overbought,
            },
            "ema": {
                "fast": round(ema_fast_val, 2) if np.isfinite(ema_fast_val) else None,
                "slow": round(ema_slow_val, 2) if np.isfinite(ema_slow_val) else None,
                "state": ema_state,
                "htf": htf_state,
                "buffer_pct": buffer_pct,
            },
            "obv": {
                "value": round(obv_last, 2) if np.isfinite(obv_last) else None,
                "ma": round(obv_ma_last, 2) if np.isfinite(obv_ma_last) else None,
                "state": obv_state,
                "ma_period": obv_ma_period,
            },
            "atr": (round(atr_value, 2) if (include_atr and np.isfinite(atr_value)) else None),
        }

        if return_format.lower() == "json":
            return json.dumps(payload, separators=(",", ":"))

        # concise summary
        parts = [
            f"Signals for {product_id} @ {granularity}:",
            f"RSI={payload['rsi']['value'] if payload['rsi']['value'] is not None else 'NA'} ({rsi_state})",
            (
                f"EMA{ema_fast}>{ema_slow} (bullish)" if ema_state == "bullish" else
                (f"EMA{ema_fast}<{ema_slow} (bearish)" if ema_state == "bearish" else "EMA neutral")
            ),
            (
                "OBV>MA (confirms)" if obv_state == "confirms" else
                ("OBV<MA (denies)" if obv_state == "denies" else "OBV neutral")
            ),
        ]
        if include_atr and payload["atr"] is not None:
            parts.append(f"ATR={payload['atr']}")
        return " | ".join(parts)

    except Exception as e:
        logger.exception("signal_hub failed: %s", e)
        return f"Error in get_signals_tool: {str(e)}"
