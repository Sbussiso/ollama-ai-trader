#!/usr/bin/env python
import sys, os
import math
import subprocess
import logging
import json
from colorama import init, Fore, Style
from ollama import chat, ChatResponse

# Import trading analysis tools from agent_tools package
from agent_tools.product_info import get_product_info
# Import technical analysis tools from agent_tools package
# Unified paper trading tool
from agent_tools.unified_trading import unified_trade_tool
# New market signal tools
from agent_tools.atr import get_latest_atr
from agent_tools.signal_hub import get_signals_tool as _get_signals_tool
# Import portfolio performance and trade tracking tools
from helpers.trade_history import get_trade_history_tool
# Import planning tool from agent_tools package
from agent_tools.planning_tool import get_current_plan, update_trading_plan, get_plan_summary, record_trade_outcome

# Configuration (model, wait interval, candle granularity)
DEFAULT_CONFIG = {
    "model": "qwen3:14b",
    "wait_seconds": 300,
    "candle_granularity": "1H",
}

def _load_config() -> dict:
    try:
        cfg_path = os.path.join(os.path.dirname(__file__), "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return DEFAULT_CONFIG
        # merge with defaults
        merged = {**DEFAULT_CONFIG, **data}
        return merged
    except Exception:
        return DEFAULT_CONFIG

CONFIG = _load_config()
# Support nested config structure while remaining backward compatible
AGENT_CFG = CONFIG.get("agent", {}) if isinstance(CONFIG.get("agent", {}), dict) else {}
COINBASE_CFG = CONFIG.get("coinbase", {}) if isinstance(CONFIG.get("coinbase", {}), dict) else {}
MODEL = str(AGENT_CFG.get("model", CONFIG.get("model", DEFAULT_CONFIG["model"])))
CANDLE_GRAN = str(AGENT_CFG.get("candle_granularity", CONFIG.get("candle_granularity", DEFAULT_CONFIG["candle_granularity"])))

def _granularity_to_seconds(gran: str) -> int:
    """Map granularity (e.g., '1M','5M','15M','1H','6H','1D') to seconds.
    Accepts common variants; falls back to DEFAULT_CONFIG['wait_seconds'] on unknown.
    """
    if not gran:
        return DEFAULT_CONFIG["wait_seconds"]
    m = str(gran).strip().upper()
    aliases = {
        "1MIN": "1M", "1MINUTE": "1M", "ONE_MIN": "1M", "ONE_MINUTE": "1M",
        "5MIN": "5M", "5MINUTE": "5M", "FIVE_MINUTE": "5M",
        "15MIN": "15M", "15MINUTE": "15M", "FIFTEEN_MINUTE": "15M",
        "1HR": "1H", "1 H": "1H", "ONE_HOUR": "1H",
        "6HR": "6H", "6 H": "6H", "SIX_HOUR": "6H",
        "1DAY": "1D", "1 D": "1D", "ONE_DAY": "1D",
        "1MINUTES": "1M", "5MINUTES": "5M", "15MINUTES": "15M",
    }
    if m in aliases:
        m = aliases[m]
    mapping = {
        "1M": 60,
        "5M": 5 * 60,
        "15M": 15 * 60,
        "1H": 60 * 60,
        "6H": 6 * 60 * 60,
        "1D": 24 * 60 * 60,
    }
    return mapping.get(m, DEFAULT_CONFIG["wait_seconds"])

_raw_wait = AGENT_CFG.get("wait_seconds", CONFIG.get("wait_seconds", DEFAULT_CONFIG["wait_seconds"]))
SYNC_WAIT = isinstance(_raw_wait, str) and _raw_wait.strip().lower() == "sync"
MANUAL_MODE = isinstance(_raw_wait, str) and _raw_wait.strip().lower() == "manual"
if SYNC_WAIT:
    WAIT_SECONDS = _granularity_to_seconds(CANDLE_GRAN)
elif MANUAL_MODE:
    WAIT_SECONDS = 0  # not used in manual mode
else:
    try:
        WAIT_SECONDS = int(_raw_wait)
    except Exception:
        WAIT_SECONDS = DEFAULT_CONFIG["wait_seconds"]


# Coinbase API setup
from coinbase.rest import RESTClient
_cb = COINBASE_CFG if isinstance(COINBASE_CFG, dict) else {}
api_key = str(_cb.get("coinbase_api_key", CONFIG.get("coinbase_api_key", "")))
api_secret = str(_cb.get("coinbase_api_secret", CONFIG.get("coinbase_api_secret", "")))
if not api_key or not api_secret:
    logging.getLogger(__name__).warning("Coinbase API credentials are not set in config.json (coinbase.coinbase_api_key/coinbase.coinbase_api_secret)")
client = RESTClient(api_key=api_key, api_secret=api_secret)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize colorama for colored console output
init(autoreset=True)


# ------------------------- Trading Tool Wrappers -------------------------

def _normalize_granularity(g: str) -> str:
    """Map common variants to supported set: ['1M','5M','15M','1H','6H','1D']."""
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
    # Already valid?
    if m in {"1M", "5M", "15M", "1H", "6H", "1D"}:
        return m
    # Fallback simple normalization like '1m' -> '1M'
    return m.replace("MIN", "M").replace("HR", "H").replace("DAY", "D").replace(" ", "")

 


def get_atr_tool(
    product_id: str = "BTC-USD",
    granularity: str = None,
    limit: int = 300,
    period: int = 14,
) -> str:
    """Latest ATR value for sizing/stops."""
    try:
        granularity = _normalize_granularity(granularity or CANDLE_GRAN)
        data = get_latest_atr(product_id=product_id, granularity=granularity, limit=limit, period=period)
        atr_val = data.get("atr")
        # Retry with larger sample if ATR is NaN (e.g., insufficient non-NaN bars)
        if atr_val is None or (isinstance(atr_val, float) and math.isnan(atr_val)):
            bigger = max(limit, period * 5)
            if bigger != limit:
                data = get_latest_atr(product_id=product_id, granularity=granularity, limit=bigger, period=period)
                atr_val = data.get("atr")
        if atr_val is None or (isinstance(atr_val, float) and math.isnan(atr_val)):
            return (
                f"ATR unavailable (NaN) for {product_id} @ {granularity} (period={period}, bars={data.get('bars')}): "
                f"Try increasing limit (>= {period*5}) or using a higher timeframe."
            )
        return (
            f"ATR for {product_id} @ {granularity} (period={period}): "
            f"ATR={atr_val:.2f}, price={data['price']:.2f}"
        )
    except Exception as e:
        return f"Error in ATR: {str(e)}"


def get_signals_tool(
    product_id: str = "BTC-USD",
    granularity: str = None,
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
    """Wrapper that injects configured candle granularity when not provided."""
    try:
        g = _normalize_granularity(granularity or CANDLE_GRAN)
        return _get_signals_tool(
            product_id=product_id,
            granularity=g,
            limit=limit,
            rsi_period=rsi_period,
            rsi_oversold=rsi_oversold,
            rsi_overbought=rsi_overbought,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            buffer_pct=buffer_pct,
            confirm_timeframe=confirm_timeframe,
            obv_ma_period=obv_ma_period,
            include_atr=include_atr,
            atr_period=atr_period,
            return_format=return_format,
        )
    except Exception as e:
        logger.error(f"Error in get_signals_tool wrapper: {e}")
        return f"Error in get_signals_tool: {str(e)}"

def get_current_market_info(product_id: str = "BTC-USD") -> str:
    """Get current market information for a trading pair."""
    try:
        product_data = get_product_info(client, product_id=product_id)
        
        if not product_data.get('success', False):
            return f"Error getting product info: {product_data.get('error', 'Unknown error')}"
        
        # Safe formatting for potentially missing or non-numeric fields
        price = product_data.get('price')
        price_str = f"${price:,.2f}" if isinstance(price, (int, float)) else str(price or 'N/A')

        pc = product_data.get('price_change_24h')
        pc_str = f"${pc:,.2f}" if isinstance(pc, (int, float)) else str(pc or 'N/A')

        pcp = product_data.get('price_change_24h_percent')
        pcp_str = f"{pcp:.2f}%" if isinstance(pcp, (int, float)) else (f"{pcp}%" if isinstance(pcp, str) else 'N/A')

        vol = product_data.get('volume_24h')
        vol_str = f"{vol:,.2f}" if isinstance(vol, (int, float)) else str(vol or 'N/A')

        response = f"""📊 CURRENT MARKET INFO - {product_id}

💰 PRICE DATA:
- Current Price: {price_str}
- 24h Change: {pc_str} ({pcp_str})
- 24h Volume: {vol_str} {product_data.get('base_currency', 'N/A')}
 
📈 TRADING INFO:
- Base Currency: {product_data.get('base_currency', 'N/A')}
- Quote Currency: {product_data.get('quote_currency', 'N/A')}
- Trading Status: {'Disabled' if product_data.get('trading_disabled', False) else 'Enabled'}
"""
        return response
        
    except Exception as e:
        error_msg = f"Error getting market info: {str(e)}"
        logger.error(error_msg)
        return error_msg

 


def get_trade_history_analysis(limit: int = 10, strategy_filter: str = None) -> str:
    """
    Get detailed trade history for performance review and analysis.
    
    Args:
        limit: Maximum number of trades to return (default: 10)
        strategy_filter: Optional strategy name to filter results
    
    Returns:
        str: Formatted trade history with P&L details
    """
    return get_trade_history_tool(limit=limit, strategy_filter=strategy_filter)

# ------------------------- Conversation Utils -------------------------

def _trim_messages(messages, max_total: int = 120, keep_tail: int = 60):
    """Keep conversation buffer bounded. Returns possibly-trimmed list.
    - Keeps the initial system message
    - Keeps the last `keep_tail` messages
    - Replaces the middle with a compact system note
    """
    try:
        if not messages:
            return messages
        if len(messages) <= max_total:
            return messages
        head = messages[0:1]  # system prompt
        tail = messages[-keep_tail:]
        omitted = len(messages) - (1 + len(tail))
        note = {
            "role": "system",
            "content": f"[Conversation trimmed: {omitted} older messages summarized/omitted to control context size]"
        }
        return head + [note] + tail
    except Exception:
        return messages

# Planning tool wrappers
def get_trading_plan() -> str:
    """Get the current trading plan for strategic context."""
    return get_current_plan()

def get_trading_plan_summary() -> str:
    """Get a concise summary of the current trading plan."""
    return get_plan_summary()

def update_trading_plan_tool(update_reason: str, content: str, section: str = "general") -> str:
    """Update the trading plan with new insights, strategies, or lessons learned."""
    return update_trading_plan(update_reason=update_reason, content=content, section=section)

def record_trade_result(trade_type: str, asset: str, outcome: str, profit_loss: float, lessons: str) -> str:
    """Record the outcome of a trade and lessons learned."""
    return record_trade_outcome(trade_type=trade_type, asset=asset, outcome=outcome, profit_loss=profit_loss, lessons=lessons)

def done_tool(note: str = "") -> str:
    """Signal that the agent has finished this reasoning cycle early.
    The note is optional context; the tool returns a simple acknowledgment.
    """
    return f"DONE{(': ' + note) if note else ''}"

def main():
    system_msg = (
        "🚀 AUTONOMOUS CRYPTO TRADING AGENT 🚀\n" +
        "You are a HIGH-FREQUENCY, ACTION-ORIENTED trading bot with ZERO tolerance for inaction.\n" +
        "CASH SITTING IDLE = LOST OPPORTUNITY. You MUST trade aggressively to maximize profits.\n\n" +

        "🎯 EXECUTION PROTOCOL:\n" +
        "1. CHECK PERFORMANCE: Review your P&L - Are you profitable? If not, CHANGE TACTICS\n" +
        "2. SCAN MARKET: Get RSI, OBV - Find your trading signal\n" +
        "3. EXECUTE TRADE: BUY oversold dips, SELL overbought peaks - NO HESITATION\n" +
        "4. DOCUMENT: Update your plan with what worked/failed\n\n" +

        "💰 PROFIT-MAXIMIZING DATABASE:\n" +
        "Your SQLite database tracks EVERY trade with P&L calculations.\n" +
        "Use this data to identify winning patterns and eliminate losing strategies.\n" +
        "If your win rate drops below 60%, IMMEDIATELY change your approach.\n\n" +


        "📊 AVAILABLE TOOLS:\n" +
        "Portfolio & Performance:\n" +
        "- get_trade_history_analysis(limit=5) - Learn from recent trades\n\n" +

        "Market Intelligence:\n" +
        "- get_current_market_info(product_id='BTC-USD') - Current price & 24h data\n" +
        "- get_signals_tool(product_id='BTC-USD') - Unified RSI/EMA/OBV (+ATR)\n" +
        "- get_atr_tool(product_id='BTC-USD') - Volatility for sizing/SL\n\n" +

        "EXECUTION TOOL (PAPER TRADING):\n" +
        "- unified_trade_tool(action='open_long', price=50000.0, risk_usd=25, atr=500, sl=49250, tp=52000)\n" +
        "- unified_trade_tool(action='on_price', price=50500.0)\n" +
        "- unified_trade_tool(action='summary', mark_price=50500.0)\n" +
        "- unified_trade_tool(action='close', price=50750.0)\n" +
        "(Optional trailing params at entry: move_to_be_atr=1.0, trail_start_atr=2.0, trail_distance_atr=1.25)\n\n" +
        "CRITICAL: When you decide to trade, you MUST execute via unified_trade_tool.\n" +
        "Do not merely describe trades. Always place orders by calling unified_trade_tool with the proper action and parameters.\n\n" +

        "TOOL CALL ENFORCEMENT:\n" +
        "- If you assert a plan update, pause, or resume directive, you MUST call update_trading_plan_tool(update_reason=..., content=..., section=...).\n" +
        "  Never claim a plan change without emitting the actual tool call.\n" +
        "- If you need the plan context, call get_trading_plan_summary() or get_trading_plan().\n" +
        "- If you log trade outcomes or lessons, call record_trade_result(...).\n\n" +
        "Turn control:\n" +
        "- done_tool(note='...') - Signal you are finished this turn early; do not emit extra tool calls.\n\n" +

        "Planning & Learning:\n" +
        "- get_trading_plan_summary() - Current strategy\n" +
        "- get_trading_plan() - Full trading plan\n" +
        "- update_trading_plan_tool(update_reason='market', content='Paused due to low volatility; resume when ADX>25 or ATR>1.5%/1H', section='risk')\n" +
        "- record_trade_result(trade_type='hold', asset='BTC-USD', outcome='no_trade', profit_loss=0.0, lessons='No edge in stagnant regime')\n\n" +

        "Your database tracks everything. Learn from it and BEAT THE MARKET!\n" +

        "YOU MUST MAKE A DECISION: BUY, SELL, or HOLD\n"
    )

    messages = [{"role": "system", "content": system_msg}]
    tools = [get_current_market_info, unified_trade_tool,
             get_trading_plan_summary, get_trading_plan,
             update_trading_plan_tool, record_trade_result,
             get_atr_tool, get_signals_tool, get_trade_history_analysis,
             done_tool]
    logger.info(f"Registered tools: {[t.__name__ for t in tools]}")

    print(Fore.GREEN + "Agent ready! Type 'exit' to quit." + Style.RESET_ALL)
    if MANUAL_MODE:
        logger.info("Manual mode enabled: running a single cycle and exiting after completion.")


    while True:
        import datetime

        # Heartbeat and performance summary
        performance_line = ""
        try:
            pd = get_product_info(client, product_id="BTC-USD")
            last_price = pd.get("price") if isinstance(pd, dict) else None
            if pd and isinstance(last_price, (int, float)):
                hb = unified_trade_tool(action="on_price", price=float(last_price), product_id="BTC-USD")
                logger.debug(f"on_price heartbeat -> {hb}")
                # Add as a tool message so the model sees latest management state
                messages.append({"role": "tool", "name": "unified_trade_tool", "content": hb})
                perf = unified_trade_tool(action="summary", product_id="BTC-USD", mark_price=float(last_price))
                performance_line = f"PERFORMANCE: {perf}"
            else:
                performance_line = "PERFORMANCE: unavailable"
        except Exception as e:
            logger.warning(f"Heartbeat/performance fetch failed: {e}")
            performance_line = "PERFORMANCE: error fetching summary"

        # Compose scheduler/heartbeat context with timestamp + performance
        context_update = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {performance_line}\n REMINDER: check your plan and only update if needed."
        
        logging.info(context_update)

        # Add as a system message so the model treats it as instruction/context, not a user chat
        messages.append({"role": "system", "content": context_update})
        
        # Multi-turn reasoning loop - allow agent to use multiple tools
        max_turns = int(AGENT_CFG.get("max_turns", CONFIG.get("max_turns", 7)))  # Prevent infinite loops
        turn_count = 0
        
        enforced_prompt_inserted = False
        while turn_count < max_turns:
            turn_count += 1
            print(f"{Fore.MAGENTA}🔄 Reasoning Turn {turn_count}{Style.RESET_ALL}")
            
            # Ask Ollama to decide on tool calls or provide final response
            response: ChatResponse = chat(
                model=MODEL,
                messages=messages,
                tools=tools,
                stream=False
            )
            
            # If no tool calls, enforce planning tool usage once per cycle
            if not response.message.tool_calls:
                content = response.message.content or ""
                if not enforced_prompt_inserted:
                    enforcement_msg = (
                        "TOOL CALL ENFORCEMENT: Respond (if necessary) with ONLY tool_calls in this exact order and with these exact arguments. "
                        "1) get_trading_plan_summary() with no arguments. "
                        "2) update_trading_plan_tool(update_reason='market', content='Paused due to low volatility; resume when ADX>25 or ATR>1.5%/1H', section='risk'). "
                        "3) record_trade_result(trade_type='hold', asset='BTC-USD', outcome='no_trade', profit_loss=0.0, lessons='No edge in stagnant regime'). "
                        
                    )
                    messages.append({"role": "system", "content": enforcement_msg})
                    enforced_prompt_inserted = True
                    logger.info("Enforcement injected (no tool_calls): requesting planning tool calls.")
                    continue

                # Second no-tool-calls -> accept and end
                print(f"{Fore.GREEN}🤖 AI Trading Agent: {Style.RESET_ALL}{content}")
                messages.append({"role": "assistant", "content": content})
                break
            
            # Execute tool calls (support early end via done_tool)
            end_turn = False
            for call in response.message.tool_calls:
                fn_name = call.function.name
                args = call.function.arguments or {}
                
                print(f"{Fore.CYAN}🔧 Using tool: {fn_name}{Style.RESET_ALL}")
                
                # Safety check: only execute functions that are in the tools list
                tool_functions = [tool.__name__ for tool in tools]
                if fn_name in tool_functions:
                    try:
                        result = globals()[fn_name](**args)
                        # For done_tool, keep logging minimal
                        if fn_name != "done_tool":
                            print(f"{Fore.YELLOW}📊 Tool Result:\n{result[:500]}{'...' if len(result) > 500 else ''}{Style.RESET_ALL}")
                        
                        # Add tool result to conversation
                        messages.append({
                            "role": "tool",
                            "name": fn_name,
                            "content": result
                        })
                        if fn_name == "done_tool":
                            end_turn = True
                            # Stop executing any further tool calls this turn
                            break
                    except Exception as e:
                        error_msg = f"Error executing {fn_name}: {str(e)}"
                        print(f"{Fore.RED}❌ Tool Error: {error_msg}{Style.RESET_ALL}")
                        messages.append({
                            "role": "tool",
                            "name": fn_name,
                            "content": error_msg
                        })
                else:
                    error_msg = f"Error: Tool '{fn_name}' is not available in this agent"
                    logger.error(f"Tool Error: {error_msg}")
                    messages.append({
                        "role": "tool",
                        "name": fn_name,
                        "content": error_msg
                    })
            if end_turn:
                # Get a concise final assistant response and end the reasoning loop early
                final_response: ChatResponse = chat(
                    model=MODEL,
                    messages=messages,
                    stream=False
                )
                logger.info(f"🤖 AI Trading Agent (early done): {final_response.message.content}")
                messages.append({"role": "assistant", "content": final_response.message.content})
                break
        
        # If we hit max turns, get final response
        if turn_count >= max_turns:
            logger.warning("Max reasoning turns reached. Getting final response...")
            final_response: ChatResponse = chat(
                model=MODEL,
                messages=messages,
                stream=False
            )
            logger.info(f"🤖 AI Trading Agent: {final_response.message.content}")
            messages.append({"role": "assistant", "content": final_response.message.content})
        
        # Trim conversation buffer to prevent unbounded growth
        prev_len = len(messages)
        messages = _trim_messages(messages, max_total=120, keep_tail=60)
        if len(messages) < prev_len:
            logger.info(f"Trimmed conversation: {prev_len} -> {len(messages)} messages")
        
        import time
        import datetime
        if MANUAL_MODE:
            logging.info("Manual mode cycle complete. Exiting without waiting.")
            break
        if SYNC_WAIT:
            # Align sleep to the next candle boundary in UTC
            period = int(WAIT_SECONDS)
            now = datetime.datetime.now(datetime.timezone.utc)
            ts = now.timestamp()
            try:
                import math
                next_ts = math.ceil(ts / period) * period
            except Exception:
                # Fallback ceil without math
                next_ts = int(-(-ts // period) * period)
            sleep_s = max(1, int(next_ts - ts))
            eta = datetime.datetime.fromtimestamp(next_ts, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            logging.info(f"sync wait: next candle in {sleep_s} seconds (until {eta} UTC)")
            time.sleep(sleep_s)
        else:
            _unit = "minutes" if WAIT_SECONDS % 60 == 0 else "seconds"
            _val = WAIT_SECONDS // 60 if _unit == "minutes" else WAIT_SECONDS
            logging.info(f"next trade in {_val} {_unit}")
            time.sleep(WAIT_SECONDS)


if __name__ == "__main__":
    main()
