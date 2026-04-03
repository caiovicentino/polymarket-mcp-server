"""
Safety limits and risk management for Polymarket trading.
Validates orders against configured limits before execution.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderRequest:
    """Represents an order request to validate"""

    token_id: str
    price: float
    size: float  # In shares
    side: str  # BUY or SELL
    market_id: Optional[str] = None


@dataclass
class Position:
    """Represents a user's position in a market"""

    token_id: str
    market_id: str
    size: float  # In shares
    avg_price: float
    current_price: float
    unrealized_pnl: float

    @property
    def value_usd(self) -> float:
        """Current value of position in USD"""
        return self.size * self.current_price


@dataclass
class MarketData:
    """Market data for validation"""

    market_id: str
    token_id: str
    best_bid: float
    best_ask: float
    bid_liquidity: float  # Liquidity at best bid (in USD)
    ask_liquidity: float  # Liquidity at best ask (in USD)
    total_volume: float  # Total market volume (in USD)

    @property
    def spread(self) -> float:
        """Calculate spread percentage"""
        if self.best_bid == 0:
            return 1.0
        return (self.best_ask - self.best_bid) / self.best_bid

    @property
    def mid_price(self) -> float:
        """Calculate mid price"""
        return (self.best_bid + self.best_ask) / 2

    @property
    def total_liquidity(self) -> float:
        """Total liquidity at best prices"""
        return self.bid_liquidity + self.ask_liquidity


