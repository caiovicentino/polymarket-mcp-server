"""Regression canary for the trading-critical dependency pins (M-7).

Why this exists (R-14/R-16):

- R-16: the legacy SDK ``py_clob_client`` 0.34.6 is ARCHIVED (no upstream
  fixes possible). Its Signer depends on the PRIVATE eth_account method
  ``Account._sign_hash`` (installed package ``py_clob_client/signer.py:22``;
  instantiated at ``py_clob_client/client.py:142`` and used on every L1/L2
  path: ``create_level_1_headers`` at ``headers/headers.py:16`` and
  ``create_level_2_headers`` at ``headers/headers.py:37``). eth-account
  release notes prove the pattern of REMOVING private APIs (0.13.0 dropped
  ``signHash`` and ``encode_structured_data``). An accidental bump to
  ``>=0.15`` would silently break L1/L2 order signing and L1 auth.
- R-14: ``pip install mcp`` today resolves to 2.2.0 -- the 2.x line removes
  the decorator API on Server (``@server.list_tools`` etc.) this server is
  built on; the 1.x line is security-fixes-only (latest 1.x = 1.30.0). The
  old floor-only pin ``mcp>=1.0.0,<2.0.0`` did NOT prevent accidental MINOR
  jumps inside 1.x/2.x resolution space.

Regression canary (not a presence check): failing loudly IS the correct
behavior when the API disappears or the installed version leaves the pinned
range (M-7, lessons L-0030/L-0094: the oracle knows how to fail). There is
NO tolerant behavior here -- no try/except swallowing, no skips.

Oracle (documented invariants):

- Test A fails when ``Account._sign_hash`` disappears (eth-account >= 0.15).
- Test B fails when the legacy ``py_clob_client.signer`` import combo breaks.
- Test C fails when the installed version leaves the pinned range.
- Test D fails when the exact pins leave ``pyproject.toml`` (double
  protection for the contract acceptance greps, L-0002).

ASCII-only by policy; stdlib-only imports (no POSIX-only modules) so the
canary runs on every runner/OS.
"""

import importlib.metadata
import re
from pathlib import Path

import pytest
from eth_account import Account


def _version_tuple(package: str) -> tuple[int, int, int]:
    raw = importlib.metadata.version(package)
    parts = raw.split(".")
    if len(parts) < 3 or any(not part.isdigit() for part in parts[:3]):
        pytest.fail(
            f"Unexpected version format for {package!r}: {raw!r} "
            "(M-7 canary: installed version could not be parsed as x.y.z)"
        )
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def test_account_sign_hash_private_api_present() -> None:
    """R-16: ``Account._sign_hash`` is the private API the archived legacy
    SDK Signer (py_clob_client 0.34.6) depends on for EVERY L1/L2 signature
    and L1 auth. Its removal is a silent break of the money path."""
    assert hasattr(Account, "_sign_hash"), (
        "Account._sign_hash disappeared (eth-account >= 0.15 is likely "
        "installed). R-16: the archived legacy SDK Signer "
        "(py_clob_client.signer) depends on this private API in every L1/L2 "
        "trading path and L1 auth -- silent break of order signing with no "
        "upstream fix possible. Failing loudly BY DESIGN (regression canary, "
        "M-7)."
    )


def test_legacy_signer_import_combo_alive() -> None:
    """R-16: the legacy combo must stay importable. The import resolves the
    module that references the private API; instantiation is NOT required
    and needs a private key -- never instantiate here."""
    from py_clob_client.signer import Signer  # noqa: F401

    assert Signer is not None, (
        "py_clob_client.signer.Signer resolved to None. R-16: the legacy "
        "Signer combo broke -- every L1/L2 trading path and L1 auth is at "
        "risk (regression canary, M-7)."
    )


def test_installed_eth_account_in_pinned_range() -> None:
    version = _version_tuple("eth-account")
    assert (0, 13, 6) <= version < (0, 15, 0), (
        f"installed eth-account {version} is outside the pinned range "
        '"eth-account>=0.13.6,<0.15" (M-7 pin in pyproject.toml). R-16: '
        ">=0.15 may remove Account._sign_hash -- silent break of the legacy "
        "SDK Signer on every L1/L2 path."
    )


def test_installed_mcp_in_pinned_range() -> None:
    version = _version_tuple("mcp")
    assert (1, 28, 0) <= version < (1, 31, 0), (
        f"installed mcp {version} is outside the pinned range "
        '"mcp>=1.28.0,<1.31" (M-7 pin in pyproject.toml). R-14: the 2.x '
        "line breaks the FastMCP->MCPServer decorator API this server is "
        "built on."
    )


def test_pyproject_pins_exact() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    mcp_pin = re.search(r'"mcp>=1\.28\.0,<1\.31",', text)
    eth_pin = re.search(r'"eth-account>=0\.13\.6,<0\.15",', text)
    assert mcp_pin is not None, (
        'pyproject.toml must pin "mcp>=1.28.0,<1.31" exactly (M-7, R-14): '
        "the 2.x line breaks FastMCP->MCPServer and the 1.x line is "
        "security-fixes-only."
    )
    assert eth_pin is not None, (
        'pyproject.toml must pin "eth-account>=0.13.6,<0.15" exactly '
        "(M-7, R-16): an accidental bump to >=0.15 silently breaks the "
        "legacy SDK Signer (Account._sign_hash) on every L1/L2 trading and "
        "L1 auth path."
    )
