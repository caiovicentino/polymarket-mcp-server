"""
Trading tools for Polymarket MCP server.
Implements 12 comprehensive tools for order management and smart trading.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import mcp.types as types

from ..config import PolymarketConfig
from ..auth import PolymarketClient
from ..utils import (
    SafetyLimits,
    OrderRequest,
    Position,
    MarketData,
    EndpointCategory,
    get_rate_limiter,
)

logger = logging.getLogger(__name__)


class TradingTools:
    """
    Trading tools for Polymarket.

    Provides 12 tools organized into three categories:
    - Order Creation (4 tools)
    - Order Management (6 tools)
    - Smart Trading (2 tools)
    """

    def __init__(
        self,
        client: PolymarketClient,
        safety_limits: SafetyLimits,
        config: PolymarketConfig
    ):
        self.client = client
        self.safety_limits = safety_limits
        self.config = config
        self.rate_limiter = get_rate_limiter()

    # ========== HELPERS ==========

    @staticmethod
    def _select_token(market: Dict[str, Any], outcome: Optional[str]) -> Tuple[str, str]:
        """
        Select the correct outcome token from a binary/multi-outcome market.

        Args:
            market: Market dict containing a 'tokens' list (each with token_id/outcome).
            outcome: Desired outcome label (e.g. 'YES'/'NO', or the exact outcome string).
                     If None, defaults to the first outcome (typically YES).

        Returns:
            Tuple of (token_id, resolved_outcome_label).

        Raises:
            ValueError: If no tokens exist or the requested outcome is not found.
        """
        tokens = market.get('tokens', [])
        if not tokens:
            raise ValueError("No tokens found for market")

        # Default: first outcome (typically YES) - preserves legacy behavior.
        if not outcome:
            first = tokens[0]
            return first['token_id'], str(first.get('outcome', 'YES'))

        target = outcome.strip().lower()

        # 1) Exact match on the outcome label.
        for t in tokens:
            if str(t.get('outcome', '')).strip().lower() == target:
                return t['token_id'], str(t.get('outcome', outcome))

        # 2) Common aliases mapped to conventional index (YES=0, NO=1).
        if target in ('yes', 'true', '1') and len(tokens) >= 1:
            return tokens[0]['token_id'], str(tokens[0].get('outcome', 'YES'))
        if target in ('no', 'false', '0') and len(tokens) >= 2:
            return tokens[1]['token_id'], str(tokens[1].get('outcome', 'NO'))

        available = [str(t.get('outcome', '?')) for t in tokens]
        raise ValueError(
            f"Outcome '{outcome}' not found in market. Available outcomes: {available}"
        )

    # ========== ORDER CREATION TOOLS ==========

    async def create_limit_order(
        self,
        market_id: str,
        side: str,
        price: float,
        size: float,
        order_type: str = "GTC",
        expiration: Optional[int] = None,
        outcome: Optional[str] = None,
        confirm: bool = False
    ) -> Dict[str, Any]:
        """
        Create a limit order on Polymarket.

        Args:
            market_id: Market condition ID
            side: 'BUY' or 'SELL'
            price: Limit price (0.00-1.00)
            size: Order size in USD
            order_type: 'GTC'|'GTD'|'FOK'|'FAK' (default 'GTC')
            expiration: Unix timestamp for GTD orders (optional)

        Returns:
            Dict with order ID, status, and details

        Raises:
            ValueError: If safety checks fail or invalid parameters
        """
        try:
            # Rate limit check
            await self.rate_limiter.acquire(EndpointCategory.TRADING_BURST)

            # Validate parameters
            if not 0 < price <= 1.0:
                raise ValueError(f"Price must be between 0 and 1, got {price}")

            if size <= 0:
                raise ValueError(f"Size must be positive, got {size}")

            side = side.upper()
            if side not in ['BUY', 'SELL']:
                raise ValueError(f"Side must be BUY or SELL, got {side}")

            order_type = order_type.upper()
            if order_type not in ['GTC', 'GTD', 'FOK', 'FAK']:
                raise ValueError(f"Invalid order type: {order_type}")

            if order_type == 'GTD' and not expiration:
                raise ValueError("GTD orders require expiration timestamp")

            # Get market data
            logger.info(f"Fetching market data for {market_id}")
            market = await self.client.get_market(market_id)

            # Select the correct outcome token (YES/NO/...) instead of blindly using tokens[0].
            token_id, resolved_outcome = self._select_token(market, outcome)
            logger.info(f"Selected outcome '{resolved_outcome}' (token {token_id}) for {market_id}")

            # Get orderbook for validation
            orderbook = await self.client.get_orderbook(token_id)

            # Parse orderbook data
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            best_bid = float(bids[0]['price']) if bids else 0.0
            best_ask = float(asks[0]['price']) if asks else 1.0

            # Calculate liquidity
            bid_liquidity = sum(float(b['price']) * float(b['size']) for b in bids[:10])
            ask_liquidity = sum(float(a['price']) * float(a['size']) for a in asks[:10])

            market_data = MarketData(
                market_id=market_id,
                token_id=token_id,
                best_bid=best_bid,
                best_ask=best_ask,
                bid_liquidity=bid_liquidity,
                ask_liquidity=ask_liquidity,
                total_volume=float(market.get('volume', 0))
            )

            # Get current positions
            positions_data = await self.client.get_positions()
            positions = self._convert_positions(positions_data)

            # Convert size from USD to shares
            size_in_shares = size / price

            # Create order request for validation
            order_request = OrderRequest(
                token_id=token_id,
                price=price,
                size=size_in_shares,
                side=side,
                market_id=market_id
            )

            # Safety validation
            is_valid, error_msg = self.safety_limits.validate_order(
                order_request,
                positions,
                market_data
            )

            if not is_valid:
                raise ValueError(f"Safety check failed: {error_msg}")

            # REAL confirmation gate (human-in-the-loop). If confirmation is required and
            # the caller did not pass confirm=True, DO NOT place the order - return a
            # pending response so the client/user can explicitly approve.
            if self.safety_limits.should_require_confirmation(
                order_request,
                self.config.ENABLE_AUTONOMOUS_TRADING
            ) and not confirm:
                reason = (
                    "autonomous trading is disabled"
                    if not self.config.ENABLE_AUTONOMOUS_TRADING
                    else (
                        f"order size ${size:.2f} exceeds confirmation threshold "
                        f"${self.config.REQUIRE_CONFIRMATION_ABOVE_USD:.2f}"
                    )
                )
                logger.warning(f"Order NOT placed - confirmation required ({reason})")
                return {
                    "success": False,
                    "status": "confirmation_required",
                    "requires_confirmation": True,
                    "message": (
                        f"This order was NOT placed because {reason}. "
                        f"Review the details and call again with confirm=true to execute."
                    ),
                    "pending_order": {
                        "market_id": market_id,
                        "outcome": resolved_outcome,
                        "side": side,
                        "price": price,
                        "size_usd": size,
                        "size_shares": size_in_shares,
                        "order_type": order_type,
                    }
                }

            # Post order
            logger.info(
                f"Posting limit order: {side} {size_in_shares:.2f} shares @ {price} "
                f"({order_type})"
            )

            order_response = await self.client.post_order(
                token_id=token_id,
                price=price,
                size=size_in_shares,
                side=side,
                order_type=order_type,
                expiration=expiration
            )

            result = {
                "success": True,
                "order_id": order_response.get('orderID'),
                "status": order_response.get('status', 'submitted'),
                "details": {
                    "market_id": market_id,
                    "token_id": token_id,
                    "outcome": resolved_outcome,
                    "side": side,
                    "price": price,
                    "size_shares": size_in_shares,
                    "size_usd": size,
                    "order_type": order_type,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                },
                "order_response": order_response
            }

            logger.info(f"Order created successfully: {result['order_id']}")
            return result

        except Exception as e:
            logger.error(f"Failed to create limit order: {e}")
            return {
                "success": False,
                "error": str(e),
                "details": {
                    "market_id": market_id,
                    "side": side,
                    "price": price,
                    "size_usd": size
                }
            }

    async def create_market_order(
        self,
        market_id: str,
        side: str,
        size: float,
        outcome: Optional[str] = None,
        confirm: bool = False
    ) -> Dict[str, Any]:
        """
        Execute market order at best available price (FOK).

        Args:
            market_id: Market condition ID
            side: 'BUY' or 'SELL'
            size: Order size in USD
            outcome: Outcome to trade ('YES'/'NO' or exact label). Defaults to YES.
            confirm: Must be True to execute when confirmation is required.

        Returns:
            Dict with execution details
        """
        try:
            # Get current best price
            market = await self.client.get_market(market_id)

            # Select the correct outcome token (not blindly tokens[0]).
            token_id, resolved_outcome = self._select_token(market, outcome)

            # Get best price from orderbook
            orderbook = await self.client.get_orderbook(token_id)

            side_upper = side.upper()
            if side_upper == 'BUY':
                # Buy at best ask
                asks = orderbook.get('asks', [])
                if not asks:
                    raise ValueError("No asks available in orderbook")
                best_price = float(asks[0]['price'])
            else:
                # Sell at best bid
                bids = orderbook.get('bids', [])
                if not bids:
                    raise ValueError("No bids available in orderbook")
                best_price = float(bids[0]['price'])

            logger.info(
                f"Executing market order: {side} ${size} @ market price {best_price}"
            )

            # Use FOK (Fill-Or-Kill) for market orders. Pass outcome + confirm through so
            # the real confirmation gate and outcome selection are honored.
            result = await self.create_limit_order(
                market_id=market_id,
                side=side,
                price=best_price,
                size=size,
                order_type='FOK',
                outcome=resolved_outcome,
                confirm=confirm
            )

            result['execution_type'] = 'market_order'
            result['executed_price'] = best_price

            return result

        except Exception as e:
            logger.error(f"Failed to create market order: {e}")
            return {
                "success": False,
                "error": str(e),
                "execution_type": "market_order",
                "details": {
                    "market_id": market_id,
                    "side": side,
                    "size_usd": size
                }
            }

    async def create_batch_orders(
        self,
        orders: List[Dict[str, Any]],
        confirm: bool = False
    ) -> Dict[str, Any]:
        """
        Submit multiple orders in batch.

        Args:
            orders: List of order objects with fields:
                - market_id (str)
                - side (str)
                - price (float)
                - size (float)
                - order_type (str, optional)
                - expiration (int, optional)
                - outcome (str, optional): 'YES'/'NO' or exact label
            confirm: Must be True to execute orders that require confirmation.

        Returns:
            Dict with results for each order
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.BATCH_OPS)

            results = []
            successful = 0
            failed = 0

            logger.info(f"Processing batch of {len(orders)} orders")

            # Process orders sequentially (could be parallelized with care)
            for idx, order in enumerate(orders):
                try:
                    result = await self.create_limit_order(
                        market_id=order['market_id'],
                        side=order['side'],
                        price=order['price'],
                        size=order['size'],
                        order_type=order.get('order_type', 'GTC'),
                        expiration=order.get('expiration'),
                        outcome=order.get('outcome'),
                        confirm=confirm
                    )

                    results.append({
                        "index": idx,
                        "success": result.get('success', False),
                        "order_id": result.get('order_id'),
                        "details": result.get('details', {})
                    })

                    if result.get('success'):
                        successful += 1
                    else:
                        failed += 1

                except Exception as e:
                    logger.error(f"Order {idx} failed: {e}")
                    results.append({
                        "index": idx,
                        "success": False,
                        "error": str(e),
                        "details": order
                    })
                    failed += 1

            return {
                "success": True,
                "total_orders": len(orders),
                "successful": successful,
                "failed": failed,
                "results": results
            }

        except Exception as e:
            logger.error(f"Batch order processing failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "total_orders": len(orders)
            }

    async def suggest_order_price(
        self,
        market_id: str,
        side: str,
        size: float,
        strategy: str = 'mid',
        outcome: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        AI suggests optimal price for order.

        Args:
            market_id: Market condition ID
            side: 'BUY' or 'SELL'
            size: Order size in USD
            strategy: 'aggressive'|'passive'|'mid'
            outcome: Outcome to price ('YES'/'NO' or exact label). Defaults to YES.

        Returns:
            Dict with suggested price and reasoning
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.MARKET_DATA)

            # Get market data
            market = await self.client.get_market(market_id)
            token_id, _ = self._select_token(market, outcome)
            orderbook = await self.client.get_orderbook(token_id)

            # Parse orderbook
            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            if not bids or not asks:
                raise ValueError("Insufficient orderbook depth")

            best_bid = float(bids[0]['price'])
            best_ask = float(asks[0]['price'])
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid

            side_upper = side.upper()
            strategy_lower = strategy.lower()

            # Calculate suggested price based on strategy
            if side_upper == 'BUY':
                if strategy_lower == 'aggressive':
                    # Buy at ask (immediate execution)
                    suggested_price = best_ask
                    reasoning = f"Aggressive buy at best ask {best_ask:.4f} for immediate execution"
                elif strategy_lower == 'passive':
                    # Place bid slightly above current best bid
                    suggested_price = best_bid + (spread * 0.1)
                    reasoning = f"Passive buy at {suggested_price:.4f}, above best bid {best_bid:.4f}"
                else:  # mid
                    # Place order at mid price
                    suggested_price = mid_price
                    reasoning = f"Mid-price buy at {suggested_price:.4f} (bid: {best_bid:.4f}, ask: {best_ask:.4f})"
            else:  # SELL
                if strategy_lower == 'aggressive':
                    # Sell at bid (immediate execution)
                    suggested_price = best_bid
                    reasoning = f"Aggressive sell at best bid {best_bid:.4f} for immediate execution"
                elif strategy_lower == 'passive':
                    # Place ask slightly below current best ask
                    suggested_price = best_ask - (spread * 0.1)
                    reasoning = f"Passive sell at {suggested_price:.4f}, below best ask {best_ask:.4f}"
                else:  # mid
                    # Place order at mid price
                    suggested_price = mid_price
                    reasoning = f"Mid-price sell at {suggested_price:.4f} (bid: {best_bid:.4f}, ask: {best_ask:.4f})"

            # Calculate estimated fill probability (simplified)
            if strategy_lower == 'aggressive':
                fill_probability = 0.95
            elif strategy_lower == 'passive':
                fill_probability = 0.4
            else:
                fill_probability = 0.7

            # Calculate expected cost/proceeds
            size_shares = size / suggested_price
            expected_value = size_shares * suggested_price

            return {
                "success": True,
                "suggested_price": suggested_price,
                "strategy": strategy,
                "reasoning": reasoning,
                "market_context": {
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid_price": mid_price,
                    "spread": spread,
                    "spread_pct": (spread / mid_price) * 100
                },
                "order_details": {
                    "side": side,
                    "size_usd": size,
                    "estimated_shares": size_shares,
                    "expected_value": expected_value,
                    "estimated_fill_probability": fill_probability
                }
            }

        except Exception as e:
            logger.error(f"Failed to suggest order price: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # ========== ORDER MANAGEMENT TOOLS ==========

    async def get_order_status(
        self,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Check status of a specific order.

        Args:
            order_id: Order ID to check

        Returns:
            Dict with order details and fill status
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)

            # Get all orders and find the specific one
            orders = await self.client.get_orders()

            for order in orders:
                if order.get('id') == order_id or order.get('orderID') == order_id:
                    filled_amount = float(order.get('sizeMatched', 0))
                    total_amount = float(order.get('originalSize', order.get('size', 0)))

                    fill_percentage = (filled_amount / total_amount * 100) if total_amount > 0 else 0

                    return {
                        "success": True,
                        "order_id": order_id,
                        "status": order.get('status', 'unknown'),
                        "fill_status": {
                            "filled": filled_amount,
                            "total": total_amount,
                            "remaining": total_amount - filled_amount,
                            "fill_percentage": fill_percentage
                        },
                        "details": order
                    }

            return {
                "success": False,
                "error": f"Order {order_id} not found",
                "order_id": order_id
            }

        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            return {
                "success": False,
                "error": str(e),
                "order_id": order_id
            }

    async def get_open_orders(
        self,
        market_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get all active/open orders.

        Args:
            market_id: Optional market filter

        Returns:
            Dict with list of open orders
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)

            orders = await self.client.get_orders(market=market_id)

            # Filter for open orders only
            open_orders = [
                order for order in orders
                if order.get('status') in ['open', 'live', 'pending']
            ]

            # Organize by market
            by_market = {}
            for order in open_orders:
                market = order.get('market', 'unknown')
                if market not in by_market:
                    by_market[market] = []
                by_market[market].append(order)

            return {
                "success": True,
                "total_open_orders": len(open_orders),
                "markets": len(by_market),
                "orders": open_orders,
                "by_market": by_market
            }

        except Exception as e:
            logger.error(f"Failed to get open orders: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_order_history(
        self,
        market_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get historical orders.

        Args:
            market_id: Optional market filter
            start_date: Start date (ISO format)
            end_date: End date (ISO format)
            limit: Maximum number of orders (default 100)

        Returns:
            Dict with order history
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.CLOB_GENERAL)

            orders = await self.client.get_orders(market=market_id)

            # Filter by date if provided
            if start_date or end_date:
                filtered_orders = []
                start_dt = datetime.fromisoformat(start_date) if start_date else None
                end_dt = datetime.fromisoformat(end_date) if end_date else None

                for order in orders:
                    order_time_str = order.get('timestamp') or order.get('created_at')
                    if order_time_str:
                        try:
                            order_time = datetime.fromisoformat(order_time_str.replace('Z', '+00:00'))
                            if start_dt and order_time < start_dt:
                                continue
                            if end_dt and order_time > end_dt:
                                continue
                            filtered_orders.append(order)
                        except:
                            filtered_orders.append(order)

                orders = filtered_orders

            # Apply limit
            orders = orders[:limit]

            # Calculate statistics
            total_volume = sum(
                float(o.get('size', 0)) * float(o.get('price', 0))
                for o in orders
            )

            filled_orders = [o for o in orders if o.get('status') == 'filled']
            cancelled_orders = [o for o in orders if o.get('status') == 'cancelled']

            return {
                "success": True,
                "total_orders": len(orders),
                "filled": len(filled_orders),
                "cancelled": len(cancelled_orders),
                "total_volume_usd": total_volume,
                "orders": orders
            }

        except Exception as e:
            logger.error(f"Failed to get order history: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def cancel_order(
        self,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Cancel a specific order.

        Args:
            order_id: Order ID to cancel

        Returns:
            Dict with cancellation confirmation
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.TRADING_BURST)

            response = await self.client.cancel_order(order_id)

            return {
                "success": True,
                "order_id": order_id,
                "cancelled": True,
                "response": response,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "order_id": order_id
            }

    async def cancel_market_orders(
        self,
        market_id: str,
        asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Cancel all orders in a specific market.

        Args:
            market_id: Market condition ID
            asset_id: Optional asset/token filter

        Returns:
            Dict with list of cancelled orders
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.TRADING_BURST)

            # Get open orders for market
            orders = await self.client.get_orders(market=market_id, asset_id=asset_id)

            open_orders = [
                o for o in orders
                if o.get('status') in ['open', 'live', 'pending']
            ]

            if not open_orders:
                return {
                    "success": True,
                    "message": "No open orders to cancel",
                    "market_id": market_id,
                    "cancelled_count": 0
                }

            # Cancel each order
            cancelled = []
            failed = []

            for order in open_orders:
                order_id = order.get('id') or order.get('orderID')
                try:
                    await self.client.cancel_order(order_id)
                    cancelled.append(order_id)
                except Exception as e:
                    logger.error(f"Failed to cancel order {order_id}: {e}")
                    failed.append({"order_id": order_id, "error": str(e)})

            return {
                "success": True,
                "market_id": market_id,
                "cancelled_count": len(cancelled),
                "failed_count": len(failed),
                "cancelled_orders": cancelled,
                "failed_orders": failed
            }

        except Exception as e:
            logger.error(f"Failed to cancel market orders: {e}")
            return {
                "success": False,
                "error": str(e),
                "market_id": market_id
            }

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """
        Cancel all open orders across all markets.

        Returns:
            Dict with count of cancelled orders
        """
        try:
            await self.rate_limiter.acquire(EndpointCategory.TRADING_BURST)

            response = await self.client.cancel_all_orders()

            # Count cancelled orders
            cancelled_count = 0
            if isinstance(response, dict):
                cancelled_count = len(response.get('cancelled', []))
            elif isinstance(response, list):
                cancelled_count = len(response)

            return {
                "success": True,
                "cancelled_count": cancelled_count,
                "response": response,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    # ========== SMART TRADING TOOLS ==========

    async def execute_smart_trade(
        self,
        market_id: str,
        intent: str,
        max_budget: float,
        outcome: Optional[str] = None,
        confirm: bool = False
    ) -> Dict[str, Any]:
        """
        AI-powered trade execution with natural language intent.

        Analyzes market and executes best strategy (limit, market, or split orders).

        Args:
            market_id: Market condition ID
            intent: Natural language intent (e.g., "Buy YES at good price up to $100")
            max_budget: Maximum budget in USD
            outcome: Outcome to trade ('YES'/'NO' or exact label). If None, inferred
                     from the intent text (defaults to YES).
            confirm: Must be True to execute orders that require confirmation.

        Returns:
            Dict with execution summary
        """
        try:
            logger.info(f"Smart trade execution: '{intent}' with budget ${max_budget}")

            # Parse intent to extract side and strategy
            intent_lower = intent.lower()

            # Determine side
            if 'buy' in intent_lower:
                side = 'BUY'
            elif 'sell' in intent_lower:
                side = 'SELL'
            else:
                raise ValueError("Cannot determine BUY or SELL from intent")

            # Determine outcome (explicit param wins; else infer from intent words).
            if not outcome:
                if re.search(r'\bno\b', intent_lower):
                    outcome = 'NO'
                elif re.search(r'\byes\b', intent_lower):
                    outcome = 'YES'

            # Determine strategy
            if any(word in intent_lower for word in ['fast', 'quick', 'now', 'immediately']):
                strategy = 'aggressive'
            elif any(word in intent_lower for word in ['patient', 'slow', 'good price', 'wait']):
                strategy = 'passive'
            else:
                strategy = 'mid'

            # Get price suggestion (for the chosen outcome)
            price_suggestion = await self.suggest_order_price(
                market_id=market_id,
                side=side,
                size=max_budget,
                strategy=strategy,
                outcome=outcome
            )

            if not price_suggestion.get('success'):
                raise ValueError(f"Failed to get price suggestion: {price_suggestion.get('error')}")

            suggested_price = price_suggestion['suggested_price']
            fill_probability = price_suggestion['order_details']['estimated_fill_probability']

            # Decide execution strategy
            execution_plan = []

            if fill_probability > 0.8 or strategy == 'aggressive':
                # Single aggressive order
                execution_plan.append({
                    "type": "market_order" if strategy == 'aggressive' else "limit_order",
                    "price": suggested_price,
                    "size": max_budget,
                    "reasoning": "High fill probability, executing as single order"
                })
            else:
                # Split into multiple orders for better execution
                split_count = 2
                size_per_order = max_budget / split_count

                for i in range(split_count):
                    # Adjust price slightly for each order
                    price_adjustment = (i * 0.01) if side == 'BUY' else -(i * 0.01)
                    adjusted_price = max(0.01, min(0.99, suggested_price + price_adjustment))

                    execution_plan.append({
                        "type": "limit_order",
                        "price": adjusted_price,
                        "size": size_per_order,
                        "reasoning": f"Split order {i+1}/{split_count} for better execution"
                    })

            # Execute orders
            executed_orders = []
            total_executed_value = 0.0

            for plan in execution_plan:
                if plan['type'] == 'market_order':
                    result = await self.create_market_order(
                        market_id=market_id,
                        side=side,
                        size=plan['size'],
                        outcome=outcome,
                        confirm=confirm
                    )
                else:
                    result = await self.create_limit_order(
                        market_id=market_id,
                        side=side,
                        price=plan['price'],
                        size=plan['size'],
                        order_type='GTC',
                        outcome=outcome,
                        confirm=confirm
                    )

                executed_orders.append(result)
                if result.get('success'):
                    total_executed_value += plan['size']

            successful_orders = [o for o in executed_orders if o.get('success')]

            return {
                "success": True,
                "intent": intent,
                "strategy": strategy,
                "execution_summary": {
                    "total_orders": len(execution_plan),
                    "successful": len(successful_orders),
                    "failed": len(executed_orders) - len(successful_orders),
                    "total_value": total_executed_value,
                    "budget_used": (total_executed_value / max_budget) * 100
                },
                "execution_plan": execution_plan,
                "executed_orders": executed_orders,
                "price_analysis": price_suggestion
            }

        except Exception as e:
            logger.error(f"Smart trade execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "intent": intent,
                "max_budget": max_budget
            }

    async def rebalance_position(
        self,
        market_id: str,
        target_size: Optional[float] = None,
        max_slippage: float = 0.02,
        outcome: Optional[str] = None,
        confirm: bool = False
    ) -> Dict[str, Any]:
        """
        Adjust position to target size (or close if target_size is None).

        Args:
            market_id: Market condition ID
            target_size: Target position size in USD (None to close)
            max_slippage: Maximum acceptable slippage (default 2%)
            outcome: Outcome to rebalance ('YES'/'NO' or exact label). Defaults to YES.
            confirm: Must be True to execute when confirmation is required.

        Returns:
            Dict with rebalance summary
        """
        try:
            logger.info(f"Rebalancing position in market {market_id} to target ${target_size}")

            # Get current position
            positions_data = await self.client.get_positions()

            current_size = 0.0
            current_position = None

            for pos in positions_data:
                if pos.get('market') == market_id or pos.get('condition_id') == market_id:
                    current_size += float(pos.get('size', 0)) * float(pos.get('price', 0))
                    current_position = pos

            if target_size is None:
                target_size = 0.0

            # Calculate required adjustment
            adjustment = target_size - current_size

            if abs(adjustment) < 1.0:  # Less than $1 difference
                return {
                    "success": True,
                    "message": "Position already at target",
                    "current_size": current_size,
                    "target_size": target_size,
                    "adjustment_needed": adjustment
                }

            # Determine side and size
            if adjustment > 0:
                # Need to buy more
                side = 'BUY'
                size = abs(adjustment)
            else:
                # Need to sell
                side = 'SELL'
                size = abs(adjustment)

            # Get market data for slippage check
            market = await self.client.get_market(market_id)
            token_id, _ = self._select_token(market, outcome)
            orderbook = await self.client.get_orderbook(token_id)

            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            best_bid = float(bids[0]['price']) if bids else 0.0
            best_ask = float(asks[0]['price']) if asks else 1.0
            mid_price = (best_bid + best_ask) / 2

            # Calculate expected execution price
            if side == 'BUY':
                expected_price = best_ask
                max_price = mid_price * (1 + max_slippage)
                if expected_price > max_price:
                    raise ValueError(
                        f"Slippage too high: expected {expected_price:.4f} > "
                        f"max {max_price:.4f}"
                    )
            else:
                expected_price = best_bid
                min_price = mid_price * (1 - max_slippage)
                if expected_price < min_price:
                    raise ValueError(
                        f"Slippage too high: expected {expected_price:.4f} < "
                        f"min {min_price:.4f}"
                    )

            # Execute rebalancing order
            logger.info(f"Rebalancing: {side} ${size} @ ~{expected_price:.4f}")

            result = await self.create_limit_order(
                market_id=market_id,
                side=side,
                price=expected_price,
                size=size,
                order_type='GTC',
                outcome=outcome,
                confirm=confirm
            )

            return {
                "success": result.get('success', False),
                "rebalance_summary": {
                    "current_size": current_size,
                    "target_size": target_size,
                    "adjustment": adjustment,
                    "side": side,
                    "size": size,
                    "execution_price": expected_price,
                    "mid_price": mid_price,
                    "slippage": abs(expected_price - mid_price) / mid_price
                },
                "order_result": result
            }

        except Exception as e:
            logger.error(f"Position rebalancing failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "market_id": market_id,
                "target_size": target_size
            }

    # ========== HELPER METHODS ==========

    def _convert_positions(
        self,
        positions_data: List[Dict[str, Any]]
    ) -> List[Position]:
        """Convert raw position data to Position objects."""
        positions = []

        for pos_data in positions_data:
            try:
                position = Position(
                    token_id=pos_data.get('asset_id', ''),
                    market_id=pos_data.get('market', ''),
                    size=float(pos_data.get('size', 0)),
                    avg_price=float(pos_data.get('avg_price', 0)),
                    current_price=float(pos_data.get('current_price', pos_data.get('avg_price', 0))),
                    unrealized_pnl=float(pos_data.get('unrealized_pnl', 0))
                )
                positions.append(position)
            except Exception as e:
                logger.warning(f"Failed to convert position: {e}")
                continue

        return positions


def get_tool_definitions() -> List[types.Tool]:
    """
    Get MCP tool definitions for all trading tools.

    Returns:
        List of Tool definitions
    """
    return [
        # Order Creation Tools
        types.Tool(
            name="create_limit_order",
            description=(
                "Create a limit order on Polymarket. "
                "Validates order against safety limits before execution. "
                "Supports GTC, GTD, FOK, and FAK order types."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market condition ID"
                    },
                    "side": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Order side"
                    },
                    "price": {
                        "type": "number",
                        "minimum": 0.01,
                        "maximum": 0.99,
                        "description": "Limit price (0.01-0.99)"
                    },
                    "size": {
                        "type": "number",
                        "minimum": 1,
                        "description": "Order size in USD"
                    },
                    "order_type": {
                        "type": "string",
                        "enum": ["GTC", "GTD", "FOK", "FAK"],
                        "default": "GTC",
                        "description": "Order type"
                    },
                    "expiration": {
                        "type": "integer",
                        "description": "Unix timestamp for GTD orders (optional)"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome to trade: 'YES'/'NO' or the exact outcome label. Defaults to YES."
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to execute when confirmation is required (large size or non-autonomous mode)."
                    }
                },
                "required": ["market_id", "side", "price", "size"]
            }
        ),
        types.Tool(
            name="create_market_order",
            description=(
                "Execute market order at best available price using FOK. "
                "Provides immediate execution at current market price."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market condition ID"
                    },
                    "side": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Order side"
                    },
                    "size": {
                        "type": "number",
                        "minimum": 1,
                        "description": "Order size in USD"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome to trade: 'YES'/'NO' or the exact outcome label. Defaults to YES."
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to execute when confirmation is required (large size or non-autonomous mode)."
                    }
                },
                "required": ["market_id", "side", "size"]
            }
        ),
        types.Tool(
            name="create_batch_orders",
            description=(
                "Submit multiple orders in batch. "
                "Each order is validated against safety limits. "
                "Returns results for each individual order."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "orders": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "market_id": {"type": "string"},
                                "side": {"type": "string", "enum": ["BUY", "SELL"]},
                                "price": {"type": "number"},
                                "size": {"type": "number"},
                                "order_type": {"type": "string"},
                                "expiration": {"type": "integer"},
                                "outcome": {"type": "string", "description": "YES/NO or exact label"}
                            },
                            "required": ["market_id", "side", "price", "size"]
                        },
                        "description": "List of orders to submit"
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to execute orders that require confirmation."
                    }
                },
                "required": ["orders"]
            }
        ),
        types.Tool(
            name="suggest_order_price",
            description=(
                "AI analyzes orderbook and suggests optimal price for order. "
                "Supports aggressive (immediate), passive (patient), and mid strategies."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market condition ID"
                    },
                    "side": {
                        "type": "string",
                        "enum": ["BUY", "SELL"],
                        "description": "Order side"
                    },
                    "size": {
                        "type": "number",
                        "description": "Order size in USD"
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["aggressive", "passive", "mid"],
                        "default": "mid",
                        "description": "Pricing strategy"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome to price: 'YES'/'NO' or exact label. Defaults to YES."
                    }
                },
                "required": ["market_id", "side", "size"]
            }
        ),

        # Order Management Tools
        types.Tool(
            name="get_order_status",
            description="Check status and fill details of a specific order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order ID to check"
                    }
                },
                "required": ["order_id"]
            }
        ),
        types.Tool(
            name="get_open_orders",
            description="Get all active/open orders, optionally filtered by market.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Optional market filter"
                    }
                }
            }
        ),
        types.Tool(
            name="get_order_history",
            description="Get historical orders with optional filters for market and date range.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Optional market filter"
                    },
                    "start_date": {
                        "type": "string",
                        "description": "Start date (ISO format)"
                    },
                    "end_date": {
                        "type": "string",
                        "description": "End date (ISO format)"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 100,
                        "description": "Maximum number of orders"
                    }
                }
            }
        ),
        types.Tool(
            name="cancel_order",
            description="Cancel a specific open order by ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "Order ID to cancel"
                    }
                },
                "required": ["order_id"]
            }
        ),
        types.Tool(
            name="cancel_market_orders",
            description="Cancel all open orders in a specific market.",
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market condition ID"
                    },
                    "asset_id": {
                        "type": "string",
                        "description": "Optional asset/token filter"
                    }
                },
                "required": ["market_id"]
            }
        ),
        types.Tool(
            name="cancel_all_orders",
            description="Cancel all open orders across all markets. Use with caution.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # Smart Trading Tools
        types.Tool(
            name="execute_smart_trade",
            description=(
                "AI-powered trade execution with natural language intent. "
                "Analyzes market and executes optimal strategy (limit, market, or split orders). "
                "Example: 'Buy YES at good price up to $100'"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market condition ID"
                    },
                    "intent": {
                        "type": "string",
                        "description": "Natural language trading intent"
                    },
                    "max_budget": {
                        "type": "number",
                        "description": "Maximum budget in USD"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome to trade: 'YES'/'NO' or exact label. If omitted, inferred from intent."
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to execute orders that require confirmation."
                    }
                },
                "required": ["market_id", "intent", "max_budget"]
            }
        ),
        types.Tool(
            name="rebalance_position",
            description=(
                "Adjust position to target size or close position entirely. "
                "Automatically calculates required trades and validates slippage."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "market_id": {
                        "type": "string",
                        "description": "Market condition ID"
                    },
                    "target_size": {
                        "type": "number",
                        "description": "Target position size in USD (null to close)"
                    },
                    "max_slippage": {
                        "type": "number",
                        "default": 0.02,
                        "description": "Maximum acceptable slippage (0.02 = 2%)"
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Outcome to rebalance: 'YES'/'NO' or exact label. Defaults to YES."
                    },
                    "confirm": {
                        "type": "boolean",
                        "default": False,
                        "description": "Must be true to execute when confirmation is required."
                    }
                },
                "required": ["market_id"]
            }
        ),
    ]
