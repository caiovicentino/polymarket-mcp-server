"""Offline suite for the Makefile backup/restore volume-name resolution (T-0235).

Contract pins (curator-proven design, /tmp/c53-mk-sim -- sandbox with a stub
``docker``):

- ``make backup``/``make restore`` must resolve the compose volume name
  DYNAMICALLY via ``docker compose config --format json`` (client-side render;
  the docker daemon is NOT required) and fail LOUD ("Error: could not resolve
  the data volume name", rc!=0, no "Backup complete") when discovery fails
  (compose rc=1 with empty stdout OR garbage stdout -> tolerant parser yields
  an empty name). NEVER a silent fallback: before this fix Makefile:144/:155
  hardcode ``polymarket-mcp_polymarket-data`` while compose resolves
  ``<project>_polymarket-data`` (project = the directory name) --
  ``docker run -v <inexistent>`` then silently CREATES an empty volume -> empty
  tar -> "Backup complete" printed with an EMPTY backup (silent data loss, P1),
  and ``make restore`` writes into the wrong volume.
- The pre-existing restore guard ("No backups found") stays FIRST: with no
  backups the recipe fails BEFORE touching docker at all (guard precedes
  discovery -- order pin below).
- Mounts use ``$(CURDIR)/backups``: GNU make does NOT re-set PWD (first-hand
  probe: subprocess with cwd=simB + stale env PWD expanded the STALE dir;
  ``$(CURDIR)`` expands the real cwd).

Hermeticity (P-0031 fail-loud stubs / P-0012 PATH-local CLI stub / zero
network): ``docker`` is a stub dispatched on argv, PATH-local per subprocess;
it logs EVERY invocation to ``stub.log`` and fails loudly (exit 99) on
unexpected calls -- reaching the real docker binary (daemon/volumes) is
impossible by construction. The one real-docker probe
(``test_real_compose_render_has_volume_name``) only renders the compose
configuration client-side (daemon DOWN on this host, proven by the curator and
re-proven here) and is SKIP-de-infra (L-0026) when the ``docker`` CLI is
absent; the make-based tests are SKIP-de-infra when ``make`` is absent.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_STUB_JSON = (
    '{"name":"sandbox_polymarket-mcp-server",'
    '"volumes":{"polymarket-data":'
    '{"name":"sandbox_polymarket-mcp-server_polymarket-data","driver":"local"}}}'
)

# Stub dispatched on docker argv. Fail-loud (P-0031): unexpected calls exit 99
# so a silent fallback to the real binary is impossible. Modes (DOCKER_STUB_MODE):
# happy (default) -> compose config emits the fixed JSON, run -> rc=0;
# compose_fail     -> compose config exits 1 (stdout empty);
# garbage          -> compose config emits non-JSON stdout (rc=0).
_STUB_TEMPLATE = r"""#!/bin/bash
# T-0235 stub: dispatches on docker argv; unexpected calls fail loud (P-0031).
LOG="${DOCKER_STUB_LOG:?DOCKER_STUB_LOG not set}"
printf '%s\n' "$*" >> "$LOG"
MODE="${DOCKER_STUB_MODE:-happy}"
if [ "$1" = "compose" ] && [ "$2" = "config" ]; then
  case "$MODE" in
    happy) printf '%s\n' '__JSON__' ;;
    compose_fail) exit 1 ;;
    garbage) printf '%s\n' 'not-json-garbage' ;;
    *) echo "DOCKER_STUB: unexpected compose mode: $MODE" >&2; exit 99 ;;
  esac
  exit 0
fi
if [ "$1" = "run" ]; then
  exit 0
