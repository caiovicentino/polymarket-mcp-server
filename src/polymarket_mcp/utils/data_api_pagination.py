"""Pagination for the Polymarket Data-API list endpoints.

Wire contract (probed live 2026-09-18): ``data-api.polymarket.com``
positions/trades/activity PAGINATE with ``limit`` + ``offset``. A call
without ``limit`` returns the default page (100 rows -- probed: 7/8 sampled
wallets returned exactly 100); a call WITH ``limit`` caps at 500 rows per
call (proven: ``limit=1000``/``limit=2000`` -> 500). Callers that fetch a
single page silently truncate everything beyond it: a wallet with 2,022
positions reports only the first 100 (or 500), so portfolio valuation and
P&L are computed over a TRUNCATED book for active wallets.

``fetch_all_pages`` keeps the FIRST request byte-identical to the pre-fix
call (``params`` are never modified), so existing call-shape pins hold;
follow-up pages are requested ONLY when the first page is full.

Guards against offset-ignoring servers/stubs: a follow-up page whose first
row equals the previous page's first row (no progress) stops the loop, as
does ``max_pages``. Pages are fetched inside the rate-limiter window the
caller already acquired (one acquire per tool call, unchanged).

Out-of-scope sites (user-capped semantics, intentionally single-page):
``get_position_details`` trades (limit=10 is the user's cap),
``get_trade_history`` (min(limit, 500)) and ``get_activity_log``
(min(limit, 500)) -- the limit there is a USER cap, not a page size.
"""
from typing import Any, Dict, List

import httpx

MAX_PAGES = 50


async def fetch_all_pages(
    client: httpx.AsyncClient,
    url: str,
    params: Dict[str, Any],
    timeout: float = 10.0,
    default_page_size: int = 100,
    max_pages: int = MAX_PAGES,
) -> List[Dict[str, Any]]:
    """Fetch every page of a Data-API list endpoint.

    The first GET uses ``params`` UNCHANGED (byte-identical to the pre-fix
    call). The page cap is ``params["limit"]`` when present (the caller's
    explicit cap, e.g. 500) or ``default_page_size`` (the wire default of
    100) otherwise. A short first page (fewer rows than the cap) means the
    total fits in one page and NO follow-up call is made.

    Raises whatever the underlying ``client.get``/``raise_for_status``
    raise (httpx.HTTPStatusError on non-2xx), unchanged.
    """
    response = await client.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    rows: List[Dict[str, Any]] = response.json()

    cap = int(params["limit"]) if "limit" in params else default_page_size
    if not rows or len(rows) < cap:
        return rows

    fetched = list(rows)
    prev_first = rows[0]
    for _ in range(max_pages):
        page_params = dict(params)
        page_params["limit"] = cap
        page_params["offset"] = len(fetched)
        resp = await client.get(url, params=page_params, timeout=timeout)
        resp.raise_for_status()
        page: List[Dict[str, Any]] = resp.json()
        if not page:
            break
        if page[0] == prev_first:
            # The wire ignored the offset (no progress) -- stop instead of
            # looping forever against pathological servers/stubs.
            break
        prev_first = page[0]
        fetched = fetched + page
        if len(page) < cap:
            break
    return fetched
