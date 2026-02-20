"""Configuration management using Pydantic Settings."""

import os
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env file at module import time
load_dotenv()


class Environment(str, Enum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class MarketCategory(str, Enum):
    ALL = "all"
    CRYPTO = "crypto"
    WEATHER = "weather"
    POLITICS = "politics"
    ECONOMICS = "economics"
    SPORTS = "sports"
    PLAYER_PROPS = "player_props"
    COLLEGE_BASKETBALL = "college_basketball"
    BASKETBALL = "basketball"


class KalshiSettings(BaseSettings):
    """Kalshi API configuration."""

    model_config = SettingsConfigDict(
        env_prefix="KALSHI_",
        env_file=".env",
        extra="ignore",
    )

    # Environment selection
    environment: Environment = Field(
        default=Environment.SANDBOX, description="API environment"
    )

    # Sandbox credentials
    sandbox_api_key_id: str = Field(default="", description="Sandbox API key ID")
    sandbox_private_key_path: Path = Field(
        default=Path("private_key.pem"), description="Path to sandbox private key"
    )

    # Production credentials
    prod_api_key_id: str = Field(default="", description="Production API key ID")
    prod_private_key_path: Path = Field(
        default=Path("private_key_prod.pem"), description="Path to production private key"
    )

    @property
    def api_key_id(self) -> str:
        """Get API key ID for current environment."""
        if self.environment == Environment.PRODUCTION:
            return self.prod_api_key_id
        return self.sandbox_api_key_id

    @property
    def private_key_path(self) -> Path:
        """Get private key path for current environment."""
        if self.environment == Environment.PRODUCTION:
            return self.prod_private_key_path
        return self.sandbox_private_key_path

    @property
    def base_url(self) -> str:
        """Get API base URL for current environment."""
        if self.environment == Environment.SANDBOX:
            return "https://demo-api.kalshi.co/trade-api/v2"
        return "https://api.elections.kalshi.com/trade-api/v2"


class TradingSettings(BaseSettings):
    """Trading strategy configuration."""

    model_config = SettingsConfigDict(
        env_prefix="TRADING_",
        env_file=".env",
        extra="ignore",
    )

    # Thresholds
    liquidity_threshold_usd: int = Field(
        default=50000, ge=0, description="Minimum market liquidity in USD"
    )
    probability_threshold: float = Field(
        default=0.80, ge=0.5, le=0.99, description="Minimum probability to enter"
    )
    max_probability_threshold: float = Field(
        default=0.90, ge=0.5, le=0.99, description="Maximum probability to enter (avoid overpaying)"
    )

    # Exit conditions
    profit_target_percent: float = Field(
        default=0.065, ge=0.01, le=0.50, description="Exit at this profit %"
    )
    stop_loss_percent: Optional[float] = Field(
        default=None, ge=0.01, le=0.50, description="Optional stop-loss %"
    )
    stop_loss_min_volume: int = Field(
        default=100000, ge=0, description="Only apply stop-loss to markets with at least this volume"
    )
    min_market_volume: int = Field(
        default=0, ge=0, description="Minimum market volume (contracts traded) to consider"
    )

    # Position sizing
    min_position_percent: float = Field(
        default=0.02, ge=0.01, le=0.50, description="Min % of portfolio per trade"
    )
    max_position_percent: float = Field(
        default=0.10, ge=0.01, le=0.50, description="Max % of portfolio per trade"
    )
    max_concurrent_positions: int = Field(
        default=10, ge=1, le=100, description="Max open positions"
    )
    min_contracts: int = Field(default=1, ge=1, description="Minimum contracts per trade")
    compound_profits: bool = Field(
        default=True, description="Reinvest profits into position sizing"
    )

    # Timing
    scan_interval_seconds: int = Field(
        default=60, ge=10, description="How often to scan for opportunities"
    )
    max_hours_until_close: int = Field(
        default=24, ge=0, description="Only consider markets closing within this many hours (0 = no limit)"
    )
    order_timeout_seconds: int = Field(
        default=300, ge=60, description="Cancel unfilled orders after this time"
    )

    # Market filter
    market_category: MarketCategory = Field(
        default=MarketCategory.ALL, description="Which market category to scan"
    )
    include_live_markets: bool = Field(
        default=False, description="Include active/live markets (games in progress)"
    )
    dry_run: bool = Field(
        default=False, description="Simulate trades without placing real orders"
    )

    @field_validator("probability_threshold", "profit_target_percent", "max_position_percent")
    @classmethod
    def round_to_decimals(cls, v: float) -> float:
        """Round float values to reasonable precision."""
        return round(v, 4)


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        env_file=".env",
        extra="ignore",
    )

    level: str = Field(default="INFO", description="Log level")
    file: Path = Field(default=Path("logs/bot.log"), description="Log file path")


class Settings(BaseSettings):
    """Main settings container."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    kalshi: KalshiSettings = Field(default_factory=KalshiSettings)
    trading: TradingSettings = Field(default_factory=TradingSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def from_yaml(cls, config_path: Path = Path("config/config.yaml")) -> "Settings":
        """Load settings from YAML file, with env vars taking precedence."""
        yaml_config = {}
        if config_path.exists():
            with open(config_path) as f:
                yaml_config = yaml.safe_load(f) or {}

        # Build nested settings from YAML
        kalshi_config = yaml_config.get("kalshi", {})
        trading_config = yaml_config.get("trading", {})
        logging_config = yaml_config.get("logging", {})

        # Environment variables take precedence over YAML
        # Remove YAML values if env var is set
        if os.environ.get("KALSHI_ENVIRONMENT"):
            kalshi_config.pop("environment", None)

        return cls(
            kalshi=KalshiSettings(**kalshi_config),
            trading=TradingSettings(**trading_config),
            logging=LoggingSettings(**logging_config),
        )


def load_settings() -> Settings:
    """Load settings from config file and environment."""
    config_path = Path("config/config.yaml")
    if config_path.exists():
        return Settings.from_yaml(config_path)
    return Settings()
