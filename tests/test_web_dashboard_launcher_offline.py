"""
Offline sandbox suite for start_web_dashboard.sh (T-0221).

The launcher is the front-door of the web dashboard (README.md "Start the web
dashboard" section and DASHBOARD_SUMMARY.md "Using helper script"). Before this
slice, EVERY fresh checkout failed with rc=127 `polymarket-web: command not
found`: the script installed only the ad-hoc libraries (fastapi/uvicorn/jinja2)
but never the package itself, whose `polymarket-web` console script
(pyproject.toml `[project.scripts] polymarket-web = polymarket_mcp.web.app:start`)
is what the final line launches. There was also no guard for the
`requires-python = ">=3.10"` floor, so an old python3 failed much later (or
opaquely inside pip/PEP 660) instead of fail-fast.

Semantics pinned (fix contract T-0221):
- a version guard runs FIRST (right after `set -e`, before the banner): a
  python3 below 3.10 is rejected with `ERROR: Python >= 3.10 required` and
  exit 1 BEFORE any artifact (venv/) is created;
- when the `polymarket-web` console script is absent from PATH, the launcher
  installs the PACKAGE (`pip install --upgrade pip` then `pip install -e .`,
  in that order — the upgrade is the precondition for the editable install)
  and reaches the final `polymarket-web` line without rc=127;
- when the console script is already present, pip is NOT invoked at all
  (idempotent re-runs) and the launcher goes straight to the start.

Mechanism (task §Suíte-NOVA): the launcher is copied BYTE-EXACT (sha256 assert)
into a pytest tmp_path sandbox and the COPY is exercised with a minimal env
(TERM/HOME/PATH — the host PATH is never inherited, P-0029-equivalent). A
`python3` shim models the interpreter version (deterministic, offline; this
host's PATH has no `python` at all — P-0031/P-0040) and a `pip` shim records
its invocations to pip.log and simulates the package installation by creating
a fake `polymarket-web` console script inside the sandbox venv. Fakes are
fail-loud: unexpected invocations abort the sandbox run instead of silently
falling through to real tooling. Zero network, zero real venv, zero writes
outside tmp_path; the REAL launcher is pinned by a sha256 tripwire (P-0013).

RED pre-fix (first-hand, worker report §RED-pré): the pre-fix copy (materialized
from main) exits 127 on `polymarket-web: command not found`, and tests
test_version_guard_rejects_old_python_fail_fast /
test_installs_package_when_console_script_missing /
test_idempotent_when_package_installed fail against it; test_bash_n_valid /
test_version_guard_passes_with_310_plus / test_real_file_tripwire already pass
pre-fix (the bug is SEMANTIC, not syntactic — the script is valid bash today).
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_NAME = "start_web_dashboard.sh"
LAUNCHER = REPO_ROOT / LAUNCHER_NAME

# The exact guard expression the fix must contain (shim pins this shape — a
# guard whose code drifts fails the sandbox LOUD with SANDBOX-PY3-UNEXPECTED).
_GUARD_CODE = "import sys; assert sys.version_info >= (3, 10)"
_BANNER = "Polymarket MCP Web Dashboard"
_GUARD_ERROR = "ERROR: Python >= 3.10 required"
_INSTALL_ECHO = "Installing polymarket-mcp package (editable)..."
_FAKE_CONSOLE_MARKER = "POLYMARKET-WEB-SANDBOX-FIXTURE"


def _fake_console_text() -> str:
    """Content of the fake polymarket-web console script (simulated install)."""
    return f'#!/bin/bash\necho "{_FAKE_CONSOLE_MARKER}"\nexit 0\n'

_PY3_SHIM = f"""#!/bin/bash
# Sandbox python3 shim — models the interpreter version deterministically
# (offline; never executes real tooling). Fail-loud on unexpected invocations.
ver="${{SANDBOX_FAKE_PY_VERSION:?SANDBOX_FAKE_PY_VERSION must be set}}"
if [ "$1" = "--version" ]; then
    echo "Python ${{ver}}"
    exit 0
fi
if [ "$1" = "-c" ] && [ "$2" = '{_GUARD_CODE}' ]; then
    major="${{ver%%.*}}"
    rest="${{ver#*.}}"
    minor="${{rest%%.*}}"
    if [ "${{major}}" -lt 3 ] || {{ [ "${{major}}" -eq 3 ] && [ "${{minor}}" -lt 10 ]; }}; then
        exit 1
    fi
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    /bin/mkdir -p venv/bin
    printf 'export PATH="$(pwd)/venv/bin:$PATH"\\n' > venv/bin/activate
    exit 0
fi
echo "SANDBOX-PY3-UNEXPECTED: $*" >&2
exit 70
"""

_PIP_SHIM = f"""#!/bin/bash
# Sandbox pip shim — records invocations to pip.log; simulates the editable
# install by creating the fake polymarket-web console script. Fail-loud.
echo "pip $*" >> "$PWD/pip.log"
case "$*" in
    *"-e ."*)
        /bin/mkdir -p venv/bin
        printf '#!/bin/bash\\necho "{_FAKE_CONSOLE_MARKER}"\\nexit 0\\n' > venv/bin/polymarket-web
        /bin/chmod +x venv/bin/polymarket-web
        ;;
