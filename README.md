# AI Trading Agent (Coinbase, Ollama)

An AI-assisted, paper-trading research agent for crypto markets using Coinbase Advanced Trade APIs and a local LLM (Ollama). The agent reasons with tools (market data, signal hub, ATR, planning, and a unified paper broker) to produce clear BUY/SELL/HOLD decisions and document its strategy.

This project focuses on analysis, planning, and simulated (paper) execution. It does not place real trades.

---

## Key Features

- **Agentic reasoning with tools**: The model decides when to call tools (market info, technical signals, ATR, and trade execution via a unified paper broker).
- **Unified paper broker**: `agent_tools/unified_trading.py` records simulated entries/exits and calculates P&L in a local SQLite database.
- **Technical Signal Hub**: `agent_tools/signal_hub.py` provides consolidated RSI/EMA/OBV (and optional ATR) signals.
- **Risk/volatility via ATR**: `agent_tools/atr.py` offers ATR for sizing and trailing stops.
- **Planning & learning**: `agent_tools/planning_tool.py` keeps a persistent `trading_plan.md` that the agent updates over time.
- **Turn control**: `done_tool` lets the model explicitly end a turn early to avoid redundant tool calls.
- **Scheduler-friendly**: `"wait_seconds": "manual"` runs a single cycle and exits (great for cron/Heroku Scheduler). `"sync"` aligns to the next candle close.

---

## Architecture at a glance

- `agent.py` — the main CLI agent; loads config, sets up tools, runs a reasoning loop.
- `config.json` — central configuration for the agent (model, wait mode, etc.) and Coinbase credentials.
- `agent_tools/`
  - `unified_trading.py` — paper broker with trade lifecycle and summary.
  - `signal_hub.py` — unified RSI/EMA/OBV (+optional ATR) signals.
  - `atr.py` — ATR helper for risk/trailing-stop logic.
  - `planning_tool.py` — persistent trading plan (read, update, summarize).
- `helpers/` — shared utility modules.
- `requirements.txt` — Python dependencies.
- Generated at runtime:
  - `trading_plan.md` — persistent plan + updates.
  - `agent_trades.db` — SQLite paper trading database.
  - Optionally `plan_archive/` — where archived plans may be stored (if rotation is enabled later).

---

## Requirements

- Python 3.10+
- An Ollama runtime with a chat-capable model installed (e.g., `llama3.1`, `gpt-oss:20b`, etc.)
- Coinbase Advanced Trade API key and private secret (for market data and account queries; execution here is paper-only)

---

## Installation

```bash
# 1) Create and activate a virtual environment (PowerShell example)
python -m venv venv
./venv/Scripts/Activate.ps1

# 2) Install dependencies
pip install -r requirements.txt
```

---

## Configuration (`config.json`)

Quick start:
- Rename `example_config.json` to `config.json` in the project root.
- Fill in your real Coinbase API key and secret values. Coinbase credentials are optional paper trading is the default.

`config.json` supports both nested and flat formats. Recommended nested structure:

```json
{
  "agent": {
    "model": "gpt-oss:20b",
    "wait_seconds": "sync",
    "candle_granularity": "1H",
    "max_turns": 10
  },
  "coinbase": {
    "coinbase_api_key": "your_api_key",
    "coinbase_api_secret": "-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----"
  }
}
```

Notes:
- `agent.model` — the Ollama model name/tag. Ensure it is pulled/available in your Ollama runtime.
- `agent.wait_seconds` — controls scheduling:
  - Integer (e.g., `300`) — waits N seconds between cycles.
  - `"sync"` — aligns the next run to the next candle boundary based on `candle_granularity`.
  - `"manual"` — one-shot mode: run a single cycle and exit (ideal for cron/Heroku Scheduler).
- `agent.candle_granularity` — examples: `1H`, `5M`, or API-style values (the agent normalizes common variants).
- `agent.max_turns` — caps multi-turn tool reasoning to prevent runaway loops.
- `coinbase.coinbase_api_key` / `coinbase.coinbase_api_secret` — credentials for Coinbase Advanced Trade API.

