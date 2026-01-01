"""
Declarative-honesty contract suite for the price/size bounds of the
``create_batch_orders`` item (trading.py): the item schema now mirrors the
single-order tool's declared bounds (price 0.01-0.99, size minimum=1) via
the module-level constants LIMIT_PRICE_MIN / LIMIT_PRICE_MAX / ORDER_SIZE_MIN
shared with ``create_limit_order`` (T-0451; the gap was registered by the
T-0447 census, class L-0433).

Pinned against clone main 91b055f. Asserts follow the code as observed
(probed offline), not the docstrings - L-0020/L-0090. Source of truth:
- The schemas are derived from the LIVE registry (get_tool_definitions) - the
  suite never reimplements the schema bytes (anti-drift, L-0023).
- The bounds constants are read via getattr so a future rename fails in the
  BODY (AssertionError) instead of crashing the SETUP (L-0417).
- The bounds are advisory client-side (MCP servers do not validate schemas);
  the runtime validator (SafetyLimits.validate_order) and the SDK price
  validation keep enforcing the same values per item and stay pinned by
  tests/test_trading_offline.py.

Zero network, zero fakes: pure in-process schema reads from the live registry.
"""
import json

from polymarket_mcp.tools import trading
from polymarket_mcp.tools.trading import get_tool_definitions


def _tool_schema(name: str) -> dict:
    """Fail-loud schema lookup in the LIVE registry (P-0031)."""
    for tool in get_tool_definitions():
        if tool.name == name:
            return tool.inputSchema
    raise AssertionError(f"tool {name!r} not found in the live registry")


def _single_props() -> dict:
    return _tool_schema("create_limit_order")["properties"]


def _batch_item_props() -> dict:
    schema = _tool_schema("create_batch_orders")
    return schema["properties"]["orders"]["items"]["properties"]


def test_item_price_bounds_mirror_single():
    """Identity derivation: batch item price bounds == single price bounds.

    RED pre-fix: the batch item price is {"type": "number"} with no bounds,
    so the first two asserts fail IN THE BODY (L-0417), not in setup. The
    identity is by construction: both literals reference the same
    module-level constants (LIMIT_PRICE_MIN/LIMIT_PRICE_MAX), so a future
    change to a single constant moves single and item together
    (anti-drift, P-0233).
    """
    single = _single_props()["price"]
    item = _batch_item_props()["price"]
    assert "minimum" in item, item
    assert "maximum" in item, item
    assert item == single, (item, single)
    # Same serialized object (zero-semantics proof: the registry value is
    # byte-identical by construction, including key order).
    assert json.dumps(item) == json.dumps(single)


def test_item_size_bounds_mirror_single():
    """Identity derivation: batch item size bound == single size bound.

    RED pre-fix: the batch item size is {"type": "number"} with no bounds,
    so the first assert fails IN THE BODY (L-0417), not in setup.
    """
    single = _single_props()["size"]
    item = _batch_item_props()["size"]
    assert "minimum" in item, item
    assert item == single, (item, single)
    assert json.dumps(item) == json.dumps(single)


def test_constants_single_source():
    """Single source: single AND item reference the SAME module constants.

    RED pre-fix: getattr yields None and the first asserts fail IN THE BODY
    (L-0417). The literal values are pinned as a conscious canary (P-0233):
    the bounds mirror the runtime SafetyLimits domain, so a silent constant
    change must fail here until the registry and the runtime are re-probed
    together.
    """
    price_min = getattr(trading, "LIMIT_PRICE_MIN", None)
    price_max = getattr(trading, "LIMIT_PRICE_MAX", None)
    size_min = getattr(trading, "ORDER_SIZE_MIN", None)
    assert price_min is not None, "LIMIT_PRICE_MIN missing from trading module"
    assert price_max is not None, "LIMIT_PRICE_MAX missing from trading module"
    assert size_min is not None, "ORDER_SIZE_MIN missing from trading module"
    assert price_min == 0.01, price_min
    assert price_max == 0.99, price_max
    assert size_min == 1, size_min
    single_props = _single_props()
    item_props = _batch_item_props()
    assert (
        single_props["price"]["minimum"]
        == item_props["price"]["minimum"]
        == price_min
    )
    assert (
        single_props["price"]["maximum"]
        == item_props["price"]["maximum"]
        == price_max
    )
    assert (
        single_props["size"]["minimum"] == item_props["size"]["minimum"] == size_min
    )


