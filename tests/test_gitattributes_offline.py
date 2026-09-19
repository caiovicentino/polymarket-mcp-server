"""Suíte de contrato do .gitattributes (offline, hermética).

Contrato T-0329: o checkout do Windows CI (actions/checkout em
windows-latest, com o autocrlf=true global do Git for Windows do
runner) converte o working tree para CRLF e quebra as âncoras
byte-exatas das suítes offline — evidencia: CI run 35412982363,
``tests/test_docker_start_offline.py::test_template_byte_parity``
assert 0 == 1 (a ancora ``b\"        cat > .env << 'EOF'\\n\"`` nao
casa com CRLF). Os offsets CRLF ja foram reconciliados 1a mao em
T-0315 (#100): CHANGELOG byte 0x8f em 305 raw = 316 no CI. O fix
prescrito e o arquivo .gitattributes na raiz do clone com a regra
UNICA ``* text=auto eol=lf``: ``eol=lf`` sobrescreve o autocrlf
global do runner, forçando LF no working tree de TODAS as
plataformas; ``text=auto`` mantem a auto-deteccao de binarios.

Pins por CONTEUDO/AUSENCIA (L-0023), nunca contagens voláteis
(L-0023/L-0180). Leitores de BLOB sempre via ``git show`` subprocess
com env sanitizado (P-0029) — NUNCA read do working tree para checks
de line-ending (checkouts humanos podem carregar CRLF local);
``git show`` devolve o blob CRU, imune a autocrlf/eol-attributes.
Leitores de texto SEMPRE com ``encoding=\"utf-8\"`` (P-0099, item 156).
ASCII-only no arquivo de config do git (item 147). Cross-platform-safe
desde o nascimento (item 147b): sem imports POSIX-only.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITATTR = ROOT / ".gitattributes"
RULE = "* text=auto eol=lf"
KEY_BLOBS = ("docker-start.sh", "install.sh", "test-docker.sh", ".env.example")


def _git_env() -> dict[str, str]:
    """Env sanitizado do subprocess git (P-0029): minimo explicito.

    GIT_CONFIG_GLOBAL/SYSTEM apontando para o devnull isola a invocacao
    da config global/system do executor (autocrlf do host nao pode
    afetar a observacao dos blobs; ``git show`` devolve o blob cru de
    qualquer forma, mas a higiene e declarativa e barata).
    """
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": os.environ.get("HOME", os.defpath),
        "LC_ALL": "C",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def _git_show_bytes(path: str) -> bytes:
    """Blob CRU do HEAD via ``git show <path>`` (bytes — imune a autocrlf)."""
    proc = subprocess.run(
        ["git", "show", f"HEAD:{path}"],
        cwd=str(ROOT),
        capture_output=True,
        env=_git_env(),
        check=False,
    )
    assert proc.returncode == 0, (
        f"git show HEAD:{path} falhou (rc={proc.returncode}): "
        f"{proc.stderr.decode('utf-8', errors='replace')!r}"
    )
    return proc.stdout


def test_gitattributes_exists_and_rule_present() -> None:
    """O arquivo existe; a regra ``* text=auto eol=lf`` presente EXATAMENTE 1x.

    Pin content-anchored (L-0070): por substring (a regra literal
    aparece uma unica vez) E por linha (exatamente uma linha cujo
    conteudo stripped e a regra — impossivel a regra vazar como
    substring de comentario ou duplicar-se).
    """
    assert GITATTR.is_file(), ".gitattributes ausente na raiz do clone"
    content = GITATTR.read_text(encoding="utf-8")  # P-0099 — NUNCA read_text bare
    assert content.count(RULE) == 1, (
        f"regra '{RULE}' deve ocorrer exatamente uma vez "
        f"(content-anchored L-0070); count={content.count(RULE)}"
    )
    rule_lines = [ln for ln in content.splitlines() if ln.strip() == RULE]
    assert len(rule_lines) == 1, (
        f"esperada exatamente UMA linha com a regra '{RULE}'; "
        f"encontradas {len(rule_lines)}: {rule_lines!r}"
    )


def test_gitattributes_is_ascii_only() -> None:
    """O .gitattributes e ASCII puro (item 147 — config do git byte-safe).

    Leitura por bytes (read_bytes) — e o check de GLIFO, imune a EOL.
    Mesma classe do item 147: arquivos de config/scripts escritos pelo
    farm nao devem conter bytes nao-ASCII (checkouts non-UTF-8 em CI
    quebram leitores default-encoding).
    """
    assert GITATTR.is_file(), ".gitattributes ausente na raiz do clone"
    content_bytes = GITATTR.read_bytes()
    non_ascii = [b for b in content_bytes if not b < 128]
    assert all(b < 128 for b in content_bytes), (
        f".gitattributes contem bytes nao-ASCII (item 147): "
        f"{len(non_ascii)} byte(s), primeiros={non_ascii[:8]!r}"
    )


def test_key_blobs_are_lf_clean() -> None:
    """Blobs commitados dos 4 arquivos-chave tem ZERO byte CR (0x0d).

    Pina a invariância do repo que sustenta o byte-parity das suites
    irma (test_docker_start_offline: ancora ``cat > .env << 'EOF'``;
    test_docker_start/install/test-docker families). Observacao via
    ``git show`` — o working tree NUNCA e lido para line-ending
    (checkout humano pode ter CRLF local sem que o repo tenha CRLF).
    """
    offenders: list[str] = []
    for name in KEY_BLOBS:
        blob = _git_show_bytes(name)
        cr_count = blob.count(b"\r")
        if cr_count:
            offenders.append(f"{name}: {cr_count} byte(s) CR (0x0d) no blob")
    assert not offenders, (
        f"blobs commitados com CR violam a invariância LF "
        f"(checkout CRLF de CI quebraria as ancoras byte-exatas): {offenders}"
    )


def test_no_committed_crlf_in_tests_and_src() -> None:
    """NENHUM blob de tests/** ou src/** contem CR (0x0d) — guard anti-regressao.

    Inventario via ``git ls-files tests src``; observacao via ``git show``
    por blob. Guard anti-regressao do checkout LF: um CRLF commitado
    re-introduziria o desvio de offsets reconciliado em T-0315 (#100)
    e quebraria as ancoras byte-exatas no Windows CI mesmo COM o
    .gitattributes presente.
    """
    proc = subprocess.run(
        ["git", "ls-files", "tests", "src"],
        cwd=str(ROOT),
        capture_output=True,
        env=_git_env(),
        check=False,
    )
    assert proc.returncode == 0, (
        f"git ls-files falhou (rc={proc.returncode}): "
        f"{proc.stderr.decode('utf-8', errors='replace')!r}"
    )
    tracked = proc.stdout.decode("utf-8", errors="replace").splitlines()
    assert tracked, "git ls-files tests src devolveu inventario vazio — ambiente estranho"

    offenders: list[str] = []
    for relpath in tracked:
        relpath = relpath.strip()
        if not relpath:
            continue
        blob = _git_show_bytes(relpath)
        cr_count = blob.count(b"\r")
        if cr_count:
            offenders.append(f"{relpath}: {cr_count} byte(s) CR")
    assert not offenders, (
        f"CRLF commitado em tests/** ou src/** (guard anti-regressao "
        f"do checkout LF — item T-0329): {offenders}"
    )
