"""Offline suite for Makefile hygiene (T-0284): version derivation, .PHONY
coverage, and the restore tar guard.

Contract provenance: Makefile hygiene slice, curator 2026-09-18, reference
branch ``sim/c62-mf`` @ 9758219 (sibling suite T-0235 proven 6/6 green
against the patched Makefile).

Bugs pinned (RED pre proven first-hand by the curator on main b240bb9):

- BUG 1 (anti-drift, lessons L-0023/L-0070): the Makefile hardcodes
  ``VERSION := 0.1.0`` while the package source of truth
  (``src/polymarket_mcp/__init__.py`` -- the very file pyproject/hatch reads)
  declares ``__version__ = "0.2.0"``. ``make -n build-multi`` renders the
  STALE tag ``polymarket-mcp:0.1.0``. Fix: derive VERSION with
  ``$(shell sed -n ... src/polymarket_mcp/__init__.py)`` so the next package
  bump stays green without touching the Makefile (derive, never update the
  literal).
- BUG 2: ``.PHONY`` lists only 9 of the recipe targets; when a file happens
  to match a non-.PHONY target name (e.g. ``env``, ``stats``) make treats it
  as a file rule and silently skips the recipe. Fix: full target set.
- BUG 3: the restore guard only checks that ``backups/`` is non-empty, so a
  directory holding non-tar garbage (``notes.txt``) PASSES the guard and
  falls into docker volume discovery / ``tar xzf`` instead of failing loud
  with "No backups found". Fix: the guard requires ``backups/*.tar.gz``
  ("No backups found" message and guard-before-discovery order preserved --
  T-0235 pins).

Hermeticity (P-0031 fail-loud stubs / P-0012 PATH-local CLI stub / zero
network): the sandbox is a tmp_path with byte-exact copies of the Makefile +
docker-compose.yml + ``src/polymarket_mcp/__init__.py`` (needed so the
VERSION ``$(shell sed ...)`` expansion can read the source of truth inside
the sandbox); ``docker`` is a stub dispatched on argv (logs EVERY invocation
to stub.log and fails loud exit 99 on unexpected calls -- reaching the real
docker binary is impossible by construction; anatomy mirrored from the
T-0235 sibling suite, re-created inline per zero-config FA-0079, never
imported). ``make -n`` (dry run) executes NOTHING -- it only echoes recipes
with variables expanded, so no docker invocation can happen there either.
``make``-based tests are SKIP-de-infra (L-0026) when make is absent.
"""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_IMAGE_NAME = "polymarket-mcp"

# Synthetic compose render (mirror of the real one: volume key
# "polymarket-data", project-prefixed name -- the Makefile parser reads
# ``volumes.polymarket-data.name`` from this JSON).
_STUB_JSON = (
    '{"name":"sandbox_polymarket-mcp-server",'
    '"volumes":{"polymarket-data":'
    '{"name":"sandbox_polymarket-mcp-server_polymarket-data","driver":"local"}}}'
)
_SYNTHETIC_VOLUME = "sandbox_polymarket-mcp-server_polymarket-data"

