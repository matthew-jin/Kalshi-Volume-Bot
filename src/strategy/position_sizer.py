"""Position sizing logic with compounding support."""

import logging
from decimal import Decimal

from config.settings import TradingSettings

logger = logging.getLogger(__name__)


class PositionSizer:
    """
    Calculates position sizes based on portfolio value.

    Supports fixed percentage sizing with optional compounding
    (using current portfolio value instead of initial capital).
    """

    def __init__(self, settings: TradingSettings):
        """
        Initialize the position sizer.

        Args:
            settings: Trading configuration
        """
        self.settings = settings
        self.min_position_pct = Decimal(str(settings.min_position_percent))
        self.max_position_pct = Decimal(str(settings.max_position_percent))
        self.min_contracts = settings.min_contracts

    def calculate_contracts(
        self,
        portfolio_value: Decimal,
        entry_price: Decimal,
    ) -> int:
        """
        Calculate number of contracts to buy.

        Args:
            portfolio_value: Total portfolio value in cents
            entry_price: Entry price per contract in cents

        Returns:
            Number of contracts to buy (at least min_contracts)
        """
        if portfolio_value <= 0 or entry_price <= 0:
            logger.warning("Invalid portfolio value or entry price")
            return self.min_contracts

        # Calculate maximum spend based on portfolio percentage
        max_spend = portfolio_value * self.max_position_pct

        # Calculate contracts
        contracts = int(max_spend / entry_price)

        # Ensure minimum
        contracts = max(contracts, self.min_contracts)

        logger.debug(
            f"Position sizing: portfolio=${portfolio_value/100:.2f}, "
            f"max_spend=${max_spend/100:.2f}, "
            f"entry_price={entry_price}c, "
            f"contracts={contracts}"
        )

        return contracts

    def calculate_position_value(
        self, contracts: int, entry_price: Decimal
    ) -> Decimal:
        """
        Calculate total position value.

        Args:
            contracts: Number of contracts
            entry_price: Entry price per contract in cents

        Returns:
            Total position value in cents
        """
        return Decimal(contracts) * entry_price

    def validate_position(
        self,
        contracts: int,
        entry_price: Decimal,
        portfolio_value: Decimal,
    ) -> bool:
        """
        Validate that a position is within min/max limits.

        Args:
            contracts: Proposed number of contracts
            entry_price: Entry price per contract
            portfolio_value: Current portfolio value

        Returns:
            True if position is within limits
        """
        position_value = self.calculate_position_value(contracts, entry_price)
        min_allowed = portfolio_value * self.min_position_pct
        max_allowed = portfolio_value * self.max_position_pct

        if position_value > max_allowed:
            logger.warning(
                f"Position value ${position_value/100:.2f} exceeds "
                f"max allowed ${max_allowed/100:.2f} "
                f"({self.max_position_pct:.0%} of portfolio)"
            )
            return False

        if position_value < min_allowed:
            logger.warning(
                f"Position value ${position_value/100:.2f} below "
                f"min allowed ${min_allowed/100:.2f} "
                f"({self.min_position_pct:.0%} of portfolio)"
            )
            return False

        return True
