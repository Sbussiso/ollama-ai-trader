#!/usr/bin/env python3
"""
AI Trading Agent Planning Tool

This tool provides persistent planning capabilities for the AI trading agent,
allowing it to maintain trading strategies, track performance, and learn from
past decisions across multiple trading sessions.
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Plan file path
PLAN_FILE_PATH = os.path.join(os.path.dirname(__file__), "..", "trading_plan.md")

def get_current_plan() -> str:
    """
    Retrieve the current trading plan for agent context.
    
    Returns:
        str: Current trading plan content or default template if none exists
    """
    try:
        if os.path.exists(PLAN_FILE_PATH):
            with open(PLAN_FILE_PATH, 'r', encoding='utf-8') as f:
                plan_content = f.read()
            logger.info("Retrieved current trading plan")
            return plan_content
        else:
            # Return default template if no plan exists
            default_plan = create_default_plan()
            logger.info("No existing plan found, returning default template")
            return default_plan
            
    except Exception as e:
        error_msg = f"Error reading trading plan: {str(e)}"
        logger.error(error_msg)
        return f"Error retrieving plan: {error_msg}"

def update_trading_plan(update_reason: str, content: str, section: str = "general") -> str:
    """
    Update the AI trading agent's persistent plan.
    
    Args:
        update_reason: Reason for the update (market_change, trade_result, strategy_update, etc.)
        content: New content to add to the plan
        section: Which section to update (strategy, risk_management, market_assessment, etc.)
    
    Returns:
        str: Confirmation message about the plan update
    """
    try:
        # Get current plan or create default
        current_plan = get_current_plan() if os.path.exists(PLAN_FILE_PATH) else create_default_plan()
        
        # Create update entry
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        update_entry = f"\n### Update: {timestamp}\n**Reason:** {update_reason}\n**Section:** {section}\n\n{content}\n\n---\n"
        
        # Determine where to insert the update based on section
        section_markers = {
            "strategy": "## Current Trading Strategy",
            "risk_management": "## Risk Management Rules", 
            "market_assessment": "## Market Assessment",
            "performance": "## Performance Tracking",
            "lessons": "## Lessons Learned",
            "objectives": "## Trading Objectives",
            "general": "## Recent Updates"
        }
        
        # Find the appropriate section or add to Recent Updates
        target_marker = section_markers.get(section, "## Recent Updates")
        
        if target_marker in current_plan:
            # Insert after the section header
            parts = current_plan.split(target_marker)
            if len(parts) >= 2:
                # Find the next section or end of file
                remaining = parts[1]
                next_section_pos = remaining.find("\n## ")
                if next_section_pos != -1:
                    before_next = remaining[:next_section_pos]
                    after_next = remaining[next_section_pos:]
                    updated_plan = parts[0] + target_marker + before_next + update_entry + after_next
                else:
                    updated_plan = parts[0] + target_marker + remaining + update_entry
            else:
                updated_plan = current_plan + update_entry
        else:
            # Add new section if it doesn't exist
            updated_plan = current_plan + f"\n{target_marker}\n{update_entry}"
        
        # Write updated plan
        with open(PLAN_FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(updated_plan)
        
        success_msg = f"✅ Trading plan updated successfully! Added {section} update: {update_reason}"
        logger.info(success_msg)
        return success_msg
        
    except Exception as e:
        error_msg = f"Error updating trading plan: {str(e)}"
        logger.error(error_msg)
        return error_msg

def get_trading_plan_summary() -> str:
    """Alias for get_plan_summary to match agent prompt/tool naming."""
    return get_plan_summary()

def create_default_plan() -> str:
    """Create a default trading plan template."""
    default_plan = f"""# AI Trading Agent Plan
*Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*

## Trading Objectives
- **Primary Goal:** Maximize profit while managing risk in the AI_Trading_Bot_Portfolio
- **Risk Tolerance:** Conservative to moderate risk approach
- **Target Assets:** Focus on major cryptocurrencies (BTC, ETH, SOL)
- **Time Horizon:** Medium-term trading with tactical adjustments

## Current Trading Strategy
- **Approach:** Data-driven decisions using technical analysis
- **Position Sizing:** Dynamic sizing based on portfolio percentage (5-15% per trade)
- **Entry Strategy:** Look for oversold conditions, support levels, and positive momentum
- **Exit Strategy:** Take profits at resistance levels, cut losses at support breaks

