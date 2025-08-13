#!/usr/bin/env python
"""
Unified Paper Trading Tool wrapping PaperBroker from paper_trade.py.
Provides a single tool entrypoint: unified_trade_tool(...) for agent use.

Actions supported:
- open_long, open_short, reverse_to_long, reverse_to_short
- close
- on_price (advance price and apply SL/TP logic)
- summary (optional mark price)

Sizing:
- Provide either explicit size (asset units) or risk_usd with ATR to compute size

Persistence:
- Database-only: all trades and position context (SL/TP/ATR) are persisted in SQLite via
  agent_tools.trade_tracker. No JSON files are read or written.
Trailing/BE (optional):
- Store ATR-based trailing parameters in strategy_context at entry:
  move_to_be_atr (default 1.0), trail_start_atr (2.0), trail_distance_atr (1.25)
  These are applied on each on_price tick to update SL deterministically.
"""
import os
import json
import logging
import uuid
import sqlite3
from typing import Optional, Dict, Any

# Local import of PaperBroker from helpers package
try:
    from helpers.paper_trade import PaperBroker
except ImportError:
    # Allow running if called from different cwd by adjusting sys.path at runtime
    import sys
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from helpers.paper_trade import PaperBroker  # type: ignore

logger = logging.getLogger(__name__)

# DB trade tracker
try:
    from agent_tools.trade_tracker import trade_tracker
except Exception:
    trade_tracker = None  # type: ignore


def _get_db_conn():
    if trade_tracker is None:
        raise RuntimeError("trade_tracker is unavailable")
    return sqlite3.connect(trade_tracker.db_path)


def _reconstruct_broker_from_open_trade(open_trade: Dict[str, Any], starting_balance: float) -> PaperBroker:
    """Create an in-memory broker for protective logic based on DB open trade."""
    broker = PaperBroker(starting_balance=starting_balance, state_path=None)
    if open_trade:
        ctx = open_trade.get("strategy_context") or {}
        broker.position.side = "LONG" if (open_trade.get("side") == "buy") else "SHORT"
        broker.position.size = float(open_trade.get("quantity") or 0.0)
        broker.position.entry_price = float(open_trade.get("entry_price") or 0.0)
        broker.position.stop_loss = ctx.get("sl")
        broker.position.take_profit = ctx.get("tp")
        broker.position.atr_at_entry = ctx.get("atr")
    return broker


def _compute_summary(starting_balance: float, product_id: str, strategy: str, mark_price: Optional[float]) -> str:
    if trade_tracker is None:
        return "Error: DB tracker unavailable"
    # Realized PnL from closed trades for this strategy+product
    realized = 0.0
    try:
        conn = _get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades WHERE strategy = ? AND product_id = ? AND status = 'closed'",
            (strategy, product_id),
        )
        row = cur.fetchone()
        realized = float(row[0] or 0.0)
        # Fallback: if no realized PnL under this strategy, sum across product regardless of strategy
        if realized == 0.0:
            cur.execute(
                "SELECT COALESCE(SUM(realized_pnl), 0) FROM trades WHERE product_id = ? AND status = 'closed'",
                (product_id,),
            )
            row2 = cur.fetchone()
            realized = float(row2[0] or 0.0)
        conn.close()
    except Exception:
        realized = 0.0

    # Open trade unrealized
    open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=strategy)
    # Fallback: if no open trade found under this strategy, look for any open trade for the product
    if not open_trade:
        open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=None)
    unreal = 0.0
    pos_side = "FLAT"
    pos_size = 0.0
    entry = 0.0
    sl = None
    tp = None
    last_price = 0.0
    if open_trade:
        ctx = open_trade.get("strategy_context") or {}
        pos_side = "LONG" if open_trade.get("side") == "buy" else "SHORT"
        pos_size = float(open_trade.get("quantity") or 0.0)
        entry = float(open_trade.get("entry_price") or 0.0)
        sl = ctx.get("sl")
        tp = ctx.get("tp")
        last_price = float(mark_price if mark_price is not None else entry)
        if pos_side == "LONG":
            unreal = (last_price - entry) * pos_size
        else:
            unreal = (entry - last_price) * pos_size

    equity = starting_balance + realized + unreal
    pnl_total = equity - starting_balance
    pnl_pct = (pnl_total / starting_balance * 100.0) if starting_balance else 0.0
    return (
        f"Equity={equity:.2f} Cash={(starting_balance + realized):.2f} PnL={pnl_total:.2f} ({pnl_pct:.2f}%). "
        f"Pos={pos_side} size={pos_size:.8f} entry={entry:.2f} SL={sl} TP={tp}"
    )


