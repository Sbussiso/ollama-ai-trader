#!/usr/bin/env python
"""
Integrated Trade Tracking System for AI Trading Agent

This system automatically tracks all trades placed by the agent,
calculates P&L, and provides performance analytics.
"""

import sqlite3
import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import pandas as pd

# Configure logging
logger = logging.getLogger(__name__)

# Note: No Coinbase client is required for DB-based tracking.

class TradeTracker:
    """Integrated trade tracking and P&L management system"""
    
    def __init__(self, db_path: str = "agent_trades.db"):
        # Ensure DB path is absolute and anchored to project root for consistency
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
        self.db_path = db_path if os.path.isabs(db_path) else os.path.join(root_dir, db_path)
        self.init_database()
    
    def init_database(self):
        """Initialize SQLite database for trade tracking"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create trades table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    strategy TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    quantity REAL NOT NULL,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    entry_order_id TEXT NOT NULL,
                    exit_order_id TEXT,
                    fees_paid REAL DEFAULT 0.0,
                    realized_pnl REAL,
                    unrealized_pnl REAL,
                    status TEXT DEFAULT 'open',
                    strategy_context TEXT,
                    notes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create strategy performance table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS strategy_performance (
                    strategy TEXT PRIMARY KEY,
                    total_trades INTEGER DEFAULT 0,
                    winning_trades INTEGER DEFAULT 0,
                    losing_trades INTEGER DEFAULT 0,
                    total_pnl REAL DEFAULT 0.0,
                    total_fees REAL DEFAULT 0.0,
                    win_rate REAL DEFAULT 0.0,
                    avg_win REAL DEFAULT 0.0,
                    avg_loss REAL DEFAULT 0.0,
                    max_drawdown REAL DEFAULT 0.0,
                    sharpe_ratio REAL DEFAULT 0.0,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"Trade tracking database initialized successfully at: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Error initializing trade database: {str(e)}")
            raise
    
    def record_trade_entry(self, strategy: str, product_id: str, side: str, 
                          entry_price: float, quantity: float, order_id: str,
                          strategy_context: Dict[str, Any] = None, notes: str = "") -> str:
        """
        Record a new trade entry (called automatically by order tools)
        
        Args:
            strategy: Trading strategy name
            product_id: Trading pair (e.g., "BTC-USD")
            side: 'buy' or 'sell'
            entry_price: Entry price
            quantity: Trade quantity
            order_id: Coinbase order ID
            strategy_context: Context about why trade was made
            notes: Additional notes
            
        Returns:
            str: Trade ID
        """
        try:
            trade_id = f"{strategy}_{product_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            entry_time = datetime.now(timezone.utc)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO trades (
                    trade_id, strategy, product_id, side, entry_price, quantity,
                    entry_time, entry_order_id, strategy_context, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_id, strategy, product_id, side, entry_price, quantity,
                entry_time.isoformat(), order_id, json.dumps(strategy_context or {}), notes
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Trade entry recorded: {trade_id} -> DB: {self.db_path}")
            return trade_id
            
        except Exception as e:
            # Propagate so the caller can surface an explicit error (instead of silently failing)
            logger.error(f"Error recording trade entry: {str(e)} | DB: {self.db_path}")
            raise
    
    def record_trade_exit(self, trade_id: str = None, product_id: str = None, 
                         exit_price: float = None, exit_order_id: str = None, 
                         fees_paid: float = 0.0) -> Dict[str, Any]:
        """
        Record trade exit and calculate P&L (called automatically by sell order tools)
        
        Args:
            trade_id: Specific trade ID to close (optional)
            product_id: Product to close positions for (if trade_id not specified)
            exit_price: Exit price
            exit_order_id: Coinbase exit order ID
            fees_paid: Total fees paid
            
        Returns:
            Dict: Trade P&L details
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Find trade to close
            if trade_id:
                cursor.execute('SELECT * FROM trades WHERE trade_id = ? AND status = "open"', (trade_id,))
            elif product_id:
                cursor.execute('SELECT * FROM trades WHERE product_id = ? AND status = "open" ORDER BY entry_time DESC LIMIT 1', (product_id,))
            else:
                return {'error': 'Must specify either trade_id or product_id'}
            
            trade_row = cursor.fetchone()
            if not trade_row:
                return {'error': 'No open trade found'}
            
            # Extract trade data
            columns = [desc[0] for desc in cursor.description]
            trade_data = dict(zip(columns, trade_row))
            
            # Calculate P&L
            entry_price = trade_data['entry_price']
            quantity = trade_data['quantity']
            side = trade_data['side']
            
            if side == 'buy':
                # Long position: profit when exit_price > entry_price
                pnl = (exit_price - entry_price) * quantity
            else:
                # Short position: profit when exit_price < entry_price
                pnl = (entry_price - exit_price) * quantity
            
            # Subtract fees
            net_pnl = pnl - fees_paid
            
            # Update trade record
            exit_time = datetime.now(timezone.utc)
            cursor.execute('''
                UPDATE trades SET 
                    exit_price = ?, exit_time = ?, exit_order_id = ?,
                    fees_paid = ?, realized_pnl = ?, status = 'closed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE trade_id = ?
            ''', (exit_price, exit_time.isoformat(), exit_order_id, fees_paid, net_pnl, trade_data['trade_id']))
            
            conn.commit()
            conn.close()
            
            # Update strategy performance
            self.update_strategy_performance(trade_data['strategy'])
            
            pnl_details = {
                'trade_id': trade_data['trade_id'],
                'gross_pnl': pnl,
                'fees_paid': fees_paid,
                'net_pnl': net_pnl,
                'pnl_percentage': (net_pnl / (entry_price * quantity)) * 100,
                'holding_period': (exit_time - datetime.fromisoformat(trade_data['entry_time'])).total_seconds() / 3600  # hours
            }
            
            logger.info(f"Trade exit recorded: {trade_data['trade_id']}, P&L: ${net_pnl:.2f} -> DB: {self.db_path}")
            return pnl_details
            
        except Exception as e:
            logger.error(f"Error recording trade exit: {str(e)}")
            return {'error': str(e)}

    def get_open_trade(self, product_id: str, strategy: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Return the most recent open trade for a product (and strategy if provided)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            if strategy is not None:
                cursor.execute(
                    'SELECT * FROM trades WHERE product_id = ? AND strategy = ? AND status = "open" '
                    'ORDER BY entry_time DESC LIMIT 1',
                    (product_id, strategy)
                )
            else:
                cursor.execute(
                    'SELECT * FROM trades WHERE product_id = ? AND status = "open" '
                    'ORDER BY entry_time DESC LIMIT 1',
                    (product_id,)
                )
            row = cursor.fetchone()
            if not row:
                conn.close()
                return None
            columns = [desc[0] for desc in cursor.description]
            trade = dict(zip(columns, row))
            conn.close()
            # Parse strategy_context JSON
            try:
                trade["strategy_context"] = json.loads(trade.get("strategy_context") or "{}")
            except Exception:
                trade["strategy_context"] = {}
            return trade
        except Exception as e:
            logger.error(f"Error fetching open trade: {str(e)}")
            return None

    def update_strategy_context(self, trade_id: str, updates: Dict[str, Any]) -> bool:
        """Merge-partially update the strategy_context JSON for a trade."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT strategy_context FROM trades WHERE trade_id = ?', (trade_id,))
            row = cursor.fetchone()
            current = {}
            if row and row[0]:
                try:
                    current = json.loads(row[0])
                except Exception:
                    current = {}
            # Merge updates
            current.update(updates or {})
            cursor.execute(
                'UPDATE trades SET strategy_context = ?, updated_at = CURRENT_TIMESTAMP WHERE trade_id = ?'
                , (json.dumps(current), trade_id)
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Error updating strategy context: {str(e)}")
            return False
    
    def update_strategy_performance(self, strategy: str):
        """Update strategy performance metrics"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get strategy trades
            cursor.execute('''
                SELECT realized_pnl, fees_paid FROM trades 
                WHERE strategy = ? AND status = 'closed' AND realized_pnl IS NOT NULL
            ''', (strategy,))
            
            trades = cursor.fetchall()
            
            if not trades:
                conn.close()
                return
            
            total_trades = len(trades)
            winning_trades = sum(1 for pnl, _ in trades if pnl > 0)
            losing_trades = sum(1 for pnl, _ in trades if pnl < 0)
            total_pnl = sum(pnl for pnl, _ in trades)
            total_fees = sum(fees for _, fees in trades)
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            wins = [pnl for pnl, _ in trades if pnl > 0]
            losses = [pnl for pnl, _ in trades if pnl < 0]
            
            avg_win = sum(wins) / len(wins) if wins else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            
            # Calculate max drawdown (simplified)
            cumulative_pnl = []
            running_total = 0
            for pnl, _ in trades:
                running_total += pnl
                cumulative_pnl.append(running_total)
            
            max_drawdown = 0
            if cumulative_pnl:
                peak = cumulative_pnl[0]
                for value in cumulative_pnl:
                    if value > peak:
                        peak = value
                    drawdown = peak - value
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
            
            # Insert or update strategy performance
            cursor.execute('''
                INSERT OR REPLACE INTO strategy_performance (
                    strategy, total_trades, winning_trades, losing_trades,
                    total_pnl, total_fees, win_rate, avg_win, avg_loss,
                    max_drawdown, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (strategy, total_trades, winning_trades, losing_trades,
                  total_pnl, total_fees, win_rate, avg_win, avg_loss, max_drawdown))
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error updating strategy performance: {str(e)}")
    
    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get comprehensive portfolio performance summary"""
        try:
            conn = sqlite3.connect(self.db_path)
            
            # Get overall performance
            df_trades = pd.read_sql_query('''
                SELECT * FROM trades WHERE status = 'closed' AND realized_pnl IS NOT NULL
            ''', conn)
            
            df_strategies = pd.read_sql_query('SELECT * FROM strategy_performance', conn)
            conn.close()
            
            if df_trades.empty:
                return {'message': 'No closed trades found'}
            
            # Calculate portfolio metrics
            total_pnl = df_trades['realized_pnl'].sum()
            total_fees = df_trades['fees_paid'].sum()
            net_pnl = total_pnl - total_fees
            total_trades = len(df_trades)
            winning_trades = len(df_trades[df_trades['realized_pnl'] > 0])
            win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
            
            avg_win = df_trades[df_trades['realized_pnl'] > 0]['realized_pnl'].mean()
            avg_loss = df_trades[df_trades['realized_pnl'] < 0]['realized_pnl'].mean()
            
            return {
                'portfolio_performance': {
                    'total_trades': total_trades,
                    'winning_trades': winning_trades,
                    'win_rate': win_rate,
                    'total_pnl': total_pnl,
                    'total_fees': total_fees,
                    'net_pnl': net_pnl,
                    'avg_win': avg_win if not pd.isna(avg_win) else 0,
                    'avg_loss': avg_loss if not pd.isna(avg_loss) else 0,
                    'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 and not pd.isna(avg_loss) else 0
                },
                'strategy_breakdown': df_strategies.to_dict('records') if not df_strategies.empty else []
            }
            
        except Exception as e:
            logger.error(f"Error getting portfolio summary: {str(e)}")
            return {'error': str(e)}

# Global trade tracker instance
trade_tracker = TradeTracker()

def get_portfolio_performance_tool() -> str:
    """
    Agent tool to get comprehensive portfolio performance summary
    
    Returns:
        str: Formatted portfolio performance summary
    """
    try:
        summary = trade_tracker.get_portfolio_summary()
        
        if 'error' in summary:
            return f"❌ Error getting portfolio summary: {summary['error']}"
        
        if 'message' in summary:
            return f"📊 {summary['message']}"
        
        perf = summary['portfolio_performance']
        
        output = []
        output.append("📊 PORTFOLIO PERFORMANCE SUMMARY")
        output.append("=" * 50)
        output.append(f"💼 Total Trades: {perf['total_trades']}")
        output.append(f"🏆 Winning Trades: {perf['winning_trades']}")
        output.append(f"📈 Win Rate: {perf['win_rate']:.1f}%")
        output.append(f"💰 Net P&L: ${perf['net_pnl']:.2f}")
        output.append(f"💸 Total Fees: ${perf['total_fees']:.2f}")
        output.append(f"📊 Avg Win: ${perf['avg_win']:.2f}")
        output.append(f"📉 Avg Loss: ${perf['avg_loss']:.2f}")
        output.append(f"⚡ Profit Factor: {perf['profit_factor']:.2f}")
        
        if summary['strategy_breakdown']:
            output.append("\n🎯 STRATEGY BREAKDOWN:")
            for strategy in summary['strategy_breakdown']:
                output.append(f"  • {strategy['strategy']}: {strategy['total_trades']} trades, ${strategy['total_pnl']:.2f} P&L, {strategy['win_rate']:.1f}% win rate")
        
        return "\n".join(output)
        
    except Exception as e:
        return f"❌ Error getting portfolio performance: {str(e)}"

# Test function
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("🧪 Testing Integrated Trade Tracking System...")
    
    # Test trade entry
    trade_id = trade_tracker.record_trade_entry(
        strategy="RSI_MEAN_REVERSION",
        product_id="BTC-USD",
        side="buy",
        entry_price=115000.0,
        quantity=0.001,
        order_id="test_order_123",
        strategy_context={"rsi": 25, "signal": "oversold"},
        notes="Test trade entry"
    )
    logger.info(f"Trade recorded: {trade_id}")
    
    # Test portfolio summary
    summary = trade_tracker.get_portfolio_summary()
    logger.info(f"Portfolio summary: {summary}")
