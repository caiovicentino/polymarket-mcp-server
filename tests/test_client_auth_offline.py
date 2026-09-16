"""
Offline regression suite for the REMAINING uncovered regions of
polymarket_mcp.auth.client (T-0048).

Coverage @ emission (main ea008dc, later confirmed byte-identical on
8597b9a via sha 0058548d...): 56.22%/57.30% missing lines 73, 111-113,
125-127, 145-166, 183-190, 202-208, 223-229, 246-252, 333-344, 356-367,
388, 402-404, 435-437, 467-469, 473/477/481, 506. This suite adds ONE
file; existing tests (tests/test_client_compat.py et al.) are untouched
and their covered regions are NOT duplicated (L-0002/L-0008).

Covers the credential lifecycle (create_api_credentials: create_api_key
-> store -> re-initialize -> return; failures propagate), the documented
passphrase fallback when POLYMARKET_API_SECRET is absent
(client.py:68-81) plus its mirrored `or` arm, failed initialization
(log + re-raise, client.py:111-113), the get_client guard
(client.py:125-127), the market-read wrappers (get_markets/get_market/
get_orderbook/get_price), cancel_order/cancel_all_orders (L2 guards,
forwards, upstream errors), the get_orders guard (client.py:388) and its
except path, except paths of get_positions/get_balance, accessors and
the create_polymarket_client factory.

Behavior pinned as OBSERVED (lessons L-0020/L-0025/L-0115):
- get_markets accepts `limit` but does NOT forward it to ClobClient —
  only next_cursor reaches the stub (client.py:183-186). The pin is
  structural and discriminating: the stub signature has NO limit
  parameter, so a future fix that starts forwarding `limit` fails this
  suite loudly with TypeError instead of passing vacuously.
- create_api_credentials returns self.api_creds (a NEW ApiCreds built
  from the upstream response), not the upstream object itself.
- The wrapper passes next_cursor=None explicitly on the default call
  (it does NOT substitute the ClobClient default "MA==").

House pattern replicated from tests/test_client_compat.py (T-0035):
in-test _StubClob records every call and returns synthetic values;
fakes fail loud (P-0031). py_clob_client modules are never patched;
the ONLY monkeypatched symbol is the module-level client_module.ClobClient
(sanctioned seam per the T-0048 contract: the wrapper instantiates
`ClobClient(**client_args)` internally, so patching the module symbol
keeps everything offline AND lets tests assert the re-initialization
kwargs through a recording factory). No network, no sleeps: every CLOB
call goes through the stub, the Data API call through httpx.MockTransport.
"""
import logging

import httpx
import pytest
from py_clob_client.clob_types import ApiCreds

import polymarket_mcp.auth.client as client_module
from polymarket_mcp.auth.client import PolymarketClient, create_polymarket_client

KEY = "0" * 63 + "1"
ADDRESS = "0xAbCdEf0123456789AbCdEf0123456789AbCdEf01"
HOST = "https://clob.polymarket.com"
CREATED_CREDS = ApiCreds(
    api_key="0xcreated0000000000000000000000000000000",
    api_secret="created-secret",
    api_passphrase="created-passphrase",
)
MARKETS_RESPONSE = {"data": [], "next_cursor": "NEXT"}
MARKET_RESPONSE = {"condition_id": "0xcond", "question": "q?"}
ORDERBOOK_RESPONSE = {"bids": [], "asks": []}
CANCEL_RESPONSE = {"canceled": "0xo1", "success": True}
CANCEL_ALL_RESPONSE = {"canceled": "all", "success": True}
LOGGER_NAME = "polymarket_mcp.auth.client"


class _CredsEcho:
    """Upstream create_api_key response: plain string attributes."""

    def __init__(self):
        self.api_key = CREATED_CREDS.api_key
        self.api_secret = CREATED_CREDS.api_secret
        self.api_passphrase = CREATED_CREDS.api_passphrase


