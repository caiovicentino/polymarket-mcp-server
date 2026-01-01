"""
Offline regression suite for the WebSocketManager MESSAGE ERROR PATHS (T-0239).

Regions under test (src/polymarket_mcp/utils/websocket_manager.py @ clone main
89edfa9; line numbers are the state at emission — L-0002/L-0008; this suite
only ADDS files):

- _send_subscription   :441-468 — channel dispatch (:444-452). A channel that
                                 matches NEITHER the CLOB pair (:445) NOR the
                                 realtime pair (:449) falls through to the
                                 message build, where
                                 ``subscription.channel.value`` (:457) raises
                                 AttributeError — NO guard exists for unknown
                                 channels, so the error PROPAGATES to the
                                 caller (branch arc :449->455 covered here and
                                 nowhere else in the offline suite).
- _send_unsubscription :505-522 — same smuggled channel: ``ws`` stays None
                                 (:507-511), ``ws_is_open(None)`` is False
                                 (:34-35) and the open-socket guard (:513)
                                 short-circuits with a bare ``return`` (arc
                                 :510->513) — SILENT.
- handle_message       :524-558 — the OUTER except (:557-558) captures any
                                 exception escaping the routing (e.g. a
                                 ``None`` payload crashing ``message.get``
                                 at :533) and logs "Error handling message"
                                 with exc_info=True (the traceback seen on
                                 stderr is the logger's — proof of the line
                                 executing, not an unhandled error). Stats
                                 (:539-540) increment BEFORE routing.
- _handle_order_update      :638-676 — parse failure (``Decimal(str(...))``
                                 at :644 raises decimal.InvalidOperation) is
                                 caught by the INNER except (:675-676, "Error
                                 handling order update") and never reaches the
                                 outer except (independent handlers).
- _handle_trade_update      :678-714 — same mechanism, "Error handling trade
                                 update" (:713-714).
- _handle_market_resolution :716-744 — ``datetime.fromisoformat`` (:722)
                                 raises ValueError for garbage; "Error
                                 handling market resolution" (:743-744).
- handler callback loops    — a subscription with ``callback_type == "log"``
                                 and ``log_callback is None`` falls through
                                 BOTH dispatch branches (price_change has the
                                 elif chain :582/:591; the other four handlers
                                 only have the notification branch :623/:661/
                                 :700/:734) and the loop CONTINUES (arcs
                                 :591->578, :623->619, :661->657, :700->696,
                                 :734->730). The bookkeeping
                                 (``events_received``/``last_event_at``,
                                 :579-580/:620-621/:658-659/:697-698/:731-732)
                                 runs BEFORE the branch, so it is updated
                                 either way.

Already covered by siblings (dedupe by reading, P-0039/L-0136 — NO overlap
with this file):
- tests/test_websocket_messages.py (T-0043) owns the NORMAL routing of all
  five event types, the malformed price_change/orderbook payloads (inner
  excepts :596-597/:635-636), the no-type drop (:533-536) and the unknown
  type fallback (:553-555). Grep proof: no existing test pins the outer
  except text, the order/trade/resolution excepts, the unknown-channel
  AttributeError or the non-notification fall-through (L-0136 calibration
  done at emission, 2026-09-17).
- tests/test_websocket_lifecycle_offline.py (T-0051) owns the CONNECTION
  layer: subscribe/unsubscribe storage, _send_subscription/
  _send_unsubscription with KNOWN channels (CLOB/realtime dispatch,
  connection guards, send mechanics) and ws_is_open.
- tests/test_websocket_supervision_offline.py (T-0052) replaces
  ``handle_message`` at INSTANCE level with a fail-loud recorder (its
  :930-945 only proves the reader hands the parsed dict over) — it never
  exercises the REAL routing; no interference with this suite (L-0025).

Coupling declarations (consumer↔producer, L-0073/L-0121) — a fix that changes
any of these must update this suite in the SAME slice:
- The AttributeError propagation on an unknown channel (SEND) and the silent
  no-op (UNSUB) are pinned AS OBSERVED (quirk-of-product, anti-fix rule
  P-0033/P-0038: follow-ups go to the curator, never patched inside a
  suite-only slice). The asymmetry between the two paths is the point of
  tests 1-2.
- The log prefixes "Error handling message" / "Error handling order update" /
  "Error handling trade update" / "Error handling market resolution" are
  pinned as observed; a reworded message fails loudly.
- Stats-before-parse (:539-540) and bookkeeping-before-dispatch (:579-580
  etc.) are semantic pins: moving them after the parse/branch flips these
  tests — intentional regression protection, not accidental coupling.

Hermeticity (P-0029, house pattern P-0035): zero network (the manager is
constructed WITHOUT connecting and no test dials a socket), zero real sleep,
zero host-env dependence (autouse ``clean_env`` strips every config-sourced
env prefix; the config is built from explicit kwargs with ``_env_file=None``).
Order-independent: every test builds its own manager and subscriptions; no
shared mutable state. Divergence declared (L-0025): the contract draft built
the config as ``PolymarketConfig(DEMO_MODE=True)``; this suite uses the house
``make_config`` factory of the sibling lifecycle suite (explicit kwargs +
``_env_file=None``) — MORE hermetic (kills .env reads), and the manager never
reads the config in any region under test, so every observable is identical.
The pyproject sets ``asyncio_mode = "auto"`` (:80) — bare ``async def`` tests
need no decorator.
"""
import logging
import os
from datetime import datetime

