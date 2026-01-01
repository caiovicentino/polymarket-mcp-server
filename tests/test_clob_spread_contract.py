"""
Wire-truth contract suite for the CLOB /spread and /midpoint endpoints
(T-0433; REQUER-HUMANO item 138): one xfail(strict=True) offline test pins
the broken get_spread tool surface (the flip contract the item 138 fix will
consume), plus two live integration greens pinning the REAL wire contract of
the CLOB /spread and /midpoint endpoints the fix option (ii) would build on.

Wire truth proven first-hand (contract emission 2026-09-20; re-probed on
this branch the same day by live token harvest):
- GET https://clob.polymarket.com/spread?token_id=<tok> -> HTTP 200 body
  {"spread":"0.001"}
- GET https://clob.polymarket.com/midpoint?token_id=<tok> -> HTTP 200 body
  {"mid":"0.0355"}
Both payloads are DECIMAL STRINGS (not floats); the live tests below pin
"Decimal(body["spread"|"mid"]) is parseable and 0 <= value <= 1", never a
volatile price magnitude (L-0340/L-0390: live pins stable facts).

State of the code proven by grep at emission: NO consumer of /midpoint or
/spread exists under src/ - get_spread flows through get_current_price
(token_id, "BOTH"), which the code expands into the two client-side /price
calls (BUY and SELL; market_analysis.py:224-230) with the inverted mapping
V12b (BUY -> .ask, SELL -> .bid). That is why the /spread endpoint is a
viable fix option (ii) for item 138 (REQUER-HUMANO) while the tool surface
stays broken.

The flip contract (precedent: tests/test_gamma_clob_fields_contract.py -
T-0212, the suite this one is modeled on). The offline xfail body asserts
the CORRECT behavior and fails against the current code (proof of the bug);
when item 138 fixes land via option (i) (two client-side calls with the
corrected mapping BUY -> .bid, SELL -> .ask), the xfail flips to XPASS
(strict -> suite RED) and the fix consumes the flip through the owner
channel.

Declared divergences contract x code (L-0020/L-0025 - asserts follow the
observed code, never the spec text; details in each docstring):
- test_get_spread_resolves_spread: the contract's prescribed failure
  mechanism ("the code sends side=BOTH to the wire -> the fake raises the
  live HTTP 400") does not hold against the observed code - get_current_price
  NEVER sends side=BOTH to the wire: it expands BOTH into two client-side
  /price calls (market_analysis.py:224-230). The xfail therefore fires today
  through the V12b inversion flowing through get_spread: the fake serves
  BUY -> "0.52" (ask) and SELL -> "0.53" (bid), so spread_value = ask - bid =
  0.52 - 0.53 = -0.01, which fails the prescribed assert (== 0.01). The
  --runxfail forensic shows EXACTLY 1 failed by BODY ASSERT (L-0417: the
  body executes; the failure is never a setup/fixture error). The fake
  KEEPS the raise-on-side=BOTH (the live HTTP 400 body) as the fix-honesty
  guard: any implementation that sends side=BOTH to the wire reproduces the
  live 400 and stays RED.
- Fix option (ii) (/spread endpoint) would need this fake adjusted by the
  fixer in the SAME change as the T-0212 flip (the fail-loud fake answers
  "unexpected clob endpoint: '/spread'" - a loud, honest signal, never a
  silent fallback to the real network). Both flips land in one change.
- reason text: the contract's literal reason ("get_spread hoje chama
  get_current_price(side='BOTH') -> HTTP 400 Invalid side") states a
  mechanism that does not hold against the observed code; the reason below
  states the OBSERVED mechanism (V12b inversion flowing through get_spread)
  with the same flip semantics (XPASS -> strict -> RED -> owner flip).

Hermeticity: the offline xfail is zero-network (module-seam fake, fail-loud
per P-0031 - any unexpected endpoint/argument raises AssertionError, no
silent fallback to the real network). The live tests are marked
`integration` - and ONLY that, so the canonical offline selection of
CONTRIBUTING.md excludes them (P-0048) - and skip on network failure: the
transport guard never fails the suite for infra. There is NO pytestmark at
module level (P-0130(4): per-test markers only, so a stray marker can never
leak into the offline selection). Values asserted via decimal.Decimal
(never float() on a contract assertion - precision).

Fix note (item 138): the prescribed fix paths for V12 are (i) two
client-side calls with the corrected mapping, or (ii) use the CLOB
/midpoint + /spread endpoints. This suite pins the wire truth of path (ii)
endpoints and the tool-level get_spread flip; T-0212 documents both paths
in its module docstring - the two suites flip in the SAME owner change.
"""

import json
from decimal import Decimal

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

GAMMA_API_URL = market_analysis.GAMMA_API_URL
CLOB_API_URL = market_analysis.CLOB_API_URL