class _StubClob:
    """Offline stand-in for the underlying ClobClient.

    Records every call and returns synthetic values; never touches the
    network. Signatures mirror the real ClobClient surface used by the
    wrapper (client.py). NOTE: get_markets deliberately has NO limit
    parameter — it pins the observed behavior that the wrapper drops
    `limit` (see module docstring / L-0115).
    """

    def __init__(self):
        self.get_markets_calls = []
        self.get_markets_response = MARKETS_RESPONSE
        self.get_market_calls = []
        self.get_market_response = MARKET_RESPONSE
        self.get_order_book_calls = []
        self.orderbook_response = ORDERBOOK_RESPONSE
        self.get_price_calls = []
        self.price_response = {}
        self.cancel_calls = []
        self.cancel_response = CANCEL_RESPONSE
        self.cancel_all_calls = []
        self.cancel_all_response = CANCEL_ALL_RESPONSE
        self.get_orders_calls = []
        self.get_balance_allowance_calls = []
        self.create_api_key_calls = []
        self.api_key_response = _CredsEcho()

    def get_markets(self, next_cursor=None):
        self.get_markets_calls.append(next_cursor)
        return self.get_markets_response

    def get_market(self, condition_id):
        self.get_market_calls.append(condition_id)
        return self.get_market_response

    def get_order_book(self, token_id):
        self.get_order_book_calls.append(token_id)
        return self.orderbook_response

    def get_price(self, token_id, side):
        self.get_price_calls.append((token_id, side))
        return self.price_response

    def cancel(self, order_id):
        self.cancel_calls.append(order_id)
        return self.cancel_response

    def cancel_all(self):
        self.cancel_all_calls.append(True)
        return self.cancel_all_response

    def get_orders(self, params, next_cursor="MA=="):
        self.get_orders_calls.append(params)
        return []

    def get_balance_allowance(self, params):
        self.get_balance_allowance_calls.append(params)
        return {}

    def create_api_key(self):
        self.create_api_key_calls.append(True)
        return self.api_key_response


def _raise(boom):
    """Return a stub-method replacement that always raises `boom`."""

    def raiser(*args, **kwargs):
        raise boom

    return raiser


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


def _logging_capture(caplog):
    """Capture INFO+ from the client module logger (default caplog is WARNING+)."""
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)


@pytest.fixture()
def pmc():
    """PolymarketClient with L2 credentials plus its stubbed underlying client."""
    return _make_client(api_key="k", api_secret="s", passphrase="p")


# --- Credential lifecycle ---------------------------------------------------


def test_init_warns_and_falls_back_to_passphrase_without_secret(caplog):
    """api_key + passphrase without api_secret: warn and use the passphrase
    for BOTH api_secret and api_passphrase (client.py:72-81). The mirrored
    `or` arm (secret without passphrase) reuses the secret silently."""
    _logging_capture(caplog)

    warned = PolymarketClient(
        private_key=KEY, address=ADDRESS, api_key="k", passphrase="pass"
    )
    assert (
        "POLYMARKET_API_SECRET not set; falling back to the passphrase"
        in caplog.text
    )
    assert warned.api_creds.api_key == "k"
    assert warned.api_creds.api_secret == "pass"
    assert warned.api_creds.api_passphrase == "pass"

    caplog.clear()
    mirrored = PolymarketClient(
        private_key=KEY, address=ADDRESS, api_key="k", api_secret="sec"
    )
    assert "POLYMARKET_API_SECRET not set" not in caplog.text
    assert mirrored.api_creds.api_secret == "sec"
    assert mirrored.api_creds.api_passphrase == "sec"


