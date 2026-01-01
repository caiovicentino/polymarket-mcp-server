"""
Offline suite for the ``create_order_signer`` factory (auth/signer.py).

Contract anchor (T-0173): ``create_order_signer(private_key: str,
chain_id: int = 137) -> OrderSigner`` (src/polymarket_mcp/auth/signer.py:255-266,
exported by ``polymarket_mcp.auth.__all__``) had ZERO in-repo callers and ZERO
tests; line :266 (the factory return) was the module's single coverage miss
(baseline: ``57 1 4 0 98.36% 266``). These two tests close the residual.

Divergences contract x code (L-0020/L-0025):
- The T-0173 contract names the ``return is_valid`` site (signer.py:248)
  "verify_message"; the actual enclosing function is ``verify_signature``
  (signer.py:214). That site is fixed by the same slice (mypy cast) but is
  exercised by tests/test_order_signer.py, NOT here — this suite covers the
  factory only.
- The contract cites the "hex WITHOUT 0x prefix" comment as signer.py:79-80;
  the comment actually lives at signer.py:86-88 ("Return signature as hex
  WITHOUT 0x prefix"). Content anchor matches; line drift recorded.

Hermeticity:
- Zero network: ``OrderSigner.__init__`` -> ``Account.from_key`` is local
  (eth_account pure computation); the factory (signer.py:266) is a pure
  constructor wrapper. No httpx/client/subprocess import in this file
  (grep-verifiable).
- Keys are SYNTHETIC hex strings ("aa"*32 / "bb"*32) — never real secrets
  (R8 hygiene: no credential logs pinned, nothing external imported).
- No integration/slow/real_api/performance markers — runs in the release gate.

Contrast pin (R3 comment signer.py:86-88): signatures returned by sign_* are
hex WITHOUT the 0x prefix (callers add it when the API requires it), while the
constructor normalizes the private key WITH-or-WITHOUT 0x — test 2 pins the
address identity across both forms.
"""
from polymarket_mcp.auth import create_order_signer
from polymarket_mcp.auth.signer import OrderSigner

KEY_A = "aa" * 32
KEY_A_0X = "0x" + KEY_A
KEY_B = "bb" * 32


def test_create_order_signer_default_chain_and_wrapper_identity():
    factory_signer = create_order_signer(KEY_A)
    direct_signer = OrderSigner(KEY_A)

    assert isinstance(factory_signer, OrderSigner)
    assert factory_signer.chain_id == 137
    # Factory is a pure wrapper: same normalization as the direct constructor,
    # therefore the same derived address.
    assert factory_signer.address == direct_signer.address


def test_create_order_signer_accepts_0x_prefix_and_custom_chain_id():
    with_prefix = create_order_signer(KEY_A_0X)
    without_prefix = create_order_signer(KEY_A)

    # Constructor normalizes with-or-without 0x prefix (signer.py:54-56) —
    # the docstring of the factory pins this; same key, same address.
    assert with_prefix.address == without_prefix.address

    assert create_order_signer(KEY_B, chain_id=80002).chain_id == 80002
