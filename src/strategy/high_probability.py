"""High-probability trading strategy."""

import logging
from decimal import Decimal
from typing import Optional

from config.settings import TradingSettings
from src.models import ExitSignal, MarketOpportunity, Position, TradeSignal
from src.strategy.position_sizer import PositionSizer

logger = logging.getLogger(__name__)


class HighProbabilityStrategy:
    """
    Strategy that enters high-probability positions and exits at profit target.

    Entry Logic:
    - Market has liquidity >= threshold
    - Yes or No price >= probability_threshold
    - Choose side with higher probability
    - Place limit order at current best ask price

    Exit Logic:
    - Current P&L >= profit_target_percent → take profit
    - Current P&L <= -stop_loss_percent → cut losses (if configured)
    - Market settles → position auto-closes
    """

    def __init__(self, settings: TradingSettings):
        """
        Initialize the strategy.

        Args:
            settings: Trading configuration
        """
        self.settings = settings
        self.sizer = PositionSizer(settings)
        self.profit_target = Decimal(str(settings.profit_target_percent))
        self.stop_loss = (
            Decimal(str(settings.stop_loss_percent))
            if settings.stop_loss_percent
            else None
        )

    def evaluate_entry(
        self, opportunity: MarketOpportunity, portfolio_value: Decimal
    ) -> Optional[TradeSignal]:
        """
        Evaluate whether to enter a position.

        Args:
            opportunity: Market opportunity that passed filters
            portfolio_value: Current portfolio value in cents

        Returns:
            TradeSignal if entry is warranted, None otherwise
        """
        # Calculate position size
        contracts = self.sizer.calculate_contracts(
            portfolio_value=portfolio_value,
            entry_price=opportunity.entry_price,
        )

        if contracts <= 0:
            logger.warning(
                f"Insufficient funds for {opportunity.market.ticker}"
            )
            return None

        # Validate position size
        if not self.sizer.validate_position(
            contracts=contracts,
            entry_price=opportunity.entry_price,
            portfolio_value=portfolio_value,
        ):
            return None

        # Create trade signal
        signal = TradeSignal(
            ticker=opportunity.market.ticker,
            side=opportunity.recommended_side,
            entry_price=opportunity.entry_price,
            contracts=contracts,
            reason=(
                f"High probability: {opportunity.probability:.1%} "
                f"(liquidity: ${opportunity.liquidity/100:,.2f})"
            ),
        )

        logger.info(
            f"Entry signal: {signal.ticker} - {signal.side.value} "
            f"x{signal.contracts} @ {signal.entry_price}c "
            f"(reason: {signal.reason})"
        )

        return signal

    def evaluate_exit(self, position: Position) -> Optional[ExitSignal]:
        """
        Evaluate whether to exit a position.

        Args:
            position: Current position

        Returns:
            ExitSignal if exit is warranted, None otherwise
        """
        pnl_percent = position.unrealized_pnl_percent

        # Check profit target
        if pnl_percent >= self.profit_target:
            signal = ExitSignal(
                ticker=position.ticker,
                side=position.side,
                contracts=position.contracts,
                exit_price=position.current_price,
                reason="profit_target",
            )
            logger.info(
                f"Exit signal (profit): {position.ticker} - "
                f"P&L {pnl_percent:.2%} >= target {self.profit_target:.2%}"
            )
            return signal

        # Check stop-loss (if configured and market has enough volume)
        # Low-volume markets have noisy price swings that trigger false stop-losses
        if self.stop_loss and pnl_percent <= -self.stop_loss:
            min_vol = self.settings.stop_loss_min_volume
            if position.volume >= min_vol:
                signal = ExitSignal(
                    ticker=position.ticker,
                    side=position.side,
                    contracts=position.contracts,
                    exit_price=position.current_price,
                    reason="stop_loss",
                )
                logger.info(
                    f"Exit signal (stop-loss): {position.ticker} - "
                    f"P&L {pnl_percent:.2%} <= limit -{self.stop_loss:.2%} "
                    f"(volume: {position.volume:,})"
                )
                return signal
            else:
                logger.debug(
                    f"Skipping stop-loss for {position.ticker}: "
                    f"volume {position.volume:,} < {min_vol:,} threshold"
                )

        return None

    def should_exit(self, position: Position) -> bool:
        """
        Quick check if position should be exited.

        Args:
            position: Position to check

        Returns:
            True if position should be exited
        """
        return self.evaluate_exit(position) is not None