import pytest

from polymarket_mcp.config import PolymarketConfig
from polymarket_mcp.utils.websocket_manager import (
    ChannelType,
    EventType,
    Subscription,
    WebSocketManager,
)

MANAGER_LOGGER = "polymarket_mcp.utils.websocket_manager"

CREATED_AT = datetime(2026, 9, 17, 12, 0, 0)

# Process env prefixes/names that feed PolymarketConfig fields; stripped by
# the autouse fixture so tests never observe the host environment (P-0035,
# house pattern of tests/test_websocket_lifecycle_offline.py:102-133).
_ENV_PREFIXES = (
    "POLYGON_",
    "POLYMARKET_",
    "DEMO_MODE",
    "LOG_LEVEL",
    "MAX_",
    "MIN_",
    "ENABLE_",
    "REQUIRE_",
    "AUTO_",
)


# ---------------------------------------------------------------------------
# Hermeticity — env neutralization (autouse; P-0035)
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Strip config-sourced env vars so tests never see the host environment.

    Every test (autouse) gets a host-neutral environment: pydantic
    ``BaseSettings`` still reads env vars for fields not passed explicitly
    even with ``_env_file=None`` (config.py:11,17-18). All configs here are
    built with explicit kwargs, so the delenv changes no pin — it only
    guarantees that a hostile host environment cannot alter any observable.
    """
    for name in list(os.environ):
        if any(name.startswith(prefix) for prefix in _ENV_PREFIXES):
            monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Factories (pure, per-test; no shared mutable state — P-0029)
# ---------------------------------------------------------------------------
def make_config():
    """Config factory (house pattern of the lifecycle suite). The dummy key
    is VALID: the T-0030 validator rejects all-zero keys, so never pass
    "0" * 64."""
    return PolymarketConfig(
        POLYGON_PRIVATE_KEY="0" * 63 + "1",
        POLYGON_ADDRESS="0x" + "0" * 40,
        POLYMARKET_CHAIN_ID=137,
        _env_file=None,
    )


def make_sub(sub_id, event_type, callback_type="notification"):
    """Subscription factory with a constructor-visible (VALID) channel.

    Every field passed here goes through pydantic validation; the bogus
    channel of tests 1-2 is smuggled in POST-construction (see below).
    """
    return Subscription(
        id=sub_id,
        type=event_type,
        channel=ChannelType.CLOB_MARKET,
        created_at=CREATED_AT,
        callback_type=callback_type,
    )


# ---------------------------------------------------------------------------
# 1-2) Unknown channel — the honest asymmetry (SEND propagates, UNSUB silences)
# ---------------------------------------------------------------------------
async def test_send_subscription_bogus_channel_raises_attributeerror():
    """Unknown channel: the dispatch has NO guard — AttributeError propagates.

    ``Subscription.channel`` is a plain pydantic field WITHOUT
    ``validate_assignment`` (websocket_manager.py:120-130), so a raw string
    can be smuggled in post-construction (the only way a real channel misses
    the CLOB/realtime dispatch: every constructor-visible value is a valid
    ChannelType). With ``channel = "bogus"`` the dispatch (:444-452) leaves
    ``ws = None`` and falls through (arc :449->455) to the message build,
    where ``subscription.channel.value`` (:457) raises AttributeError. The
    error reaches the CALLER — pinned honestly: there is no guard to convert
    it into a silent failure, and this suite pins the behaviour AS OBSERVED
    instead of asserting the idealized symmetric spec (L-0025/L-0115; a
    future guard must update this test in the same slice, L-0073).
    """
    manager = WebSocketManager(config=make_config())
    subscription = make_sub("sub-bogus-send", EventType.ORDER)
    subscription.channel = "bogus"  # no validate_assignment: accepted silently

    with pytest.raises(AttributeError):
        await manager._send_subscription(subscription)


async def test_send_unsubscription_bogus_channel_returns_silently():
    """Unknown channel on UNSUBSCRIBE: silent no-op (asymmetry pinned).

    Same smuggled channel as the SEND pin — but the unsubscribe path has no
    message build: ``ws`` stays None (:507-511, arc :510->513) and
    ``ws_is_open(None)`` returns False (:34-35), so the guard (:513)
    short-circuits with a bare ``return`` and the method returns None. The
    asymmetry SEND-raises × UNSUB-silences is the OBSERVED contract (both
    tests 1-2 together; a fix that unifies the behaviour must update both in
    the same slice, L-0073).
    """
    manager = WebSocketManager(config=make_config())
    subscription = make_sub("sub-bogus-unsub", EventType.ORDER)
    subscription.channel = "bogus"  # no validate_assignment: accepted silently

    result = await manager._send_unsubscription(subscription)
    assert result is None


# ---------------------------------------------------------------------------
# 3) The outer except of handle_message (:557-558)
# ---------------------------------------------------------------------------
async def test_handle_message_none_payload_captured_by_outer_except(caplog):
    """``None`` payload: the outer except captures it; nothing propagates.

    ``message.get("type")`` (:533) raises AttributeError BEFORE the stats —
    the outer except (:557-558) logs "Error handling message" with
    exc_info=True and returns normally (the traceback visible on stderr is
    the logger's, i.e. PROOF of the except executing, not an unhandled
    error). Sanity pin: stats stay at 0 because the exception precedes the
    counters (:539-540) — the capture point is discriminated from the
    handler-level captures of tests 4-6.
    """
    manager = WebSocketManager(config=make_config())
    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        await manager.handle_message("clob", None)  # must NOT raise

    assert "Error handling message" in caplog.text
    assert manager.total_events_received == 0


# ---------------------------------------------------------------------------
# 4-6) Malformed payloads — the INNER excepts of the typed handlers
# ---------------------------------------------------------------------------
async def test_order_update_malformed_decimal_captured_by_except(caplog):
    """Malformed order payload: inner except captures; stats still count.

    ``Decimal(str(...))`` (:644) raises decimal.InvalidOperation during the
    OrderUpdate parse — before any subscription matching; the handler's
    except (:675-676) logs "Error handling order update" and the exception
    never reaches the outer except (independent handlers). Semantic pin:
    the router already incremented the stats BEFORE the parse (:539-540) —
    the event counts even though it failed (total_events_received >= 1).
    """
    manager = WebSocketManager(config=make_config())
    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        await manager.handle_message(
            "clob", {"type": "order", "filled_size": "not-a-number"}
        )  # must NOT raise

    assert "Error handling order update" in caplog.text
    assert manager.total_events_received >= 1


async def test_trade_update_malformed_price_captured_by_except(caplog):
    """Malformed trade payload: inner except captures, nothing propagates.

    ``Decimal(str(...))`` (:685) raises decimal.InvalidOperation during the
    TradeUpdate parse; the except (:713-714) logs "Error handling trade
    update" and the exception never reaches the outer except (independent
    handlers — this payload does NOT hit :557-558).
    """
    manager = WebSocketManager(config=make_config())
    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        await manager.handle_message(
            "clob", {"type": "trade", "price": "not-a-number"}
        )  # must NOT raise

    assert "Error handling trade update" in caplog.text


async def test_market_resolution_malformed_timestamp_captured_by_except(caplog):
    """Malformed resolution payload: inner except captures, nothing propagates.

    ``datetime.fromisoformat("garbage")`` (:722) raises ValueError during the
    MarketResolutionEvent parse; the except (:743-744) logs "Error handling
    market resolution" and the exception never reaches the outer except
    (independent handlers).
    """
    manager = WebSocketManager(config=make_config())
    with caplog.at_level(logging.ERROR, logger=MANAGER_LOGGER):
        await manager.handle_message(
            "clob", {"type": "market_resolved", "timestamp": "garbage"}
        )  # must NOT raise

    assert "Error handling market resolution" in caplog.text


# ---------------------------------------------------------------------------
# 7) Non-notification subscriptions pass through all five handler loops
# ---------------------------------------------------------------------------
async def test_non_notification_subscriptions_pass_through_all_handlers():
    """callback_type "log" + no callbacks: bookkeeping runs, dispatch skips.

    Five subscriptions (one per routable event type) are registered DIRECTLY
    in the dict — bypassing ``subscribe`` (whose ``_send_subscription`` would
    raise against the unconnected sockets; the ROUTING behaviour under test
    does not depend on registration mechanics, the sibling
    tests/test_websocket_messages.py:13 states the same rationale). Each
    valid event finds its type-matching subscription
    (_find_matching_subscriptions :750-776 — no market/token filters set),
    runs the bookkeeping (events_received/last_event_at BEFORE the branch)
    and falls through BOTH dispatch branches: price_change's
    ``callback_type == "log"`` matches the elif (:591) but ``log_callback``
    is None → False; the other four handlers only have the notification
    branch (:623/:661/:700/:734) → False. The loop CONTINUES (arcs
    :591->578, :623->619, :661->657, :700->696, :734->730), no exception
    escapes, and the outer except never fires. The ``agg_orderbook`` value
    is used verbatim (EventType.AGG_ORDERBOOK.value == "agg_orderbook", NOT
    "orderbook").
    """
    manager = WebSocketManager(config=make_config())  # BOTH callbacks are None
    ordered_types = (
        EventType.PRICE_CHANGE,
        EventType.AGG_ORDERBOOK,
        EventType.ORDER,
        EventType.TRADE,
        EventType.MARKET_RESOLVED,
    )
    subs = []
    for event_type in ordered_types:
        sub = make_sub(f"sub-{event_type.value}", event_type, callback_type="log")
        manager.subscriptions[sub.id] = sub  # direct dict insertion, no send
        subs.append(sub)

    # One valid payload per type; the parse succeeds with defaults where the
    # payload omits "timestamp" (datetime.now() default, :566/:610).
    await manager.handle_message(
        "clob", {"type": "price_change", "asset_id": "a", "price": "0.5", "market": "m1"}
    )
    await manager.handle_message(
        "clob",
        {"type": "agg_orderbook", "asset_id": "a", "bids": [["0.5", "1"]], "asks": []},
    )
    await manager.handle_message(
        "clob",
        {
            "type": "order",
            "order_id": "o1",
            "filled_size": "1",
            "remaining_size": "2",
            "price": "0.5",
            "side": "BUY",
            "timestamp": "2026-01-01T00:00:00",
        },
    )
    await manager.handle_message(
        "clob",
        {
            "type": "trade",
            "trade_id": "t1",
            "order_id": "o1",
            "market_id": "m1",
            "price": "0.5",
            "size": "1",
            "side": "BUY",
            "timestamp": "2026-01-01T00:00:00",
        },
    )
    await manager.handle_message(
        "clob",
        {
            "type": "market_resolved",
            "market_id": "m1",
            "outcome": "YES",
            "timestamp": "2026-01-01T00:00:00",
        },
    )

    # Sanity: every subscription received EXACTLY its one matching event and
    # the bookkeeping ran (loop bodies executed, not just the fall-through).
    counts = [sub.events_received for sub in subs]
    assert counts == [1, 1, 1, 1, 1]
    assert all(sub.last_event_at is not None for sub in subs)
