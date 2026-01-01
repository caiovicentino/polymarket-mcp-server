"""
Offline suite for uninstall.sh (T-0214) — 100% offline, byte-exact copy discipline.

The real uninstall.sh is currently syntactically invalid (bash -n rc=2
'unexpected end of file') because of two compounded defects (contract T-0214):

- :141 opens a heredoc WITHOUT passing the config file as argv
  (`python3 << 'PYEOF'`): the body's `sys.argv[1]` raises IndexError, the
  internal except prints a warning and the polymarket entry NEVER leaves the
  Claude Desktop config.
- :164 has the heredoc terminator with an invalid suffix
  (`PYEOF "$CONFIG_FILE" || true`). Bash requires the delimiter alone on its
  own line, so the heredoc never terminates, the parser swallows the rest of
  the file and bash -n fails at EOF. A real run dies MID-uninstall (after the
  .env was renamed), leaving partial state (config untouched, no summary).

Fix under test (verbatim, 2 lines):
- :141 -> `python3 - "$CONFIG_FILE" << 'PYEOF' || true`
- :164 -> `PYEOF`   (delimiter alone on the line)

Mechanics (contract-mandated):
- The REAL script is NEVER executed: every case copies it byte-exactly into a
  pytest tmp_path (P-0018, hash-provable) and exercises ONLY the copy with a
  sandboxed HOME and cwd. Tripwire: sha256 of the real file is captured at
  import time (pre) and re-checked in test_real_file_tripwire (post).
- Assertions are content-anchored, never file:line (L-0127/L-0023): the
  parser error of the broken script lands on whatever line the EOF falls on;
  the FIX itself is anchored by its literal text.
- Mutation oracle (L-0065/L-0094): test_bash_n_valid_after_fix reverts the two
  fix lines on a SECOND copy and proves bash -n fails again (rc=2) — the
  oracle knows how to fail. Substitution counts are asserted == 1
  (L-0082/L-0112/L-0128: no silent no-op mutations).

Offline proof (L-0138/L-0133): subprocesses run with a minimal explicit env
(PATH_SAFE, TERM, HOME) so no host env vars/credentials leak into the run; the
script only uses stdlib `json` + core shell tools; zero sockets are created;
zero writes outside the tmpdir (the script only touches cwd and $HOME, both
pointing inside the sandbox).

Divergence notes (L-0025/L-0090):
- P-0021 "set -u, no -e, sentinel rc=99 on captures": materialized directly —
  every captured returncode starts as the sentinel 99 and is only overwritten
  after a successful subprocess.run (no bash pipelines exist to mask a rc);
  the timeout guard turns a hang into a loud rc=99 failure with the right
  label instead of a dead suite.
- L-0089g/FA-0061 "trap 'rc=$?; cleanup; exit $rc' at the top": there is no
  bash trap here (the suite is Python); the pytest tmp_path fixture is the
  Python-idiomatic equivalent (teardown guaranteed on every exit path,
  including exceptions), declared here instead of silently skipped.
- L-0163b: no banner path — the suite prints no sandbox paths in its own
  output (pytest may echo tmp paths only on failure, which is its teardown
  surface, not our banner).

Prediction (TDD, causal proof — L-0130/P-0036): RED pre-fix = 4 failed /
1 passed (only the tripwire passes; the single variable separating RED from
GREEN is the fix). GREEN post-fix = 5 passed.
"""

import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL = REPO_ROOT / "uninstall.sh"

# Pre-state hash captured at import time — BEFORE any test touches anything.
REAL_SHA_PRE = hashlib.sha256(REAL.read_bytes()).hexdigest()

# Fix under test (verbatim, content-anchored — never file:line, L-0127/L-0023).
FIX_HEREDOC = 'python3 - "$CONFIG_FILE" << \'PYEOF\' || true'
FIX_TERM = "PYEOF"
# The broken state (re-applied by the dev-only oracle mutation).
BAD_HEREDOC = "python3 << 'PYEOF'"
BAD_TERM = 'PYEOF "$CONFIG_FILE" || true'

PATH_SAFE = "/usr/bin:/bin:/usr/sbin:/sbin"
# macOS path of the Claude Desktop config (uninstall.sh, darwin* branch).
CFG_REL = Path("Library") / "Application Support" / "Claude" / "claude_desktop_config.json"

ENV_CONTENT = "FAKE_SECRET=sentinel-env-content\n"
ORIGINAL_SERVERS = {
    "polymarket": {"command": "python-fake-a", "args": ["-m", "fake_a"]},
    "other-mcp": {"command": "python-fake-b", "args": ["-m", "fake_b"]},
    "another": {"command": "python-fake-c"},
}


