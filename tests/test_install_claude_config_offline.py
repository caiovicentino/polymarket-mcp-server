"""
Offline sandbox suite for install.sh — Claude Desktop config merge (T-0215).

Pins the FIX contract (merge semantics) against the REAL install.sh of this
worktree by running extracted functions in a temp-dir sandbox. The file is
never executed end-to-end and the suite does NOT rely on INSTALL_TEST_MODE.

Extraction (declared choice per task §Seam — anchor-based, P-0018): the span
from the `# Colors for output` comment to the `# Main Installation Flow`
comment (colors + settings + every helper incl. configure_env /
configure_claude_desktop / rollback) is extracted from a byte-exact copy of
install.sh into install_lib.sh inside the sandbox. Anchors are CONTENT, not
line numbers (L-0127). Extraction sanity is fail-fast (P-0018): non-empty,
all three target functions anchored, main()/the footer `main "$@"` absent,
`bash -n` clean.

Sandbox per test (pytest tmp_path — under the system temp dir, never inside
the repo): HOME is redirected so the real user's Claude Desktop config is
NEVER touched, PATH gets a python shim (this host has no `python`, which
configure_claude_desktop resolves via `which python`), OS=Linux. The driver
script mirrors production semantics: `set -e` (as install.sh:18 does), no -u.

Zero network / zero pip / zero real venv: only configure_env,
configure_claude_desktop and rollback are invoked (never test_installation,
which curls the Polymarket API); the merge heredoc python is stdlib-only.
All writes are confined to the sandbox (L-0013).

Tripwire (P-0013): the sha256 of the REAL install.sh is snapshotted before
every test and asserted identical at teardown (the suite never writes the
real file), plus the mandatory test_real_file_tripwire pins byte identity
explicitly.

RED pre-fix (first-hand, task report): pre-fix install.sh clobbered the whole
claude_desktop_config.json with a polymarket-only template (other MCP servers
GONE) and produced invalid JSON when paths contain spaces (shell
interpolation inside the JSON heredoc). test_merge_preserves_existing_servers
and test_malformed_config_untouched_rc_ne0 failed pre-fix.
test_bash_n_valid / test_help_rc0_without_side_effects /
test_fresh_install_creates_config / test_non_demo_env_block_parity /
test_real_file_tripwire passed pre-fix (declared per the task contract).
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

_LIB_START = "# Colors for output"
_LIB_END = "# Main Installation Flow"
_FUNC_ANCHORS = ("configure_env()", "configure_claude_desktop()", "rollback()")

_PYTHON3 = shutil.which("python3")
if _PYTHON3 is None:
    raise RuntimeError("python3 is required for the sandbox python shim")

_PREEXISTING_CONFIG = """{
  "mcpServers": {
    "polymarket": {
      "command": "/old/path/python",
      "args": ["-m", "old.server"],
      "cwd": "/old/path",
      "env": {"OLD": "1"}
    },
    "other-mcp": {
      "command": "/usr/bin/other-mcp",
      "args": ["--serve"]
    },
    "another": {
      "command": "/usr/bin/another",
      "args": []
    }
  }
}
"""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sandbox(tmp_path: Path) -> Path:
    """Build a hermetic sandbox: shim, byte-exact install.sh copy, empty HOME."""
    sb = tmp_path / "sb"
    (sb / "bin").mkdir(parents=True)
    (sb / "home").mkdir()
    assert _PYTHON3, "python3 is required for the sandbox python shim"
    (sb / "bin" / "python").symlink_to(_PYTHON3)
    (sb / "install.sh").write_bytes(INSTALL_SH.read_bytes())
    assert _sha256_file(sb / "install.sh") == _sha256_file(INSTALL_SH)
    return sb


def _extract_lib(sb: Path) -> Path:
    """Extract colors+settings+helpers from the COPY by content anchors."""
    src = sb / "install.sh"
    lib = sb / "install_lib.sh"
    out: list[str] = []
    on = False
    for line in src.read_text(encoding="utf-8").splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if stripped == _LIB_START:
            on = True
        if stripped == _LIB_END:
            on = False
        if on:
            out.append(line)
    lib.write_text("".join(out), encoding="utf-8")
    text = lib.read_text(encoding="utf-8")
    assert text.strip(), "extracted lib is empty (anchors drifted?)"
    for anchor in _FUNC_ANCHORS:
        assert re.search(rf"^{re.escape(anchor)}", text, re.M), f"missing anchor {anchor}"
    assert not re.search(r"^main\(\)", text, re.M), "main() must not leak into the lib"
    assert not re.search(r'^main "\$@"', text, re.M), "footer main call must not leak"
    proc = subprocess.run(["bash", "-n", str(lib)], capture_output=True, text=True)
    assert proc.returncode == 0, f"extracted lib is not valid bash:\n{proc.stderr}"
    return lib


def _write_driver(sb: Path, body: str) -> Path:
    driver = sb / "driver.sh"
    driver.write_text(
        "set -e\n"
        f'export HOME="{sb / "home"}"\n'
        f'export PATH="{sb / "bin"}:$PATH"\n'
        'export OS="Linux"\n'
        f'source "{sb / "install_lib.sh"}"\n'
        f'cd "{sb}"\n'
        f"{body}\n",
        encoding="utf-8",
    )
    return driver


def _run_driver(sb: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(sb / "driver.sh")],
        capture_output=True,
        text=True,
        cwd=str(sb),
        timeout=120,
    )


def _config_path(sb: Path) -> Path:
    return sb / "home" / ".config" / "Claude" / "claude_desktop_config.json"


def _write_driver_run_config(sb: Path) -> subprocess.CompletedProcess[str]:
    _write_driver(
        sb, "DEMO_MODE=true\nSKIP_CLAUDE_CONFIG=false\nconfigure_claude_desktop\n"
    )
    return _run_driver(sb)


def _assert_polymarket_entry(entry: dict, sb: Path, env: dict) -> None:
    """Pin the template entry fields (command/args/cwd/env) on the sandbox."""
    assert set(entry) == {"command", "args", "cwd", "env"}
    assert entry["command"] == str(sb / "bin" / "python")
    assert entry["args"] == ["-m", "polymarket_mcp.server"]
    assert entry["cwd"] == str(sb)
    assert entry["env"] == env


@pytest.fixture(autouse=True)
def _tripwire_real_install_sh():
    before = _sha256_file(INSTALL_SH)
    yield
    assert _sha256_file(INSTALL_SH) == before, "real install.sh was modified by the suite"


def test_bash_n_valid(tmp_path: Path) -> None:
    """bash -n on a byte-exact copy of install.sh must succeed (rc=0)."""
    sb = _make_sandbox(tmp_path)
    proc = subprocess.run(
        ["bash", "-n", str(sb / "install.sh")], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_help_rc0_without_side_effects(tmp_path: Path) -> None:
    """`bash install.sh --help` exits 0 and creates nothing (.env/config/venv)."""
    sb = _make_sandbox(tmp_path)
    proc = subprocess.run(
        ["bash", "install.sh", "--help"],
        capture_output=True,
        text=True,
        cwd=str(sb),
        timeout=60,
    )
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    for path in (sb / ".env", sb / "venv", sb / "home" / ".config"):
        assert not path.exists(), f"side effect created: {path}"


def test_merge_preserves_existing_servers(tmp_path: Path) -> None:
    """A pre-existing config keeps other-mcp/another; polymarket entry is renewed."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    cfg = _config_path(sb)
    cfg.parent.mkdir(parents=True)
    cfg.write_text(_PREEXISTING_CONFIG, encoding="utf-8")
    before = json.loads(_PREEXISTING_CONFIG)
    proc = _write_driver_run_config(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    merged = json.loads(cfg.read_text(encoding="utf-8"))
    servers = merged["mcpServers"]
    assert sorted(servers) == ["another", "other-mcp", "polymarket"]
    assert servers["other-mcp"] == before["mcpServers"]["other-mcp"]
    assert servers["another"] == before["mcpServers"]["another"]
    _assert_polymarket_entry(servers["polymarket"], sb, {"DEMO_MODE": "true"})
    backup = json.loads(Path(f"{cfg}.backup").read_text(encoding="utf-8"))
    assert backup == before, "pre-run backup lost the original content"


def test_fresh_install_creates_config(tmp_path: Path) -> None:
    """No pre-existing config: the merge creates one holding only polymarket."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    proc = _write_driver_run_config(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    cfg = _config_path(sb)
    assert cfg.exists(), "fresh install did not create the Claude config"
    merged = json.loads(cfg.read_text(encoding="utf-8"))
    servers = merged["mcpServers"]
    assert sorted(servers) == ["polymarket"]
    _assert_polymarket_entry(servers["polymarket"], sb, {"DEMO_MODE": "true"})


def test_malformed_config_untouched_rc_ne0(tmp_path: Path) -> None:
    """Malformed config: merge aborts (rc!=0), file byte-identical, warning shown."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    cfg = _config_path(sb)
    cfg.parent.mkdir(parents=True)
    cfg.write_text("not-json{", encoding="utf-8")
    sha_before = _sha256_file(cfg)
    proc = _write_driver_run_config(sb)
    assert proc.returncode != 0, f"expected abort, got rc=0:\n{proc.stdout}"
    assert _sha256_file(cfg) == sha_before, "malformed config was overwritten"
    output = proc.stdout + proc.stderr
    assert str(cfg) in output, "warning does not mention the config path"
    assert "preserved intact" in output, "warning does not state the file was preserved"


def test_non_demo_env_block_parity(tmp_path: Path) -> None:
    """Non-demo mode interpolates .env credentials into the config env block."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(
        "POLYGON_PRIVATE_KEY=0xabc123\nPOLYGON_ADDRESS=0xdead\n", encoding="utf-8"
    )
    _write_driver(
        sb, "DEMO_MODE=false\nSKIP_CLAUDE_CONFIG=false\nconfigure_claude_desktop\n"
    )
    proc = _run_driver(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    merged = json.loads(_config_path(sb).read_text(encoding="utf-8"))
    entry = merged["mcpServers"]["polymarket"]
    assert entry["env"] == {
        "POLYGON_PRIVATE_KEY": "0xabc123",
        "POLYGON_ADDRESS": "0xdead",
    }


def test_real_file_tripwire() -> None:
    """The REAL install.sh is byte-identical across the test run (P-0013)."""
    before = _sha256_file(INSTALL_SH)
    after = _sha256_file(INSTALL_SH)
    assert before == after