def test_init_propagates_clob_client_failure(monkeypatch, caplog):
    """A failing ClobClient constructor is logged and re-raised; __init__
    never swallows it (client.py:111-113)."""
    _logging_capture(caplog)
    boom = RuntimeError("clob constructor exploded")

    def factory(**kwargs):
        raise boom

    monkeypatch.setattr(client_module, "ClobClient", factory)
    with pytest.raises(RuntimeError) as excinfo:
        PolymarketClient(private_key=KEY, address=ADDRESS)
    assert excinfo.value is boom
    assert "Failed to initialize ClobClient" in caplog.text


def test_get_client_raises_when_client_uninitialized(pmc):
    """get_client returns the SAME underlying object when initialized and
    raises RuntimeError when the client is falsy (client.py:125-127)."""
    pmc_, stub = pmc
    assert pmc_.get_client() is stub

    pmc_.client = None
    with pytest.raises(RuntimeError, match="ClobClient not initialized"):
        pmc_.get_client()


async def test_create_api_credentials_stores_creds_and_reinitializes(
    pmc, monkeypatch, caplog
):
    """create_api_credentials: upstream create_api_key -> creds stored as
    ApiCreds -> _initialize_client re-creates the client WITH the new
    credentials -> returns the stored creds (client.py:145-162)."""
    _logging_capture(caplog)
    pmc_, stub = pmc
    factory_calls = []
    marker = object()

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return marker

    monkeypatch.setattr(client_module, "ClobClient", factory)

    result = await pmc_.create_api_credentials()

    assert stub.create_api_key_calls == [True]
    assert isinstance(pmc_.api_creds, ApiCreds)
    assert pmc_.api_creds.api_key == CREATED_CREDS.api_key
    assert pmc_.api_creds.api_secret == "created-secret"
    assert pmc_.api_creds.api_passphrase == "created-passphrase"
    # The wrapper returns the NEW stored creds, not the upstream object.
    assert result is pmc_.api_creds
    assert result is not stub.api_key_response

    # Re-initialization happened exactly once, with the new credentials.
    assert len(factory_calls) == 1
    assert factory_calls[0]["host"] == HOST
    assert factory_calls[0]["chain_id"] == 137
    assert factory_calls[0]["key"] == KEY
    assert factory_calls[0]["creds"] is pmc_.api_creds
    assert pmc_.client is marker

    assert "API credentials created: 0xcreate..." in caplog.text


async def test_create_api_credentials_failure_propagates(monkeypatch, caplog):
    """A failing create_api_key is logged and re-raised; no credentials are
    stored and the client is NOT re-initialized (client.py:164-166)."""
    _logging_capture(caplog)
    pmc_, stub = _make_client()  # no L2 credentials yet
    boom = RuntimeError("credential creation failed upstream")

    def raiser():
        raise boom

    stub.create_api_key = raiser
    factory_calls = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return object()

    monkeypatch.setattr(client_module, "ClobClient", factory)

    with pytest.raises(RuntimeError) as excinfo:
        await pmc_.create_api_credentials()
    assert excinfo.value is boom
    assert pmc_.api_creds is None
    assert factory_calls == []
    assert "Failed to create API credentials" in caplog.text


# --- Market-read wrappers ---------------------------------------------------


async def test_get_markets_forwards_cursor_and_pins_limit_ignored(pmc):
    """get_markets forwards ONLY next_cursor; `limit` is accepted by the
    wrapper and dropped before reaching the CLOB (client.py:183-186). The
    stub has no limit parameter, so forwarding it would raise TypeError."""
    pmc_, stub = pmc
    result = await pmc_.get_markets(next_cursor="CURSOR", limit=50)
    assert stub.get_markets_calls == ["CURSOR"]
    assert result is stub.get_markets_response

    await pmc_.get_markets()
    assert stub.get_markets_calls == ["CURSOR", None]


async def test_get_market_forwards_condition_id(pmc):
    pmc_, stub = pmc
    result = await pmc_.get_market("0xcond1")
    assert stub.get_market_calls == ["0xcond1"]
    assert result is stub.get_market_response