def _probe_env() -> dict:
    """Minimal env for syntax probes (bash -n executes nothing).

    TERM is probed-required for the real run: `clear` returns rc=1 without it
    under set -e (L-0165: preflight mirrors the resolution environment).
    """
    return {"PATH": PATH_SAFE, "TERM": "xterm"}


def _run_env(home: Path) -> dict:
    """Minimal explicit env for execution: PATH_SAFE, TERM, sandboxed HOME —
    nothing else inherited from the host (hermeticity direction 2, L-0130)."""
    return {"PATH": PATH_SAFE, "TERM": "xterm", "HOME": str(home)}


def _copy_byte_exact(tmp_path: Path) -> Path:
    """Copy the REAL script byte-exactly into the sandbox (P-0018)."""
    dst = tmp_path / "uninstall.sh"
    dst.write_bytes(REAL.read_bytes())
    post = hashlib.sha256(dst.read_bytes()).hexdigest()
    assert post == REAL_SHA_PRE, "sandbox copy is not byte-identical to the real script"
    return dst


def _bash_n(script: Path):
    """bash -n syntax probe. rc starts as the P-0021 sentinel 99 and is only
    overwritten after a successful subprocess.run."""
    rc = 99
    stderr = ""
    try:
        proc = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            env=_probe_env(),
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:  # hang guard: fails LOUD, not dead
        stderr = f"TIMEOUT (hang guard): {(exc.stderr or b'').decode('utf-8', errors='replace')}"
    else:
        rc = proc.returncode
        stderr = proc.stderr.decode("utf-8", errors="replace")
    return rc, stderr


def _run_force(script: Path, cwd: Path, home: Path):
    """Run the SANDBOX COPY with --force (never the real script). rc starts as
    the P-0021 sentinel 99 and is only overwritten after a successful run."""
    rc = 99
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            ["bash", str(script), "--force"],
            cwd=str(cwd),
            env=_run_env(home),
            capture_output=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:  # hang guard: fails LOUD, not dead
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = f"TIMEOUT (hang guard): {(exc.stderr or b'').decode('utf-8', errors='replace')}"
    else:
        rc = proc.returncode
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
    return rc, stdout, stderr


def _mutate_revert_fix(src: Path, dst: Path) -> None:
    """Dev-only oracle mutation: revert the 2 fix lines on the SECOND copy
    (never the real script — L-0128a: substitution, never deletion)."""
    text = src.read_text(encoding="utf-8")
    n_open = text.count(FIX_HEREDOC)
    assert n_open == 1, (
        f"mutation precondition failed: FIX_HEREDOC occurs {n_open} times (expected 1)"
    )
    text = text.replace(FIX_HEREDOC, BAD_HEREDOC)
    lines = text.splitlines(keepends=True)
    lone = [i for i, line in enumerate(lines) if line.strip() == FIX_TERM]
    assert len(lone) == 1, (
        f"mutation precondition failed: lone terminator appears on {len(lone)} lines (expected 1)"
    )
    eol = "\n" if lines[lone[0]].endswith("\n") else ""
    lines[lone[0]] = BAD_TERM + eol
    dst.write_text("".join(lines), encoding="utf-8")
    # Application proof (L-0112): each mutation applied exactly once, in the copy.
    mutated = dst.read_text(encoding="utf-8")
    assert BAD_HEREDOC in mutated, "mutation 1 (heredoc open) not applied in the copy"
    assert BAD_TERM in mutated, "mutation 2 (terminator suffix) not applied in the copy"
    assert FIX_HEREDOC not in mutated, "fix line survived the mutation (no-op)"
    assert not [line for line in mutated.splitlines() if line.strip() == FIX_TERM], (
        "lone terminator survived the mutation (no-op)"
    )


def test_bash_n_valid_after_fix(tmp_path):
    """The copy of the FIXED script parses (rc=0); the dev-only oracle reverts
    the two fix lines on a second copy and bash -n fails again (rc=2)."""
    copy = _copy_byte_exact(tmp_path)
    rc, stderr = _bash_n(copy)
    assert rc == 0, f"bash -n must accept the fixed script; stderr: {stderr}"
    mutated = tmp_path / "uninstall.sh.reverted"
    _mutate_revert_fix(copy, mutated)
    rc2, stderr2 = _bash_n(mutated)
    assert rc2 == 2, f"oracle must know how to fail: rc={rc2}, stderr: {stderr2}"
    assert "unexpected end of file" in stderr2, (
        f"oracle failure must be the parse error itself; stderr: {stderr2}"
    )


