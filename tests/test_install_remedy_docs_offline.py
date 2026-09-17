"""Offline suite: installation remedy docs give the correct tkinter remedy.

Contract: farm(T-0247) - this suite is the slice's acceptance harness (provenance below).

Bug (pre-fix, RED proven on main 7d91856 — first-hand probes from mission
increment 38, re-proven in this slice's preflight):

1. QUICKSTART_GUIDE.md ("Wizard won't start" block) and
   INSTALLATION_COMPARISON.md ("Common Installation Issues > GUI Wizard")
   taught `pip install tk`. First-hand provenance: the PyPI wheel `tk` 0.1.0
   fetched via `pip download tk --no-deps` is TensorKit ("deep learning
   helper between Python and C++" in its METADATA; ships
   `tk/structure/Tensor.py`) — NOT tkinter. tkinter ships with the Python
   interpreter build itself (stdlib bound to the interpreter build; the
   `import tkinter` probe failed in the repo venv). A user following the doc
   installs the WRONG package: the wizard stays broken and the environment
   gets polluted (L-0178 class: remedy that silently "succeeds").
2. INSTALLATION_COMPARISON.md ("From Demo to Full > Auto Script") taught
   `./install.sh --upgrade-to-full`. First-hand provenance: the arg parser of
   `install.sh` accepts ONLY `--demo`/`--skip-claude`/`--help`; a real run in
   a HOME sandbox prints `Unknown option: --upgrade-to-full` and exits 1.
   Re-proven on main: `bash install.sh --help` lists exactly those three
   flags (the script's own help does NOT mention INSTALLATION.md — so the fix
   note points to the section DIRECTLY, never claiming the script points to
   it).

Fix under test (2 files, content-anchored — nothing else):
1. QUICKSTART_GUIDE.md: the broken remedy becomes an explanatory note
   (tkinter ships with the interpreter build; `tk` on PyPI is unrelated) plus
   OS-specific remedies (macOS Homebrew: `brew install python-tk`;
   Debian/Ubuntu: `sudo apt install python3-tk`) with the existing
   `./install.sh` fallback preserved verbatim.
2. INSTALLATION_COMPARISON.md: the Auto Script block runs plain
   `./install.sh` with a note stating the script has no mode-switch flag and
   pointing at the REAL documented path: INSTALLATION.md
   "Switching from DEMO to Full Mode"; the GUI Wizard fix line mirrors the
   OS-specific remedies.

House rules applied:
- L-0056/L-0079: every negation (absence of the broken remedy) is paired with
  a positive presence assertion (the correct remedy) in the same test.
- L-0070: assertions anchor on CONTENT (exact literals), never line numbers.
- Explicit encoding for Windows CI (cp1252 locale): every doc read passes `encoding="utf-8"` (repo precedent: tests/test_web_xss_offline.py).
- Scope guard: this suite READS INSTALLATION.md (the referenced section must
  exist — guard against breaking the cross-reference in this slice) but never
  writes it; INSTALLATION.md is not part of this slice's allow-scope.
- Pure text tests: no network, no disk writes, no docker — offline by design.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
QUICKSTART = REPO_ROOT / "QUICKSTART_GUIDE.md"
COMPARISON = REPO_ROOT / "INSTALLATION_COMPARISON.md"
INSTALLATION = REPO_ROOT / "INSTALLATION.md"

BROKEN_REMEDY = "pip install tk"
CORRECT_MACOS_REMEDY = "brew install python-tk"
CORRECT_APT_REMEDY = "apt install python3-tk"
GHOST_FLAG = "upgrade-to-full"
MODE_SWITCH_SECTION = "Switching from DEMO to Full Mode"
AUTOMATED_FALLBACK = "./install.sh"


def test_no_pip_install_tk_remedy():
    """The TensorKit remedy (`pip install tk`) is gone; correct remedy present."""
    for doc, name in ((QUICKSTART, "QUICKSTART_GUIDE.md"), (COMPARISON, "INSTALLATION_COMPARISON.md")):
        content = doc.read_text(encoding="utf-8")
        assert BROKEN_REMEDY not in content, (
            f"{name} still teaches `pip install tk` — the PyPI `tk` wheel is "
            "TensorKit, not tkinter (bug provenance: mission increment 38)"
        )
        # Paired positive (L-0056): the correct macOS remedy must be present.
        assert CORRECT_MACOS_REMEDY in content, (
            f"{name} is missing the corrected remedy `{CORRECT_MACOS_REMEDY}`"
        )


def test_no_upgrade_to_full_flag():
    """The never-existing `--upgrade-to-full` flag is gone; real section referenced."""
    content = COMPARISON.read_text(encoding="utf-8")
    assert GHOST_FLAG not in content, (
        "INSTALLATION_COMPARISON.md still teaches `--upgrade-to-full` — "
        "install.sh's parser accepts only --demo/--skip-claude/--help "
        "(bug provenance: mission increment 38)"
    )
    # Paired positive (L-0056): the note points at the REAL documented path.
    assert MODE_SWITCH_SECTION in content, (
        "INSTALLATION_COMPARISON.md no longer references the "
        f"`{MODE_SWITCH_SECTION}` section the remedy note should point to"
    )


def test_os_specific_remedies_present():
    """Both docs carry the Debian/Ubuntu remedy and the fallback stays."""
    for doc, name in ((QUICKSTART, "QUICKSTART_GUIDE.md"), (COMPARISON, "INSTALLATION_COMPARISON.md")):
        content = doc.read_text(encoding="utf-8")
        assert CORRECT_APT_REMEDY in content, (
            f"{name} is missing the Debian/Ubuntu remedy `{CORRECT_APT_REMEDY}`"
        )
    # The existing automated-script fallback must remain (verbatim preserved).
    assert AUTOMATED_FALLBACK in QUICKSTART.read_text(encoding="utf-8"), (
        "QUICKSTART_GUIDE.md lost the `./install.sh` fallback in the "
        "`Wizard won't start` block"
    )


def test_installation_md_reference_section_exists():
    """The referenced INSTALLATION.md section exists and the anchor slug matches."""
    content = INSTALLATION.read_text(encoding="utf-8")
    heading = f"### {MODE_SWITCH_SECTION}"
    assert heading in content, (
        "INSTALLATION.md lost the section the remedy note points to — the "
        "cross-reference in INSTALLATION_COMPARISON.md would dangle"
    )
    # The note's markdown anchor must slugify from the heading it claims to
    # reference (GitHub-style: lowercase, spaces -> dashes).
    note = COMPARISON.read_text(encoding="utf-8")
    anchor = "INSTALLATION.md#switching-from-demo-to-full-mode"
    assert anchor in note, (
        "INSTALLATION_COMPARISON.md does not link the referenced section "
        f"({anchor})"
    )
    slug = heading.lstrip("#").strip().lower().replace(" ", "-")
    assert slug == "switching-from-demo-to-full-mode", (
        f"anchor/slug mismatch: heading `{heading}` slugifies to `{slug}`, "
        "so the note's anchor would not resolve"
    )
