"""
Offline sandbox suite for the repo's Docker self-test script ``test-docker.sh``
(T-0222) -- the front door behind ``make test`` (the Makefile ``test`` target
runs ``bash test-docker.sh``).

Before this slice the script shipped three coupled defects, all proven RED
first-hand in stubbed sandboxes on main (probes recorded in the task report;
L-0130/P-0036):

1. ``set -e`` (:5) + ``run_test`` returning 1 on failure -- a bare ``run_test``
   call that fails killed the script at the FIRST failing test, before the
   summary (probe: tmpdir without repo files died at "x Dockerfile exists",
   rc=1, zero summary lines; with repo fixtures it died at "x Docker daemon
   is running", the CI-realistic point :73 post-fix).
2. ``((TESTS_PASSED++))``/``((TESTS_FAILED++))`` at 8 sites -- on bash 5 (the
   Linux CI), ``((X++))`` with X=0 returns status 1, so under ``set -e`` the
   script died at the first PASSING test (when the counter was still 0). The
   host bash here is 3.2.57 (macOS, exempt -- probed: ``set -e; X=0; ((X));
   echo ALIVE`` -> ALIVE), so this mechanism is REGISTER-ONLY on this host;
   the fix (``$((N+1))``) eliminates it in ANY bash by construction.
3. No trap/cleanup on early death -- the inline cleanup block only ran at the
   end, so an early death left ``.env.test`` in the repo and (post-build) the
   ``polymarket-mcp:test`` image orphaned (probe: sandbox with
   info=0/build=0/images=1 died at ``IMAGE_SIZE=$(docker images ...)`` -- the
   only non-condition site after .env.test creation (:81-90) -- leaving
   ``.env.test`` behind).

The fix (this slice): (1) ``run_test`` never returns 1 -- its failure branch
returns 0 and only records the failure; the script's exit code is decided by
the final summary (``exit 0`` iff ``TESTS_FAILED == 0``, else ``exit 1`` --
``make test`` semantics preserved); (2) all 8 counter sites use ``$((N+1))``;
(3) the cleanup block was extracted into ``cleanup()`` and installed as
``trap 'rc=$?; cleanup; exit $rc' EXIT INT TERM``, with the end-of-run
inline block (:167-171) replaced by a ``cleanup()`` call -- the summary does
NOT run on early death, but the cleanup does. ``set -e``, the color/print
helpers, the real ``docker build`` (:93), the conditional kubectl block
(:136-142) and the docker-compose validation (:159-165) are preserved
unchanged.

Mandatory cases (names verbatim from the contract):
- ``test_bash_n_valid`` -- syntactic invariant (rc=0 before and after; the
  defects are semantic, not syntactic).
- ``test_run_test_never_returns_1`` -- content pin of run_test's failure
  branch (returns 0, registers the failure); execution-level discriminant in
  the next case.
- ``test_first_failing_test_does_not_kill_script`` -- with a failing docker
  stub, the fixed copy reaches the summary (rc=1) and cleans up; the
  dev-only mutated copy (``return 1`` restored) dies at the first failing
  test without any summary -- the oracle knows how to fail (L-0014/L-0065).
- ``test_all_counter_sites_use_arith_expansion`` -- zero post-increment
  counter forms; >= 8 arith-expansion sites, counted as a SET (L-0023; the
  real count at write time is 8 = 4 PASSED + 4 FAILED, never asserted as an
  exact equality).
- ``test_trap_cleanup_runs_on_early_death`` -- early death AFTER .env.test
  creation and BEFORE the end-of-run cleanup (via the failing
  ``IMAGE_SIZE=$(docker images ...)`` site) is cleaned by the trap on the
  fixed copy, while the dev-only trap-neutralized copy leaves ``.env.test``
  behind -- proving the trap's value on both sides.
- ``test_exit_semantics_preserved`` -- happy path (all stubs rc=0) reaches
  the full 24-test pass surface and exits 0 with "All tests passed!"; a
  failing test through run_test's fixed branch registers exactly one failure
  and exits 1 with "Some tests failed".

Anatomy (P-0021/P-0031/P-0040 adapted to a shell script under test):
- The REAL script is copied BYTE-EXACT (asserted on read_bytes) into each
  test's tmp_path and only the copy is executed -- the repo file is read,
  never modified (P-0018 tripwire by equality: this suite exercises the real
  script, not a variant).
- Fixtures: a minimal repo-like cwd (Dockerfile, docker-compose.yml,
  .dockerignore, executable docker-start.sh, .env.example, k8s/*, the CI/CD
  workflow and doc files) plus PATH stubs for ``docker``/``kubectl``/
  ``timeout`` whose exit codes are keyed by env vars (DOCKER_STUB_*_RC /
  KUBECTL_STUB_RC, default 0) -- stubs at the border, never the real daemons
  (P-0031/P-0040; real docker builds/scaling are deny by contract).
- Hermeticity: the subprocess env is constructed FROM SCRATCH (env -i
  equivalent -- no host/daemon env can leak into the script; L-0098 direction
  1 by construction, direction 2 vacuously covered because nothing is
  inherited), zero network (docker/kubectl are intercepted by the PATH
  stubs; the script itself makes no network calls -- verified by grep in the
  task report, L-0138), zero writes outside tmp_path EXCEPT the script's own
  hardcoded scratch redirects /tmp/docker-build.log and /tmp/docker-run.log
  (preserved observable of the script under test -- benign, repo-independent,
  no state effect; parallel runs may overwrite each other's empty stub logs
  harmlessly).
- Every subprocess run has timeout=60 (contract mandate) and rc is captured
  behind a 99 sentinel so a swallowed exec error cannot masquerade as pass
  or fail (P-0021). The script's internal ``timeout 10s`` is exercised
  through the ``timeout`` stub so behavior is identical on hosts without
  GNU timeout.
- Mutations (dev-only, for the oracles) are applied to COPIES in tmp_path
  with replace-count asserted and parseability re-checked via ``bash -n``
  (L-0016/L-0082/L-0144): restoring ``return 1`` into run_test's else branch
  (mechanism 1 discriminant) and neutralizing the trap line (mechanism 3
  discriminant).

Coupling (L-0073): this suite pins observable content of test-docker.sh --
the summary literals, the trap line shape, the counter arithmetic forms and
the 24-test happy-path count. Any slice that changes the script's test
surface must update this suite in the SAME slice. Line numbers cited above
refer to the fixed script as of this slice; they drift with concurrent edits
(L-0070/L-0127) -- the pins are content-anchored, not line-anchored.
"""

