"""Offline pins for .pre-commit-config.yaml hook correctness.

Two defects pinned here (both proved pre-fix):

1. The local `pytest-fast` hook selected `-m "not integration and not slow and
   not real_api"` WITHOUT excluding the `performance` tier - so every commit
   ran 13 live-API benchmark tests (network access, 30 s per-test timeout)
   that the canonical offline selection excludes everywhere else.
2. The `check-imports` hook printed a non-ASCII checkmark (U+2705), which
   raises UnicodeEncodeError on Windows consoles using cp1252 (item 156
   class) - the hook fails on every commit for Windows contributors.

The pins are content-level (the hook config is parsed and asserted); the live
hook behavior itself is verified by pre-commit on the contributor machine.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".pre-commit-config.yaml"

CANONICAL_ARG = "not integration and not slow and not real_api and not performance"
STALE_ARG = "not integration and not slow and not real_api"


def _hooks() -> dict[str, dict]:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    hooks: dict[str, dict] = {}
    for repo in data["repos"]:
        for hook in repo.get("hooks", []):
            hooks[hook["id"]] = hook
    return hooks


def test_pytest_fast_hook_still_registered():
    """Mirrors tests/test_root_scripts_hygiene_offline.py - the local hook must survive edits."""
    assert "pytest-fast" in _hooks(), "pytest-fast hook removed by the fix"


def test_pytest_fast_excludes_performance_tier():
    """The 'fast' hook must select the same tier as the canonical offline selection."""
    args = _hooks()["pytest-fast"]["args"]
    assert CANONICAL_ARG in args, (
        f"pytest-fast args {args!r} do not exclude the performance tier "
        "(13 live-API benchmarks would run on every commit)"
    )


def test_pytest_fast_stale_selection_fully_gone():
    """Paired negation: the old 3-tier selection as a COMPLETE arg value is absent."""
    args = _hooks()["pytest-fast"]["args"]
    assert STALE_ARG not in args, (
        "old selection (without 'and not performance') still present as a full arg"
    )


def test_check_imports_hook_print_is_ascii_only():
    """U+2705 raises UnicodeEncodeError on cp1252 Windows consoles - print must be ASCII."""
    hook = _hooks()["check-imports"]
    code = next(a for a in hook["args"] if "polymarket_mcp" in a)
    assert code.isascii(), "check-imports print contains non-ASCII (Windows cp1252 breaks)"


def test_check_imports_hook_still_imports_server():
    hook = _hooks()["check-imports"]
    code = next(a for a in hook["args"] if "polymarket_mcp" in a)
    assert "from polymarket_mcp import server" in code, "import check scope changed (over-fix)"


def test_mypy_hook_still_excludes_tests():
    """Regression guard: mypy runs on src/ only (item 96 documents 28 type errors in tests/)."""
    assert _hooks()["mypy"].get("exclude") == "^tests/", "mypy hook exclusion changed"


def test_no_print_statements_hook_intact():
    hook = _hooks()["no-print-statements"]
    assert hook["entry"] == "print\\(", "no-print-statements hook changed"


def test_config_file_is_ascii_only():
    text = CONFIG.read_text(encoding="utf-8")
    assert text.isascii(), ".pre-commit-config.yaml must stay ASCII-only after the fix"
