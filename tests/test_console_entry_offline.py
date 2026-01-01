"""Offline contract suite for the ``polymarket-mcp`` console entry point.

P1 bug being fixed: ``pyproject.toml`` bound
``polymarket-mcp = "polymarket_mcp.server:main"`` where ``main()`` is a coroutine
function (``src/polymarket_mcp/server.py:705``). The pip-generated console
wrapper executes ``sys.exit(<target>())`` — calling a coroutine function returns
an un-awaited coroutine object, so the wrapper printed
``<coroutine object main at 0x...>`` + ``RuntimeWarning: coroutine 'main' was
never awaited`` and exited: the MCP server NEVER started (silent false success).
The fix is the one-line binding change to ``polymarket_mcp.server:run`` (sync
wrapper at ``src/polymarket_mcp/server.py:771-773`` that calls
``asyncio.run(main())``). ``main``/``run`` in ``src/`` are NEVER touched by this
fatia: the lifecycle pin ``test_run_entrypoint_uses_asyncio_run``
(tests/test_server_lifecycle_offline.py, T-0065) survives — the fix lives in
the pyproject binding, not in src/.

Test 5 derives the console wrapper FORM from the binding itself (never
hard-codes the target) and runs it against the real server with stdin EOF:
pre-fix the binding points at ``main`` → stderr contains ``<coroutine object
main`` and the "Loading configuration" log never appears; post-fix the binding
points at ``run`` → the server actually starts (log ``Loading configuration...``
from ``src/polymarket_mcp/server.py:616``) and exits fast and deterministically
through config validation (``field_validator`` requires POLYGON_PRIVATE_KEY /
POLYGON_ADDRESS unless DEMO_MODE, ``src/polymarket_mcp/config.py:132/:161``).
No network is reachable on this path: config validation fails before any client
construction.

Declared divergences from the contract body (L-0025/L-0090 — asserts follow the
observed code):
- Env strip for the wrapper-form subprocess is a superset of the prescribed
  ``POLYMARKET_*`` prefix: ``POLYGON_*`` and ``DEMO_MODE`` are also stripped.
  Same class: host credentials would divert the validation path (a valid
  POLYGON_PRIVATE_KEY would push the subprocess into ``create_api_credentials``
  and real network); stripping keeps the config-validation failure deterministic.
- The subprocess return code is NOT asserted (the contract does not prescribe
  it): observed rc=1 on BOTH sides — pre-fix ``sys.exit(<coroutine>)`` prints the
  object and exits 1; post-fix the propagated ValidationError prints a traceback
  and exits 1. The contract's "rc=0" phrasing is likely a ``$?``-after-pipe
  artifact (L-0085); the discriminating observables are the two asserts below,
  both proven first-hand before this suite was written.
- Suite has no tier markers (runs in the release gate, P-0031) and makes zero
  network calls by construction (P-0029/P-0035).
"""

from __future__ import annotations

import importlib
import inspect
import os
import subprocess
import sys
from pathlib import Path

import tomllib

_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"

# Env entries stripped for the wrapper-form subprocess. The contract prescribes
# the POLYMARKET_* prefix; POLYGON_*/DEMO_MODE are added as a declared superset
# (same class: keep the deterministic fast-fail validation path — see module
# docstring).
_STRIPPED_PREFIXES = ("POLYMARKET_", "POLYGON_", "DEMO_MODE")
_WRAPPER_TIMEOUT = 30  # safety net only: the fast-fail path exits in seconds


def _read_console_binding() -> str:
    """Return the current ``[project.scripts]["polymarket-mcp"]`` value."""
    with _PYPROJECT.open("rb") as fh:
        data = tomllib.load(fh)
    return data["project"]["scripts"]["polymarket-mcp"]


def _clean_env() -> dict[str, str]:
    """Host env minus credential prefixes, plus PYTHONPATH pointing at src/."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not (key.startswith(_STRIPPED_PREFIXES) or key == "DEMO_MODE")
    }
    env["PYTHONPATH"] = str(_ROOT / "src")
    return env


def test_console_binding_points_at_sync_run() -> None:
    """[project.scripts] must bind the sync wrapper run, never the coroutine."""
    binding = _read_console_binding()
    assert binding == "polymarket_mcp.server:run", (
        f"console entry point must be the sync wrapper 'polymarket_mcp.server:run'; "
        f"got {binding!r} (a coroutine-function target is never awaited by the "
        f"pip wrapper: sys.exit(<coroutine>) starts nothing)"
    )


def test_console_target_is_sync() -> None:
    """The sync wrapper run (the post-fix binding target) must be sync + callable.

    Pins the attribute named by the contract (``polymarket_mcp.server:run``)
    directly — the property under test is the CODE (server.py:771-773), not the
    pyproject binding (test 1 covers the binding; deriving the target from the
    binding here would collapse tests 1 and 2 into the same failure pre-fix).
    """
    target = importlib.import_module("polymarket_mcp.server").run
    assert callable(target), "console target run must be callable"
    assert not inspect.iscoroutinefunction(target), (
        "console target run must be a plain sync function; "
        "iscoroutinefunction returned True (pip wrapper sys.exit(<target>()) "
        "never awaits coroutine functions)"
    )


def test_main_remains_async() -> None:
    """Guard against the WRONG fix: main() stays a coroutine function.

    De-asyncing ``main`` would break the lifecycle pin
    ``test_run_entrypoint_uses_asyncio_run`` (tests/test_server_lifecycle_offline.py).
    The P1 fix belongs to the pyproject binding only; src/ is untouched.
    """
    server = importlib.import_module("polymarket_mcp.server")
    assert inspect.iscoroutinefunction(server.main), (
        "server.main must remain a coroutine function — the fix goes to the "
        "pyproject binding (polymarket_mcp.server:run), never to src/"
    )


def test_binding_target_resolves() -> None:
    """The module:attr referenced by the console binding must be importable."""
    mod, attr = _read_console_binding().split(":", 1)
    module = importlib.import_module(mod)
    assert hasattr(module, attr), (
        f"console binding points at '{mod}:{attr}' which does not resolve "
        f"(module imported but attribute missing)"
    )


def test_wrapper_form_starts_server_without_coroutine_warning(tmp_path) -> None:
    """Functional proof derived from the binding: the real server must start.

    The wrapper form is exactly what a pip-generated console script executes
    (``sys.exit(getattr(import_module(mod), attr)())``) with mod/attr parsed from
    the binding — never hard-coded. With stdin EOF and credential-free env, the
    fixed binding must reach server startup (log "Loading configuration...") and
    exit fast through config validation, with NO never-awaited coroutine artifact
    in the output. Pre-fix state (binding = main) fails BOTH asserts.
    """
    mod, attr = _read_console_binding().split(":", 1)
    wrapper = (
        "import sys\n"
        "from importlib import import_module\n"
        f"mod, attr = {mod!r}, {attr!r}\n"
        "sys.exit(getattr(import_module(mod), attr)())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", wrapper],
        stdin=subprocess.DEVNULL,
        cwd=str(tmp_path),
        env=_clean_env(),
        capture_output=True,
        text=True,
        timeout=_WRAPPER_TIMEOUT,
    )
    output = proc.stdout + proc.stderr
    assert "coroutine" not in output, (
        f"console wrapper leaked an un-awaited coroutine artifact (binding "
        f"{mod}:{attr} is a coroutine function): {output[:2000]!r}"
    )
    assert "Loading configuration" in output, (
        f"server never started — no 'Loading configuration' log in output "
        f"(exit code {proc.returncode}): {output[:2000]!r}"
    )