fi
echo "DOCKER_STUB: unexpected docker call: $*" >&2
exit 99
"""

_MAKE_REQUIRED = pytest.mark.skipif(
    shutil.which("make") is None, reason="make not available (infra skip, L-0026)"
)
_DOCKER_REQUIRED = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI not available (infra skip, L-0026)"
)


def _sandbox(tmp_path: Path) -> Path:
    """Byte-exact copies of the real Makefile + compose file + stub docker."""
    for name in ("Makefile", "docker-compose.yml"):
        shutil.copy2(_ROOT / name, tmp_path / name)
        assert (tmp_path / name).read_bytes() == (_ROOT / name).read_bytes()  # L-0232
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(_STUB_TEMPLATE.replace("__JSON__", _STUB_JSON))
    stub.chmod(0o755)
    return tmp_path


def _run_make(
    tmp_path: Path, target: str, mode: str = "happy"
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["DOCKER_STUB_LOG"] = str(tmp_path / "stub.log")
    env["DOCKER_STUB_MODE"] = mode
    return subprocess.run(
        ["make", target],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _stub_log(tmp_path: Path) -> str:
    log = tmp_path / "stub.log"
    return log.read_text() if log.exists() else ""


@_MAKE_REQUIRED
def test_backup_uses_resolved_volume_name(tmp_path):
    tmp = _sandbox(tmp_path)
    proc = _run_make(tmp, "backup")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    log = _stub_log(tmp)
    assert "sandbox_polymarket-mcp-server_polymarket-data" in log
    assert "polymarket-mcp_polymarket-data" not in log  # silent-loss hardcode gone
    assert "Backup complete" in proc.stdout
    assert "tar czf /backup/data-backup-" in log  # the run invoked IS the backup tar


@_MAKE_REQUIRED
def test_backup_fails_loud_when_compose_config_fails(tmp_path):
    tmp = _sandbox(tmp_path)
    proc = _run_make(tmp, "backup", "compose_fail")
    assert proc.returncode != 0
    assert "could not resolve the data volume name" in (proc.stdout + proc.stderr)
    assert "Backup complete" not in proc.stdout
    log = _stub_log(tmp)
    # fail-loud guard runs BEFORE docker run (no run call in the log)
    assert not any(line.startswith("run ") for line in log.splitlines())


@_MAKE_REQUIRED
def test_backup_fails_loud_on_garbage_render(tmp_path):
    tmp = _sandbox(tmp_path)
    proc = _run_make(tmp, "backup", "garbage")
    assert proc.returncode != 0
    out = proc.stdout + proc.stderr
    assert "could not resolve the data volume name" in out
    assert "Backup complete" not in proc.stdout
    assert "Traceback" not in out  # tolerant parser: no noisy traceback leaks
    assert not any(line.startswith("run ") for line in _stub_log(tmp).splitlines())


@_MAKE_REQUIRED
def test_restore_guard_no_backups_preserved(tmp_path):
    tmp = _sandbox(tmp_path)
    proc = _run_make(tmp, "restore")
    assert proc.returncode != 0
    assert "No backups found" in proc.stdout
    log = _stub_log(tmp)
    assert not any(line.startswith("run ") for line in log.splitlines())
    # order pin: the guard runs BEFORE discovery -> zero docker invocations at all
    assert "compose" not in log
    assert "run" not in log


@_MAKE_REQUIRED
def test_restore_uses_resolved_volume_name(tmp_path):
    tmp = _sandbox(tmp_path)
    (tmp / "backups").mkdir()
    (tmp / "backups" / "old.tar.gz").write_bytes(b"")  # empty file suffices
    proc = _run_make(tmp, "restore")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    log = _stub_log(tmp)
    assert "sandbox_polymarket-mcp-server_polymarket-data" in log
    assert "polymarket-mcp_polymarket-data" not in log
    assert "tar xzf /backup/old.tar.gz" in log
    assert "Restoring from" in proc.stdout
    assert "Restore complete" in proc.stdout


@_DOCKER_REQUIRED
def test_real_compose_render_has_volume_name(tmp_path):
    """Real compose render, client-side only (no daemon required -- proven)."""
    for name in ("Makefile", "docker-compose.yml"):
        shutil.copy2(_ROOT / name, tmp_path / name)
        assert (tmp_path / name).read_bytes() == (_ROOT / name).read_bytes()  # L-0232
    proc = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    data = json.loads(proc.stdout)
    volume_name = data.get("volumes", {}).get("polymarket-data", {}).get("name", "")
    assert volume_name, proc.stdout
    assert volume_name.endswith("_polymarket-data")  # project-prefixed by compose