class _FakeClob:
    """Fail-loud stand-in for market_analysis._fetch_clob_api (P-0031).

    Serves exactly the two /price calls the real code makes for
    side="BOTH" (market_analysis.py:224-230) and RAISES on side=BOTH (the
    live HTTP 400 {"error":"Invalid side"} body, proven live 2026-09-17):
    a fix that sends side=BOTH to the wire reproduces the 400 here and
    keeps the xfail RED. Any other endpoint/argument fails loud - no
    silent fallback to the real network.
    """

    def __init__(self):
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "/price":
            token_id = params.get("token_id")
            side = params.get("side")
            if side == "BOTH":
                raise RuntimeError("Invalid side")
            if side == "BUY":
                return {"price": "0.52"}
            if side == "SELL":
                return {"price": "0.53"}
            raise AssertionError(
                f"no synthetic price for token={token_id!r} side={side!r}"
            )
        raise AssertionError(f"unexpected clob endpoint: {endpoint!r}")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "get_spread flows get_current_price(token_id, 'BOTH') whose two "
        "client-side /price calls map BUY -> .ask and SELL -> .bid inverted "
        "(V12b) - so spread_value comes out -0.01, not +0.01 "
        "(REQUER-HUMANO item 138: fix via (i) corrected mapping or (ii) "
        "/spread; XPASS forces the owner flip)"
    ),
)
async def test_get_spread_resolves_spread(monkeypatch):
    """get_spread (market_analysis.py:300-334) must resolve to a POSITIVE
    spread with bid/ask in the real semantics (BUY = best bid, SELL = best
    ask): spread_value = ask - bid = +0.01 for the synthetic book. Today the
    code assigns the two /price results inverted (BUY -> .ask, SELL ->
    .bid; market_analysis.py:224-230), so the fake's payload produces
    bid=0.53, ask=0.52 and spread_value = -0.01 - the assert below fails
    (proof of the bug); XPASS after the item 138 fix forces the owner flip
    (strict).

    The fake raises the live-proven "Invalid side" (HTTP 400 body) if any
    implementation sends side=BOTH to the wire - the fix-honesty guard.
    """
    fake = _FakeClob()
    monkeypatch.setattr(market_analysis, "_fetch_clob_api", fake)

    result = await market_analysis.get_spread("tok")

    assert result["spread_value"] == pytest.approx(0.01)
    assert result["bid"] == pytest.approx(0.52)  # BUY = best bid (real semantics)
    assert result["ask"] == pytest.approx(0.53)  # SELL = best ask (real semantics)


# ---------------------------------------------------------------------------
# Live integration greens - the REAL /spread and /midpoint wire contract
# (marked integration ONLY; transport guard never fails the suite for infra)
# ---------------------------------------------------------------------------
def _skip_on_transport(exc, label):
    """Network guard: infra failures SKIP (never fail the suite for infra)."""
    pytest.skip(f"{label} unreachable ({type(exc).__name__}: {exc})")


def _check_response(response, label):
    """Fail-closed response check: 5xx is an API-side outage (documented
    skip); any other non-200 is a live-contract violation (FAIL)."""
    if response.status_code >= 500:
        pytest.skip(f"{label}: live API outage (HTTP {response.status_code})")
    assert response.status_code == 200, f"{label}: expected HTTP 200, got {response.status_code}"


async def _derive_live_token(client):
    """Harvest the CLOB token id LIVE from the gamma feed - never a literal
    (a 64-hex constant in this file would pin a volatile token; the suite
    must follow the live market). Skip is reserved for degenerate feed
    slices (infra-ish), never for a contract violation."""
    try:
        response = await client.get(f"{GAMMA_API_URL}/markets", params={"limit": 1})
    except (httpx.HTTPError, OSError) as exc:
        _skip_on_transport(exc, "gamma /markets")
    _check_response(response, "gamma /markets")
    markets = response.json()
    assert isinstance(markets, list) and markets, "gamma /markets returned no markets"
    raw = markets[0].get("clobTokenIds")
    try:
        token_id = json.loads(raw)[0]
    except (json.JSONDecodeError, TypeError, IndexError):
        pytest.skip(
            "gamma /markets: top market without a parseable clobTokenIds (degenerate slice)"
        )
    if not isinstance(token_id, str) or not token_id:
        pytest.skip("gamma /markets: top market without a usable token id (degenerate slice)")
    return token_id


@pytest.mark.integration
async def test_wire_spread_endpoint_returns_decimal_string():
    """Live pin of the /spread wire truth (proven first-hand 2026-09-20):
    GET {CLOB_API_URL}/spread?token_id=<tok> answers HTTP 200 with a body
    whose "spread" value is decimal-parseable and within the [0, 1] price
    domain. The token is derived live from the gamma feed (never a
    literal). Observed body today: {"spread":"0.001"} - a decimal STRING;
    the assertion pins parseability and range, never the magnitude."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_id = await _derive_live_token(client)
        try:
            response = await client.get(
                f"{CLOB_API_URL}/spread", params={"token_id": token_id}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "CLOB /spread")
    _check_response(response, "CLOB /spread")
    body = response.json()
    spread = Decimal(str(body["spread"]))
    assert 0 <= spread <= 1


@pytest.mark.integration
async def test_wire_midpoint_endpoint_returns_decimal_string():
    """Live pin of the /midpoint wire truth (proven first-hand 2026-09-20):
    GET {CLOB_API_URL}/midpoint?token_id=<tok> answers HTTP 200 with a body
    whose "mid" value is decimal-parseable and within the [0, 1] price
    domain. The token is derived live from the gamma feed (never a
    literal). Observed body today: {"mid":"0.0355"} - a decimal STRING;
    the assertion pins parseability and range, never the magnitude."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        token_id = await _derive_live_token(client)
        try:
            response = await client.get(
                f"{CLOB_API_URL}/midpoint", params={"token_id": token_id}
            )
        except (httpx.HTTPError, OSError) as exc:
            _skip_on_transport(exc, "CLOB /midpoint")
    _check_response(response, "CLOB /midpoint")
    body = response.json()
    mid = Decimal(str(body["mid"]))
    assert 0 <= mid <= 1