import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_REL = "test-docker.sh"
RUN_TIMEOUT_S = 60
RC_SENTINEL = 99  # P-0021: a swallowed exec error must not masquerade as 0/1

_bash = shutil.which("bash")
assert _bash is not None, "bash not found in PATH -- the script under test requires it"
BASH: Final[str] = _bash

# Post-increment counter forms (the bash 5 footgun) must be gone; the
# arith-expansion replacements must exist at every counter site (>= 8 as a
# set: 4 PASSED + 4 FAILED at write time -- never an exact equality).
_POST_INCREMENT_RE = re.compile(r"\(\(TESTS_(PASSED|FAILED)\+\+\)\)")
_ARITH_PASSED_RE = re.compile(r"\$\(\(TESTS_PASSED\+1\)\)")
_ARITH_FAILED_RE = re.compile(r"\$\(\(TESTS_FAILED\+1\)\)")
_TRAP_LINE_RE = re.compile(r"^trap '.*' EXIT INT TERM$", re.MULTILINE)

# Sandbox fixtures (existence-only for the script; content is irrelevant).
_ROOT_FILES = ("Dockerfile", "docker-compose.yml", ".dockerignore", "docker-start.sh", ".env.example")
_K8S_FILES = ("deployment.yaml", "service.yaml", "configmap.yaml", "secret.yaml.template", "README.md")

_DOCKER_STUB = """\
#!/bin/sh
# Offline stub for the `docker` CLI (sandbox-only, T-0222 suite).
# Exit codes are keyed per subcommand via DOCKER_STUB_<NAME>_RC (default 0);
# the sandbox PATH puts this stub first, so the real daemon is never touched.
rc_for() {
    eval "RC=\\${DOCKER_STUB_${1}_RC:-0}"
    printf '%s' "$RC"
}
sub="${1:-}"
case "$sub" in
    info) exit "$(rc_for INFO)" ;;
    build) exit "$(rc_for BUILD)" ;;
    images)
        if [ "$(rc_for IMAGES)" != "0" ]; then exit "$(rc_for IMAGES)"; fi
        echo "128MB"
        exit 0
        ;;
    history)
        if [ "$(rc_for HISTORY)" != "0" ]; then exit "$(rc_for HISTORY)"; fi
        echo "sha256:stub-layer-1"
        echo "sha256:stub-layer-2"
        exit 0
        ;;
    run) exit "$(rc_for RUN)" ;;
    rmi) exit "$(rc_for RMI)" ;;
    compose)
        case "${2:-}" in
            version) exit "$(rc_for COMPOSE_VERSION)" ;;
            config) exit "$(rc_for COMPOSE_CONFIG)" ;;
            *) exit 1 ;;
        esac
        ;;
    *) exit 1 ;;
esac
"""