class SafetyLimits:
    """
    Risk management and safety limit validation.

    Validates orders against configured limits:
    - Order size limits
    - Total exposure limits
    - Position size limits per market
    - Liquidity requirements
    - Spread tolerance
    """

    def __init__(
        self,
        max_order_size_usd: float,
        max_total_exposure_usd: float,
        max_position_size_per_market: float,
        min_liquidity_required: float,
        max_spread_tolerance: float,
        require_confirmation_above_usd: float,
        auto_cancel_on_large_spread: bool = True,
    ):
        self.max_order_size_usd = max_order_size_usd
        self.max_total_exposure_usd = max_total_exposure_usd
        self.max_position_size_per_market = max_position_size_per_market
        self.min_liquidity_required = min_liquidity_required
        self.max_spread_tolerance = max_spread_tolerance
        self.require_confirmation_above_usd = require_confirmation_above_usd
        self.auto_cancel_on_large_spread = auto_cancel_on_large_spread

    def validate_order(
        self, order: OrderRequest, current_positions: List[Position], market_data: MarketData
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate an order against all safety limits.

        Args:
            order: Order request to validate
            current_positions: List of current positions
            market_data: Market data for the order

        Returns:
            Tuple of (is_valid, error_message)
            If valid, error_message is None
        """
        # 1. Validate order size
        order_value_usd = order.size * order.price
        if order_value_usd > self.max_order_size_usd:
            return False, (
                f"Order size ${order_value_usd:.2f} exceeds maximum "
                f"${self.max_order_size_usd:.2f}"
            )

        # 2. Validate total exposure
        total_exposure = self._calculate_total_exposure(current_positions)
        new_exposure = total_exposure

        # Adjust exposure based on order side
        if order.side.upper() == "BUY":
            new_exposure += order_value_usd
        else:  # SELL
            # Selling reduces exposure (unless it's a short)
            existing_position = self._get_position(current_positions, order.token_id)
            if existing_position:
                new_exposure -= min(order_value_usd, existing_position.value_usd)
            else:
                # Shorting increases exposure
                new_exposure += order_value_usd

        if new_exposure > self.max_total_exposure_usd:
            return False, (
                f"Order would increase exposure to ${new_exposure:.2f}, "
                f"exceeding maximum ${self.max_total_exposure_usd:.2f}"
            )

        # 3. Validate position size per market
        if order.market_id:
            market_positions = [p for p in current_positions if p.market_id == order.market_id]
            market_exposure = self._calculate_total_exposure(market_positions)

            if order.side.upper() == "BUY":
                new_market_exposure = market_exposure + order_value_usd
            else:
                existing_position = self._get_position(market_positions, order.token_id)
                if existing_position:
                    new_market_exposure = market_exposure - min(
                        order_value_usd, existing_position.value_usd
                    )
                else:
                    new_market_exposure = market_exposure + order_value_usd

            if new_market_exposure > self.max_position_size_per_market:
                return False, (
                    f"Order would increase market exposure to ${new_market_exposure:.2f}, "
                    f"exceeding per-market maximum ${self.max_position_size_per_market:.2f}"
                )

        # 4. Validate liquidity
        if market_data.total_liquidity < self.min_liquidity_required:
            return False, (
                f"Insufficient market liquidity ${market_data.total_liquidity:.2f}, "
                f"minimum required ${self.min_liquidity_required:.2f}"
            )

        # 5. Validate spread
        if market_data.spread > self.max_spread_tolerance:
            msg = (
                f"Market spread {market_data.spread:.2%} exceeds maximum "
                f"{self.max_spread_tolerance:.2%}"
            )
            if self.auto_cancel_on_large_spread:
                return False, msg
            else:
                logger.warning(f"{msg} - proceeding anyway (auto-cancel disabled)")

        # All validations passed
        return True, None

    def check_exposure(self, current_positions: List[Position]) -> Tuple[float, bool]:
        """
        Check total exposure across all positions.

        Args:
            current_positions: List of current positions

        Returns:
            Tuple of (total_exposure_usd, is_within_limits)
        """
        total_exposure = self._calculate_total_exposure(current_positions)
        is_within_limits = total_exposure <= self.max_total_exposure_usd

        if not is_within_limits:
            logger.warning(
                f"Total exposure ${total_exposure:.2f} exceeds maximum "
                f"${self.max_total_exposure_usd:.2f}"
            )

        return total_exposure, is_within_limits

    def should_require_confirmation(
        self, order: OrderRequest, autonomous_trading_enabled: bool = True
    ) -> bool:
        """
        Determine if order requires user confirmation.

        Args:
            order: Order request to check
            autonomous_trading_enabled: Whether autonomous trading is enabled

        Returns:
            True if confirmation required, False otherwise
        """
        # If autonomous trading disabled, always require confirmation
        if not autonomous_trading_enabled:
            return True

        # Check if order size exceeds confirmation threshold
        order_value_usd = order.size * order.price
        return order_value_usd > self.require_confirmation_above_usd

    def get_position_summary(self, current_positions: List[Position]) -> Dict[str, any]:
        """
        Get summary of current positions and exposure.

        Args:
            current_positions: List of current positions

        Returns:
            Dictionary with position summary
        """
        total_exposure = self._calculate_total_exposure(current_positions)
        total_pnl = sum(p.unrealized_pnl for p in current_positions)

        # Group by market
        markets: Dict[str, List[Position]] = {}
        for position in current_positions:
            if position.market_id not in markets:
                markets[position.market_id] = []
            markets[position.market_id].append(position)

        market_exposures = {
            market_id: self._calculate_total_exposure(positions)
            for market_id, positions in markets.items()
        }

        return {
            "total_positions": len(current_positions),
            "total_exposure_usd": total_exposure,
            "total_unrealized_pnl": total_pnl,
            "exposure_limit_usd": self.max_total_exposure_usd,
            "exposure_utilization": total_exposure / self.max_total_exposure_usd,
            "markets": {
                market_id: {
                    "exposure_usd": exposure,
                    "position_count": len(markets[market_id]),
                    "limit_usd": self.max_position_size_per_market,
                    "utilization": exposure / self.max_position_size_per_market,
                }
                for market_id, exposure in market_exposures.items()
            },
        }

    def _calculate_total_exposure(self, positions: List[Position]) -> float:
        """Calculate total exposure from positions"""
        return sum(abs(p.value_usd) for p in positions)

    def _get_position(self, positions: List[Position], token_id: str) -> Optional[Position]:
        """Get position for a specific token"""
        for position in positions:
            if position.token_id == token_id:
                return position
        return None


def create_safety_limits_from_config(config) -> SafetyLimits:
    """
    Create SafetyLimits instance from configuration.

    Args:
        config: PolymarketConfig instance

    Returns:
        SafetyLimits instance
    """
    return SafetyLimits(
        max_order_size_usd=config.MAX_ORDER_SIZE_USD,
        max_total_exposure_usd=config.MAX_TOTAL_EXPOSURE_USD,
        max_position_size_per_market=config.MAX_POSITION_SIZE_PER_MARKET,
        min_liquidity_required=config.MIN_LIQUIDITY_REQUIRED,
        max_spread_tolerance=config.MAX_SPREAD_TOLERANCE,
        require_confirmation_above_usd=config.REQUIRE_CONFIRMATION_ABOVE_USD,
        auto_cancel_on_large_spread=config.AUTO_CANCEL_ON_LARGE_SPREAD,
    )