Security reminder: never commit real API secrets. Use local files or secret managers for production.

---

## Running the Agent

```bash
# From the project root
python agent.py
```

You should see startup logs, then the agent will run a reasoning cycle. Depending on `wait_seconds`:
- Integer: sleeps and repeats.
- `sync`: sleeps until the next candle boundary and repeats.
- `manual`: runs once and exits.

### Scheduler/Serverless (one-shot)
Set `"wait_seconds": "manual"` and invoke `python agent.py` from:
- Cron (Linux/macOS)
- Windows Task Scheduler
- Heroku Scheduler / serverless cron

Each invocation runs one full cycle (market heartbeat, tool reasoning, final response) and then exits.

---

## What the agent can do (tools)

Within `agent.py`, the agent can call these tools during reasoning:

- **Market intelligence**
  - `get_current_market_info(product_id="BTC-USD")` — current price & 24h stats.
  - `get_signals_tool(product_id="BTC-USD")` — unified RSI/EMA/OBV (+optional ATR).
  - `get_atr_tool(product_id="BTC-USD")` — latest ATR for risk sizing / trailing stops.

- **Execution (paper trading only)**
  - `unified_trade_tool(...)` — open/manage/close paper trades and return summaries. Examples:
    - `action="open_long", price=50000.0, risk_usd=25, atr=500, sl=49250, tp=52000`
    - `action="on_price", price=50500.0` (heartbeat/mark-to-market)
    - `action="summary"` (current position + P&L)
    - `action="close", price=50750.0`
    - Optional trailing params at entry: `move_to_be_atr`, `trail_start_atr`, `trail_distance_atr`

- **Planning & learning**
  - `get_trading_plan_summary()` — quick summary of the plan.
  - `get_trading_plan()` — full `trading_plan.md` content.
  - `update_trading_plan_tool(update_reason, content, section)` — append a structured update.
  - `record_trade_result(trade_type, asset, outcome, profit_loss, lessons)` — log results + lessons learned.

- **Turn control**
  - `done_tool(note="...")` — explicitly end the current reasoning turn early.

---

## Paper Trading Database

- SQLite file: `agent_trades.db` (created automatically in the project root)
- Records entries/exits and computes P&L for transparent analysis.
- Best practice: back up this file if you’re running long experiments.

---

## Trading Plan (`trading_plan.md`)

- Created at first run; contains objectives, strategy, and update sections.
- Use the planning tools to add updates and record lessons/results.
- Tip: If `trading_plan.md` grows very large during long experiments, consider archiving older versions. An automated rotation/archiving mechanism can be added on request.

---

## Logging

- Logs use Python’s `logging` and go to stdout by default.
- Adjust verbosity by setting the root logging level in your environment or in code if desired.

---

## Troubleshooting

- **Ollama/model errors**: Ensure your model is installed and running in Ollama. Try `ollama run llama3.1` (or your chosen model) to verify.
- **Coinbase authentication**: Confirm API key/secret are correct; Advanced Trade API must be enabled on your key.
- **Time sync issues**: When using `sync` mode, verify your system clock is accurate.
- **Data availability**: ATR and some signals require a minimum amount of recent candle history; if you see NaN, increase sample size or timeframe.

---

## Safety and Scope

- This repository is for research and educational purposes.
- The agent executes PAPER trades only. No real orders are sent.
- Always manage secrets responsibly and test thoroughly before any production usage.

---

## Contributing / Extending

- Add new tools into `agent_tools/` and wire them into `agent.py`.
- Keep tool outputs concise to preserve context for LLM reasoning.
- Prefer logging over prints (except CLI cues in `agent.py`).
- Keep helper modules in `helpers/`.

---

## License

This project is provided "as is" without warranty. See repository for license details or add one if missing.
