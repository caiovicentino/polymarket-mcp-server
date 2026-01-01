"""Offline suite for docker-start.sh (T-0232): template parity + non-TTY fail-loud.

Scope (sibling-disjoint, L-0148): only `docker-start.sh` behaviour is exercised —
specifically the fallback `.env` template heredoc, the validation placeholders
and the interactive `read`. No docker daemon is ever contacted: the version
check is answered by a PATH stub (P-0031 fail-loud stub — unexpected docker
calls exit 99 with a sentinel), and the script must fail LOUD at validation
(rc=1) BEFORE any build step is ever possible.

Semantics pinned (pre/post declared, L-0067/L-0008 — probed 1st hand on the
pre-fix state, main 89edfa9):
- PRE-fix: under stdin EOF (`curl | bash`, CI) the script dies AT the
  interactive `read -p` (set -e, :95) — rc=1 WITHOUT the validation message,
  on BOTH routes (template fallback and `cp .env.example .env`). The fallback
  heredoc had only 10/22 config keys and diverged from `.env.example` defaults
  (byte-parity RED at char 39 / line 2: template's 21 lines vs 111).
- POST-fix: `read ... || true` swallows EOF (interactive behaviour unchanged);
  validation then fails LOUD with the existing message; the fallback heredoc is
  byte-identical to `.env.example` (the source of truth, so both routes —
  template and cp — produce the SAME file); validation pins the NEW placeholder
  `0xYourAddressHere` and the stale `your_wallet_address_here` is absent from
  the whole script (template × validation consistency).

Hermeticity (P-0029 direction — sandboxed, environment-from-scratch): every run
happens in a tmp sandbox OUTSIDE the repo; subprocess env is built from scratch
(PATH with the docker stub FIRST + HOME=tmp) so host env cannot influence the
outcome; no network is reachable (the only external binary is the stub).
`.env` must never be created in the repo root (guarded fail-loud, mirrors the
web-suite hermeticity guard): the suite writes only inside tmp sandboxes.

Mutation oracle (dev-only, proven by mutation on the real file with shasum-verified
restoration — L-0014/L-0016; results OBSERVED, not predicted):
- M1: restore `your_wallet_address_here` in the validation line -> test 3 fails
  (paired negation + exact validation-line assert). Tests 4/5 still pass: the
  PRIVATE_KEY check (:103) precedes the ADDRESS check, so the sandbox .env (whose
  private key is the placeholder) exits at the private-key check before the
  broken address check is ever consulted — the address consistency is observable
  statically only (probed: 1 failed / 5 passed).
- M2: remove `|| true` from the `read` line -> tests 4/5 fail (silent death at
  the read: rc=1 but WITHOUT the validation message).
- M3: tamper one value inside the heredoc block -> test 2 fails (byte-parity).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
SCRIPT: Final[Path] = REPO_ROOT / "docker-start.sh"
ENV_EXAMPLE: Final[Path] = REPO_ROOT / ".env.example"

NEW_PLACEHOLDER: Final[str] = "0xYourAddressHere"
STALE_PLACEHOLDER: Final[str] = "your_wallet_address_here"
PRIVATE_KEY_PLACEHOLDER: Final[str] = "your_private_key_here"
VALIDATION_MSG: Final[str] = "POLYGON_PRIVATE_KEY not set in .env!"
STUB_SENTINEL: Final[str] = "STUB-DOCKER-UNEXPECTED-CALL"

_BASH = shutil.which("bash")
assert _BASH is not None, "bash not found on PATH (offline suite requires bash)"
BASH: Final[str] = _BASH

# Fail-loud docker stub (P-0031/P-0040): ONLY the `compose version` probe is
# answered; any other docker call exits 99 with the sentinel on stderr. If the
# script under test ever reaches `docker compose build` inside this suite, the
# run fails loudly instead of silently building anything.
_STUB_DOCKER: Final[str] = """#!/bin/bash
if [ "$1" = "compose" ] && [ "$2" = "version" ]; then
    exit 0