## Risk Management Rules
- **Maximum Position Size:** 20% of portfolio per asset
- **Stop Loss:** Set stops 3-5% below entry for long positions
- **Portfolio Allocation:** Maintain 10-20% cash for opportunities
- **Daily Loss Limit:** No more than 2% portfolio loss per day

## Market Assessment
- **Current Conditions:** To be updated based on analysis
- **Key Levels:** To be identified through technical analysis
- **Market Sentiment:** To be assessed through order book and volume analysis

## Lessons Learned
- Initial setup complete
- Ready to begin systematic trading approach

## Recent Updates
*Updates will be added here as the agent learns and adapts*

---
"""
    return default_plan

def get_plan_summary() -> str:
    """
    Get a concise summary of the current trading plan for quick reference.
    
    Returns:
        str: Summary of key plan elements
    """
    try:
        plan_content = get_current_plan()
        
        # Extract key information (this is a simplified version)
        lines = plan_content.split('\n')
        summary_lines = []
        
        current_section = ""
        for line in lines:
            if line.startswith("## "):
                current_section = line.replace("## ", "").strip()
            elif line.startswith("- **") and current_section in ["Trading Objectives", "Current Trading Strategy", "Risk Management Rules"]:
                summary_lines.append(f"{current_section}: {line.strip()}")
        
        if summary_lines:
            summary = "📋 TRADING PLAN SUMMARY:\n" + "\n".join(summary_lines[:8])  # Limit to 8 key points
        else:
            summary = "📋 Trading plan exists but summary extraction failed. Use get_current_plan() for full details."
            
        logger.info("Generated plan summary")
        return summary
        
    except Exception as e:
        error_msg = f"Error generating plan summary: {str(e)}"
        logger.error(error_msg)
        return error_msg

def record_trade_outcome(trade_type: str, asset: str, outcome: str, profit_loss: float, lessons: str) -> str:
    """
    Record the outcome of a trade and update the plan with lessons learned.
    
    Args:
        trade_type: 'buy' or 'sell'
        asset: Asset traded (e.g., 'BTC-USD')
        outcome: 'profit', 'loss', or 'break_even'
        profit_loss: Dollar amount gained or lost
        lessons: Key lessons learned from this trade
    
    Returns:
        str: Confirmation of trade recording
    """
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Update performance section
        performance_update = f"""
**Trade Recorded: {timestamp}**
- Type: {trade_type.upper()} {asset}
- Outcome: {outcome.upper()}
- P&L: ${profit_loss:+.2f}
- Lessons: {lessons}
"""
        
        update_result = update_trading_plan(
            update_reason=f"Trade outcome recorded: {outcome}",
            content=performance_update,
            section="performance"
        )
        
        # Also add to lessons learned if there are insights
        if lessons and lessons.strip():
            lessons_update = f"**{timestamp}:** {lessons} (from {trade_type} {asset})"
            update_trading_plan(
                update_reason="New trading lesson",
                content=lessons_update,
                section="lessons"
            )
        
        success_msg = f"✅ Trade outcome recorded: {trade_type} {asset} resulted in {outcome} (${profit_loss:+.2f})"
        logger.info(success_msg)
        return success_msg
        
    except Exception as e:
        error_msg = f"Error recording trade outcome: {str(e)}"
        logger.error(error_msg)
        return error_msg

# Test the functions
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("🧠 AI Trading Agent Planning Tool Test")
    logger.info("=" * 50)
    
    # Test getting current plan
    logger.info("\n1. Getting current plan...")
    plan = get_current_plan()
    logger.info(f"Plan length: {len(plan)} characters")
    
    # Test updating plan
    logger.info("\n2. Testing plan update...")
    result = update_trading_plan(
        update_reason="Initial system test",
        content="Planning tool successfully integrated and tested. Agent ready for strategic planning.",
        section="general"
    )
    logger.info(result)
    
    # Test plan summary
    logger.info("\n3. Testing plan summary...")
    summary = get_plan_summary()
    logger.info(summary)
    
    # Test trade recording
    logger.info("\n4. Testing trade outcome recording...")
    trade_result = record_trade_outcome(
        trade_type="buy",
        asset="BTC-USD", 
        outcome="profit",
        profit_loss=25.50,
        lessons="Technical analysis correctly identified support level. RSI oversold signal was accurate."
    )
    logger.info(trade_result)
    
    logger.info("\n✅ Planning tool test complete!")