async def test_get_orderbook_forwards_token_id(pmc):
    """get_orderbook forwards the token_id to ClobClient.get_order_book
    (plural wrapper name, singular upstream method — client.py:224)."""
    pmc_, stub = pmc
    result = await pmc_.get_orderbook("tok1")
    assert stub.get_order_book_calls == ["tok1"]
    assert result is stub.orderbook_response


async def test_get_price_uppercases_side_and_floats_price(pmc):
    """get_price upper-cases the side, coerces the upstream price into
    float, and defaults a missing price to 0 (client.py:247-248)."""
    pmc_, stub = pmc
    stub.price_response = {"price": "0.5432"}
    result = await pmc_.get_price("tok1", "buy")
    assert stub.get_price_calls == [("tok1", "BUY")]
    assert result == 0.5432
    assert isinstance(result, float)

    stub.price_response = {"price": 0.25}
    assert await pmc_.get_price("tok1", "sell") == 0.25
    stub.price_response = {}
    assert await pmc_.get_price("tok1", "buy") == 0.0
    assert stub.get_price_calls[1] == ("tok1", "SELL")
    assert stub.get_price_calls[2] == ("tok1", "BUY")


async def test_market_read_methods_propagate_upstream_errors(pmc, caplog):
    """Each market-read wrapper logs and re-raises the ORIGINAL upstream
    exception (client.py except paths: 188-190/206-208/227-229/250-252)."""
    _logging_capture(caplog)
    pmc_, stub = pmc
    boom = RuntimeError("clob upstream is down")
    probes = (
        ("get_markets", lambda: pmc_.get_markets(next_cursor="c")),
        ("get_market", lambda: pmc_.get_market("0xcond")),
        ("get_order_book", lambda: pmc_.get_orderbook("tok1")),
        ("get_price", lambda: pmc_.get_price("tok1", "buy")),
    )
    for attr, call in probes:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(stub, attr, _raise(boom))
            with pytest.raises(RuntimeError) as excinfo:
                await call()
        assert excinfo.value is boom
    assert "Failed to fetch markets" in caplog.text
    assert "Failed to fetch market 0xcond" in caplog.text
    assert "Failed to fetch orderbook for tok1" in caplog.text
    assert "Failed to fetch price for tok1" in caplog.text


# --- Cancels and get_orders -------------------------------------------------


async def test_cancel_order_forwards_order_id(pmc):
    pmc_, stub = pmc
    result = await pmc_.cancel_order("0xo1")
    assert stub.cancel_calls == ["0xo1"]
    assert result is stub.cancel_response


async def test_cancel_all_orders_forwards_to_clob(pmc):
    pmc_, stub = pmc
    result = await pmc_.cancel_all_orders()
    assert stub.cancel_all_calls == [True]
    assert result is stub.cancel_all_response


async def test_cancel_and_get_orders_fail_closed_without_l2_credentials():
    """Without L2 credentials, cancel_order/cancel_all_orders/get_orders
    raise BEFORE touching the CLOB, with the two distinct observed guard
    messages (client.py:333-334/356-357/387-388)."""
    pmc_, stub = _make_client()

    with pytest.raises(RuntimeError, match="required for canceling orders"):
        await pmc_.cancel_order("0xo1")
    with pytest.raises(RuntimeError, match="L2 API credentials required"):
        await pmc_.cancel_all_orders()
    with pytest.raises(RuntimeError, match="L2 API credentials required"):
        await pmc_.get_orders(market="0xm")

    # Fail closed: the underlying client was never called.
    assert stub.cancel_calls == []
    assert stub.cancel_all_calls == []
    assert stub.get_orders_calls == []


async def test_get_orders_propagates_upstream_error(pmc, caplog):
    """The get_orders except path logs and re-raises the original error
    (client.py:402-404; happy path covered by test_client_compat)."""
    _logging_capture(caplog)
    pmc_, stub = pmc
    boom = RuntimeError("clob orders down")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stub, "get_orders", _raise(boom))
        with pytest.raises(RuntimeError) as excinfo:
            await pmc_.get_orders(market="0xm")
    assert excinfo.value is boom
    assert "Failed to fetch orders" in caplog.text


