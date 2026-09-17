"""Offline suite: WEBSOCKET_INTEGRATION.md Testing block + open_config.sh entry name.

Bugs under test (proven live on main 35fce9e -- mission increment 33 probes,
re-proven by the curator on 35fce9e in increment 56):

1. WEBSOCKET_INTEGRATION.md ("Testing" block) taught THREE live-only commands
   as if they were the routine offline workflow:

   - bare ``pytest tests/test_websocket.py -v`` -- the whole file carries
     ``pytestmark = pytest.mark.integration`` (tests/test_websocket.py:23),
     so the bare command runs 13 LIVE tests (real network) by default;
   - ``-m "not slow"`` -- runs 12 LIVE tests (the "Skip slow integration
     tests" label suggests skipping the live part; it skips only the single
     ``@pytest.mark.slow`` test, tests/test_websocket.py:492);
   - ``-m "slow"`` -- runs exactly 1 live-slow test.

   A user following the doc consumes real network/API budget while believing
   they run the offline suite. Fix: the block now shows the canonical offline
   selection (default gate: ``not integration and not slow and not real_api
   and not performance``) and the live tier EXPLICITLY labeled as network
   required (``-m "integration"``).

2. open_config.sh:13 instructed the user to find the section
   'polymarket-trading' but install.sh:366 writes ``"polymarket"`` -- the user
   searches for a section that does not exist. Fix: the instruction names the
   real entry ('polymarket').

Preservation pins (must stay identical pre/post fix):
- WEBSOCKET_INTEGRATION.md:39 ``Server("polymarket-trading")`` is the Server
  name of the PROTOCOL, consistent with server.py:79 -- NOT the Claude
  Desktop config entry; it must NOT be touched by the entry-name fix.
- WEBSOCKET_INTEGRATION.md:391 explanatory paragraph (offline layer +
  default gate selection) stays intact.

House rules applied:
- Item 147b: explicit ``read_text(encoding="utf-8")`` (the doc contains
  non-ASCII punctuation; open_config.sh contains emoji) -- no locale drift.
- L-0056: every negation is paired with a positive presence assertion.
- L-0070: assertions anchor on CONTENT (exact literals), never line numbers.
- Pure text tests: no network, no disk writes -- offline by design (this
  suite is itself part of the offline gate selection it pins).
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "WEBSOCKET_INTEGRATION.md"
OPEN_CONFIG = REPO_ROOT / "open_config.sh"

LIVE_BARE = "pytest tests/test_websocket.py -v"
LIVE_EXPLICIT = 'pytest tests/test_websocket.py -m "integration"'
OFFLINE_SELECTION = (
    "not integration and not slow and not real_api and not performance"
)
SERVER_NAME_PROTOCOL = 'Server("polymarket-trading")'
FAKES_PIN = "covers the same manager logic with fakes"
WRONG_ENTRY = "polymarket-trading"
CORRECT_ENTRY = "'polymarket'"


def test_no_live_only_commands():
    """The bare live-only command (`... -v`) is gone from the Testing block."""
    content = DOC.read_text(encoding="utf-8")
    assert LIVE_BARE not in content, (
        "WEBSOCKET_INTEGRATION.md still teaches `pytest tests/test_websocket.py "
        '-v` as routine -- the file is entirely integration-marked '
        "(tests/test_websocket.py:23), so it runs 13 LIVE tests (real network) "
        "by default"
    )


def test_live_explicit_and_canonical_selection():
    """Live tier is explicit (`-m "integration"`); offline selection present twice."""
    content = DOC.read_text(encoding="utf-8")
    # The live command is explicit and labeled (paired positive, L-0056).
    assert content.count(LIVE_EXPLICIT) == 1, (
        'WEBSOCKET_INTEGRATION.md must teach the live tier exactly once as '
        '`pytest tests/test_websocket.py -m "integration"` (real connections, '
        "network required)"
    )
    # The canonical offline selection: the new block + the :391 paragraph
    # (preservation pin -- if the paragraph drops, the count falls to 1).
    assert content.count(OFFLINE_SELECTION) == 2, (
        "the default gate selection string must appear exactly twice: in the "
        "Testing block command and in the :391 explanatory paragraph"
    )


def test_server_name_protocol_preserved():
    """Server name of the protocol and the :391 paragraph are untouched."""
    content = DOC.read_text(encoding="utf-8")
    assert content.count(SERVER_NAME_PROTOCOL) == 1, (
        'WEBSOCKET_INTEGRATION.md:39 Server("polymarket-trading") is the '
        "Server name of the MCP protocol (server.py:79) -- the entry-name fix "
        "must not touch it"
    )
    assert content.count(FAKES_PIN) == 1, (
        "the :391 explanatory paragraph (offline layer covers the same manager "
        "logic with fakes) must stay intact"
    )


def test_open_config_entry_name():
    """open_config.sh names the real config entry written by install.sh:366."""
    content = OPEN_CONFIG.read_text(encoding="utf-8")
    assert WRONG_ENTRY not in content, (
        "open_config.sh still instructs the user to find the section "
        f"'{WRONG_ENTRY}' -- install.sh:366 writes \"polymarket\""
    )
    # Paired positive (L-0056): the corrected quoted entry is present exactly
    # once (the pre-fix form `'polymarket-trading'` does NOT match this
    # substring, so the pair is discriminating in both directions).
    assert content.count(CORRECT_ENTRY) == 1, (
        "open_config.sh must instruct exactly one 'polymarket' entry name, "
        "matching install.sh:366"
    )
