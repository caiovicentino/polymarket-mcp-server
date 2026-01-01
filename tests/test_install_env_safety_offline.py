"""
Offline sandbox suite for install.sh — .env overwrite safety (T-0215).

Pins the FIX contract (backup first-wins + rollback restore/keep) against the
REAL install.sh of this worktree by running extracted functions
(configure_env / rollback) in a temp-dir sandbox. The file is never executed
end-to-end and the suite does NOT rely on INSTALL_TEST_MODE.

Extraction (declared choice per task §Seam — anchor-based, P-0018): the span
from the `# Colors for output` comment to the `# Main Installation Flow`
comment (colors + settings incl. ENV_CREATED init + every helper incl.
configure_env and rollback) is extracted from a byte-exact copy of install.sh
into install_lib.sh inside the sandbox. Anchors are CONTENT, not line numbers
(L-0127); extraction sanity is fail-fast (P-0018): non-empty, both target
functions anchored, main()/the footer `main "$@"` absent, `bash -n` clean.

Sandbox per test (pytest tmp_path — under the system temp dir, never inside
the repo): HOME/PATH/OS are redirected to the sandbox; the driver mirrors
production semantics (`set -e`, no -u). Zero network / zero pip / zero real
venv: only configure_env and rollback run (configure_env's demo path writes a
plain text file; nothing else is executed). All writes are confined to the
sandbox (L-0013).

Semantics pinned (task §Fix B):
- a pre-existing .env is backed up ONCE to `.env.pre-install-backup`
  (first-wins: a second run never overwrites the backup with the template;
  the name is deliberately distinct from uninstall.sh's `.env.backup` to
  avoid cross-rotation);
- rollback() restores the pre-existing .env from the backup (mv), removes an
  .env created by the current run (ENV_CREATED=1), and keeps anything else.

RED pre-fix (first-hand, task report): pre-fix configure_env overwrote a
pre-existing .env with no backup at all, and rollback() removed ANY .env
unconditionally — an install over a working setup destroyed the user's
configuration. test_demo_env_write_creates_first_backup /
test_second_run_preserves_backup / test_rollback_restores_preexisting_env /
test_rollback_removes_created_env failed pre-fix (the last one on the
ENV_CREATED=1 observability — the .env-gone part already held pre-fix).
test_bash_n_valid / test_real_file_tripwire passed pre-fix (declared).
"""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

_LIB_START = "# Colors for output"
_LIB_END = "# Main Installation Flow"
_FUNC_ANCHORS = ("configure_env()", "rollback()")

_ORIGINAL_ENV = "MAX_ORDER_SIZE_USD=777\nPOLYGON_ADDRESS=0xdead\n"

_PYTHON3 = shutil.which("python3")
if _PYTHON3 is None:
    raise RuntimeError("python3 is required for the sandbox python shim")


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


def test_demo_env_write_creates_first_backup(tmp_path: Path) -> None:
    """A pre-existing .env (777 custom limit) is backed up; .env becomes template."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(_ORIGINAL_ENV, encoding="utf-8")
    _write_driver(sb, "DEMO_MODE=true\nconfigure_env\n")
    proc = _run_driver(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    backup = sb / ".env.pre-install-backup"
    assert backup.exists(), "first-run backup of the pre-existing .env missing"
    assert backup.read_text(encoding="utf-8") == _ORIGINAL_ENV
    env_now = (sb / ".env").read_text(encoding="utf-8")
    assert "MAX_ORDER_SIZE_USD=100" in env_now, "demo template not written"
    assert "777" not in env_now, "custom limit leaked into the rewritten .env"


def test_second_run_preserves_backup(tmp_path: Path) -> None:
    """Second run (same sandbox state): the backup keeps the ORIGINAL content."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(_ORIGINAL_ENV, encoding="utf-8")
    _write_driver(sb, "DEMO_MODE=true\nconfigure_env\nconfigure_env\n")
    proc = _run_driver(sb)
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    backup = sb / ".env.pre-install-backup"
    assert backup.exists(), "backup vanished after the second run"
    assert backup.read_text(encoding="utf-8") == _ORIGINAL_ENV, (
        "second run clobbered the first-wins backup with the template"
    )


def test_rollback_restores_preexisting_env(tmp_path: Path) -> None:
    """Rollback with a backup present: .env is the pre-existing content, backup gone."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    (sb / ".env").write_text(_ORIGINAL_ENV, encoding="utf-8")
    _write_driver(sb, "DEMO_MODE=true\nconfigure_env\nrollback\n")
    proc = _run_driver(sb)
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert (sb / ".env").read_text(encoding="utf-8") == _ORIGINAL_ENV, (
        "rollback did not restore the pre-existing .env"
    )
    assert "Restored pre-existing .env" in proc.stdout, "restore branch not taken"
    assert not (sb / ".env.pre-install-backup").exists(), "backup not consumed by mv"


def test_rollback_removes_created_env(tmp_path: Path) -> None:
    """Same-process run+rollback with no pre-existing .env: created .env removed."""
    sb = _make_sandbox(tmp_path)
    _extract_lib(sb)
    _write_driver(
        sb,
        "DEMO_MODE=true\n"
        "configure_env\n"
        'echo "ENV_CREATED=$ENV_CREATED"\n'
        "rollback\n",
    )
    proc = _run_driver(sb)
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert "ENV_CREATED=1" in proc.stdout, "ENV_CREATED not observable after the write"
    assert not (sb / ".env").exists(), "rollback kept the .env created by this run"
    assert not (sb / ".env.pre-install-backup").exists(), "stray backup after removal"
    assert "Removed .env file" in proc.stdout, "remove-created branch not taken"


def test_real_file_tripwire() -> None:
    """The REAL install.sh is byte-identical across the test run (P-0013)."""
    before = _sha256_file(INSTALL_SH)
    after = _sha256_file(INSTALL_SH)
    assert before == after
