"""Shared 429-note helpers for the rate-limiter backoff wiring.

Single canonical implementation of the two 429 note helpers that the
429-backoff fatias duplicated per module (the parallel-slices decision of
increment 75 landed 7 byte-identical copies in 5 files; this consolidation
is the declared L-0073 follow-up). Per-module delegates keep the helper
NAME and SIGNATURE, so call sites and the wired 429 suites are untouched.

Both helpers are intentionally LOUD-NOOP on everything that is not a real
429: ``status_code`` is read via ``getattr`` with default ``None`` so stub
responses/exceptions without the attribute (the offline suites' fakes) are
untouched - they never report 429, so no backoff is armed and nothing can
AttributeError. The ``Retry-After`` clamp lives in
``RateLimiter.handle_429_error`` (never here).
"""
from typing import Any, Optional


async def note_http_429(rate_limiter: Any, response: Any, category: Any) -> None:
    """Record an HTTP 429 on the rate limiter so the NEXT acquire() waits.

    Wiring for the previously-dead 429 path: ``RateLimiter.handle_429_error``
    had ZERO callers in src/ (grep-proven), so a real 429 from the wire armed
    no backoff and immediate retries hammered the API. Called right before
    ``raise_for_status()``: on a 429 it arms the exponential backoff (or the
    server's ``Retry-After``) and the existing raise/return path proceeds
    UNCHANGED, so the error-envelope pins of the offline suites hold.

    ``status_code`` is read via getattr with default None so stub responses
    without the attribute (the offline suites' fakes) are untouched: they
    never report 429, so no backoff is armed and nothing can AttributeError.
    """
    if getattr(response, "status_code", None) != 429:
        return
    headers = getattr(response, "headers", None)
    retry_after: Optional[int] = None
    if headers is not None:
        raw = headers.get("retry-after")
        if raw is not None and str(raw).strip().isdigit():
            retry_after = int(raw)
    await rate_limiter.handle_429_error(category, retry_after)


async def note_clob_429(rate_limiter: Any, exc: BaseException, category: Any) -> None:
    """Record a CLOB 429 on the rate limiter so the NEXT acquire() waits.

    Wiring for the PolyApiException surfaces: py_clob_client raises
    PolyApiException carrying ``status_code`` from the wire response. A real
    429 from the CLOB armed no backoff (``handle_429_error`` had ZERO callers
    in src/, grep-proven) and immediate retries hammered the API. The error
    envelope is returned UNCHANGED, so the offline envelope pins hold.
    PolyApiException does not expose response headers, so the exponential
    default is used (the Retry-After clamp lives in
    ``RateLimiter.handle_429_error``); ``category`` matches the acquire()
    that preceded the failing call.
    """
    if getattr(exc, "status_code", None) != 429:
        return
    await rate_limiter.handle_429_error(category, None)
