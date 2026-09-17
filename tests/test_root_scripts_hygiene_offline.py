"""Suíte de higiene da raiz do clone (offline, hermética).

Contrato T-0240: pins por CONTEÚDO/AUSÊNCIA (L-0023) — NUNCA contagens
de linhas/repos, que são voláteis (L-0023/L-0180). SKIP-de-infra para
o binário ruff ausente (L-0026); ruff FILE-SCOPED aos scripts raiz
(L-0233) — NUNCA repo-wide (os 31 erros semânticos F401/E722/F841 são
divergência EXPECTED, fora do subset zero-semântico).

Pyyaml não está em dev extras ainda (T-0225 done-unmerged): o teste do
YAML usa pytest.importorskip (L-0026).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ROOT_SCRIPTS = sorted(ROOT.glob("*.py"))


def test_no_author_absolute_paths_in_root_scripts() -> None:
    """Nenhum script raiz contém path absoluto do autor ou /Users/.

    Pin por AUSÊNCIA: o conteúdo dos 12 *.py da raiz não pode conter
    'caiovicentino' nem '/Users/' (paths absolutos do ambiente do
    autor não pertencem ao código commitado).
    """
    assert ROOT_SCRIPTS, "glob '*.py' na raiz não achou scripts — ambiente estranho"
    offenders: list[str] = []
    for script in ROOT_SCRIPTS:
        content = script.read_text(encoding="utf-8")
        if "caiovicentino" in content:
            offenders.append(f"{script.name}: contém 'caiovicentino'")
        if "/Users/" in content:
            offenders.append(f"{script.name}: contém '/Users/'")
    assert not offenders, f"paths absolutos do autor em {offenders}"


def test_mcp_connection_uses_path_file_relative() -> None:
    """Pin positivo: test_mcp_connection.py constrói paths via Path(__file__).

    O script é executável offline (`python3 test_mcp_connection.py`);
    o fix substitui paths absolutos por derivação relativa ao próprio
    arquivo — pin de PRESENCE do mecanismo (import equivalente a
    py_compile: arquivo parseável).
    """
    content = (ROOT / "test_mcp_connection.py").read_text(encoding="utf-8")
    assert "from pathlib import Path" in content, "import Path ausente"
    assert "Path(__file__)" in content, (
        "test_mcp_connection.py não deriva paths de Path(__file__)"
    )
    compile(content, "test_mcp_connection.py", "exec")  # arquivo parseável


def test_precommit_yaml_has_no_poetry_check_hook() -> None:
    """Nenhum repo do pre-commit é do poetry (poetry-check removido).

    O pyproject é hatchling (0 ocorrências de tool.poetry) — o hook
    poetry-check produzia FALSA falha em toda edição de pyproject.
    Sanity: repos é lista não-vazia e o hook pytest-fast (repo local)
    segue presente — a remoção não abriu buraco nos hooks vizinhos.
    """
    yaml = pytest.importorskip("yaml", reason="pyyaml não instalado (T-0225 adiciona)")
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    repos = config["repos"]
    assert isinstance(repos, list) and repos, "pre-commit config sem repos"
    poetry_repos = [r["repo"] for r in repos if "poetry" in str(r.get("repo", ""))]
    assert not poetry_repos, f"hook poetry presente: {poetry_repos}"
    hook_ids = {h.get("id") for r in repos for h in r.get("hooks", [])}
    assert "pytest-fast" in hook_ids, "pytest-fast ausente — hooks vizinhos removidos indevidamente"


def test_zero_semantic_ruff_subset_clean() -> None:
    """Ruff FILE-SCOPED nos scripts raiz: subset F541,I001,B905 limpo.

    O subset é ZERO-SEMÂNTICO: f-strings sem placeholder (F541),
    ordem de imports (I001) e zip sem strict= (B905 — fixado com
    strict=False, truncagem intencional). Os 31 erros semânticos
    F401/E722/F841 permanecem EXPECTED e fora deste subset.
    SKIP-de-infra (L-0026): sem binário ruff, o teste pula — não falha.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        candidate = Path(sys.executable).parent / "ruff"
        if candidate.is_file():
            ruff = str(candidate)
    if ruff is None:
        pytest.skip("binário ruff ausente no ambiente (SKIP-de-infra L-0026)")
    assert ROOT_SCRIPTS, "glob '*.py' na raiz não achou scripts — ambiente estranho"
    result = subprocess.run(
        [ruff, "check", *[s.name for s in ROOT_SCRIPTS], "--select", "F541,I001,B905"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"subset zero-semântico sujo (rc={result.returncode}): "
        f"{result.stdout}\n{result.stderr}"
    )
    assert "All checks passed" in result.stdout, (
        f"saída inesperada do ruff: {result.stdout!r}"
    )
