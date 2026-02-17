"""Order management for placing and tracking orders."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from config.settings import TradingSettings
from src.api.client import KalshiClient
from src.api.exceptions import InsufficientFundsError, MarketClosedError, OrderFailedError
from src.models import OrderResult, OrderStatus, Side, TradeSignal

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages order placement and tracking.

    Responsibilities:
    - Place entry and exit orders
    - Track pending orders
    - Cancel stale orders
    """

    def __init__(self, client: KalshiClient, settings: TradingSettings):
        """
        Initialize the order manager.

        Args:
            client: Kalshi API client
            settings: Trading configuration
        """
        self.client = client
        self.settings = settings
        self._pending_orders: Dict[str, OrderResult] = {}  # order_id -> OrderResult

    def place_entry_order(self, signal: TradeSignal) -> Optional[OrderResult]:
        """
        Place an entry order based on a trade signal.

        Args:
            signal: Trade signal with entry details

        Returns:
            OrderResult if successful, None if failed
        """
        logger.info(
            f"Placing entry order: {signal.ticker} - "
            f"{signal.side.value} x{signal.contracts} @ {signal.entry_price}c"
        )

        try:
            result = self.client.place_order(
                ticker=signal.ticker,
                side=signal.side,
                action="buy",
                contracts=signal.contracts,
                price=int(signal.entry_price),
                order_type="limit",
            )

            if result.status in (
                OrderStatus.OPEN, OrderStatus.FILLED,
                OrderStatus.EXECUTED, OrderStatus.RESTING,
            ):
                self._pending_orders[result.order_id] = result
                logger.info(
                    f"Entry order placed: {result.order_id} - "
                    f"status={result.status.value}, filled={result.filled_contracts}"
                )
                return result
            else:
                logger.warning(f"Entry order rejected: {result.status}")
                return None

        except InsufficientFundsError as e:
            logger.error(f"Insufficient funds for entry: {e}")
            return None
        except MarketClosedError as e:
            logger.warning(f"Market closed, cannot enter: {e}")
            return None
        except OrderFailedError as e:
            logger.error(f"Entry order failed: {e}")
            return None

    def place_exit_order(
        self,
        ticker: str,
        side: Side,
        contracts: int,
        price: int,
    ) -> Optional[OrderResult]:
        """
        Place an exit order to close a position.

        Args:
            ticker: Market ticker
            side: Position side (YES or NO)
            contracts: Number of contracts to sell
            price: Exit price in cents

        Returns:
            OrderResult if successful, None if failed
        """
        logger.info(
            f"Placing exit order: {ticker} - "
            f"sell {side.value} x{contracts} @ {price}c"
        )

        try:
            result = self.client.place_order(
                ticker=ticker,
                side=side,
                action="sell",
                contracts=contracts,
                price=price,
                order_type="limit",
            )

            if result.status in (
                OrderStatus.OPEN, OrderStatus.FILLED,
                OrderStatus.EXECUTED, OrderStatus.RESTING,
            ):
                self._pending_orders[result.order_id] = result
                logger.info(
                    f"Exit order placed: {result.order_id} - "
                    f"status={result.status.value}, filled={result.filled_contracts}"
                )
                return result
            else:
                logger.warning(f"Exit order rejected: {result.status}")
                return None

        except MarketClosedError as e:
            logger.warning(f"Market closed, cannot exit: {e}")
            return None
        except OrderFailedError as e:
            logger.error(f"Exit order failed: {e}")
            return None

    def cancel_stale_orders(self) -> List[str]:
        """
        Cancel orders that have been pending too long.

        Returns:
            List of cancelled order IDs
        """
        timeout = timedelta(seconds=self.settings.order_timeout_seconds)
        now = datetime.utcnow()
        cancelled = []

        for order_id, order in list(self._pending_orders.items()):
            if order.status == OrderStatus.OPEN:
                age = now - order.created_at.replace(tzinfo=None)
                if age > timeout:
                    logger.info(
                        f"Cancelling stale order {order_id} "
                        f"(age: {age.total_seconds():.0f}s)"
                    )
                    if self.client.cancel_order(order_id):
                        cancelled.append(order_id)
                        del self._pending_orders[order_id]

        return cancelled

    def get_pending_orders(self) -> List[OrderResult]:
        """Get all pending orders."""
        return list(self._pending_orders.values())

    def refresh_order_status(self, order_id: str) -> Optional[OrderStatus]:
        """
        Refresh the status of a pending order.

        Args:
            order_id: Order ID to refresh

        Returns:
            Updated status or None if not found
        """
        try:
            orders = self.client.get_orders(status="open")
            for order in orders:
                if order.get("order_id") == order_id:
                    status = OrderStatus(order.get("status", "unknown"))
                    if order_id in self._pending_orders:
                        self._pending_orders[order_id].status = status
                    return status

            # Order not in open orders, might be filled or cancelled
            if order_id in self._pending_orders:
                del self._pending_orders[order_id]
            return None

        except Exception as e:
            logger.error(f"Failed to refresh order {order_id}: {e}")
            return None