def test_heredoc_passes_config_file_arg(tmp_path):
    """Content anchors: the heredoc open passes $CONFIG_FILE as argv and the
    terminator is alone on its own line (verified line by line)."""
    copy = _copy_byte_exact(tmp_path)
    text = copy.read_text(encoding="utf-8")
    # Positive (paired with the negations — L-0056): the fix literal is present.
    assert FIX_HEREDOC in text, (
        "heredoc must pass $CONFIG_FILE as argv (python3 - \"$CONFIG_FILE\")"
    )
    # Negation: the terminator is never seen with a suffix anywhere.
    assert 'PYEOF "$CONFIG_FILE"' not in text, (
        "terminator must be alone on its own line"
    )
    # Terminator alone, verified line by line: exactly one lone 'PYEOF'.
    lone = [line for line in text.splitlines() if line.strip() == FIX_TERM]
    assert len(lone) == 1, f"expected exactly 1 lone 'PYEOF' line, got {len(lone)}"


def test_force_uninstall_removes_entry_and_preserves_others(tmp_path):
    """Sandbox (HOME + cwd inside tmp): fake .env, fake config (macOS path)
    with polymarket + other-mcp + another, fake venv/ (empty dir) ->
    `bash <copy> --force` rc=0; .env GONE and .env.backup with the old
    content; config after: polymarket ABSENT, other-mcp+another PRESERVED;
    ${CONFIG_FILE}.backup exists with the whole original config; summary
    'Uninstallation Complete' present on stdout."""
    home = tmp_path / "sb"
    cfg = home / CFG_REL
    cfg.parent.mkdir(parents=True)
    original_config = {"mcpServers": ORIGINAL_SERVERS}
    cfg.write_text(json.dumps(original_config, indent=2) + "\n", encoding="utf-8")

    (tmp_path / ".env").write_text(ENV_CONTENT, encoding="utf-8")
    (tmp_path / "venv").mkdir()  # fake venv: empty dir

    copy = _copy_byte_exact(tmp_path)
    rc, stdout, stderr = _run_force(copy, cwd=tmp_path, home=home)

    assert rc == 0, f"script must exit 0; stderr: {stderr}\nstdout tail: {stdout[-400:]}"
    # .env GONE, .env.backup with the old content.
    assert not (tmp_path / ".env").exists(), ".env must be removed (moved)"
    backup = tmp_path / ".env.backup"
    assert backup.exists(), ".env.backup must exist after the uninstall"
    assert backup.read_text(encoding="utf-8") == ENV_CONTENT, ".env.backup holds the old content"
    # Fake venv removed (step 1 of the observed flow).
    assert not (tmp_path / "venv").exists(), "venv/ must be removed"

    # Config after: polymarket ABSENT, other-mcp+another PRESERVED.
    post = json.loads(cfg.read_text(encoding="utf-8"))
    post_servers = post.get("mcpServers", {})
    assert "polymarket" not in post_servers, "polymarket entry must be removed"
    assert post_servers.get("other-mcp") == ORIGINAL_SERVERS["other-mcp"], (
        "other-mcp must be preserved"
    )
    assert post_servers.get("another") == ORIGINAL_SERVERS["another"], "another must be preserved"

    # ${CONFIG_FILE}.backup exists with the WHOLE original config.
    cfg_backup = cfg.parent / (cfg.name + ".backup")
    assert cfg_backup.exists(), "config backup must exist"
    assert json.loads(cfg_backup.read_text(encoding="utf-8")) == original_config, (
        "config backup must hold the whole original config"
    )

    # Summary on stdout.
    assert "Uninstallation Complete" in stdout, f"summary missing; stdout: {stdout[-600:]}"


def test_uninstall_clean_slate_rc0(tmp_path):
    """Clean-slate sandbox (no .env, no config): rc=0 with the 'not found'
    messages — clean-state idempotency; NEVER an error."""
    home = tmp_path / "sb"
    home.mkdir()
    copy = _copy_byte_exact(tmp_path)
    rc, stdout, stderr = _run_force(copy, cwd=tmp_path, home=home)
    assert rc == 0, f"clean slate must exit 0; stderr: {stderr}"
    assert "Virtual environment not found" in stdout
    assert "Environment file not found" in stdout
    assert "Claude Desktop config not found" in stdout
    assert "Uninstallation Complete" in stdout
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / ".env.backup").exists()
    assert not (home / CFG_REL).exists()


def test_real_file_tripwire():
    """The suite NEVER touches the real script: sha256 pre (import time)
    == post (now)."""
    post = hashlib.sha256(REAL.read_bytes()).hexdigest()
    assert post == REAL_SHA_PRE, "real uninstall.sh was modified by the suite run (tripwire)"
