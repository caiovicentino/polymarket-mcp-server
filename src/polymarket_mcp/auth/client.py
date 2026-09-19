"""
Polymarket CLOB client with authentication.
Handles L1 (private key) and L2 (API key) authentication.
"""
import logging
from dataclasses import asdict
from typing import Any, Dict, List, Optional, cast

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    AssetType,
    BalanceAllowanceParams,
    OpenOrderParams,
    OrderArgs,
    OrderBookSummary,
    OrderType,
)

from ..utils.data_api_pagination import fetch_all_pages
from ..utils.rate_limiter import EndpointCategory, get_rate_limiter
from .signer import OrderSigner

logger = logging.getLogger(__name__)


class PolymarketClient:
    """
    Authenticated client for Polymarket CLOB API.

    Features:
    - L1 authentication with private key signing
    - L2 authentication with API key HMAC
    - Auto-creation of API credentials if not provided
    - Comprehensive market and trading operations
    """

    def __init__(
        self,
        private_key: str,
        address: str,
        chain_id: int = 137,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        passphrase: Optional[str] = None,
        host: str = "https://clob.polymarket.com",
    ):
        """
        Initialize Polymarket client.

        Args:
            private_key: Polygon wallet private key
            address: Polygon wallet address
            chain_id: Chain ID (137 for mainnet, 80002 for Amoy testnet)
            api_key: Optional L2 API key
            api_secret: Optional L2 API secret used to sign requests
            passphrase: Optional L2 API passphrase
            host: CLOB API host URL
        """
        self.private_key = private_key
        self.address = address.lower()
        self.chain_id = chain_id
        self.host = host

        # Initialize order signer
        self.signer = OrderSigner(private_key, chain_id)

        # L2 API credentials
        self.api_creds: Optional[ApiCreds] = None
        if api_key and (api_secret or passphrase):
            # secret and passphrase are distinct values issued by Polymarket.
            # Falling back to one for both keeps older configs working, but the
            # HMAC signature is only valid when the real secret is supplied.
            if not api_secret:
                logger.warning(
                    "POLYMARKET_API_SECRET not set; falling back to the passphrase. "
                    "L2 requests will fail if they are not the same value."
                )
            self.api_creds = ApiCreds(
                api_key=api_key,
                api_secret=api_secret or passphrase,
                api_passphrase=passphrase or api_secret
            )

        # Initialize CLOB client
        self.client: Optional[ClobClient] = None
        self._initialize_client()

        logger.info(
            f"PolymarketClient initialized for {self.address} "
            f"(chain_id: {chain_id}, L2 auth: {self.api_creds is not None})"
        )

    def _initialize_client(self) -> None:
        """Initialize the ClobClient with appropriate authentication"""
        try:
            # Build client arguments
            client_args = {
                "host": self.host,
                "chain_id": self.chain_id,
                "key": self.private_key,
            }

            # Add L2 credentials if available
            if self.api_creds:
                client_args["creds"] = self.api_creds

            # Create client
            self.client = ClobClient(**client_args)

            logger.info("ClobClient initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize ClobClient: {e}")
            raise

    def get_client(self) -> ClobClient:
        """
        Get the underlying ClobClient instance.

        Returns:
            ClobClient instance

        Raises:
            RuntimeError: If client not initialized
        """
        if not self.client:
            raise RuntimeError("ClobClient not initialized")
        return self.client

    async def create_api_credentials(self, nonce_timeout: int = 3600) -> ApiCreds:
        """
        Create L2 API credentials for this wallet.

        This is required for authenticated operations like posting orders.
        The credentials are created once and can be reused.

        Args:
            nonce_timeout: Nonce timeout in seconds (default: 1 hour)

        Returns:
            ApiCreds object with api_key, api_secret, api_passphrase

        Raises:
            Exception: If credential creation fails
        """
        try:
            logger.info("Creating API credentials...")

            # Use the client's built-in method to create credentials
            creds = self.get_client().create_api_key()

            # Store credentials
            self.api_creds = ApiCreds(
                api_key=creds.api_key,
                api_secret=creds.api_secret,
                api_passphrase=creds.api_passphrase
            )

            # Reinitialize client with new credentials
            self._initialize_client()

            logger.info(f"API credentials created: {creds.api_key[:8]}...")
            return self.api_creds

        except Exception as e:
            logger.error(f"Failed to create API credentials: {e}")
            raise

    async def get_markets(
        self,
        next_cursor: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Fetch markets from Polymarket.

        Args:
            next_cursor: Pagination cursor
            limit: Number of markets to fetch (max 100)

        Returns:
            Dictionary with markets data
        """
        try:
            # Use simplified markets endpoint
            markets = self.get_client().get_markets(next_cursor=next_cursor)
            return cast(Dict[str, Any], markets)

        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            raise

    async def get_market(self, condition_id: str) -> Dict[str, Any]:
        """
        Fetch single market by condition ID.

        Args:
            condition_id: Market condition ID

        Returns:
            Market data dictionary
        """
        try:
            market = self.get_client().get_market(condition_id)
            return cast(Dict[str, Any], market)

        except Exception as e:
            logger.error(f"Failed to fetch market {condition_id}: {e}")
            raise

    async def get_orderbook(
        self,
        token_id: str
    ) -> Dict[str, Any]:
        """
        Fetch order book for a token.

        Args:
            token_id: Token ID to fetch orderbook for

        Returns:
            Order book with bids and asks
        """
        try:
            orderbook = self.get_client().get_order_book(token_id)
            if isinstance(orderbook, OrderBookSummary):
                # py-clob-client 0.34.6 devolve OrderBookSummary dataclass (não-dict).
                # Converter para dict (o contrato de consumo do repo) e normalizar a
                # ordenação worst-first do CLOB (/book: bids ascendente, asks descendente)
                # para best-first (bids desc, asks asc) — o padrão que TODOS os consumidores
                # assumem (trading.py, portfolio.py). Dicts passam intocados por identidade.
                orderbook = asdict(orderbook)
                orderbook["bids"] = sorted(
                    orderbook.get("bids") or [],
                    key=lambda entry: float(entry["price"]),
                    reverse=True,
                )
                orderbook["asks"] = sorted(
                    orderbook.get("asks") or [],
                    key=lambda entry: float(entry["price"]),
                )
            return cast(Dict[str, Any], orderbook)

        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {token_id}: {e}")
            raise

    async def get_price(
        self,
        token_id: str,
        side: str
    ) -> float:
        """
        Get current price for a token.

        Args:
            token_id: Token ID
            side: BUY or SELL

        Returns:
            Price as float
        """
        try:
            price_data = self.get_client().get_price(token_id, side.upper())
            return float(price_data.get("price", 0))

        except Exception as e:
            logger.error(f"Failed to fetch price for {token_id}: {e}")
            raise

    async def post_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str,
        order_type: str = "GTC",
        expiration: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Post a limit order.

        Args:
            token_id: Token ID to trade
            price: Limit price (0-1 for probabilities)
            size: Order size in shares
            side: BUY or SELL
            order_type: Order type (GTC, FOK, GTD)
            expiration: Order expiration timestamp (required for GTD)

        Returns:
            Order response dictionary

        Raises:
            RuntimeError: If L2 credentials not available
        """
        if not self.api_creds:
            raise RuntimeError(
                "L2 API credentials required for posting orders. "
                "Call create_api_credentials() first."
            )

        try:
            order_type = (order_type or "GTC").upper()
            if not hasattr(OrderType, order_type):
                raise ValueError(f"Invalid order type: {order_type}")

            # Build order args. OrderArgs does NOT carry order_type
            # (py-clob-client 0.34); the order type is passed to post_order.
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side.upper(),
            )

            if expiration:
                order_args.expiration = int(expiration)

            # create_order only signs the order; post_order submits it.
            signed = self.get_client().create_order(order_args)
            response = self.get_client().post_order(
                signed, orderType=getattr(OrderType, order_type)
            )

            logger.info(
                f"Order posted: {side} {size} @ {price} "
                f"(token: {token_id}, order_id: {response.get('orderID')})"
            )

            return cast(Dict[str, Any], response)

        except Exception as e:
            logger.error(f"Failed to post order: {e}")
            raise

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel an open order.

        Args:
            order_id: ID of order to cancel

        Returns:
            Cancellation response

        Raises:
            RuntimeError: If L2 credentials not available
        """
        if not self.api_creds:
            raise RuntimeError("L2 API credentials required for canceling orders")

        try:
            response = self.get_client().cancel(order_id)

            logger.info(f"Order cancelled: {order_id}")
            return cast(Dict[str, Any], response)

        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            raise

    async def cancel_all_orders(self) -> Dict[str, Any]:
        """
        Cancel all open orders.

        Returns:
            Cancellation response

        Raises:
            RuntimeError: If L2 credentials not available
        """
        if not self.api_creds:
            raise RuntimeError("L2 API credentials required")

        try:
            response = self.get_client().cancel_all()

            logger.info("All orders cancelled")
            return cast(Dict[str, Any], response)

        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            raise

    async def get_orders(
        self,
        market: Optional[str] = None,
        asset_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get user's open orders.

        Args:
            market: Filter by market ID
            asset_id: Filter by asset ID

        Returns:
            List of open orders

        Raises:
            RuntimeError: If L2 credentials not available
        """
        if not self.api_creds:
            raise RuntimeError("L2 API credentials required")

        try:
            # ClobClient.get_orders expects a single OpenOrderParams object
            # (positional), not keyword arguments (py-clob-client 0.34).
            params = OpenOrderParams()
            if market is not None:
                params.market = market
            if asset_id is not None:
                params.asset_id = asset_id

            orders = self.get_client().get_orders(params)
            return cast(List[Dict[str, Any]], orders)

        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            raise

    async def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get user's positions.

        Positions are served by Polymarket's public Data API
        (https://data-api.polymarket.com/positions); the CLOB API does not
        expose them. This mirrors the pattern used by tools/portfolio.py.

        Returns:
            List of positions

        Raises:
            RuntimeError: If L2 credentials not available
        """
        if not self.api_creds:
            raise RuntimeError("L2 API credentials required")

        try:
            await get_rate_limiter().acquire(EndpointCategory.DATA_API)

            async with httpx.AsyncClient() as client:
                positions = await fetch_all_pages(
                    client,
                    "https://data-api.polymarket.com/positions",
                    {"user": self.address},
                )
                return cast(List[Dict[str, Any]], positions)

        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            raise

    async def get_balance(self) -> Dict[str, Any]:
        """
        Get user's USDC balance.

        Queries the CLOB /balance-allowance endpoint via
        get_balance_allowance() and normalizes the raw USDC units
        (6 decimals on Polygon) into USD.

        Returns:
            Dictionary with "balance" in USD (float, normalized from the
            6-decimal raw units reported by the CLOB) and "allowances".

        Raises:
            RuntimeError: If L2 credentials not available
        """
        if not self.api_creds:
            raise RuntimeError("L2 API credentials required")

        try:
            balance_data = self.get_client().get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            balance = float(balance_data.get("balance", 0)) / 1_000_000
            return {
                "balance": balance,
                "allowances": balance_data.get("allowances", {}),
            }

        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            raise

    def has_api_credentials(self) -> bool:
        """Check if L2 API credentials are available"""
        return self.api_creds is not None

    def get_address(self) -> str:
        """Get wallet address"""
        return self.address

    def get_chain_id(self) -> int:
        """Get chain ID"""
        return self.chain_id


def create_polymarket_client(
    private_key: str,
    address: str,
    chain_id: int = 137,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    passphrase: Optional[str] = None,
) -> PolymarketClient:
    """
    Create PolymarketClient instance.

    Args:
        private_key: Polygon wallet private key
        address: Polygon wallet address
        chain_id: Chain ID (default: 137)
        api_key: Optional L2 API key
        api_secret: Optional L2 API secret
        passphrase: Optional L2 API passphrase

    Returns:
        PolymarketClient instance
    """
    return PolymarketClient(
        private_key=private_key,
        address=address,
        chain_id=chain_id,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase
    )