def _ensure_size(size: Optional[float], risk_usd: Optional[float], price: Optional[float], atr: Optional[float]) -> float:
    if size is not None:
        return float(size)
    if risk_usd is None or price is None:
        raise ValueError("Provide either size or (risk_usd and price) for sizing")
    return PaperBroker.size_from_risk(risk_usd=float(risk_usd), price=float(price), atr=atr)


def unified_trade_tool(
    action: str,
    price: Optional[float] = None,
    side: str = "LONG",
    size: Optional[float] = None,
    risk_usd: Optional[float] = None,
    sl: Optional[float] = None,
    tp: Optional[float] = None,
    atr: Optional[float] = None,
    starting_balance: float = 10_000.0,
    state_path: Optional[str] = None,
    mark_price: Optional[float] = None,
    product_id: str = "BTC-USD",
    strategy: str = "PAPER_TRADE",
    notes: Optional[str] = None,
    move_to_be_atr: Optional[float] = None,
    trail_start_atr: Optional[float] = None,
    trail_distance_atr: Optional[float] = None,
) -> str:
    """
    Unified paper trading tool (DB-only). Returns concise, model-friendly strings.

    Params:
      - action: one of {'open_long','open_short','close','reverse_to_long','reverse_to_short','on_price','summary'}
      - price: current price (required for open/close/reverse/on_price)
      - side: LONG/SHORT (used for open_* actions)
      - size: asset units to trade (optional if risk_usd+atr given)
      - risk_usd: $ risk per trade; used with ATR to compute size if size not given
      - sl/tp: stop loss / take profit prices (optional)
      - atr: average true range at entry (optional but recommended for sizing/trailing)
      - starting_balance: only used for summary math (DB holds trade state)
      - state_path: DEPRECATED/ignored (DB-only persistence)
      - mark_price: used by summary to compute unrealized PnL
    """
    try:
        # DB-only persistence; construct an in-memory broker only when needed for protective logic

        act = (action or "").lower()
        if act in ("open_long", "open_short"):
            if price is None:
                return "Error: price is required for open actions"
            trade_size = _ensure_size(size, risk_usd, price, atr)
            if trade_tracker is None:
                return "Error: DB tracker unavailable"
            entry_order_id = f"paper_entry_{uuid.uuid4().hex[:12]}"
            # Defaults for ATR-based management
            mbe = 1.0 if move_to_be_atr is None else float(move_to_be_atr)
            tstart = 2.0 if trail_start_atr is None else float(trail_start_atr)
            tdist = 1.25 if trail_distance_atr is None else float(trail_distance_atr)
            if act == "open_long":
                trade_tracker.record_trade_entry(
                    strategy=strategy,
                    product_id=product_id,
                    side="buy",
                    entry_price=float(price),
                    quantity=trade_size,
                    order_id=entry_order_id,
                    strategy_context={
                        "atr": atr, "sl": sl, "tp": tp, "side": "LONG",
                        "move_to_be_atr": mbe, "trail_start_atr": tstart, "trail_distance_atr": tdist,
                    },
                    notes=notes or ""
                )
                return f"Opened LONG size={trade_size:.8f} @ {float(price):.2f} SL={sl} TP={tp}"
            else:
                trade_tracker.record_trade_entry(
                    strategy=strategy,
                    product_id=product_id,
                    side="sell",
                    entry_price=float(price),
                    quantity=trade_size,
                    order_id=entry_order_id,
                    strategy_context={
                        "atr": atr, "sl": sl, "tp": tp, "side": "SHORT",
                        "move_to_be_atr": mbe, "trail_start_atr": tstart, "trail_distance_atr": tdist,
                    },
                    notes=notes or ""
                )
                return f"Opened SHORT size={trade_size:.8f} @ {float(price):.2f} SL={sl} TP={tp}"

        if act == "close":
            if price is None:
                return "Error: price is required for close"
            if trade_tracker is None:
                return "Error: DB tracker unavailable"
            open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=strategy)
            if not open_trade:
                open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=None)
            if not open_trade:
                return "No open position to close"
            exit_order_id = f"paper_exit_{uuid.uuid4().hex[:12]}"
            res = trade_tracker.record_trade_exit(
                trade_id=open_trade["trade_id"],
                exit_price=float(price),
                exit_order_id=exit_order_id,
                fees_paid=0.0,
            )
            if "error" in res:
                return f"Error closing trade: {res['error']}"
            return f"Closed position. Realized PnL={res['net_pnl']:.2f}"

        if act in ("reverse_to_long", "reverse_to_short"):
            if price is None:
                return "Error: price is required for reverse"
            trade_size = _ensure_size(size, risk_usd, price, atr)
            if trade_tracker is None:
                return "Error: DB tracker unavailable"
            # Exit existing position if any
            open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=strategy)
            if not open_trade:
                open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=None)
            if open_trade:
                trade_tracker.record_trade_exit(
                    trade_id=open_trade["trade_id"],
                    exit_price=float(price),
                    exit_order_id=f"paper_reverse_exit_{uuid.uuid4().hex[:8]}",
                    fees_paid=0.0,
                )
            # Enter new side
            entry_order_id = f"paper_entry_{uuid.uuid4().hex[:12]}"
            if act == "reverse_to_long":
                trade_tracker.record_trade_entry(
                    strategy=strategy,
                    product_id=product_id,
                    side="buy",
                    entry_price=float(price),
                    quantity=trade_size,
                    order_id=entry_order_id,
                    strategy_context={"atr": atr, "sl": sl, "tp": tp, "side": "LONG"},
                    notes=notes or ""
                )
                return f"Reversed to LONG size={trade_size:.8f} @ {float(price):.2f}"
            else:
                trade_tracker.record_trade_entry(
                    strategy=strategy,
                    product_id=product_id,
                    side="sell",
                    entry_price=float(price),
                    quantity=trade_size,
                    order_id=entry_order_id,
                    strategy_context={"atr": atr, "sl": sl, "tp": tp, "side": "SHORT"},
                    notes=notes or ""
                )
                return f"Reversed to SHORT size={trade_size:.8f} @ {float(price):.2f}"

        if act == "on_price":
            if price is None:
                return "Error: price is required for on_price"
            if trade_tracker is None:
                return "Error: DB tracker unavailable"
            open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=strategy)
            if not open_trade:
                open_trade = trade_tracker.get_open_trade(product_id=product_id, strategy=None)
            if not open_trade:
                return "No open position to manage"
            broker = _reconstruct_broker_from_open_trade(open_trade, starting_balance=starting_balance)
            ctx = open_trade.get("strategy_context") or {}
            # ATR-based trailing & break-even logic before evaluating exit
            try:
                atr_val = float(ctx.get("atr") or 0.0)
            except Exception:
                atr_val = 0.0
            try:
                mbe = float(ctx.get("move_to_be_atr", 1.0))
                tstart = float(ctx.get("trail_start_atr", 2.0))
                tdist = float(ctx.get("trail_distance_atr", 1.25))
            except Exception:
                mbe, tstart, tdist = 1.0, 2.0, 1.25

            side = ctx.get("side") or ("LONG" if open_trade.get("side") == "buy" else "SHORT")
            entry = float(open_trade.get("entry_price") or 0.0)
            cur_sl = broker.position.stop_loss if broker.position.stop_loss is not None else ctx.get("sl")
            new_sl = None
            p = float(price)
            if atr_val and entry:
                if side == "LONG":
                    # Move to BE
                    be_px = entry + mbe * atr_val
                    if p >= be_px:
                        be_sl = entry
                        if cur_sl is None or be_sl > (cur_sl or -float("inf")):
                            new_sl = be_sl
                    # Trailing after start
                    start_px = entry + tstart * atr_val
                    if p >= start_px:
                        t_sl = p - tdist * atr_val
                        candidate = max(cur_sl or -float("inf"), t_sl)
                        if cur_sl is None or candidate > cur_sl:
                            new_sl = candidate
                else:
                    # SHORT
                    be_px = entry - mbe * atr_val
                    if p <= be_px:
                        be_sl = entry
                        if cur_sl is None or be_sl < (cur_sl or float("inf")):
                            new_sl = be_sl
                    start_px = entry - tstart * atr_val
                    if p <= start_px:
                        t_sl = p + tdist * atr_val
                        candidate = min(cur_sl or float("inf"), t_sl)
                        if cur_sl is None or candidate < cur_sl:
                            new_sl = candidate

            if new_sl is not None:
                broker.position.stop_loss = float(new_sl)
                trade_tracker.update_strategy_context(open_trade["trade_id"], {"sl": float(new_sl)})

            event = broker.on_price(float(p))
            if event:
                trade_tracker.record_trade_exit(
                    trade_id=open_trade["trade_id"],
                    exit_price=float(event["price"]),
                    exit_order_id=f"paper_auto_exit_{uuid.uuid4().hex[:8]}",
                    fees_paid=0.0,
                )
                return f"Exit event at {float(event['price']):.2f}. Realized PnL={float(event['pnl']):.2f}"
            return "No exit. Position managed."

        if act == "summary":
            return _compute_summary(starting_balance=starting_balance, product_id=product_id, strategy=strategy, mark_price=mark_price)

        return "Error: unsupported action. Use open_long/open_short/close/reverse_to_long/reverse_to_short/on_price/summary"

    except Exception as e:
        logger.exception("unified_trade_tool failed")
        return f"Error in unified_trade_tool: {str(e)}"