esac
exit 0
"""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_sandbox(tmp_path: Path, py_version: str) -> Path:
    """Hermetic sandbox: shim dir, byte-exact launcher copy, fake .env, empty HOME."""
    sb = tmp_path / "sb"
    (sb / "bin").mkdir(parents=True)
    (sb / "home").mkdir()
    (sb / LAUNCHER_NAME).write_bytes(LAUNCHER.read_bytes())
    assert _sha256_file(sb / LAUNCHER_NAME) == _sha256_file(LAUNCHER), (
        "byte-exact copy of start_web_dashboard.sh required (P-0018)"
    )
    for name, body in (("python3", _PY3_SHIM), ("pip", _PIP_SHIM)):
        shim = sb / "bin" / name
        shim.write_text(body, encoding="utf-8")
        shim.chmod(0o755)
    (sb / ".env").write_text(
        "POLYMARKET_API_KEY=sandbox\nPOLYGON_PRIVATE_KEY=sandbox\n", encoding="utf-8"
    )
    assert py_version in {"3.9.6", "3.12.0"}, f"unexpected sandbox python model {py_version}"
    return sb


def _run_launcher(sb: Path, py_version: str) -> subprocess.CompletedProcess[str]:
    """Run the COPY with a minimal sandbox env — no host PATH inheritance."""
    env = {
        "TERM": "dumb",
        "HOME": str(sb / "home"),
        "PATH": str(sb / "bin"),
        "SANDBOX_FAKE_PY_VERSION": py_version,
    }
    return subprocess.run(
        ["/bin/bash", str(sb / LAUNCHER_NAME)],
        capture_output=True,
        text=True,
        cwd=str(sb),
        env=env,
        timeout=60,
    )


@pytest.fixture(autouse=True)
def _tripwire_real_launcher():
    before = _sha256_file(LAUNCHER)
    yield
    assert _sha256_file(LAUNCHER) == before, "real start_web_dashboard.sh was modified"


def test_bash_n_valid(tmp_path: Path) -> None:
    """bash -n on a byte-exact copy of the launcher must succeed (rc=0)."""
    sb = _make_sandbox(tmp_path, "3.12.0")
    proc = subprocess.run(
        ["/bin/bash", "-n", str(sb / LAUNCHER_NAME)], capture_output=True, text=True
    )
    assert proc.returncode == 0, proc.stderr


def test_version_guard_rejects_old_python_fail_fast(tmp_path: Path) -> None:
    """A pre-3.10 python3 is rejected fail-fast: rc=1, ERROR message, NO venv/."""
    sb = _make_sandbox(tmp_path, "3.9.6")
    proc = _run_launcher(sb, "3.9.6")
    assert proc.returncode == 1, (proc.returncode, proc.stdout, proc.stderr)
    assert _GUARD_ERROR in proc.stdout, "version guard did not fire for 3.9.6"
    assert "(found: Python 3.9.6)" in proc.stdout, "guard did not report the found version"
    assert "SANDBOX-PY3-UNEXPECTED" not in proc.stderr, proc.stderr
    assert not (sb / "venv").exists(), "guard must fail-fast BEFORE creating any venv"
    assert not (sb / "pip.log").exists(), "pip must not be reached past the guard"


def test_version_guard_passes_with_310_plus(tmp_path: Path) -> None:
    """A 3.12 python3 passes the guard: the banner (next observable) appears."""
    sb = _make_sandbox(tmp_path, "3.12.0")
    proc = _run_launcher(sb, "3.12.0")
    assert _BANNER in proc.stdout, "launcher never reached the banner past the guard"
    assert _GUARD_ERROR not in proc.stdout, "guard fired on a 3.12 interpreter model"
    assert "SANDBOX-PY3-UNEXPECTED" not in proc.stderr, proc.stderr


def test_installs_package_when_console_script_missing(tmp_path: Path) -> None:
    """Missing console script: pip installs the package (upgrade, then -e .)."""
    sb = _make_sandbox(tmp_path, "3.12.0")
    proc = _run_launcher(sb, "3.12.0")
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    pip_log = sb / "pip.log"
    assert pip_log.exists(), "launcher never invoked pip"
    lines = pip_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, f"expected exactly 2 pip invocations, got {lines!r}"
    assert "--upgrade pip" in lines[0], f"upgrade must be the FIRST pip call: {lines!r}"
    assert "-e ." in lines[1], f"editable install must be the SECOND pip call: {lines!r}"
    assert _INSTALL_ECHO in proc.stdout, "install-block echo missing from the output"
    assert (sb / "venv" / "bin" / "polymarket-web").exists(), (
        "pip shim did not simulate the console script installation"
    )
    assert _FAKE_CONSOLE_MARKER in proc.stdout, (
        "launcher did not reach the final polymarket-web line (no rc=127)"
    )


def test_idempotent_when_package_installed(tmp_path: Path) -> None:
    """Console script already present: pip is NOT invoked and the start happens."""
    sb = _make_sandbox(tmp_path, "3.12.0")
    (sb / "venv" / "bin").mkdir(parents=True)
    (sb / "venv" / "bin" / "activate").write_text(
        'export PATH="$(pwd)/venv/bin:$PATH"\n', encoding="utf-8"
    )
    fake = sb / "venv" / "bin" / "polymarket-web"
    fake.write_text(_fake_console_text(), encoding="utf-8")
    fake.chmod(0o755)
    proc = _run_launcher(sb, "3.12.0")
    assert proc.returncode == 0, (proc.returncode, proc.stdout, proc.stderr)
    pip_log = sb / "pip.log"
    assert not pip_log.exists() or pip_log.read_text(encoding="utf-8") == "", (
        "idempotent run must not invoke pip at all"
    )
    assert _INSTALL_ECHO not in proc.stdout, "install block ran on an installed package"
    assert _FAKE_CONSOLE_MARKER in proc.stdout, "launcher did not start the dashboard"


def test_real_file_tripwire() -> None:
    """The REAL start_web_dashboard.sh is byte-identical across the test run (P-0013)."""
    before = _sha256_file(LAUNCHER)
    after = _sha256_file(LAUNCHER)
    assert before == after