_KUBECTL_STUB = """\
#!/bin/sh
# Offline stub for `kubectl` (sandbox-only, T-0222 suite): succeeds unless
# KUBECTL_STUB_RC says otherwise; the real cluster API is never contacted.
exit "${KUBECTL_STUB_RC:-0}"
"""

_TIMEOUT_STUB = """\
#!/bin/sh
# Offline stub for GNU `timeout` (sandbox-only, T-0222 suite): drops the
# duration argument and execs the rest, so the script's
# `timeout 10s docker run ...` line is deterministic on hosts without
# GNU timeout in PATH.
shift
exec "$@"
"""

_STUBS = (("docker", _DOCKER_STUB), ("kubectl", _KUBECTL_STUB), ("timeout", _TIMEOUT_STUB))

# All-docker-failing sandbox (first failing test = "Docker daemon is
# running", the CI-realistic death point pre-fix).
_ALL_FAIL_OVERRIDES: dict[str, str] = {
    "DOCKER_STUB_INFO_RC": "1",
    "DOCKER_STUB_COMPOSE_VERSION_RC": "1",
    "DOCKER_STUB_BUILD_RC": "1",
    "DOCKER_STUB_COMPOSE_CONFIG_RC": "1",
}

# Early-death sandbox: docker works until `docker images` fails -- the only
# non-condition site after .env.test creation, so under set -e the script
# dies mid-flight (the trap-value oracle).
_EARLY_DEATH_OVERRIDES: dict[str, str] = {
    "DOCKER_STUB_INFO_RC": "0",
    "DOCKER_STUB_COMPOSE_VERSION_RC": "0",
    "DOCKER_STUB_BUILD_RC": "0",
    "DOCKER_STUB_IMAGES_RC": "1",
    "DOCKER_STUB_RUN_RC": "0",
    "DOCKER_STUB_COMPOSE_CONFIG_RC": "0",
}


def _make_sandbox(base: Path) -> Path:
    """Build the repo-like fixture cwd + PATH stubs inside ``base``."""
    sandbox = base / "sandbox"
    (sandbox / "k8s").mkdir(parents=True)
    (sandbox / ".github" / "workflows").mkdir(parents=True)
    for name in _ROOT_FILES:
        (sandbox / name).write_text("# sandbox fixture\n", encoding="utf-8")
    (sandbox / "docker-start.sh").chmod(0o755)
    for name in _K8S_FILES:
        (sandbox / "k8s" / name).write_text("# sandbox fixture\n", encoding="utf-8")
    (sandbox / "DOCKER.md").write_text("# sandbox fixture\n", encoding="utf-8")
    (sandbox / ".github" / "workflows" / "docker-publish.yml").write_text(
        "name: sandbox-fixture\n", encoding="utf-8"
    )
    bin_dir = sandbox / "bin"
    bin_dir.mkdir()
    for name, content in _STUBS:
        stub = bin_dir / name
        stub.write_text(content, encoding="utf-8")
        stub.chmod(0o755)
    return sandbox


def _sandbox_env(sandbox: Path, rc_overrides: Mapping[str, str]) -> dict[str, str]:
    """Fresh env for the subprocess (env -i equivalent) + stub rc overrides."""
    env = {
        "TERM": "dumb",
        "HOME": str(sandbox),
        "PATH": f"{sandbox / 'bin'}:/usr/bin:/bin:/usr/sbin:/sbin",
    }
    env.update(rc_overrides)
    return env


