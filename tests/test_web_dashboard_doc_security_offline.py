"""
Offline doc-security contract suite for WEB_DASHBOARD.md.

T-0248 — doc-security alignment: the doc taught a STALE `start()` signature
with a hardcoded 0.0.0.0 default and a dev command that exposes the
no-authentication dashboard beyond loopback (`POST /api/config` can rewrite
the trading safety limits — whoever reaches the port controls the trading
configuration).

SOURCE OF TRUTH IS THE CODE (L-0020 — code is the observable source, not
comments, not docs): src/polymarket_mcp/web/app.py `start()` is defined as
`def start(host: str | None = None, port: int | None = None)` and binds to
loopback by default — `host or os.getenv("WEB_HOST", "127.0.0.1")` — logging
a warning when bound off loopback (`if host not in ("127.0.0.1", "localhost",
"::1"): logger.warning(...)`). The doc must mirror the OBSERVED code, never
the idealized behavior.

House patterns:
- L-0056/L-0079: negations are ALWAYS paired with a positive sister assertion
  in the same test (a missing/unreadable doc fails LOUD on the positive arm
  and can never flip a negation into a silent pass).
- L-0070: content anchors, no fragile line numbers.
- P-0056: acceptance runs as
  `env PYTHONPATH=src .venv/bin/python -m pytest ...`.

Scope note (declared): the `host="0.0.0.0"` inside the "Enable HTTPS"
production block REMAINS by design (production with TLS is legitimate) and
now carries a no-authentication warning. The negations below are therefore
SURGICAL to the dev command and the snippet signature — they must never match
the production HTTPS block.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "WEB_DASHBOARD.md"

DEV_COMMAND = (
    "uvicorn polymarket_mcp.web.app:app --reload --host 127.0.0.1 --port 8080"
)
REAL_SIGNATURE = "def start(host: str | None = None, port: int | None = None):"
STALE_SIGNATURE = 'def start(host: str = "0.0.0.0"'
DEV_HOST_EXPOSED = "--reload --host 0.0.0.0"
REMEDY_CORE = "pip install fastapi uvicorn jinja2"
REMEDY_PARTIAL = "pip install pytest pytest-asyncio httpx"


def _doc_text() -> str:
    """Read the doc with a fail-loud guard (L-0056: negations need a proven file)."""
    text = DOC.read_text(encoding="utf-8")
    assert text.strip(), (
        f"{DOC} is empty or unreadable — doc-security contract cannot be judged"
    )
    return text


def test_dev_command_binds_loopback() -> None:
    """The development command must bind 127.0.0.1 and never teach 0.0.0.0."""
    text = _doc_text()
    # POS: the exact loopback-bound dev command is present.
    assert DEV_COMMAND in text, (
        "WEB_DASHBOARD.md must contain the loopback-bound dev command "
        f"{DEV_COMMAND!r} (matches the code's loopback default, app.py start())"
    )
    # NEG (paired with the POS above, L-0056/L-0079): the dev command must not
    # expose the dashboard off loopback. Surgical pattern — the "Enable HTTPS"
    # production block legitimately keeps host="0.0.0.0" (without --reload).
    assert DEV_HOST_EXPOSED not in text, (
        "WEB_DASHBOARD.md must not teach binding the no-auth dashboard to "
        f"0.0.0.0 via a dev command ({DEV_HOST_EXPOSED!r} found)"
    )
    # Also assert the NO-AUTH note accompanies the dev command (in-design).
    assert "the dashboard has no authentication" in text, (
        "the dev command must be followed by the no-authentication note "
        "explaining why loopback is kept"
    )


def test_snippet_matches_real_signature() -> None:
    """The 'Custom Host and Port' snippet must mirror the real start() signature."""
    text = _doc_text()
    # POS: the snippet mirrors the REAL signature (str | None defaults).
    assert REAL_SIGNATURE in text, (
        "WEB_DASHBOARD.md must show the real start() signature: "
        f"{REAL_SIGNATURE!r}"
    )
    # NEG (paired, L-0056/L-0079): the stale 0.0.0.0-default signature is gone.
    assert STALE_SIGNATURE not in text, (
        "WEB_DASHBOARD.md must not show the stale signature "
        f"{STALE_SIGNATURE!r} (the real default is None -> 127.0.0.1)"
    )
    # POS: the WEB_HOST env override is documented (the code reads it).
    assert "WEB_HOST" in text, (
        "WEB_DASHBOARD.md must document WEB_HOST as the override mechanism"
    )


def test_no_auth_warnings_present() -> None:
    """No-authentication warnings must appear at the dev command and the HTTPS block."""
    text = _doc_text()
    # POS: "no authentication" appears at least twice (dev-command note and
    # the Enable HTTPS warning block).
    count = text.count("no authentication")
    assert count >= 2, (
        "WEB_DASHBOARD.md must warn about the missing authentication at least "
        f"twice (dev command note + HTTPS block); found {count}"
    )


def test_remedies_use_editable_install() -> None:
    """Remedies install from the project (extras), not ad-hoc package lists."""
    text = _doc_text()
    # POS first (guarantee the file we negate against is the right one).
    assert text.count("pip install -e .") >= 2, (
        "WEB_DASHBOARD.md must use `pip install -e .` at least twice "
        "(installation section + troubleshooting remedy); found "
        f"{text.count('pip install -e .')}"
    )
    assert 'pip install -e ".[dev]"' in text, (
        "WEB_DASHBOARD.md must use `pip install -e \".[dev]\"` for test deps "
        "(pytest/pytest-asyncio/httpx live in the dev extras, pyproject.toml)"
    )
    # NEG (paired, L-0056/L-0079): partial ad-hoc remedies are gone.
    assert REMEDY_CORE not in text, (
        "WEB_DASHBOARD.md must not list core deps ad-hoc "
        f"({REMEDY_CORE!r} found) — `pip install -e .` already covers them"
    )
    assert REMEDY_PARTIAL not in text, (
        "WEB_DASHBOARD.md must not list test deps ad-hoc "
        f"({REMEDY_PARTIAL!r} found) — `pip install -e \".[dev]\"` covers them"
    )


def test_loopback_default_documented() -> None:
    """The snippet note must document the real 127.0.0.1 default."""
    text = _doc_text()
    # POS: the snippet's note explicitly names the default (content anchor).
    assert "(default `127.0.0.1`)" in text, (
        "WEB_DASHBOARD.md must state that start() reads WEB_HOST with "
        "default 127.0.0.1"
    )
    # POS: the loopback address appears at least twice in the doc (snippet
    # note + dev command/note) — paired context for L-0056 negations elsewhere.
    count = text.count("127.0.0.1")
    assert count >= 2, (
        "WEB_DASHBOARD.md must reference the loopback default at least twice; "
        f"found {count}"
    )
