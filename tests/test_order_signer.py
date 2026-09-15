"""
Offline regression suite for OrderSigner (eth-account 0.14 API).

Proves the signing path end-to-end without network:
- EIP-712 typed-data signing uses the current API (encode_typed_data(full_message=...));
  the positional full-dict form raises ValueError ("Invalid domain key: `types`")
  and was never a valid API (T-0031).
- Personal-message signing uses encode_defunct; sign_message(text=...) was
  removed in eth-account 0.13+.
- Round-trips (sign -> verify/recover), determinism, and malformed-input
  fail-closed behavior are pinned per T-0031 contract.
"""
import pytest

from polymarket_mcp.auth.signer import OrderSigner

KEY_A = "0" * 63 + "1"
KEY_A_0X = "0x" + KEY_A
KEY_B = "0" * 63 + "2"
KEY_MAKER = "a" * 63 + "1"

ORDER = {
    "salt": 123456789012345678901234567890,
    "maker": OrderSigner(KEY_MAKER).address,
    "signer": OrderSigner(KEY_MAKER).address,
    "taker": "0x" + "b" * 40,
    "tokenId": 12345,
    "makerAmount": 100,
    "takerAmount": 200,
    "expiration": 1893456000,
    "nonce": 42,
    "feeRateBps": 100,
    "side": 0,
    "signatureType": 0,
}


@pytest.fixture()
def signer_a():
    return OrderSigner(KEY_A)


@pytest.fixture()
def signer_b():
    return OrderSigner(KEY_B)


def test_signer_initializes_with_valid_key(signer_a):
    assert signer_a.address.startswith("0x")
    assert len(signer_a.address) == 42


def test_signer_accepts_key_without_0x_prefix(signer_a):
    signer = OrderSigner(KEY_A_0X)
    assert signer.address == signer_a.address


def test_signer_rejects_zero_key():
    with pytest.raises(ValueError):
        OrderSigner("0" * 64)


def test_sign_order_verify_roundtrip(signer_a):
    sig = signer_a.sign_order(ORDER)
    assert signer_a.verify_signature(ORDER, sig) is True


def test_verify_signature_rejects_foreign_signer(signer_a, signer_b):
    sig = signer_b.sign_order(ORDER)
    assert signer_a.verify_signature(ORDER, sig) is False


def test_sign_order_is_deterministic(signer_a):
    assert signer_a.sign_order(ORDER) == signer_a.sign_order(ORDER)


def test_verify_signature_malformed_returns_false(signer_a):
    assert signer_a.verify_signature(ORDER, "zz") is False


def test_sign_api_key_request_is_deterministic(signer_a):
    from eth_account import Account
    from eth_account.messages import encode_defunct

    nonce = 42
    sig_a = signer_a.sign_api_key_request(nonce)
    assert sig_a == signer_a.sign_api_key_request(nonce)
    assert sig_a != signer_a.sign_api_key_request(nonce + 1)

    recovered = Account.recover_message(
        encode_defunct(text=f"This message attests that I control the given wallet\n{nonce}"),
        signature=sig_a,
    )
    assert recovered.lower() == signer_a.address.lower()


def test_sign_cancel_order_is_deterministic(signer_a):
    sig = signer_a.sign_cancel_order("order-1", "asset-1")
    assert sig == signer_a.sign_cancel_order("order-1", "asset-1")
    assert sig != signer_a.sign_cancel_order("order-2", "asset-1")
