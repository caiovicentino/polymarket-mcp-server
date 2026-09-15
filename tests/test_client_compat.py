"""
Offline regression suite for PolymarketClient against py-clob-client 0.34.6 (T-0035).

Proves the four money-path wrappers without network:
- post_order: builds OrderArgs WITHOUT order_type (removed in 0.34 —
  TypeError: unexpected keyword argument), signs via create_order and
  submits the signed order via post_order (create_order alone never posts),
  maps the order type through OrderType (str-subclass: OrderType.GTC ==
  "GTC") and rejects unknown types, requires L2 credentials.
- get_orders: passes a single OpenOrderParams positionally (ClobClient
  signature is get_orders(params, next_cursor); kwargs market=/asset_id=
  raise TypeError).
- get_positions: served by the public Data API (ClobClient has no
  get_positions) — endpoint/params pinned against the live pattern in
  tools/portfolio.py.
- get_balance: ClobClient.get_balance does not exist; get_balance_allowance
  does, returning raw USDC units (6 decimals on Polygon) that the wrapper
  normalizes into USD.

The underlying ClobClient is replaced by an in-test stub that records calls
and returns synthetic values. py_clob_client modules are never patched; no
network, no sleeps. Divergences from the contract spec follow the observed
behavior (lessons L-0020/L-0025).
"""
import httpx
import pytest
from py_clob_client.clob_types import AssetType, OpenOrderParams

import polymarket_mcp.auth.client as client_module
from polymarket_mcp.auth.client import PolymarketClient

KEY = "0" * 63 + "1"
ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
POSITIONS = [
    {"market": "0xm1", "asset_id": "111", "size": "10.0", "average_price": "0.5"},
    {"market": "0xm2", "asset_id": "222", "size": "3.5", "average_price": "0.25"},
]
POST_RESPONSE = {"success": True, "orderID": "0xdeadbeef", "status": "matched"}


class _SignedOrderStub:
    """Marker object standing in for a SignedOrder returned by create_order."""

    def __init__(self, order_args):
        self.order_args = order_args


class _StubClob:
    """Offline stand-in for the underlying ClobClient.

    Records every call and returns synthetic values; never touches the
    network. Signatures mirror the real ClobClient surface used by the
    wrapper (create_order/post_order/get_orders/get_balance_allowance).
    """

    def __init__(self):
        self.create_order_calls = []
        self.signed_returned = []
        self.post_order_calls = []
        self.get_orders_calls = []
        self.get_balance_allowance_calls = []
        self.post_response = POST_RESPONSE
        self.orders_response = []
        self.balance_response = {}

    def create_order(self, order_args, options=None):
        self.create_order_calls.append(order_args)
        signed = _SignedOrderStub(order_args)
        self.signed_returned.append(signed)
        return signed

    def post_order(self, order, orderType=None, post_only=False):
        self.post_order_calls.append((order, orderType))
        return self.post_response

    def get_orders(self, params, next_cursor="MA=="):
        self.get_orders_calls.append(params)
        return self.orders_response

    def get_balance_allowance(self, params):
        self.get_balance_allowance_calls.append(params)
        return self.balance_response


def _make_client(api_key=None, api_secret=None, passphrase=None):
    """Build PolymarketClient (offline-safe) and swap its client for the stub."""
    pmc = PolymarketClient(
        private_key=KEY,
        address=ADDRESS,
        api_key=api_key,
        api_secret=api_secret,
        passphrase=passphrase,
    )
    stub = _StubClob()
    pmc.client = stub
    return pmc, stub


@pytest.fixture()
def pmc():
    """PolymarketClient with L2 credentials plus its stubbed underlying client."""
    return _make_client(api_key="k", api_secret="s", passphrase="p")


async def test_post_order_builds_order_args_without_order_type(pmc):
    pmc_, stub = pmc
    await pmc_.post_order(
        token_id="tok1", price=0.5, size=2.0, side="buy", expiration=None
    )
    order_args = stub.create_order_calls[0]
    assert order_args.token_id == "tok1"
    assert order_args.price == 0.5
    assert order_args.size == 2.0
    assert order_args.side == "BUY"
    # OrderArgs has no order_type field in py-clob-client 0.34.
    assert not hasattr(order_args, "order_type")
    assert order_args.expiration == 0

    await pmc_.post_order(
        token_id="tok2", price=0.6, size=1.0, side="SELL", expiration=123
    )
    order_args2 = stub.create_order_calls[1]
    assert order_args2.expiration == 123
    assert isinstance(order_args2.expiration, int)


