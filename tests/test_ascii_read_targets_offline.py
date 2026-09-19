"""Read targets of bare read_text() in tests/ are PURE ASCII (Windows CI guard).

Incident (origin/main CI, 7 consecutive red runs since PR #77, 2026-09-18):
the Windows job crashes with UnicodeDecodeError 'charmap' codec on
TRADING_ARCHITECTURE.md (byte 0x90) and CHANGELOG.md (byte 0x8f). Root
cause: tests/test_trading_architecture_offline.py calls Path.read_text()
WITHOUT an encoding= argument, so on Windows it decodes with the locale
codec (cp1252) - and the files carry UTF-8 multi-byte content (box-drawing
diagrams, emoji headers) whose continuation bytes are INVALID in cp1252.

Agent-side fix (this slice): make the five read targets PURE ASCII, so
ANY locale codec decodes them identically:
- TRADING_ARCHITECTURE.md: box-drawing diagrams converted 1:1
  (- | # + .) - alignment preserved, every registered tool name and all
  test anchors intact (tests/test_trading_architecture_offline.py passes
  unchanged; it was RED on Windows for the decode, not the content).
- CHANGELOG.md: the two emoji headers (U+26A0 U+FE0F, U+1F389) carry the
  cp1252-invalid bytes 0x8f/0x8e - headers de-emoji'd, text preserved.
- k8s/configmap.yaml, k8s/secret.yaml.template, k8s/README.md: one em-dash
  each in a comment (latent trap: cp1252-decodable TODAY, but any byte
  edit could reintroduce an invalid one) - em-dash -> "--".

The canonical encoding= fix in the tests themselves is REQUER-HUMANO
(item 156) - complementary defense, not replaced by this slice.

This suite is the drift guard: any future merge that reintroduces
non-ASCII content into one of the five read targets fails here (P-0007).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# The five files read by tests/ via read_text() WITHOUT an encoding=
# argument (enumerated by grep, item 156): the two CI-crash sources plus
# the three latent traps in k8s/.
READ_TARGETS = (
    "TRADING_ARCHITECTURE.md",
    "CHANGELOG.md",
    "k8s/configmap.yaml",
    "k8s/secret.yaml.template",
    "k8s/README.md",
)


@pytest.mark.parametrize("target", READ_TARGETS)
def test_read_target_is_pure_ascii(target):
    """Every bare-read_text target must decode identically in ANY locale.

    pure ASCII <=> utf-8, cp1252, latin-1, ascii all produce the same
    string, so Path.read_text() without encoding= can never crash.
    """
    raw = (REPO_ROOT / target).read_bytes()
    non_ascii = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert non_ascii == [], (
        f"{target} carries {len(non_ascii)} non-ASCII byte(s) "
        f"(first: offsets {[off for off, _ in non_ascii[:5]]}) - the Windows "
        "CI read_text() (cp1252) will crash or mojibake on these; convert "
        "to ASCII (em-dash -> --, box-drawing -> -|#+, emoji -> text)"
    )
    # Belt-and-suspenders: cp1252 must decode without error (the exact
    # Windows failure mode).
    (REPO_ROOT / target).read_text(encoding="cp1252")


def test_architecture_anchors_survive_conversion():
    """The ASCII conversion preserved the doc's test anchors (positive pair)."""
    body = (REPO_ROOT / "TRADING_ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "Tool routing (canonical registry, see Tool Registry section)" in body
    assert "## Tool Registry (canonical)" in body


def test_changelog_anchors_survive_de_emoji():
    """The CHANGELOG header texts survive without the emoji (positive pair)."""
    body = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "### Breaking Changes" in body
    assert "### Initial Public Release" in body
