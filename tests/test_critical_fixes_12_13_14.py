"""Regression tests for the 3 critical bugs fixed: #12, #13, #14.

#12 portfolio crash: portfolio tools were handed a SafetyLimits object where a RateLimiter
    was expected (server.py routed safety_limits into the rate_limiter slot).
#13 websocket: the message loop was never started; WS auth reused the passphrase as the secret.
#14 wrong-side trades: trading always used tokens[0] (the YES token) regardless of YES/NO.
"""

import pytest

from polymarket_mcp.tools.trading import TradingTools
from polymarket_mcp.utils.rate_limiter import RateLimiter, get_rate_limiter
from polymarket_mcp.utils.safety_limits import SafetyLimits

# ----------------------------------------------------------------- #14
YES = {"token_id": "TOKEN_YES", "outcome": "Yes"}
NO = {"token_id": "TOKEN_NO", "outcome": "No"}


def test_select_token_matches_outcome_field():
    assert TradingTools._select_token([YES, NO], "YES") == "TOKEN_YES"
    assert TradingTools._select_token([YES, NO], "NO") == "TOKEN_NO"
    # order-independent: still resolves by the outcome field, not position
    assert TradingTools._select_token([NO, YES], "NO") == "TOKEN_NO"
    assert TradingTools._select_token([NO, YES], "YES") == "TOKEN_YES"


def test_select_token_default_is_yes():
    assert TradingTools._select_token([YES, NO]) == "TOKEN_YES"


def test_select_token_index_fallback_when_no_outcome_field():
    toks = [{"token_id": "T0"}, {"token_id": "T1"}]
    assert TradingTools._select_token(toks, "YES") == "T0"
    assert TradingTools._select_token(toks, "NO") == "T1"


def test_select_token_rejects_bad_outcome_and_empty():
    with pytest.raises(ValueError):
        TradingTools._select_token([YES, NO], "MAYBE")
    with pytest.raises(ValueError):
        TradingTools._select_token([], "YES")


def test_trade_methods_accept_outcome_param():
    import inspect

    for name in (
        "create_limit_order",
        "create_market_order",
        "suggest_order_price",
        "rebalance_position",
    ):
        sig = inspect.signature(getattr(TradingTools, name))
        assert "outcome" in sig.parameters, f"{name} missing outcome param"
        assert sig.parameters["outcome"].default == "YES"


# ----------------------------------------------------------------- #12
def test_rate_limiter_has_acquire_but_safety_limits_does_not():
    # the portfolio tools call rate_limiter.acquire(...); passing SafetyLimits there crashed.
    rl = get_rate_limiter()
    assert isinstance(rl, RateLimiter)
    assert hasattr(rl, "acquire") and callable(rl.acquire)
    assert not hasattr(SafetyLimits, "acquire")


def test_server_routes_rate_limiter_not_safety_limits():
    # guard against regressing the exact swap that caused the crash.
    import inspect
    from polymarket_mcp import server

    src = inspect.getsource(server)
    assert "get_rate_limiter()," in src.split("call_portfolio_tool")[1][:200]


# ----------------------------------------------------------------- #13
def test_websocket_init_starts_background_loop():
    import inspect
    from polymarket_mcp import server

    src = inspect.getsource(server)
    # connect() alone is not enough; the message loop must be started too.
    assert "start_background_task()" in src


def test_websocket_auth_secret_prefers_api_secret_over_passphrase():
    import inspect
    from polymarket_mcp.utils import websocket_manager

    src = inspect.getsource(
        websocket_manager._authenticate_clob
        if hasattr(websocket_manager, "_authenticate_clob")
        else websocket_manager.WebSocketManager._authenticate_clob
    )
    assert "POLYMARKET_API_SECRET" in src


def test_config_exposes_api_secret_field():
    from polymarket_mcp.config import PolymarketConfig

    assert "POLYMARKET_API_SECRET" in PolymarketConfig.model_fields
