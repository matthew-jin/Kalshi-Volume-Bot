# Kalshi High-Probability Trading Bot

A Python trading bot for Kalshi prediction markets that identifies high-probability opportunities and compounds profits.

## Strategy

The bot uses a simple but effective strategy:

1. **Scan** for markets with high liquidity (default: >$50k)
2. **Filter** for positions with high probability (default: >80%)
3. **Enter** positions on qualifying markets
4. **Exit** when profit target is reached (default: 6.5%)
5. **Compound** profits into subsequent trades

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Kalshi account with API access
- API key and private key from Kalshi

### 2. Installation

```bash
# Clone the repository
git clone <your-repo-url>
cd kalshiBot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .
```

### 3. Configuration

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Kalshi API credentials:

```
KALSHI_API_KEY_ID=your_api_key_id_here
KALSHI_PRIVATE_KEY_PATH=/path/to/your/private_key.pem
KALSHI_ENVIRONMENT=sandbox
```

### 4. Run the Bot

```bash
python scripts/run_bot.py
```

## Configuration

All trading parameters can be configured in `config/config.yaml`:

```yaml
kalshi:
  # sandbox (demo money) or production (real money)
  environment: sandbox

trading:
  # Minimum market liquidity in USD
  liquidity_threshold_usd: 50000

  # Minimum probability to enter (0.5 - 0.99)
  probability_threshold: 0.80

  # Exit at this profit percentage
  profit_target_percent: 0.065

  # Optional stop-loss (null = disabled)
  stop_loss_percent: null

  # Max % of portfolio per position
  max_position_percent: 0.10

  # Max concurrent open positions
  max_concurrent_positions: 10

  # Reinvest profits into position sizing
  compound_profits: true

  # Scan interval in seconds
  scan_interval_seconds: 60

  # Market category filter
  # Options: all, crypto, weather, politics, economics, sports
  market_category: all
```

### Environment Variables

Settings can also be overridden via environment variables:

```bash
KALSHI_ENVIRONMENT=production
TRADING_LIQUIDITY_THRESHOLD_USD=100000
TRADING_PROBABILITY_THRESHOLD=0.85
TRADING_PROFIT_TARGET_PERCENT=0.07
```

## Market Categories

Focus on specific market types:

| Category | Markets |
|----------|---------|
| `all` | All open markets |
| `crypto` | Bitcoin, Ethereum, crypto prices |
| `weather` | Temperature, storms, precipitation |
| `politics` | Elections, policy, government |
| `economics` | Fed rates, inflation, GDP, jobs |
| `sports` | NFL, NBA, championships |

## Project Structure

```
kalshiBot/
├── config/
│   ├── settings.py      # Pydantic configuration
│   └── config.yaml      # User settings
├── src/
│   ├── api/             # Kalshi API client
│   ├── models/          # Data models
│   ├── scanner/         # Market scanning & filtering
│   ├── strategy/        # Trading strategy
│   ├── executor/        # Order execution
│   ├── portfolio/       # Portfolio tracking
│   └── core/            # Main bot orchestrator
├── scripts/
│   └── run_bot.py       # Entry point
├── tests/               # Test suite
└── logs/                # Log files
```

## Logs

The bot writes to two log files:

- `logs/bot.log` - General bot activity
- `logs/trades.log` - Entry and exit records

## Safety Features

- **Sandbox mode**: Test with demo money before going live
- **Position limits**: Cap maximum concurrent positions
- **Stop-loss**: Optional automatic loss limiting
- **Rate limiting**: Respects Kalshi API limits (5 req/sec)
- **Graceful shutdown**: Ctrl+C stops cleanly

## Risk Warning

**This bot trades real money when in production mode.** Always:

1. Start with sandbox mode for testing
2. Use small position sizes initially
3. Monitor the bot regularly
4. Understand that past performance doesn't guarantee future results
5. Never invest more than you can afford to lose

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with debug logging
python scripts/run_bot.py --log-level DEBUG
```

## License

MIT
