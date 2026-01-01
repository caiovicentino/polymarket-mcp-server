"""
Offline suite for the PEP 561 typing marker (src/polymarket_mcp/py.typed).

Contract anchor (T-0233): the package is 100% typed (mypy src/ = Success, 21
source files @ main 89edfa9) but shipped WITHOUT the PEP 561 marker — RED
pre-proven by the curator on main 89edfa9 (find src -name py.typed = 0).
Consumers of `pip install polymarket-mcp-server` get an "untyped" library
(imports become `Any` in THEIR mypy) even though the source is fully typed.
PEP 561 fixes this with a `py.typed` marker file inside the package
directory; the Hatchling build backend (pyproject [build-system]) auto-includes
the marker in built wheels — NO pyproject change required (curator probe:
[tool.hatch.build.targets.wheel] carries no include config and the built wheel
carries the marker, 32 entries, SERVER/CONFIG present).

Dual-state suite (L-0026/L-0094/L-0071):
- test_pytyped_marker_exists: always executable offline (committed file, ZERO
  infra) — anchored on ``__file__`` so it is cwd-independent (L-0011).
- test_wheel_includes_pytyped_marker: hermetic wheel build from a tmpdir COPY
  (pyproject.toml + README.md + src/ — exactly what pyproject references)
  via subprocess [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
  "-w", out_dir] with a 180s ceiling:
  * build fails (rc != 0 | no .whl | TimeoutExpired) -> pytest.skip with an
    EXPLICIT infra reason ("infra: wheel build indisponível
    (pip/rede/hatchling)") — offline hosts SKIP with the reason; CI (with
    network) runs GREEN. Sanctioned dual-state, NOT a suite weakness.
  * build OK + wheel generated -> the namelist MUST contain
    ``polymarket_mcp/py.typed`` (the REAL RED: marker missing while the build
    succeeds = genuine regression, L-0071) plus a sanity that
    ``polymarket_mcp/server.py`` and ``polymarket_mcp/config.py`` are present
    (absent = the COPY is broken — fail with a clear message, NOT infra).

Hermeticity (zero worktree pollution):
- The build NEVER runs in the worktree/clone: everything lives under
  ``tmp_path`` (pytest builtin); ``pip wheel`` runs with cwd=the COPY dir, so
  sdist/wheel artifacts land in tmpdir only. The copy excludes bytecode
  caches (ignore __pycache__/*.pyc — no stale .pyc may leak into the wheel).
- The only shared state is pip's HTTP cache outside the repo — not a repo
  artifact.

Declared divergences (L-0025):
- Ruff I001: the contract sketch put ``from pathlib import Path`` AFTER
  ``pytest``; the executable acceptance (ruff check) rejects that order
  (I001 — proven by probe before writing). Compliant order keeps the stdlib
  plain imports first with the stdlib from-import inside the stdlib block,
  before the third-party block. Executable acceptance wins.
- pytest-timeout interplay: the global per-test timeout is 120s
  (pyproject [tool.pytest.ini_options]) while the prescribed subprocess
  ceiling is 180s — in a pathological slow-network run the OUTER timeout
  fires first (FAIL, not skip). On CI/normal hosts the build finishes in
  seconds (hatchling is pip-cached), so this never fires; the prescribed
  180s is kept verbatim as the in-test ceiling (pyproject is out of scope).

Markers: none — the suite runs in the release gate selection
("not integration and not slow and not real_api and not performance").
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER = REPO_ROOT / "src" / "polymarket_mcp" / "py.typed"
WHEEL_ENTRY = "polymarket_mcp/py.typed"
SANITY_ENTRIES = ("polymarket_mcp/server.py", "polymarket_mcp/config.py")
INFRA_SKIP = "infra: wheel build indisponível (pip/rede/hatchling) — {detail}"


def test_pytyped_marker_exists():
    """The PEP 561 marker exists as a file inside the package (offline, no infra)."""
    assert MARKER.is_file(), (
        f"PEP 561 marker ausente: {MARKER} — consumidores de "
        "'pip install polymarket-mcp-server' recebem um pacote 'untyped' "
        "(imports viram Any no mypy deles) apesar do código-fonte 100% tipado."
    )


def test_wheel_includes_pytyped_marker(tmp_path):
    """A wheel built from a tmpdir COPY must ship the PEP 561 marker (dual-state)."""
    build_dir = tmp_path / "pkgcopy"
    out_dir = tmp_path / "wheels"
    build_dir.mkdir()
    out_dir.mkdir()

    # Copy ONLY what the build references: pyproject.toml + README.md ([project]
    # readme) + src/ (the package, WITH the marker). Bytecode caches are excluded
    # so no stale .pyc can leak into the wheel.
    shutil.copy2(REPO_ROOT / "pyproject.toml", build_dir / "pyproject.toml")
    shutil.copy2(REPO_ROOT / "README.md", build_dir / "README.md")
    shutil.copytree(
        REPO_ROOT / "src",
        build_dir / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    cmd = [sys.executable, "-m", "pip", "wheel", ".", "--no-deps", "-w", str(out_dir)]
    try:
        proc = subprocess.run(
            cmd, cwd=str(build_dir), capture_output=True, text=True, timeout=180
        )
    except subprocess.TimeoutExpired as exc:
        pytest.skip(
            INFRA_SKIP.format(
                detail=f"timeout após 180s ({type(exc).__name__}): {exc}"
            )
        )

    wheels = sorted(out_dir.glob("*.whl"))
    if proc.returncode != 0 or not wheels:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        pytest.skip(
            INFRA_SKIP.format(detail=f"rc={proc.returncode}, wheels={len(wheels)}: {detail}")
        )

    our_wheels = [w for w in wheels if w.name.startswith("polymarket_mcp-")]
    assert our_wheels, (
        f"CÓPIA/config quebrada: wheels gerados {[w.name for w in wheels]} não são do pacote "
        "polymarket_mcp — revisar a cópia tmpdir (falha clara, NÃO é infra)."
    )

    with zipfile.ZipFile(our_wheels[0]) as zf:
        names = set(zf.namelist())

    # Sanity FIRST: a broken copy would make the marker verdict meaningless.
    missing_sanity = [n for n in SANITY_ENTRIES if n not in names]
    assert not missing_sanity, (
        f"CÓPIA quebrada: {missing_sanity} ausente(s) no namelist do wheel — a build não "
        "empacotou o pacote copiado (falha clara, NÃO é infra)."
    )

    # THE dual-state RED: build OK + copy intact + marker absent = real regression.
    assert WHEEL_ENTRY in names, (
        f"Wheel NÃO embarca o marker PEP 561 ({WHEEL_ENTRY} ausente do namelist): consumidores "
        "de 'pip install' recebem um pacote untyped. O marker é auto-incluído pelo hatchling — "
        "se falhar com src/polymarket_mcp/py.typed presente, algo removeu o arquivo ou mudou "
        "o build backend (ver pyproject [tool.hatch.build])."
    )
