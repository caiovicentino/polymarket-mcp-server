"""Offline pins for artifact-hygiene files (.dockerignore / .gitignore).

The bare `venv/` pattern does not match dot-prefixed directories under Docker's
filepath matching or gitignore semantics, so `.venv/` (253 MB), `.mypy_cache/`
(19 MB) and the farm's `.worktrees/` (1.6 GB) leak into the docker build
context and `git status` noise. This suite pins the corrected patterns in both
files, guards the pre-existing patterns against regression, and pins the
Dockerfile COPY lines (the fix must not touch image content - context size
only).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = (".venv/", ".mypy_cache/", ".ruff_cache/", ".worktrees/")


def _lines(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]


def test_dockerignore_excludes_dot_prefixed_caches():
    lines = _lines(ROOT / ".dockerignore")
    for pattern in (".venv/", ".mypy_cache/", ".ruff_cache/", ".worktrees/"):
        assert pattern in lines, f".dockerignore missing dot-prefixed pattern {pattern!r}"


def test_dockerignore_keeps_bare_venv_pattern():
    """Doc followers create `venv/` (CONTRIBUTING.md:40); the bare pattern must survive."""
    lines = _lines(ROOT / ".dockerignore")
    for pattern in ("venv/", "env/", "ENV/"):
        assert pattern in lines, f"pre-existing pattern {pattern!r} removed (regression)"


def test_dockerignore_has_no_orphan_negation():
    """`!pyproject.toml` after `*.yaml` matched nothing (toml != yaml) - no-op removed."""
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "!pyproject.toml" not in text, "no-op negation still present"


def test_dockerignore_documents_the_dot_prefix_rule():
    lines = [ln for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines() if ln.strip()]
    comments = [ln for ln in lines if ln.startswith("#") and "dot-prefixed" in ln]
    assert comments, "expected a comment explaining why dot-prefixed patterns are required"


def test_gitignore_excludes_dot_prefixed_caches_and_worktrees():
    lines = _lines(ROOT / ".gitignore")
    for pattern in (".venv/", ".mypy_cache/", ".ruff_cache/", ".worktrees/"):
        assert pattern in lines, f".gitignore missing dot-prefixed pattern {pattern!r}"


def test_gitignore_keeps_bare_venv_patterns():
    lines = _lines(ROOT / ".gitignore")
    for pattern in ("venv/", "env/", "ENV/"):
        assert pattern in lines, f"pre-existing pattern {pattern!r} removed (regression)"


def test_dockerfile_copy_lines_untouched():
    """The hygiene fix changes context size only - the image content must be identical."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for expected in ("COPY pyproject.toml README.md ./", "COPY src/ ./src/"):
        assert expected in dockerfile, f"Dockerfile COPY line changed: {expected!r}"


def test_both_files_stay_ascii_only():
    for name in (".dockerignore", ".gitignore"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert text.isascii(), f"{name} must stay ASCII-only (item 147 / FA-0079 class)"
