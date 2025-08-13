from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, List
import json
import logging

logger = logging.getLogger(__name__)


# -----------------------------
# Minimal paper trading engine
# -----------------------------

@dataclass
class Position:
    side: str = "FLAT"            # FLAT | LONG | SHORT
    size: float = 0.0             # asset units (e.g., BTC)
    entry_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    atr_at_entry: Optional[float] = None


class PaperBroker:
    """
    Standalone, dependency‑free paper trading core extracted from a larger project.
    You push prices in; it manages open/close/reverse, SL/TP, breakeven and trailing.

    Trailing logic (same as source):
      • Arm breakeven after +1×ATR in favor
      • After +1.5×ATR, trail by 1×ATR
    """

    def __init__(self, starting_balance: float = 10_000.0, state_path: Optional[str] = None):
        self.starting_balance = float(starting_balance)
        self.cash = float(starting_balance)
        self.position: Position = Position()
        self.trade_history: List[Dict] = []
        self.state_path = state_path
        if self.state_path:
            self._load()

    # -----------------------------
    # Persistence (optional)
    # -----------------------------
    def _save(self) -> None:
        if not self.state_path:
            return
        state = {
            "starting_balance": self.starting_balance,
            "cash": self.cash,
            "position": asdict(self.position),
            "trade_history": self.trade_history,
            "updated": datetime.now(timezone.utc).isoformat(),
        }
        with open(self.state_path, "w") as f:
            json.dump(state, f, indent=2)

    def _load(self) -> None:
        try:
            with open(self.state_path, "r") as f:
                s = json.load(f)
            self.starting_balance = float(s.get("starting_balance", self.starting_balance))
            self.cash = float(s.get("cash", self.cash))
            self.position = Position(**s.get("position", {}))
            self.trade_history = list(s.get("trade_history", []))
        except Exception:
            pass

    # -----------------------------
    # Sizing helper
    # -----------------------------
    @staticmethod
    def size_from_risk(risk_usd: float, price: float, atr: Optional[float], min_vol_frac: float = 0.001) -> float:
        """ATR‑aware unit sizing with a floor (matches source approach).
        Ensures you don't oversize in low‑vol regimes.
        """
        if atr is None or not (atr == atr) or atr <= 0:
            # If ATR unavailable, fallback to price * min_vol_frac as a proxy
            atr_for_size = max(price * min_vol_frac, 1e-12)
        else:
            atr_for_size = max(atr, price * min_vol_frac)
        return max(1e-9, float(risk_usd) / float(atr_for_size))

    # -----------------------------
    # Core order methods
    # -----------------------------
    def open_long(self, price: float, size: float, sl: Optional[float] = None, tp: Optional[float] = None, atr: Optional[float] = None) -> None:
        self.position = Position(side="LONG", size=float(size), entry_price=float(price), stop_loss=sl, take_profit=tp, atr_at_entry=atr)
        self.trade_history.append({
            "event": "OPEN", "side": "LONG", "size": float(size), "price": float(price),
            "sl": sl, "tp": tp, "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._save()

    def open_short(self, price: float, size: float, sl: Optional[float] = None, tp: Optional[float] = None, atr: Optional[float] = None) -> None:
        self.position = Position(side="SHORT", size=float(size), entry_price=float(price), stop_loss=sl, take_profit=tp, atr_at_entry=atr)
        self.trade_history.append({
            "event": "OPEN", "side": "SHORT", "size": float(size), "price": float(price),
            "sl": sl, "tp": tp, "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._save()

    def close(self, price: float, reason: str = "MANUAL") -> float:
        pos = self.position
        if pos.side == "FLAT" or pos.size <= 0:
            return 0.0
        if pos.side == "LONG":
            pnl = (float(price) - pos.entry_price) * pos.size
        else:  # SHORT
            pnl = (pos.entry_price - float(price)) * pos.size
        self.cash += pnl
        self.trade_history.append({
            "event": "CLOSE", "side": pos.side, "size": pos.size, "price": float(price),
            "pnl": pnl, "reason": reason, "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self.position = Position()
        self._save()
        return pnl

    def reverse_to_long(self, price: float, size: float, sl: Optional[float] = None, tp: Optional[float] = None, atr: Optional[float] = None) -> float:
        pnl = 0.0
        if self.position.side == "SHORT" and self.position.size > 0:
            pnl = self.close(price, reason="REVERSE")
        self.open_long(price, size, sl=sl, tp=tp, atr=atr)
        return pnl

    def reverse_to_short(self, price: float, size: float, sl: Optional[float] = None, tp: Optional[float] = None, atr: Optional[float] = None) -> float:
        pnl = 0.0
        if self.position.side == "LONG" and self.position.size > 0:
            pnl = self.close(price, reason="REVERSE")
        self.open_short(price, size, sl=sl, tp=tp, atr=atr)
        return pnl

    # -----------------------------
    # Mark‑to‑market & protective logic
    # -----------------------------
    def on_price(self, price: float) -> Optional[Dict]:
        """Call this whenever you have a new price.
        It updates trailing/BE and executes SL/TP if hit.
        Returns an exit event dict if a position was closed by SL/TP, else None.
        """
        pos = self.position
        if pos.side == "FLAT" or pos.size <= 0:
            return None

        last_price = float(price)
        atr = pos.atr_at_entry or 0.0

        # Arm BE at +1×ATR; trail by 1×ATR after +1.5×ATR
        if pos.side == "LONG" and atr > 0:
            profit = last_price - pos.entry_price
            if profit >= atr:
                pos.stop_loss = max(pos.stop_loss or -1e18, pos.entry_price)
            if profit >= 1.5 * atr:
                pos.stop_loss = max(pos.stop_loss or -1e18, last_price - atr)
        elif pos.side == "SHORT" and atr > 0:
            profit = pos.entry_price - last_price
            if profit >= atr:
                pos.stop_loss = min(pos.stop_loss or 1e18, pos.entry_price)
            if profit >= 1.5 * atr:
                pos.stop_loss = min(pos.stop_loss or 1e18, last_price + atr)

        # Check protective levels
        hit_sl = pos.stop_loss is not None and (
            (last_price <= pos.stop_loss and pos.side == "LONG") or
            (last_price >= pos.stop_loss and pos.side == "SHORT")
        )
        hit_tp = pos.take_profit is not None and (
            (last_price >= pos.take_profit and pos.side == "LONG") or
            (last_price <= pos.take_profit and pos.side == "SHORT")
        )

        if hit_sl or hit_tp:
            exit_price = pos.stop_loss if hit_sl else pos.take_profit
            pnl = self.close(exit_price, reason="SL" if hit_sl else "TP")
            event = {
                "event": "EXIT", "side": "LONG" if pnl >= 0 else "SHORT",  # side here is not critical
                "price": float(exit_price), "pnl": pnl, "timestamp": datetime.now(timezone.utc).isoformat()
            }
            self._save()
            return event

        self._save()
        return None

    # -----------------------------
    # Reporting
    # -----------------------------
    def summary(self, mark_price: Optional[float] = None) -> Dict:
        pos = self.position
        last_price = float(mark_price) if mark_price is not None else pos.entry_price
        unreal = 0.0
        if pos.side == "LONG" and pos.size > 0 and last_price:
            unreal = (last_price - pos.entry_price) * pos.size
        elif pos.side == "SHORT" and pos.size > 0 and last_price:
            unreal = (pos.entry_price - last_price) * pos.size
        total = self.cash + (pos.size * last_price if pos.side == "LONG" else 0.0)
        return {
            "cash": self.cash,
            "position": asdict(pos),
            "last_price": last_price,
            "equity": total,
            "pnl": total - self.starting_balance,
            "pnl_pct": ((total - self.starting_balance) / self.starting_balance * 100.0) if self.starting_balance else 0.0,
            "unrealized_pnl": unreal,
            "realized_pnl": self.cash - self.starting_balance,
        }


# -----------------------------
# Example usage
# -----------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    broker = PaperBroker(starting_balance=10_000.0, state_path=None)

    # Suppose you computed ATR and want to risk $25 per trade
    price = 50_000.0
    atr = 500.0
    size = PaperBroker.size_from_risk(25.0, price, atr)

    # Open a long with SL/TP based on ATR multiples (1.5× and 4× like source)
    broker.open_long(price=price, size=size, sl=price - 1.5 * atr, tp=price + 4.0 * atr, atr=atr)

    # Feed prices
    for p in [50_200, 50_800, 51_000, 51_200, 49_800, 49_500, 52_000, 52_500]:
        event = broker.on_price(p)
        if event:
            logger.info(f"Exit: {event}")
            break

    logger.info(f"Summary: {broker.summary(mark_price=52_500)}")
