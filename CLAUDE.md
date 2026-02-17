# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Install dependencies
pip install -e .

# Install dev dependencies
pip install -e ".[dev]"

# Run the bot
python scripts/run_bot.py

# Run with debug logging
python scripts/run_bot.py --log-level DEBUG

# Run tests
pytest
```

## Architecture

This is a Kalshi prediction market trading bot with the following structure:

- `config/` - Configuration management using Pydantic Settings
  - `settings.py` - Settings classes with validation
  - `config.yaml` - User-editable configuration

- `src/api/` - Kalshi API client layer
  - `client.py` - Main API wrapper around kalshi-python SDK
  - `rate_limiter.py` - Token bucket rate limiter (5 req/sec)
  - `exceptions.py` - Custom exception hierarchy

- `src/models/` - Data models (dataclasses)
  - `market.py` - Market, OrderBook, MarketOpportunity
  - `order.py` - OrderRequest, OrderResult, TradeSignal
  - `position.py` - Position, PortfolioSnapshot

- `src/scanner/` - Market discovery and filtering
  - `market_scanner.py` - Fetches markets and applies filters
  - `filters.py` - Liquidity and probability filters
  - `categories.py` - Market category matching (crypto, weather, etc.)

- `src/strategy/` - Trading logic
  - `high_probability.py` - Entry/exit decision logic
  - `position_sizer.py` - Calculates position sizes with compounding

- `src/executor/` - Order execution
  - `order_manager.py` - Places and tracks orders
  - `position_monitor.py` - Monitors open positions and P&L
  - `exit_handler.py` - Executes exits at profit target or stop-loss

- `src/portfolio/` - Portfolio state
  - `tracker.py` - Tracks cash, positions, and P&L
  - `compound.py` - Compound growth calculations

- `src/core/bot.py` - Main orchestrator that runs the scan/enter/exit loop

## Key Concepts

- **Prices are in cents**: Kalshi prices are 1-99 cents representing probability
- **Sandbox vs Production**: Toggle via `KALSHI_ENVIRONMENT` env var
- **Compounding**: When enabled, position sizes use current portfolio value