async def test_cancel_order_propagates_upstream_error(pmc, caplog):
    _logging_capture(caplog)
    pmc_, stub = pmc
    boom = RuntimeError("clob cancel down")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stub, "cancel", _raise(boom))
        with pytest.raises(RuntimeError) as excinfo:
            await pmc_.cancel_order("0xo1")
    assert excinfo.value is boom
    assert "Failed to cancel order 0xo1" in caplog.text


async def test_cancel_all_orders_propagates_upstream_error(pmc, caplog):
    _logging_capture(caplog)
    pmc_, stub = pmc
    boom = RuntimeError("clob cancel-all down")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stub, "cancel_all", _raise(boom))
        with pytest.raises(RuntimeError) as excinfo:
            await pmc_.cancel_all_orders()
    assert excinfo.value is boom
    assert "Failed to cancel all orders" in caplog.text


# --- Data API / balance except paths ----------------------------------------


async def test_data_api_and_balance_propagate_upstream_errors(monkeypatch, caplog):
    """get_positions: a Data API 500 surfaces through raise_for_status and
    is logged + re-raised (client.py:435-437). get_balance: a failing
    get_balance_allowance is logged and re-raised (client.py:467-469).
    Happy paths and guards are covered by test_client_compat (not
    duplicated)."""
    _logging_capture(caplog)

    # get_positions: MockTransport returns 500 -> raise_for_status raises.
    pmc_, _stub = _make_client(api_key="k", api_secret="s", passphrase="p")
    real_async_client = client_module.httpx.AsyncClient

    def handler(request):
        return httpx.Response(500, json={"error": "upstream"})

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(**kwargs)

    monkeypatch.setattr(client_module.httpx, "AsyncClient", factory)
    with pytest.raises(httpx.HTTPStatusError):
        await pmc_.get_positions()
    assert "Failed to fetch positions" in caplog.text

    # get_balance: the underlying call raises -> propagates unchanged.
    pmc2, stub2 = _make_client(api_key="k", api_secret="s", passphrase="p")
    boom = RuntimeError("clob balance down")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(stub2, "get_balance_allowance", _raise(boom))
        with pytest.raises(RuntimeError) as excinfo:
            await pmc2.get_balance()
    assert excinfo.value is boom
    assert "Failed to fetch balance" in caplog.text


# --- Accessors and factory --------------------------------------------------


def test_accessors_expose_address_chain_and_credential_state():
    """has_api_credentials reflects the credential state; the address is
    lower-cased at construction (client.py:59/471-481)."""
    with_creds, _stub = _make_client(api_key="k", api_secret="s", passphrase="p")
    assert with_creds.has_api_credentials() is True
    assert with_creds.get_address() == ADDRESS.lower()
    assert with_creds.get_chain_id() == 137

    without_creds, _stub2 = _make_client()
    assert without_creds.has_api_credentials() is False
    assert without_creds.get_address() == ADDRESS.lower()
    assert without_creds.get_chain_id() == 137


def test_factory_create_polymarket_client_builds_wrapper():
    """create_polymarket_client wires the wrapper with the supplied
    credentials and chain (client.py:484-513)."""
    pmc = create_polymarket_client(
        private_key=KEY,
        address=ADDRESS,
        chain_id=80002,
        api_key="k",
        api_secret="s",
        passphrase="p",
    )
    assert isinstance(pmc, PolymarketClient)
    assert pmc.address == ADDRESS.lower()
    assert pmc.chain_id == 80002
    assert pmc.api_creds.api_key == "k"
    assert pmc.api_creds.api_secret == "s"
    assert pmc.api_creds.api_passphrase == "p"
    assert pmc.host == HOST
