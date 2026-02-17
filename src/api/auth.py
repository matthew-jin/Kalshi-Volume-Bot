"""Authentication handling for Kalshi API."""

import logging
from pathlib import Path

from config.settings import KalshiSettings
from src.api.exceptions import AuthenticationError, ConfigurationError

logger = logging.getLogger(__name__)


def load_private_key(key_path: Path) -> str:
    """
    Load private key from PEM file.

    Args:
        key_path: Path to the PEM file

    Returns:
        Private key contents as string

    Raises:
        ConfigurationError: If key file doesn't exist or is invalid
    """
    if not key_path.exists():
        raise ConfigurationError(f"Private key file not found: {key_path}")

    try:
        with open(key_path) as f:
            key_content = f.read()

        if "PRIVATE KEY" not in key_content:
            raise ConfigurationError(
                f"Invalid private key format in {key_path}. Expected PEM format."
            )

        return key_content
    except IOError as e:
        raise ConfigurationError(f"Failed to read private key: {e}")


def validate_credentials(settings: KalshiSettings) -> None:
    """
    Validate that all required credentials are configured.

    Args:
        settings: Kalshi settings containing credentials

    Raises:
        ConfigurationError: If credentials are missing or invalid
    """
    env_name = settings.environment.value
    env_prefix = "SANDBOX" if env_name == "sandbox" else "PROD"

    if not settings.api_key_id:
        raise ConfigurationError(
            f"KALSHI_{env_prefix}_API_KEY_ID environment variable not set. "
            f"Please set it in your .env file for {env_name} environment."
        )

    if not settings.private_key_path.exists():
        raise ConfigurationError(
            f"Private key file not found at {settings.private_key_path}. "
            f"Please set KALSHI_{env_prefix}_PRIVATE_KEY_PATH to the correct path "
            f"for {env_name} environment."
        )

    # Validate key format
    load_private_key(settings.private_key_path)
    logger.info(f"Credentials validated successfully for {env_name} environment")


def get_auth_headers(api_key_id: str, private_key: str) -> dict:
    """
    Generate authentication headers for API requests.

    Note: The kalshi-python SDK handles authentication internally,
    so this is mainly for reference or custom implementations.

    Args:
        api_key_id: Kalshi API key ID
        private_key: Private key contents

    Returns:
        Dict of headers for authenticated requests
    """
    # Kalshi uses RSA signature-based auth handled by the SDK
    # This function is a placeholder for any custom auth needs
    return {
        "Content-Type": "application/json",
    }
