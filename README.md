# Kalshi High-Probability Trading Bot

A Python trading bot for Kalshi prediction markets that identifies high-probability opportunities and compounds profits.

## Strategy

1. **Scan** for markets matching your category filter (e.g., college basketball)
2. **Filter** by volume, liquidity, and probability thresholds
3. **Enter** YES positions on qualifying markets
4. **Exit** when profit target is reached (default: 6.5%) or stop-loss triggers
5. **Compound** profits into subsequent trades

## Quick Start

### 1. Prerequisites

- Python 3.10+
- Kalshi account with API access
- API key and private key from Kalshi

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/matthew-jin/Kalshi-Volume-Bot.git
cd Kalshi-Volume-Bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -e .
```

**macOS note**: If you installed Python from python.org and get SSL certificate errors, run:
```bash
/Applications/Python\ 3.XX/Install\ Certificates.command
```

### 3. Configuration

Copy the example environment file and add your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your Kalshi API credentials:

```bash
# For production trading:
KALSHI_ENVIRONMENT=production
KALSHI_PROD_API_KEY_ID=your_api_key_id_here
KALSHI_PROD_PRIVATE_KEY_PATH=/absolute/path/to/your/private_key.pem

# For sandbox/demo testing:
KALSHI_ENVIRONMENT=sandbox
KALSHI_SANDBOX_API_KEY_ID=your_sandbox_key_id_here
KALSHI_SANDBOX_PRIVATE_KEY_PATH=/absolute/path/to/your/sandbox_key.pem
```

To get your API credentials:
1. Go to [Kalshi Settings](https://kalshi.com/account/settings) (or demo site for sandbox)
2. Create a new API key
3. Save the Key ID and download the private key PEM file
4. Set the paths in your `.env` file (use absolute paths)

### 4. Run the Bot

```bash
python scripts/run_bot.py

# With debug logging
python scripts/run_bot.py --log-level DEBUG
```

## Configuration

All trading parameters are in `config/config.yaml`:

```yaml
kalshi:
  environment: production  # sandbox or production

trading:
  # Market filtering
  market_category: college_basketball  # all, crypto, weather, politics, economics, sports, player_props, college_basketball
  liquidity_threshold_usd: 0           # Minimum orderbook liquidity in USD (0 for markets with indicative quotes only)
  min_market_volume: 10000             # Minimum contracts traded to consider a market
  include_live_markets: false          # Set to false to skip games already in progress

  # Entry thresholds
  probability_threshold: 0.70         # Minimum probability to enter (0.5 - 0.99)
  max_probability_threshold: 0.90     # Maximum probability (hard cap, never buy above 90c)

  # Exit conditions
  profit_target_percent: 0.065        # Exit at 6.5% profit
  stop_loss_percent: 0.1              # Exit if down 10% (null = disabled)
  stop_loss_min_volume: 100000        # Only apply stop-loss to markets with this volume+

  # Position sizing
  min_position_percent: 0.02          # Min % of portfolio per trade
  max_position_percent: 0.10          # Max % of portfolio per trade
  max_concurrent_positions: 4         # Max open positions at once
  min_contracts: 1                    # Minimum contracts per trade
  compound_profits: true              # Reinvest profits into position sizing

  # Timing
  scan_interval_seconds: 30           # How often to scan for opportunities
  order_timeout_seconds: 300          # Cancel unfilled orders after 5 minutes
  max_hours_until_close: 0            # Only consider markets closing within N hours (0 = no limit)

  # Safety
  dry_run: false                      # Scan and log without placing real orders

logging:
  level: INFO
  file: logs/bot.log
```

### Environment Variables

Settings can also be overridden via environment variables:

```bash
KALSHI_ENVIRONMENT=production
TRADING_LIQUIDITY_THRESHOLD_USD=50000
TRADING_PROBABILITY_THRESHOLD=0.85
TRADING_PROFIT_TARGET_PERCENT=0.07
```

## Market Categories

| Category | Markets |
|----------|---------|
| `all` | All open markets |
| `crypto` | Bitcoin, Ethereum, crypto prices |
| `weather` | Temperature, storms, precipitation |
| `politics` | Elections, policy, government |
| `economics` | Fed rates, inflation, GDP, jobs |
| `sports` | NFL, NBA, championships |
| `player_props` | Player-level stat markets |
| `college_basketball` | NCAAB game winners, spreads, totals |

## Project Structure

```
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

- `logs/bot.log` - General bot activity
- `logs/trades.log` - Entry and exit records with prices

## Safety Features

- **Sandbox mode**: Test with demo money before going live
- **Dry run mode**: Scan and log opportunities without placing orders
- **Position limits**: Cap maximum concurrent positions and per-trade sizing
- **Hard price cap**: Never buys above 90c entry price
- **Stop-loss**: Optional automatic loss limiting (with volume threshold to avoid noisy low-volume markets)
- **Volume filter**: Skip markets with insufficient trading activity
- **Rate limiting**: Respects Kalshi API limits (5 req/sec)
- **Graceful shutdown**: Ctrl+C stops cleanly with daily summary

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