# Stub dispatched on docker argv. Fail-loud (P-0031): unexpected calls exit
# 99 so a silent fallback to the real binary is impossible. Default happy
# mode: ``compose config`` emits the fixed JSON, ``run`` logs and rc=0.
_STUB_TEMPLATE = r"""#!/bin/bash
# T-0284 stub: dispatches on docker argv; unexpected calls fail loud (P-0031).
LOG="${DOCKER_STUB_LOG:?DOCKER_STUB_LOG not set}"
printf '%s\n' "$*" >> "$LOG"
if [ "$1" = "compose" ] && [ "$2" = "config" ]; then
  printf '%s\n' '__JSON__'
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


def _package_version() -> str:
    """Derive the expected version AT RUNTIME from the package source of
    truth (never hardcode it -- the next package bump keeps this suite
    green, L-0023/L-0070). Fail loud if the source is unparsable."""
    src = (_ROOT / "src" / "polymarket_mcp" / "__init__.py").read_text(
        encoding="utf-8"
    )
    match = re.search(r'^__version__ = "([^"]+)"', src, flags=re.M)
    assert match, (
        "package source of truth unparsable: no `__version__ = \"...\"` line "
        "found in src/polymarket_mcp/__init__.py"
    )
    version = match.group(1)
    assert version, "package source of truth yielded an empty version"
    return version


def _sandbox(tmp_path: Path) -> Path:
    """Byte-exact copies of the real Makefile + compose file + the package
    version source of truth + stub docker (L-0232 asserts)."""
    for relpath in (
        "Makefile",
        "docker-compose.yml",
        "src/polymarket_mcp/__init__.py",
    ):
        target = tmp_path / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_ROOT / relpath, target)
        assert target.read_bytes() == (_ROOT / relpath).read_bytes()  # L-0232
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text(_STUB_TEMPLATE.replace("__JSON__", _STUB_JSON), encoding="utf-8")
    stub.chmod(0o755)
    return tmp_path


def _run_make(
    tmp_path: Path, target: str, dry_run: bool = False
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{tmp_path / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env["DOCKER_STUB_LOG"] = str(tmp_path / "stub.log")
    cmd = ["make"]
    if dry_run:
        cmd.append("-n")
    cmd.append(target)
    return subprocess.run(
        cmd,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def _stub_log(tmp_path: Path) -> str:
    log = tmp_path / "stub.log"
    return log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""


@_MAKE_REQUIRED
def test_version_derived_from_package_source(tmp_path):
    """Anti-drift (L-0023/L-0070) done right: the expected version is derived
    at runtime from the package source of truth, and ``make -n build-multi``
    renders the tag ``<image>:<derived-version>``. Against the pristine
    Makefile this is RED (stale 0.1.0 hardcoded while the package says 0.2.0);
    after the fix the test never needs updating when the package bumps."""
    tmp = _sandbox(tmp_path)
    expected = _package_version()
    proc = _run_make(tmp, "build-multi", dry_run=True)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert f"{_IMAGE_NAME}:{expected}" in proc.stdout, (proc.stdout, proc.stderr)
    assert f"-t {_IMAGE_NAME}:{expected}" in proc.stdout, (proc.stdout, proc.stderr)
    # The dry run executes nothing: no docker invocation may land in the log.
    assert _stub_log(tmp) == ""


def test_phony_covers_all_targets(tmp_path):
    """Parse-only pin: EVERY recipe target declared in the Makefile must be
    listed on the .PHONY line (a target missing from .PHONY is shadowed when
    a file of the same name exists -- make then treats the recipe as a file
    rule and silently skips it). RED pre: 15 targets missing."""
    tmp = _sandbox(tmp_path)
    makefile = (tmp / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-z][a-z0-9-]*):", makefile, flags=re.M))
    assert targets, "no targets parsed from the sandbox Makefile (copy broken?)"
    phony_line = None
    for line in makefile.splitlines():
        if line.startswith(".PHONY:"):
            phony_line = line
            break
    assert phony_line is not None, ".PHONY line missing from the Makefile"
    phony = set(phony_line.split()[1:])
    assert phony, ".PHONY line declares no targets"
    missing = sorted(targets - phony)
    assert not missing, f"targets missing from .PHONY: {missing}"


@_MAKE_REQUIRED
def test_restore_guard_rejects_non_tar_backups(tmp_path):
    """BUG 3 pin: a non-empty ``backups/`` directory WITHOUT any ``.tar.gz``
    must fail loud at the guard ("No backups found", rc!=0) BEFORE any docker
    discovery/run (order pin extended from T-0235 -- zero docker invocations
    of any kind, not just zero ``run``). RED pre: the old guard accepted the
    non-tar garbage and the flow fell into docker discovery/extract."""
    tmp = _sandbox(tmp_path)
    (tmp / "backups").mkdir()
    (tmp / "backups" / "notes.txt").write_text("not a backup\n")
    proc = _run_make(tmp, "restore")
    assert proc.returncode != 0, (proc.stdout, proc.stderr)
    assert "No backups found" in proc.stdout, (proc.stdout, proc.stderr)
    assert _stub_log(tmp) == "", "docker was invoked before the tar guard"


@_MAKE_REQUIRED
def test_restore_happy_path_with_tar_still_works(tmp_path):
    """Compat pin (T-0235 sibling test_restore_uses_resolved_volume_name):
    the tar-guard fix must NOT regress the happy path -- a real ``.tar.gz``
    file restores through dynamic volume discovery (stub) with the exact
    observed strings ("Restoring from", "Restore complete", resolved
    synthetic volume name, ``tar xzf /backup/<file>``)."""
    tmp = _sandbox(tmp_path)
    (tmp / "backups").mkdir()
    (tmp / "backups" / "old.tar.gz").write_bytes(b"")  # empty bytes suffice
    proc = _run_make(tmp, "restore")
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    log = _stub_log(tmp)
    assert _SYNTHETIC_VOLUME in log, log
    assert "tar xzf /backup/old.tar.gz" in log, log
    assert "Restoring from" in proc.stdout, (proc.stdout, proc.stderr)
    assert "Restore complete" in proc.stdout, (proc.stdout, proc.stderr)
