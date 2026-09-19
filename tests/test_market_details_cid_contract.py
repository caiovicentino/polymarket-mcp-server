"""Contract suite for get_market_details(condition_id=...) -- the V-CID wire
contract (REQUER-HUMANO item 154).

Finding proven live first-hand (curator preflight 2026-09-18; gamma-api
stateless public endpoints):

1. ``GET /markets?condition_id=<cid>`` (the parameter the code sends,
   market_analysis.py:159) is SILENTLY IGNORED by the wire: the response is
   the UNFILTERED default listing (proven with a real cid that is NOT the
   default first market: n=20, first="Xi Jinping out before 2027?").
   ``get_market_details`` collapses the list (``data[0]``) => the tool
   returns an ARBITRARY, UNRELATED market for ANY condition_id query (P1,
   user-facing: the tool confidently answers the WRONG market).
2. ``GET /markets?condition_ids=<cid>`` (plural) IS the real filter: the
   exact single market (proven: n=1, conditionId matches).
3. ``GET /markets/<numeric-id>`` (the market_id branch) works (proven 200
   with the exact market) -- out of scope of this suite.

This suite pins the REAL contract as xfail(strict=True) (the flip contract
for the human fix -- precedent R3/T-0261) plus live integration greens
pinning the wire routes. Known flip target when the fix lands:
tests/test_market_analysis_offline.py:372 pins the SINGULAR param name
(``{"condition_id": "cond-1"}``) -- the fix flips it (item 154).

The offline fake models the REAL wire (the discriminating behavior), not
the code's expectation: with ``condition_id`` the fake returns the default
listing; with ``condition_ids`` the fake returns the exact market.
"""

import httpx
import pytest

from polymarket_mcp.tools import market_analysis

# Real condition id (AOC 2028 Dem nomination) -- probed live; NOT the default
# first market of the unfiltered listing, so the bug is observable.
TARGET_CID = "0xe6bcc2f1dd025ce5e1833190f7c60a71171c94f805df55b9ab0ded695ec93565"
TARGET_QUESTION = "Will Alexandria Ocasio-Cortez win the 2028 Democratic presidential nomination?"
DEFAULT_FIRST_QUESTION = "Xi Jinping out before 2027?"
GAMMA_URL = "https://gamma-api.polymarket.com"


class _FakeGammaWire:
    """Models the REAL gamma /markets wire behavior (probed 2026-09-18).

    - params {"condition_id": X}  -> IGNORED: returns the default listing
      (first item is the default first market, NOT the queried cid).
    - params {"condition_ids": X} -> the REAL filter: the exact single
      market for a known cid; [] for unknown cids (proven).
    - path /markets/<id>          -> dict with the exact market for the
      known numeric id (the market_id branch works -- out of scope here).
    """

    DEFAULT_LISTING = [
        {
            "id": "559651",
            "question": DEFAULT_FIRST_QUESTION,
            "conditionId": "0xa467b14d51f01b957109d9cbb1d6c124fab2a089d52ed8f471d23c2812e743b7",
        }
    ]
    TARGET = {
        "id": "559653",
        "question": TARGET_QUESTION,
        "conditionId": TARGET_CID,
    }

    def __init__(self):
        self.calls = []

    async def __call__(self, endpoint, params=None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        if endpoint == "/markets":
            if "condition_ids" in params:
                cid = params["condition_ids"]
                if cid == TARGET_CID:
                    return [dict(self.TARGET)]
                return []
            # "condition_id" (singular) is IGNORED by the real wire: the
            # unfiltered default listing comes back either way.
            return [dict(m) for m in self.DEFAULT_LISTING]
        raise AssertionError(f"unexpected endpoint {endpoint!r}")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "V-CID: GET /markets?condition_id=<cid> is silently ignored by the "
        "wire (proven live); get_market_details(condition_id=...) collapses "
        "data[0] of the UNFILTERED listing => an arbitrary WRONG market for "
        "any condition_id query. Fix = query condition_ids (plural), the "
        "real filter (REQUER-HUMANO item 154)."
    ),
)
async def test_get_market_details_by_condition_id_returns_the_queried_market(monkeypatch):
    """The CORRECT behavior: condition_id resolves to the queried market."""
    fake = _FakeGammaWire()
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", fake)

    result = await market_analysis.get_market_details(condition_id=TARGET_CID)

    # With the fix the tool must return the market the user asked for.
    assert result["conditionId"] == TARGET_CID
    assert result["question"] == TARGET_QUESTION


async def test_condition_id_param_is_ignored_by_the_wire_documented(monkeypatch):
    """Documents the OBSERVED bug as the fake's contract (green today).

    This test is the negative-image of the xfail above: it pins that the
    fake models the real wire (condition_id ignored) so the xfail pin above
    cannot be satisfied by a fixture that silently 'fixes' the fake.
    """
    fake = _FakeGammaWire()
    monkeypatch.setattr(market_analysis, "_fetch_gamma_api", fake)

    result = await market_analysis.get_market_details(condition_id=TARGET_CID)

    # The BUGGED observable: the default listing's first market comes back.
    assert result["question"] == DEFAULT_FIRST_QUESTION
    assert fake.calls == [("/markets", {"condition_id": TARGET_CID})]


@pytest.mark.integration
@pytest.mark.real_api
async def test_live_condition_ids_is_the_real_filter():
    """Live: GET /markets?condition_ids=<cid> returns the exact market."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{GAMMA_URL}/markets", params={"condition_ids": TARGET_CID}
        )
        response.raise_for_status()
        rows = response.json()
    assert len(rows) == 1
    assert rows[0]["conditionId"].lower() == TARGET_CID
    assert rows[0]["question"] == TARGET_QUESTION


@pytest.mark.integration
@pytest.mark.real_api
async def test_live_condition_id_param_is_ignored():
    """Live: GET /markets?condition_id=<cid> returns the unfiltered listing."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(
            f"{GAMMA_URL}/markets", params={"condition_id": TARGET_CID}
        )
        response.raise_for_status()
        rows = response.json()
    assert len(rows) > 1
    assert rows[0]["question"] != TARGET_QUESTION