fi
echo "STUB-DOCKER-UNEXPECTED-CALL: $*" >&2
exit 99
"""


def _assert_no_env_in_worktree() -> None:
    """Fail loud if a .env appeared in the repo root (hermeticity guard).

    docker-start.sh writes `.env` relative to its CWD; this suite runs every
    script invocation inside an isolated tmp sandbox. A .env here would leak
    sandbox state into the repo (and invalidate the env-only web suites).
    """
    assert not (REPO_ROOT / ".env").exists(), (
        "A .env file appeared in the repo root — docker-start.sh must only write "
        ".env inside the isolated tmp sandbox (hermeticity precondition violated)."
    )


def _make_sandbox(tmp_path: Path, copy_env_example: bool) -> tuple[Path, Path]:
    """Create a tmp sandbox (docker stub FIRST in PATH) with byte-verified copies.

    L-0232: copies are verified byte-exact before use — a diverged copy would
    silently test the wrong fixture.
    """
    stub_dir = tmp_path / "stubs"
    sandbox = tmp_path / "sandbox"
    stub_dir.mkdir()
    sandbox.mkdir()
    stub = stub_dir / "docker"
    stub.write_text(_STUB_DOCKER, encoding="utf-8")
    stub.chmod(0o755)
    script_copy = sandbox / "docker-start.sh"
    shutil.copy(SCRIPT, script_copy)
    assert script_copy.read_bytes() == SCRIPT.read_bytes(), "script copy diverged from source"
    if copy_env_example:
        example_copy = sandbox / ".env.example"
        shutil.copy(ENV_EXAMPLE, example_copy)
        assert example_copy.read_bytes() == ENV_EXAMPLE.read_bytes(), ".env.example copy diverged"
    return sandbox, stub_dir


def _run_sandbox(sandbox: Path, stub_dir: Path) -> subprocess.CompletedProcess[bytes]:
    """Run the sandboxed script copy with stdin=DEVNULL (the non-TTY case)."""
    return subprocess.run(
        [BASH, "docker-start.sh"],
        cwd=sandbox,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={"PATH": f"{stub_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}", "HOME": str(sandbox)},
        timeout=60,
        check=False,
    )


def test_script_parses() -> None:
    """`bash -n docker-start.sh` parses cleanly (syntax invariant)."""
    proc = subprocess.run(
        [BASH, "-n", str(SCRIPT)],
        capture_output=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")


def test_template_byte_parity() -> None:
    """The fallback heredoc block is byte-identical to .env.example.

    Content-anchored (L-0070): the START anchor is the `.env`-WRITING heredoc
    (banner uses `cat << "EOF"` without `>` and must not match); the END anchor
    is the first bare `EOF` line after it (heredoc semantics; .env.example
    contains no `EOF` line and no `$` — probed — so the quoted heredoc is safe).
    """
    example_bytes = ENV_EXAMPLE.read_bytes()
    assert example_bytes, ".env.example missing/empty (source of truth)"
    lines = SCRIPT.read_bytes().splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line == b"        cat > .env << 'EOF'\n"]
    assert len(starts) == 1, "the .env-writing heredoc start anchor drifted"
    start = starts[0]
    terminator = next((j for j in range(start + 1, len(lines)) if lines[j] == b"EOF\n"), None)
    assert terminator is not None, "heredoc terminator not found"
    block = b"".join(lines[start + 1 : terminator])
    assert block == example_bytes, "fallback heredoc is not byte-identical to .env.example"


def test_validation_matches_template_placeholders() -> None:
    """Validation pins the NEW template placeholders; stale one is gone.

    Paired negation (L-0056): the positive presences first prove the file was
    read and is non-degenerate, so the negation cannot mask a read failure.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    assert NEW_PLACEHOLDER in text
    assert PRIVATE_KEY_PLACEHOLDER in text
    assert STALE_PLACEHOLDER not in text, (
        "stale placeholder survives — template x validation consistency broken"
    )
    assert f'[ "$POLYGON_ADDRESS" = "{NEW_PLACEHOLDER}" ]' in text
    assert f'[ "$POLYGON_PRIVATE_KEY" = "{PRIVATE_KEY_PLACEHOLDER}" ]' in text


def test_read_guard_non_tty_reaches_validation(tmp_path: Path) -> None:
    """stdin EOF must reach the fail-loud validation (no silent death at read).

    Discriminant (pre-fix: rc=1 WITHOUT the message — death AT `read`; post-fix:
    rc=1 WITH the message). The docker stub guards against any build step: an
    unexpected call yields rc=99 + sentinel, which the assertions reject.
    """
    sandbox, stub_dir = _make_sandbox(tmp_path, copy_env_example=False)
    proc = _run_sandbox(sandbox, stub_dir)
    output = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 1, f"rc={proc.returncode} output={output!r}"
    assert VALIDATION_MSG in output, (
        f"validation must fail loud under stdin EOF (silent death = pre-fix bug). output={output!r}"
    )
    assert STUB_SENTINEL not in output, f"build step reached after failed validation: {output!r}"
    assert (sandbox / ".env").exists(), "template route must have created .env in the sandbox"
    _assert_no_env_in_worktree()


def test_env_example_present_path_also_fails_loud(tmp_path: Path) -> None:
    """The `cp .env.example .env` route is coherent with the template route."""
    sandbox, stub_dir = _make_sandbox(tmp_path, copy_env_example=True)
    proc = _run_sandbox(sandbox, stub_dir)
    output = proc.stdout.decode("utf-8", "replace")
    assert proc.returncode == 1, f"rc={proc.returncode} output={output!r}"
    assert VALIDATION_MSG in output, f"cp route must fail loud too. output={output!r}"
    assert STUB_SENTINEL not in output, f"build step reached after failed validation: {output!r}"
    assert (sandbox / ".env").exists(), "cp route must have created .env in the sandbox"
    _assert_no_env_in_worktree()


def test_docker_steps_preserved() -> None:
    """Regression pin by presence (L-0002): the docker workflow is intact."""
    text = SCRIPT.read_text(encoding="utf-8")
    for step in ("docker compose build", "docker compose up -d", "docker compose ps"):
        assert step in text, f"docker step drifted: {step}"
