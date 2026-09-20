"""
Declarative-honesty contract suite for the order_type enum on batch items
(trading.py): the ``create_batch_orders`` item schema now mirrors the runtime
validator domain (GTC/GTD/FOK/FAK) that the single-order tool already declares
(T-0447, class L-0433).

Pinned against clone main 3ad9954. Asserts follow the code as observed (probed
offline), not the docstrings - L-0020/L-0090. Source of truth:
- The schemas are derived from the LIVE registry (get_tool_definitions) - the
  suite never reimplements the schema bytes (anti-drift, L-0023).
- VALID_ORDER_TYPES is read via getattr so a future rename fails in the BODY
  (AssertionError) instead of crashing the SETUP (L-0417).
- The enum is advisory client-side (MCP servers do not validate schemas); the
  runtime validator (upper() + rejection) is unchanged and stays pinned by
  tests/test_trading_offline.py ("Invalid order type: IOC" / "GTD orders
  require expiration timestamp").
- E1-E5 are zero-semantics: the serialized registry value is identical
  (json.dumps of the enum: same array) and the validator list is the same
  values.

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


def test_batch_items_order_type_enum_matches_single():
    """Identity derivation: batch enum == single enum == VALID_ORDER_TYPES.

    RED pre-fix: the batch item declares only {"type": "string"} so
    ``.get("enum")`` is None and the first assert fails IN THE BODY
    (L-0417), not in setup.
    """
    enum_single = _single_props()["order_type"].get("enum")
    enum_batch = _batch_item_props()["order_type"].get("enum")
    const = getattr(trading, "VALID_ORDER_TYPES", None)
    assert enum_batch is not None, (
        "batch item order_type has no enum (the declarative-honesty gap)"
    )
    assert enum_batch == enum_single, (enum_batch, enum_single)
    assert const is not None, "VALID_ORDER_TYPES missing from trading module"
    assert enum_batch == const, (enum_batch, const)
    # same serialized array (zero-semantics proof: the registry value is
    # byte-identical before/after the refactor)
    assert json.dumps(enum_batch) == json.dumps(enum_single)


def test_valid_order_types_values():
    """Pin of the VALUE (as a set), never the incidental format (L-0023).

    RED pre-fix: getattr yields None and the first assert fails IN THE BODY.
    """
    const = getattr(trading, "VALID_ORDER_TYPES", None)
    assert const is not None, "VALID_ORDER_TYPES missing from trading module"
    assert set(const) == {"GTC", "GTD", "FOK", "FAK"}, const


def test_docstring_declares_same_types():
    """Anti-drift docstring x constant (GREEN pre and post).

    The create_limit_order docstring must keep naming the four tokens; the
    constant<->schema identity is covered by test 1. Literal tokens only -
    never the incidental 'GTC'|'GTD' formatting.
    """
    doc = trading.TradingTools.create_limit_order.__doc__ or ""
    for token in ("GTC", "GTD", "FOK", "FAK"):
        assert token in doc, token


def test_batch_items_expiration_description():
    """E5 mirror: the batch item gains the single tool's expiration wording.

    RED pre-fix: the batch item expiration has no "description" key, so the
    assert fails IN THE BODY (L-0417).
    """
    expiration = _batch_item_props()["expiration"]
    desc = expiration.get("description")
    assert isinstance(desc, str) and "Unix timestamp for GTD orders" in desc, (
        expiration
    )


def test_other_schemas_unchanged():
    """Anti-over-fix (GREEN pre and post): ONLY E4/E5 touched the batch item.

    - create_market_order gains NO order_type (props without it);
    - the create_batch_orders top-level stays {type: object, properties:
      {orders: ...}, required: [orders]};
    - the batch item keeps exactly its seven property keys and its required
      list, with every non-order_type/non-expiration prop byte-identical
      (by value) to the fork state (3ad9954);
    - the single schema keeps its other props (market_id/side/price/size/
      confirm/outcome) and the full order_type prop (type/default/
      description) identical by value - the enum itself is covered by
      test_batch_items_order_type_enum_matches_single.
    """
    market_props = _tool_schema("create_market_order")["properties"]
    assert "order_type" not in market_props, sorted(market_props)

    batch_schema = _tool_schema("create_batch_orders")
    assert batch_schema["type"] == "object"
    assert batch_schema["required"] == ["orders"]
    assert list(batch_schema["properties"].keys()) == ["orders"]

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
    # order_type/expiration values of the batch item are NOT pinned here:
    # they are exactly the fields the E4/E5 edits change (covered by tests
    # 1 and 4) - pinning the post-state here would break the GREEN pre
    # property of this anti-over-fix test.
    for key in ("market_id", "side", "price", "size", "outcome"):
        assert item_props[key] == {
            "market_id": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "price": {"type": "number"},
            "size": {"type": "number"},
            "outcome": {"type": "string"},
        }[key], item_props[key]

    items_node = batch_schema["properties"]["orders"]["items"]
    assert items_node["required"] == ["market_id", "side", "price", "size"]
    assert _tool_schema("create_batch_orders")["properties"]["orders"][
        "description"
    ] == "List of orders to submit"

    single_props = _single_props()
    assert sorted(single_props.keys()) == [
        "confirm",
        "expiration",
        "market_id",
        "order_type",
        "outcome",
        "price",
        "side",
        "size",
    ], sorted(single_props.keys())
    assert single_props["market_id"] == {
        "type": "string",
        "description": "Market condition ID",
    }
    assert single_props["side"] == {
        "type": "string",
        "enum": ["BUY", "SELL"],
        "description": "Order side",
    }
    assert single_props["price"] == {
        "type": "number",
        "minimum": 0.01,
        "maximum": 0.99,
        "description": "Limit price (0.01-0.99)",
    }
    assert single_props["size"] == {
        "type": "number",
        "minimum": 1,
        "description": "Order size in USD",
    }
    assert single_props["order_type"]["default"] == "GTC"
    assert single_props["order_type"]["type"] == "string"
    assert single_props["order_type"]["description"] == "Order type"
    assert single_props["expiration"] == {
        "type": "integer",
        "description": "Unix timestamp for GTD orders (optional)",
    }
    assert single_props["confirm"] == {
        "type": "boolean",
        "default": False,
        "description": (
            "Set true to place an order that requires confirmation. "
            "Without it the order is described back to you instead "
            "of being placed."
        ),
    }
    assert single_props["outcome"] == {
        "type": "string",
        "description": (
            "Outcome to trade, e.g. 'Yes', 'No', 'Lakers'. "
            "Defaults to 'Yes' on Yes/No markets; required for "
            "sports and other multi-outcome markets."
        ),
    }