def _run(script: Path, sandbox: Path, rc_overrides: Mapping[str, str] | None = None) -> tuple[int, str, str]:
    """Run the script under test inside the sandbox; return (rc, stdout, stderr).

    rc stays at the 99 sentinel when the subprocess itself fails (timeout,
    OSError) so the caller's assert on 0/1 fails loud instead of masking.
    """
    rc = RC_SENTINEL
    stdout = ""
    stderr = ""
    try:
        proc = subprocess.run(
            [BASH, str(script)],
            cwd=str(sandbox),
            env=_sandbox_env(sandbox, rc_overrides or {}),
            capture_output=True,
            encoding="utf-8",
            timeout=RUN_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return rc, stdout, stderr
    return proc.returncode, proc.stdout, proc.stderr


def _bash_n(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([BASH, "-n", str(script)], capture_output=True, encoding="utf-8", timeout=RUN_TIMEOUT_S)


def _extract_run_test_body(text: str) -> str:
    """Lines from ``run_test() {`` through its closing ``}`` (anchor-based)."""
    try:
        start = text.index("run_test() {")
        end = text.index("\n}", start)
    except ValueError as exc:
        raise AssertionError("run_test() anchor drifted (L-0070/L-0127)") from exc
    return text[start:end]


def _mutate_run_test_returns_1(text: str) -> str:
    """Dev-only oracle mutation: restore ``return 1`` in run_test's else branch.

    Substitution (not deletion -- L-0082) of the failure-branch statement with
    exactly one replacement asserted (L-0144); parseability is re-checked by
    the caller via ``bash -n``.
    """
    start = text.index("run_test() {")
    end = text.index("\n}", start)
    body = text[start:end]
    else_idx = body.index("else")
    tail = body[else_idx:]
    ret = tail.index("return 0")
    mutated_body = body[:else_idx] + tail[:ret] + "return 1" + tail[ret + len("return 0") :]
    mutated = text[:start] + mutated_body + text[end:]
    assert mutated.count("return 1") == 1, "return-1 mutation not applied exactly once"
    return mutated


def _neutralize_trap(text: str) -> str:
    """Dev-only oracle mutation: turn the trap installation line into a no-op."""
    matches = _TRAP_LINE_RE.findall(text)
    assert len(matches) == 1, f"trap line drift: expected exactly 1, found {len(matches)}"
    return _TRAP_LINE_RE.sub(": # trap disabled (T-0222 dev-only mutation)", text, count=1)


@pytest.fixture()
def script_copy(tmp_path: Path) -> Path:
    """Byte-exact copy of the real script (the copy equality is the tripwire)."""
    source = REPO_ROOT / SCRIPT_REL
    copy = tmp_path / SCRIPT_REL
    copy.write_bytes(source.read_bytes())
    assert copy.read_bytes() == source.read_bytes(), "byte-exact copy of test-docker.sh violated"
    return copy


def test_bash_n_valid(script_copy: Path) -> None:
    """``bash -n`` parses the script -- syntactic invariant (rc=0 before/after)."""
    proc = _bash_n(script_copy)
    assert proc.returncode == 0, f"bash -n failed on the script:\n{proc.stderr[-400:]}"


def test_run_test_never_returns_1(script_copy: Path) -> None:
    """Content pin: run_test's failure branch returns 0, never 1.

    Anchor: lines between ``run_test() {`` and its closing ``}``. The pin is
    content-adjacent (failure branch must hand control back AND register the
    failure); the execution-level discriminant lives in
    ``test_first_failing_test_does_not_kill_script`` (mutated copy).
    """
    body = _extract_run_test_body(script_copy.read_text(encoding="utf-8"))
    assert "return 1" not in body, "run_test still returns 1 on failure (mechanism 1 unfixed)"
    assert body.count("return 0") >= 1, "run_test lost its unconditional return 0"
    before_else, sep, after_else = body.partition("else")
    assert sep, "run_test lost its if/else failure branch"
    first_return = after_else[after_else.index("return") :]
    assert first_return.startswith("return 0"), "failure branch does not return 0"
    assert "TESTS_FAILED=$((TESTS_FAILED+1))" in after_else, "failure branch no longer registers the failure"
    assert "TESTS_PASSED=$((TESTS_PASSED+1))" in before_else, "success branch no longer registers the pass"


def test_first_failing_test_does_not_kill_script(script_copy: Path, tmp_path: Path) -> None:
    """With a failing docker stub, the fixed copy reaches the summary; the
    dev-only mutated copy (return 1 restored) dies at the first failing test
    without any summary -- the oracle discriminates (L-0014/L-0065)."""
    sandbox = _make_sandbox(tmp_path)
    rc, out, err = _run(script_copy, sandbox, _ALL_FAIL_OVERRIDES)
    assert rc == 1, f"expected rc=1 (some failed), got {rc}\n{err[-400:]}"
    assert "Tests passed:" in out and "Tests failed:" in out, "script did not reach the summary"
    assert not (sandbox / ".env.test").exists(), "cleanup (trap/end-of-run) did not remove .env.test"

    mutated = tmp_path / "mutated-return-1.sh"
    mutated.write_text(_mutate_run_test_returns_1(script_copy.read_text(encoding="utf-8")), encoding="utf-8")
    parsed = _bash_n(mutated)
    assert parsed.returncode == 0, f"mutation broke parseability (L-0082):\n{parsed.stderr[-400:]}"
    rc2, out2, err2 = _run(mutated, sandbox, _ALL_FAIL_OVERRIDES)
    assert rc2 == 1, f"expected rc=1 (set -e death), got {rc2}\n{err2[-400:]}"
    assert "Tests passed:" not in out2 and "Tests failed:" not in out2, "mutated copy reached the summary"
    assert "Docker daemon is running" in out2, "mutated copy did not die at the first failing test"


def test_all_counter_sites_use_arith_expansion(script_copy: Path) -> None:
    """All counter sites use $((N+1)); zero post-increment forms remain.

    Counted as a SET (L-0023): the sum of both arith forms must be >= 8
    (4 PASSED + 4 FAILED at write time -- a legitimate future refactor that
    adds sites keeps passing; an exact equality would be over-pin).
    """
    text = script_copy.read_text(encoding="utf-8")
    assert not _POST_INCREMENT_RE.search(text), "post-increment counter form survived (mechanism 2 unfixed)"
    arith_sites = len(_ARITH_PASSED_RE.findall(text)) + len(_ARITH_FAILED_RE.findall(text))
    assert arith_sites >= 8, f"only {arith_sites} arith-expansion counter sites (expected >= 8)"


def test_trap_cleanup_runs_on_early_death(script_copy: Path, tmp_path: Path) -> None:
    """The trap cleans up on early death (after .env.test creation, before the
    end-of-run cleanup); the trap-neutralized dev-only copy leaves it behind."""
    sandbox = _make_sandbox(tmp_path)
    rc, out, err = _run(script_copy, sandbox, _EARLY_DEATH_OVERRIDES)
    assert rc == 1, f"expected rc=1 (set -e death at IMAGE_SIZE=$(docker images ...)), got {rc}\n{err[-400:]}"
    assert not (sandbox / ".env.test").exists(), "trap did not clean up on early death"
    assert "Tests failed:" not in out, "summary ran on early death (must not -- dies before the summary)"

    mutated = tmp_path / "mutated-no-trap.sh"
    mutated.write_text(_neutralize_trap(script_copy.read_text(encoding="utf-8")), encoding="utf-8")
    parsed = _bash_n(mutated)
    assert parsed.returncode == 0, f"mutation broke parseability (L-0082):\n{parsed.stderr[-400:]}"
    rc2, out2, err2 = _run(mutated, sandbox, _EARLY_DEATH_OVERRIDES)
    assert rc2 == 1, f"expected rc=1 (set -e death without trap), got {rc2}\n{err2[-400:]}"
    assert (sandbox / ".env.test").exists(), "orphan .env.test absent without trap -- oracle vacuous"
    assert "Tests failed:" not in out2, "summary ran on early death in the mutated copy too"


def test_exit_semantics_preserved(script_copy: Path, tmp_path: Path) -> None:
    """exit 0 iff all tests passed; exit 1 with failures (``make test`` semantics).

    Happy sandbox (all stubs rc=0): the full 24-test pass surface is reached
    and the script exits 0. Failing variant (docker info fails through
    run_test's FIXED failure branch): exactly one failure is registered and
    the script exits 1.
    """
    sandbox = _make_sandbox(tmp_path)
    rc, out, err = _run(script_copy, sandbox)
    assert rc == 0, f"expected rc=0 on the happy path, got {rc}\n{err[-400:]}"
    assert "All tests passed!" in out, "happy-path banner missing"
    assert "Tests passed: 24" in out, "full pass surface drifted (expected the 24-test pass; L-0073 coupling)"
    assert "Tests failed: 0" in out
    assert not (sandbox / ".env.test").exists(), "end-of-run cleanup call did not remove .env.test"

    rc2, out2, err2 = _run(script_copy, sandbox, {"DOCKER_STUB_INFO_RC": "1"})
    assert rc2 == 1, f"expected rc=1 with a failing test, got {rc2}\n{err2[-400:]}"
    assert "Some tests failed" in out2, "failure summary banner missing"
    assert "All tests passed!" not in out2, "happy banner leaked into the failing run"
    assert "Tests failed: 1" in out2, "failure branch did not register exactly one failure"
