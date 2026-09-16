"""Offline pin: the initialize_server failure log never carries key material.

P2 finding (L-0155, T-0061): str(ValidationError) echoes a truncated copy of
a malformed POLYGON_PRIVATE_KEY (pydantic 2.13.5: two ~23-hex-char runs
around an ellipsis = 184 bits) and the except clause of initialize_server
logged that rendering verbatim into the server log. The fix redacts hex runs
of 16+ chars AT THE LOG SITE ONLY: the exception object itself is untouched
and still re-raised by identity (pinned by test_server_lifecycle_offline.py,
whose plain-ValueError pin stays green because non-hex messages pass through
byte-identically).

Scope: the single initialize_server funnel (the except clause). Other error
logs (discover / tool-call / shutdown) are out of scope; the R8 sites
(server.py debug logs of api_key[:8]) belong to a separate human-owned fix.
Residual declared: the re-raised ValidationError still carries the echo in
its own str() - the stderr traceback surface is out of scope of this slice.

Anti-fix probes (report evidence, outside acceptance):
- M1: call-site reverted to plain {e} -> the integration pin fails with the
  23-char echo runs found in the log;
- M2: _safe_error_message turned into a pass-through -> the unit redact pins
  and the integration pin fail;
- M3: threshold 16 -> 32 -> the 23-char echo runs survive -> the integration
  pin fails; the 15/16 boundary pin catches drift at exactly 16.
"""
import logging
import re

import pytest
from pydantic import ValidationError

from polymarket_mcp import server as server_module
from polymarket_mcp.config import PolymarketConfig

SERVER_LOGGER = "polymarket_mcp.server"


def _invalid_hex_key_error() -> ValidationError:
    """A realistic 64-char key with one typo ('g') raises ValidationError.

    Mirrors test_tiny_gaps_offline.make_config (hermetic, _env_file=None):
    valid address, invalid-hex key. The pydantic render echoes the key
    truncated to two ~23-hex-char runs - the exact leak class (probed on
    pydantic 2.13.5: input_value='g73b...b0c1d' with runs of 23 and 23).
    """
    key = "g" + "b73b1c5c0f1c78b7a91f2e0a8c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d"[1:]
    with pytest.raises(ValidationError) as excinfo:
        PolymarketConfig(
            _env_file=None,
            POLYGON_PRIVATE_KEY=key,
            POLYGON_ADDRESS="0x" + "a" * 40,
        )
    return excinfo.value


async def test_plain_exception_message_logged_verbatim(monkeypatch, caplog):
    """Non-hex exception messages pass through byte-identically.

    Compat pin (dual-trava with test_server_lifecycle_offline.py:866): the
    except clause keeps the exact f-string shape, so a plain load_config
    failure is logged as "Failed to initialize server: <message>" with no
    transformation. If this pin breaks, the sanitizer changed the plain path.
    """
    error = ValueError("invalid configuration")

    def _raise():
        raise error

    monkeypatch.setattr(server_module, "load_config", _raise)
    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        with pytest.raises(ValueError, match="invalid configuration"):
            await server_module.initialize_server()

    assert any(
        record.message == "Failed to initialize server: invalid configuration"
        for record in caplog.records
    )


async def test_validation_error_hex_echo_redacted_in_log(monkeypatch, caplog):
    """A malformed key never reaches the error log as key material.

    The real ValidationError still echoes the truncated key (asserted as a
    fail-loud precondition - if pydantic stops echoing, this pin would be
    vacuous), but the LOGGED message carries zero hex runs of 16+ chars.
    The exception object is re-raised by identity (compat with the lifecycle
    re-raise pin) and the diagnostic branch message survives.
    """
    error = _invalid_hex_key_error()
    rendered = str(error)
    echo_fragments = re.findall(r"[0-9a-fA-F]{16,}", rendered)
    assert echo_fragments, (
        "precondition: pydantic 2.13.5 echoes the input_value; if this fails "
        "the pin is vacuous and must be re-derived"
    )

    def _raise():
        raise error

    monkeypatch.setattr(server_module, "load_config", _raise)
    with caplog.at_level(logging.ERROR, logger=SERVER_LOGGER):
        with pytest.raises(ValidationError) as reexcinfo:
            await server_module.initialize_server()

    assert reexcinfo.value is error, "the original exception object is re-raised"
    (record,) = [
        record
        for record in caplog.records
        if record.message.startswith("Failed to initialize server: ")
    ]
    message = record.message
    assert "must be valid hex" in message, "the branch diagnostic survives"
    assert re.search(r"[0-9a-fA-F]{16,}", message) is None, (
        "no hex run of 16+ chars in the logged message"
    )
    for fragment in echo_fragments:
        assert fragment not in message, "no key-echo fragment in the log"


def test_safe_error_message_passes_plain_text_through():
    """A message without long hex runs is returned byte-identically."""
    from polymarket_mcp.server import _safe_error_message

    class _Boom(ValueError):
        pass

    assert (
        _safe_error_message(_Boom("Connection refused (os error 61)"))
        == "Connection refused (os error 61)"
    )


def test_safe_error_message_redacts_hex_runs_and_preserves_context():
    """Hex runs of 16+ chars are redacted; a 15-char run and uuid-style
    short segments pass through; the surrounding text survives byte-exactly."""
    from polymarket_mcp.server import _safe_error_message

    key_64 = "ab" * 32
    out = _safe_error_message(ValueError("key=%s end" % key_64))
    assert out == "key=[REDACTED:64 hex chars] end"
    assert key_64 not in out

    run_23 = "73b1c5c0f1c78b7a91f2e0a"
    out = _safe_error_message(ValueError("input_value='%s...'" % run_23))
    assert out == "input_value='[REDACTED:23 hex chars]...'"

    run_16 = "a" * 16
    out = _safe_error_message(ValueError("tok %s ." % run_16))
    assert out == "tok [REDACTED:16 hex chars] ."

    run_15 = "f" * 15
    out = _safe_error_message(ValueError("short %s kept" % run_15))
    assert out == "short %s kept" % run_15, "15-hex runs pass through (boundary)"

    out = _safe_error_message(
        ValueError("uuid 4b3a2c1d-9e8f-47a1-b2c3-d4e5f6a7b8c9 ok")
    )
    assert out == "uuid 4b3a2c1d-9e8f-47a1-b2c3-d4e5f6a7b8c9 ok", (
        "uuid-style short hex segments pass through"
    )