async def test_post_order_passes_signed_order_to_client_post(pmc):
    pmc_, stub = pmc
    result = await pmc_.post_order(token_id="tok1", price=0.5, size=1.0, side="buy")

    assert len(stub.post_order_calls) == 1
    order, order_type = stub.post_order_calls[0]
    # The signed object (create_order's return value) is what gets posted,
    # not a dict and not a fresh object.
    assert order is stub.signed_returned[0]
    assert isinstance(order, _SignedOrderStub)
    assert order_type == "GTC"

    # The wrapper returns the post response verbatim.
    assert result is stub.post_response
    assert result == {"success": True, "orderID": "0xdeadbeef", "status": "matched"}


async def test_post_order_maps_order_type_and_rejects_unknown(pmc):
    pmc_, stub = pmc
    for order_type in ("GTD", "FOK", "FAK", "gtc"):
        await pmc_.post_order(
            token_id="tok1", price=0.5, size=1.0, side="buy", order_type=order_type
        )
    mapped = [mapped_type for _, mapped_type in stub.post_order_calls]
    assert mapped == ["GTD", "FOK", "FAK", "GTC"]

    with pytest.raises(ValueError, match="MARKET"):
        await pmc_.post_order(
            token_id="tok1", price=0.5, size=1.0, side="buy", order_type="MARKET"
        )
    # The rejected call never reached create_order/post_order.
    assert len(stub.create_order_calls) == 4
    assert len(stub.post_order_calls) == 4


async def test_post_order_requires_l2_credentials():
    pmc_, stub = _make_client()
    with pytest.raises(RuntimeError, match="create_api_credentials"):
        await pmc_.post_order(token_id="tok1", price=0.5, size=1.0, side="buy")
    assert stub.create_order_calls == []
    assert stub.post_order_calls == []


async def test_get_orders_builds_open_order_params(pmc):
    pmc_, stub = pmc
    stub.orders_response = ["o1", "o2"]

    result = await pmc_.get_orders(market="0xabc", asset_id="123")
    params = stub.get_orders_calls[0]
    assert isinstance(params, OpenOrderParams)
    assert params.market == "0xabc"
    assert params.asset_id == "123"
    assert result is stub.orders_response
    assert result == ["o1", "o2"]

    await pmc_.get_orders()
    params2 = stub.get_orders_calls[1]
    assert params2.market is None
    assert params2.asset_id is None

    await pmc_.get_orders(market=None)
    params3 = stub.get_orders_calls[2]
    assert params3.market is None
    assert params3.asset_id is None


async def test_get_positions_uses_data_api_endpoint(monkeypatch):
    pmc_, _stub = _make_client(api_key="k", api_secret="s", passphrase="p")
    captured = {"calls": 0}

    def handler(request):
        captured["calls"] += 1
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=POSITIONS)

    real_async_client = client_module.httpx.AsyncClient

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)

    positions = await pmc_.get_positions()

    assert captured["url"].split("?")[0] == "https://data-api.polymarket.com/positions"
    assert captured["params"]["user"] == ADDRESS.lower()
    assert captured["calls"] == 1
    assert positions == POSITIONS

    # Sibling case: without L2 credentials the wrapper fails closed before
    # any HTTP request is made.
    no_creds, _no_creds_stub = _make_client()
    with pytest.raises(RuntimeError, match="L2 API credentials required"):
        await no_creds.get_positions()
    assert captured["calls"] == 1


async def test_get_balance_uses_get_balance_allowance_and_normalizes(pmc):
    pmc_, stub = pmc
    stub.balance_response = {
        "balance": "5000000",
        "allowances": {"erc20": "1", "erc1155": "1"},
    }
    result = await pmc_.get_balance()
    params = stub.get_balance_allowance_calls[0]
    assert params.asset_type == AssetType.COLLATERAL
    # Raw USDC units (6 decimals) normalized into USD: 5000000 -> 5.0.
    assert result["balance"] == 5.0
    assert result["allowances"] == {"erc20": "1", "erc1155": "1"}


async def test_get_balance_requires_l2_credentials():
    pmc_, stub = _make_client()
    with pytest.raises(RuntimeError, match="L2 API credentials required"):
        await pmc_.get_balance()
    assert stub.get_balance_allowance_calls == []
