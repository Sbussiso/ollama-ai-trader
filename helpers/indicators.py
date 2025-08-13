# indicators.py
# Shared, vectorized indicators + helpers used by backtest & live

from typing import Iterable
import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> np.ndarray:
    return series.ewm(span=span, adjust=False).mean().to_numpy()


def sma(series: pd.Series, period: int) -> np.ndarray:
    return series.rolling(period, min_periods=period).mean().to_numpy()


def rsi_wilder(close: pd.Series, period: int = 14) -> np.ndarray:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    ag = np.empty(len(close)); ag[:] = np.nan
    al = np.empty(len(close)); al[:] = np.nan

    if len(close) > period:
        ag[period] = gain.iloc[1:period + 1].mean()
        al[period] = loss.iloc[1:period + 1].mean()
        for i in range(period + 1, len(close)):
            ag[i] = (ag[i - 1] * (period - 1) + gain.iloc[i]) / period
            al[i] = (al[i - 1] * (period - 1) + loss.iloc[i]) / period

    rs = np.divide(ag, al, out=np.zeros_like(ag), where=al != 0)
    out = 100 - 100 / (1 + rs)
    out[:period + 1] = np.nan
    return out


def atr_wilder(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> np.ndarray:
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(),
                    (high - prev).abs(),
                    (low - prev).abs()], axis=1).max(axis=1)

    atr = np.empty(len(tr)); atr[:] = np.nan
    if len(tr) > period:
        atr[period] = tr.iloc[1:period + 1].mean()
        for i in range(period + 1, len(tr)):
            atr[i] = (atr[i - 1] * (period - 1) + tr.iloc[i]) / period
    return atr


def obv(close: pd.Series, volume: pd.Series) -> np.ndarray:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum().to_numpy()


def rolling_percentile(x: pd.Series, window: int = 200) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(window - 1, len(x)):
        w = x.iloc[i - window + 1:i + 1]
        out[i] = (w.rank(pct=True).iloc[-1] * 100.0)
    return out


def resampled_ema_trend(
    close: pd.Series,
    index: pd.DatetimeIndex,
    rule: str = "6h",   # NOTE: lowercase to avoid pandas FutureWarning
    fast: int = 20,
    slow: int = 50,
    buffer: float = 0.0
) -> np.ndarray:
    """
    Returns -1/0/1 using EMA(fast) vs EMA(slow) on a resampled series with optional buffer.
    """
    s = pd.Series(close.values, index=index)
    r = s.resample(rule, label="right", closed="right").last().dropna()
    efast = r.ewm(span=fast, adjust=False).mean()
    eslow = r.ewm(span=slow, adjust=False).mean()

    bull = efast > eslow * (1 + buffer)
    bear = efast < eslow * (1 - buffer)

    state = pd.Series(0, index=r.index)
    state[bull] = 1
    state[bear] = -1

    return state.reindex(index, method="ffill").fillna(0).to_numpy()


def daily_ema200_regime(close: pd.Series, index: pd.DatetimeIndex) -> np.ndarray:
    """
    - Output: 1 (bull, long-only), -1 (bear, short-only), 0 (neutral)
    - Logic: price above daily EMA200 AND EMA200 rising -> bull
             price below daily EMA200 AND EMA200 falling -> bear
    """
    s = pd.Series(close.values, index=index)
    r = s.resample("1d", label="right", closed="right").last().dropna()

    ema200 = r.ewm(span=200, adjust=False).mean()
    ema200_prev = ema200.shift(1)

    state = pd.Series(0, index=r.index)
    bull = (r > ema200) & (ema200 > ema200_prev)
    bear = (r < ema200) & (ema200 < ema200_prev)
    state[bull] = 1
    state[bear] = -1

    return state.reindex(index, method="ffill").fillna(0).to_numpy()
