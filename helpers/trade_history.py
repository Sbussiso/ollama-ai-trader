#!/usr/bin/env python
"""
Trade History tool, extracted from portfolio_performance.py
Provides:
- get_trade_history(limit, strategy_filter) -> Dict
- get_trade_history_tool(limit, strategy_filter) -> str (agent-friendly)
"""

import logging
from typing import Dict, Any
from agent_tools.trade_tracker import trade_tracker

logger = logging.getLogger(__name__)


def get_trade_history(limit: int = 20, strategy_filter: str = None) -> Dict[str, Any]:
    """
    Get detailed trade history for analysis.
    
    Args:
        limit: Maximum number of trades to return (default 20)
        strategy_filter: Optional strategy name to filter results
    
    Returns:
        Dict containing detailed trade history
    """
    try:
        logger.info(f"📋 Retrieving trade history (limit: {limit})")
        
        # Get trades from database directly
        import sqlite3
        
        conn = sqlite3.connect(trade_tracker.db_path)
        cursor = conn.cursor()
        
        # Build query with optional strategy filter
        query = "SELECT trade_id, strategy, product_id, side, entry_price, exit_price, quantity, realized_pnl, status, entry_time, exit_time, fees_paid, notes FROM trades"
        params = []
        
        if strategy_filter:
            query += " WHERE strategy = ?"
            params.append(strategy_filter)
            
        query += " ORDER BY entry_time DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        raw_trades = cursor.fetchall()
        conn.close()
        
        if not raw_trades:
            logger.warning("⚠️ No trades found in database")
            return {
                "success": True,
                "trade_count": 0,
                "trades": [],
                "summary": "No trading history available"
            }
        
        # Process and format trades
        formatted_trades = []
        for row in raw_trades:
            # Calculate P&L percentage if we have both entry and exit prices
            pnl_percentage = None
            holding_period_hours = None
            
            if row[4] is not None and row[5] is not None:  # entry_price and exit_price
                pnl_percentage = ((row[5] - row[4]) / row[4]) * 100
                
            # Calculate holding period if we have both times
            if row[9] is not None and row[10] is not None:  # entry_time and exit_time
                from datetime import datetime
                try:
                    entry_dt = datetime.fromisoformat(row[9].replace('Z', '+00:00'))
                    exit_dt = datetime.fromisoformat(row[10].replace('Z', '+00:00'))
                    holding_period_hours = (exit_dt - entry_dt).total_seconds() / 3600
                except:
                    holding_period_hours = None
            
            formatted_trade = {
                "trade_id": row[0],
                "strategy": row[1],
                "product_id": row[2],
                "side": row[3],
                "status": row[8],
                "entry_price": row[4],
                "exit_price": row[5],
                "quantity": row[6],
                "realized_pnl": row[7],
                "pnl_percentage": round(pnl_percentage, 2) if pnl_percentage is not None else None,
                "entry_time": row[9],
                "exit_time": row[10],
                "holding_period_hours": round(holding_period_hours, 1) if holding_period_hours is not None else None,
                "fees_paid": row[11],
                "notes": row[12]
            }
            formatted_trades.append(formatted_trade)
        
        result = {
            "success": True,
            "trade_count": len(formatted_trades),
            "strategy_filter": strategy_filter or "ALL_STRATEGIES",
            "trades": formatted_trades,
            "summary": f"Retrieved {len(formatted_trades)} trades from history"
        }
        
        logger.info(f"✅ Trade history retrieved: {len(formatted_trades)} trades")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error retrieving trade history: {str(e)}")
        return {
            "success": False,
            "error": f"Trade history retrieval failed: {str(e)}",
            "trade_count": 0,
            "trades": []
        }


def get_trade_history_tool(limit: int = 10, strategy_filter: str = None) -> str:
    """
    Agent tool wrapper for trade history retrieval.
    Returns formatted string with recent trade details.
    """
    try:
        result = get_trade_history(limit=limit, strategy_filter=strategy_filter)
        
        if not result.get("success", False):
            return f"❌ Trade history failed: {result.get('error', 'Unknown error')}"
        
        if result["trade_count"] == 0:
            return "📋 No trades found in history database"
        
        # Format response for agent
        response_lines = [
            f"📋 TRADE HISTORY ({result['trade_count']} trades)",
            f"Strategy Filter: {result['strategy_filter']}",
            ""
        ]
        
        for i, trade in enumerate(result["trades"][:limit], 1):
            status_val = (trade.get("status") or "").lower()
            status_emoji = "✅" if status_val == "closed" else "🔄"
            # Safely interpret realized_pnl for emoji selection
            _rp = trade.get("realized_pnl")
            try:
                rpnl = float(_rp) if _rp is not None else 0.0
            except Exception:
                rpnl = 0.0
            pnl_emoji = "💚" if rpnl > 0 else "❌" if rpnl < 0 else "➖"
            
            trade_lines = [
                f"{status_emoji} Trade #{i} ({trade['trade_id']})",
                f"   Strategy: {trade['strategy']} | {trade['product_id']} | {trade['side'].upper()}",
                f"   Entry: ${trade['entry_price']:.2f} | Exit: ${trade.get('exit_price', 'PENDING'):.2f}" if trade.get('exit_price') else f"   Entry: ${trade['entry_price']:.2f} | Exit: PENDING",
                f"   Quantity: {trade['quantity']} | Status: {trade['status']}"
            ]
            
            if trade.get("realized_pnl") is not None:
                pnl_pct = trade.get("pnl_percentage")
                pct_str = f"{float(pnl_pct):.2f}%" if isinstance(pnl_pct, (int, float)) else "N/A"
                trade_lines.append(f"   {pnl_emoji} P&L: ${float(trade['realized_pnl']):.2f} ({pct_str})")
            
            if trade.get("holding_period_hours"):
                trade_lines.append(f"   ⏱️ Held: {trade['holding_period_hours']:.1f} hours")
            
            response_lines.extend(trade_lines)
            response_lines.append("")
        
        return "\n".join(response_lines)
        
    except Exception as e:
        logger.error(f"❌ Trade history tool error: {str(e)}")
        return f"❌ Trade history tool failed: {str(e)}"


if __name__ == "__main__":
    history = get_trade_history_tool()
    logger.info(history)
