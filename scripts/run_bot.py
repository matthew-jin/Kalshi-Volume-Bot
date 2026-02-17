#!/usr/bin/env python3
"""Entry point for the Kalshi trading bot."""

import argparse
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import load_settings
from src.core.bot import create_bot


def setup_logging(log_level: str, log_file: Path) -> None:
    """Configure logging for the application."""
    # Create log directory if needed
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Console handler
    console_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)

    # File handler (rotating)
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)

    # Trade logger (separate file)
    trade_logger = logging.getLogger("trades")
    trade_file = log_file.parent / "trades.log"
    trade_handler = RotatingFileHandler(
        trade_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
    )
    trade_format = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    trade_handler.setFormatter(trade_format)
    trade_logger.addHandler(trade_handler)
    trade_logger.setLevel(logging.INFO)

    # Reduce noise from libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Kalshi High-Probability Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_bot.py                    # Run with config.yaml settings
  python scripts/run_bot.py --dry-run          # Simulate without placing orders
  python scripts/run_bot.py --log-level DEBUG  # Enable debug logging
        """,
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/config.yaml"),
        help="Path to config file (default: config/config.yaml)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level from config",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without placing actual orders (not yet implemented)",
    )

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Load settings
    try:
        settings = load_settings()
    except Exception as e:
        print(f"Error loading settings: {e}", file=sys.stderr)
        return 1

    # Override log level if specified
    log_level = args.log_level or settings.logging.level

    # Setup logging
    setup_logging(log_level, settings.logging.file)
    logger = logging.getLogger(__name__)

    if args.dry_run:
        logger.warning("Dry-run mode is not yet implemented")

    # Create bot
    try:
        bot = create_bot(settings)
    except Exception as e:
        logger.exception(f"Failed to create bot: {e}")
        return 1

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        bot.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run bot
    try:
        bot.start()
        return 0
    except Exception as e:
        logger.exception(f"Bot crashed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
