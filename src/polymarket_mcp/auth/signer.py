"""
Order signing utilities for Polymarket CLOB.
Handles EIP-712 signatures and order hash generation.
"""
import logging
from typing import Any, Dict

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import keccak

logger = logging.getLogger(__name__)


class SignatureType:
    """Signature types supported by Polymarket"""
    EOA = 0  # Externally Owned Account
    POLY_PROXY = 1  # Polymarket Proxy
    GNOSIS_SAFE = 2  # Gnosis Safe Multisig


# EIP-712 domain for Polymarket CTF Exchange
EIP712_DOMAIN = {
    "name": "ClobAuthDomain",
    "version": "1",
    "chainId": 137,
}


class OrderSigner:
    """
    Handles signing of orders for Polymarket CLOB.

    Uses EIP-712 for typed data signing to ensure:
    - Orders are cryptographically signed
    - Signatures can be verified on-chain
    - Protection against replay attacks
    """

    def __init__(self, private_key: str, chain_id: int = 137):
        """
        Initialize order signer.

        Args:
            private_key: Private key (without 0x prefix)
            chain_id: Chain ID (137 for Polygon mainnet)
        """
        # Ensure private key has 0x prefix for eth_account
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key

        self.account = Account.from_key(private_key)
        self.chain_id = chain_id
        self.address = self.account.address

        logger.info(f"OrderSigner initialized for address: {self.address}")

    def sign_order(
        self,
        order: Dict[str, Any],
        signature_type: int = SignatureType.EOA
    ) -> str:
        """
        Sign an order using EIP-712.

        Args:
            order: Order dictionary with required fields
            signature_type: Type of signature (default: EOA)

        Returns:
            Signature as hex string
        """
        # Build EIP-712 typed data structure
        typed_data = self._build_typed_data(order)

        # Encode and sign
        encoded_data = encode_typed_data(typed_data)
        signed_message = self.account.sign_message(encoded_data)

        # Return signature as hex (with 0x prefix)
        signature = signed_message.signature.hex()

        logger.debug(f"Signed order: {self._get_order_hash(order)}")
        return signature

    def sign_api_key_request(self, nonce: int) -> str:
        """
        Sign API key creation request.

        Args:
            nonce: Nonce from server

        Returns:
            Signature as hex string
        """
        message = f"This message attests that I control the given wallet\n{nonce}"

        # Sign the message
        signed_message = self.account.sign_message(
            text=message
        )

        return signed_message.signature.hex()

    def sign_cancel_order(
        self,
        order_id: str,
        asset_id: str
    ) -> str:
        """
        Sign order cancellation request.

        Args:
            order_id: ID of order to cancel
            asset_id: Asset ID of the order

        Returns:
            Signature as hex string
        """
        cancel_data = {
            "orderId": order_id,
            "assetId": asset_id
        }

        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "CancelOrder": [
                    {"name": "orderId", "type": "string"},
                    {"name": "assetId", "type": "string"},
                ]
            },
            "primaryType": "CancelOrder",
            "domain": {
                **EIP712_DOMAIN,
                "chainId": self.chain_id
            },
            "message": cancel_data
        }

        encoded_data = encode_typed_data(typed_data)
        signed_message = self.account.sign_message(encoded_data)

        return signed_message.signature.hex()

    def _build_typed_data(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build EIP-712 typed data structure for order.

        Args:
            order: Order dictionary

        Returns:
            EIP-712 typed data structure
        """
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "Order": [
                    {"name": "salt", "type": "uint256"},
                    {"name": "maker", "type": "address"},
                    {"name": "signer", "type": "address"},
                    {"name": "taker", "type": "address"},
                    {"name": "tokenId", "type": "uint256"},
                    {"name": "makerAmount", "type": "uint256"},
                    {"name": "takerAmount", "type": "uint256"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "feeRateBps", "type": "uint256"},
                    {"name": "side", "type": "uint8"},
                    {"name": "signatureType", "type": "uint8"},
                ]
            },
            "primaryType": "Order",
            "domain": {
                **EIP712_DOMAIN,
                "chainId": self.chain_id
            },
            "message": order
        }

    def _get_order_hash(self, order: Dict[str, Any]) -> str:
        """
        Calculate order hash for tracking.

        Args:
            order: Order dictionary

        Returns:
            Order hash as hex string
        """
        typed_data = self._build_typed_data(order)
        encoded_data = encode_typed_data(typed_data)

        # Hash the encoded data
        order_hash = keccak(encoded_data.body)
        return order_hash.hex()

    def verify_signature(
        self,
        order: Dict[str, Any],
        signature: str
    ) -> bool:
        """
        Verify an order signature.

        Args:
            order: Order dictionary
            signature: Signature to verify

        Returns:
            True if signature is valid
        """
        try:
            typed_data = self._build_typed_data(order)
            encoded_data = encode_typed_data(typed_data)

            # Recover signer address from signature
            recovered_address = Account.recover_message(
                encoded_data,
                signature=signature
            )

            # Check if recovered address matches signer
            is_valid = recovered_address.lower() == self.address.lower()

            if not is_valid:
                logger.warning(
                    f"Signature verification failed. "
                    f"Expected: {self.address}, Got: {recovered_address}"
                )

            return is_valid

        except Exception as e:
            logger.error(f"Error verifying signature: {e}")
            return False


def create_order_signer(private_key: str, chain_id: int = 137) -> OrderSigner:
    """
    Create OrderSigner instance.

    Args:
        private_key: Private key (with or without 0x prefix)
        chain_id: Chain ID (default: 137 for Polygon mainnet)

    Returns:
        OrderSigner instance
    """
    return OrderSigner(private_key, chain_id)