def test_item_required_and_other_props_unchanged():
    """Anti-over-fix (GREEN pre and post): E3 touches ONLY the item price/size.

    - create_market_order gains NO order_type (the T-0447 pin survives);
    - the create_batch_orders top-level stays {type: object, properties:
      {orders: ...}, required: [orders]} with the orders description;
    - the batch item keeps exactly its seven property keys and its required
      list ["market_id", "side", "price", "size"];
    - the other five item props (market_id/side/order_type/expiration/
      outcome) stay byte-identical (by value) to the fork state (91b055f).

    The price/size props themselves are NOT pinned byte-wise here: they are
    exactly the fields the E3 edit changes (covered by tests 1/2/3) -
    pinning the post-state would break the GREEN pre property of this
    anti-over-fix test (T-0447 pattern).
    """
    market_props = _tool_schema("create_market_order")["properties"]
    assert "order_type" not in market_props, sorted(market_props)

    batch_schema = _tool_schema("create_batch_orders")
    assert batch_schema["type"] == "object"
    assert batch_schema["required"] == ["orders"]
    assert list(batch_schema["properties"].keys()) == ["orders"]
    assert (
        batch_schema["properties"]["orders"]["description"]
        == "List of orders to submit"
    )

    item_props = _batch_item_props()
    assert sorted(item_props.keys()) == [
        "expiration",
        "market_id",
        "order_type",
        "outcome",
        "price",
        "side",
        "size",
    ], sorted(item_props.keys())
    const = getattr(trading, "VALID_ORDER_TYPES", None)
    assert const is not None, "VALID_ORDER_TYPES missing from trading module"
    for key, expected in (
        ("market_id", {"type": "string"}),
        ("side", {"type": "string", "enum": ["BUY", "SELL"]}),
        ("order_type", {"type": "string", "enum": const}),
        (
            "expiration",
            {
                "type": "integer",
                "description": "Unix timestamp for GTD orders (optional)",
            },
        ),
        ("outcome", {"type": "string"}),
    ):
        assert item_props[key] == expected, item_props[key]

    items_node = batch_schema["properties"]["orders"]["items"]
    assert items_node["required"] == ["market_id", "side", "price", "size"]


def test_registry_serialization_unchanged_for_single():
    """Guard: E2 is zero-semantics - the single's serialized registry value
    stays byte-identical to the fork state (91b055f).

    The expected side is assembled from the fork literals in fork key order
    (T-0447 pins, by value); the observed side is derived from the LIVE
    registry. json.dumps compares value AND key order, so any reordering or
    int/float drift (e.g. minimum 1 -> 1.0) fails here even though dict
    equality would pass.
    """
    const = getattr(trading, "VALID_ORDER_TYPES", None)
    assert const is not None, "VALID_ORDER_TYPES missing from trading module"
    expected_props = {
        "market_id": {
            "type": "string",
            "description": "Market condition ID",
        },
        "side": {
            "type": "string",
            "enum": ["BUY", "SELL"],
            "description": "Order side",
        },
        "price": {
            "type": "number",
            "minimum": 0.01,
            "maximum": 0.99,
            "description": "Limit price (0.01-0.99)",
        },
        "size": {
            "type": "number",
            "minimum": 1,
            "description": "Order size in USD",
        },
        "order_type": {
            "type": "string",
            "enum": const,
            "default": "GTC",
            "description": "Order type",
        },
        "expiration": {
            "type": "integer",
            "description": "Unix timestamp for GTD orders (optional)",
        },
        "confirm": {
            "type": "boolean",
            "default": False,
            "description": (
                "Set true to place an order that requires confirmation. "
                "Without it the order is described back to you instead "
                "of being placed."
            ),
        },
        "outcome": {
            "type": "string",
            "description": (
                "Outcome to trade, e.g. 'Yes', 'No', 'Lakers'. "
                "Defaults to 'Yes' on Yes/No markets; required for "
                "sports and other multi-outcome markets."
            ),
        },
    }
    expected = {
        "type": "object",
        "properties": expected_props,
        "required": ["market_id", "side", "price", "size"],
    }
    actual = _tool_schema("create_limit_order")
    assert json.dumps(actual) == json.dumps(expected)
