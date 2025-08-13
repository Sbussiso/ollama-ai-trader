# ===============================
# base_candles.py
# Robust Coinbase candle fetch with retries + UTC handling
# ===============================
import http.client
import json
import time
from typing import Optional, Tuple

import pandas as pd

_GRAN_MAP = {
    "1M": 60,
    "5M": 300,
    "15M": 900,
    "1H": 3600,
    "6H": 21600,
    "1D": 86400,
}


def _request_with_retries(path: str, retries: int = 5, backoff: float = 0.5) -> Tuple[int, str]:
    last_status = 0
    last_reason = ""
    for i in range(retries):
        try:
            conn = http.client.HTTPSConnection("api.exchange.coinbase.com", timeout=20)
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "SB-OneShotTrader/1.0",
            }
            conn.request("GET", path, body=None, headers=headers)
            resp = conn.getresponse()
            data = resp.read().decode("utf-8")
            status, reason = resp.status, resp.reason
            conn.close()
            if status == 200:
                return status, data
            last_status, last_reason = status, reason
        except Exception as e:
            last_status, last_reason = 0, str(e)
        sleep_for = backoff * (2 ** i)
        time.sleep(sleep_for)
    raise RuntimeError(f"HTTP failed after {retries} retries: status={last_status}, reason={last_reason}")


def get_coinbase_candles_df(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    limit: int = 300,
) -> pd.DataFrame:
    if granularity not in _GRAN_MAP:
        raise ValueError(f"Invalid granularity. Use: {list(_GRAN_MAP.keys())}")
    gran = _GRAN_MAP[granularity]
    path = f"/products/{product_id}/candles?granularity={gran}"
    status, raw = _request_with_retries(path)
    arr = json.loads(raw)
    if isinstance(arr, dict) and arr.get("message"):
        raise RuntimeError(arr["message"])
    rows = [r for r in arr[:limit] if isinstance(r, list) and len(r) >= 6]
    if not rows:
        raise RuntimeError("No candle data returned")
    df = pd.DataFrame(rows, columns=["timestamp", "low", "high", "open", "close", "volume"]).astype(
        {
            "timestamp": "int64",
            "low": "float64",
            "high": "float64",
            "open": "float64",
            "close": "float64",
            "volume": "float64",
        }
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def get_coinbase_candles_df_range(
    product_id: str = "BTC-USD",
    granularity: str = "1H",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    from datetime import datetime, timedelta, timezone

    if granularity not in _GRAN_MAP:
        raise ValueError(f"Invalid granularity. Use: {list(_GRAN_MAP.keys())}")

    def _to_utc(x) -> datetime:
        if x is None:
            return None
        if isinstance(x, datetime):
            return x.astimezone(timezone.utc) if x.tzinfo else x.replace(tzinfo=timezone.utc)
        s = str(x).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            dt = pd.to_datetime(s, utc=True).to_pydatetime()
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    end_dt = _to_utc(end) or datetime.now(timezone.utc)
    start_dt = _to_utc(start) or (end_dt - timedelta(days=365))  # 1 year default

    gran = _GRAN_MAP[granularity]
    chunk = gran * 300  # max per CB request

    all_rows = []
    cur = start_dt
    while cur < end_dt:
        chunk_end = min(cur + timedelta(seconds=chunk), end_dt)
        s = cur.isoformat().replace("+00:00", "Z")
        e = chunk_end.isoformat().replace("+00:00", "Z")
        path = f"/products/{product_id}/candles?granularity={gran}&start={s}&end={e}"
        status, raw = _request_with_retries(path)
        arr = json.loads(raw)
        if isinstance(arr, dict) and arr.get("message"):
            raise RuntimeError(arr["message"])
        rows = [r for r in arr if isinstance(r, list) and len(r) >= 6]
        all_rows.extend(rows)
        cur = chunk_end

    if not all_rows:
        raise RuntimeError("No candle data returned for range")

    df = pd.DataFrame(all_rows, columns=["timestamp", "low", "high", "open", "close", "volume"]).astype(
        {
            "timestamp": "int64",
            "low": "float64",
            "high": "float64",
            "open": "float64",
            "close": "float64",
            "volume": "float64",
        }
    )
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)
