"""
Offline regression suite for Host/Origin validation on the FastAPI web dashboard
(src/polymarket_mcp/web/app.py).

The dashboard has no authentication and relies on its loopback bind. Without
Host validation a DNS-rebinding page reaches POST /api/config as same-origin
and rewrites the trading safety limits in .env. These tests pin that a request
whose Host is not the dashboard itself is refused before any route runs, that
cross-origin writes and WebSocket handshakes are refused, and that legitimate
loopback access keeps working.
"""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from polymarket_mcp.web import app as wa

ATTACKER_HOST = "rebind.attacker.example:8080"
ATTACKER_ORIGIN = "http://rebind.attacker.example:8080"
LOOPBACK_HOST = "127.0.0.1:8080"
LOOPBACK_BASE_URL = f"http://{LOOPBACK_HOST}"

ENV_BEFORE = "\n".join(
    [
        "MAX_ORDER_SIZE_USD=1000",
        "MAX_TOTAL_EXPOSURE_USD=5000",
        "MAX_POSITION_SIZE_PER_MARKET=2000",
        "MIN_LIQUIDITY_REQUIRED=10000",
        "MAX_SPREAD_TOLERANCE=0.05",
        "ENABLE_AUTONOMOUS_TRADING=false",
        "REQUIRE_CONFIRMATION_ABOVE_USD=500",
        "AUTO_CANCEL_ON_LARGE_SPREAD=true",
    ]
)

MALICIOUS_PAYLOAD = {
    "max_order_size_usd": 1_000_000_000,
    "max_total_exposure_usd": 1_000_000_000,
    "max_position_size_per_market": 1_000_000_000,
    "min_liquidity_required": 0.01,
    "max_spread_tolerance": 1,
    "enable_autonomous_trading": True,
    "require_confirmation_above_usd": 1_000_000_000,
    "auto_cancel_on_large_spread": False,
}


@pytest.fixture(autouse=True)
def isolated_dashboard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEB_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.setattr(wa, "bound_host", None)
    monkeypatch.setattr(wa, "config", None)
    monkeypatch.setattr(wa, "client", None)
    monkeypatch.setattr(wa, "safety_limits", None)
    monkeypatch.setattr(wa, "stats", dict(wa.stats))
    monkeypatch.setattr(wa, "active_websockets", [])
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_BEFORE, encoding="utf-8")
    return env_file


@pytest.fixture
def loopback_client():
    return TestClient(wa.app, base_url=LOOPBACK_BASE_URL)


def test_rebinding_host_cannot_read_status(loopback_client):
    response = loopback_client.get("/api/status", headers={"Host": ATTACKER_HOST})

    assert response.status_code == 400
    assert "WEB_ALLOWED_HOSTS" in response.json()["detail"]


def test_rebinding_host_cannot_rewrite_safety_limits(loopback_client, isolated_dashboard):
    response = loopback_client.post(
        "/api/config",
        json=MALICIOUS_PAYLOAD,
        headers={"Host": ATTACKER_HOST, "Origin": ATTACKER_ORIGIN},
    )

    assert response.status_code == 400
    assert isolated_dashboard.read_text(encoding="utf-8") == ENV_BEFORE


def test_rejected_request_still_carries_security_headers(loopback_client):
    response = loopback_client.get("/", headers={"Host": ATTACKER_HOST})

    assert response.status_code == 400
    assert response.headers["X-Frame-Options"] == "DENY"


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1:8080", "127.0.0.1", "localhost:8080", "LOCALHOST", "[::1]:8080"],
)
def test_loopback_hosts_are_served(loopback_client, host):
    response = loopback_client.get("/api/status", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "",
        "127.0.0.1.attacker.example",
        "localhost.attacker.example:8080",
        "attacker.example:127.0.0.1",
    ],
)
def test_lookalike_hosts_are_rejected(loopback_client, host):
    response = loopback_client.get("/api/status", headers={"Host": host})

    assert response.status_code == 400


def test_cross_origin_write_is_rejected(loopback_client, isolated_dashboard):
    response = loopback_client.post(
        "/api/config", json=MALICIOUS_PAYLOAD, headers={"Origin": "https://attacker.example"}
    )

    assert response.status_code == 403
    assert isolated_dashboard.read_text(encoding="utf-8") == ENV_BEFORE


def test_opaque_origin_write_is_rejected(loopback_client, isolated_dashboard):
    response = loopback_client.post(
        "/api/config", json=MALICIOUS_PAYLOAD, headers={"Origin": "null"}
    )

    assert response.status_code == 403
    assert isolated_dashboard.read_text(encoding="utf-8") == ENV_BEFORE


@pytest.mark.parametrize("headers", [{}, {"Origin": LOOPBACK_BASE_URL}])
def test_same_origin_write_reaches_the_route(loopback_client, headers):
    response = loopback_client.post("/api/config", json={}, headers=headers)

    assert response.status_code == 422


def test_extra_host_is_opt_in(loopback_client, monkeypatch):
    headers = {"Host": "dashboard.internal:8080"}

    assert loopback_client.get("/api/status", headers=headers).status_code == 400

    monkeypatch.setenv("WEB_ALLOWED_HOSTS", "other.internal, Dashboard.Internal")

    assert loopback_client.get("/api/status", headers=headers).status_code == 200


def test_specific_bind_host_is_allowed(loopback_client, monkeypatch):
    monkeypatch.setenv("WEB_HOST", "192.168.1.50")

    response = loopback_client.get("/api/status", headers={"Host": "192.168.1.50:8080"})

    assert response.status_code == 200


@pytest.mark.parametrize("wildcard", ["0.0.0.0", "::"])
def test_wildcard_bind_does_not_allow_foreign_hosts(loopback_client, monkeypatch, wildcard):
    monkeypatch.setenv("WEB_HOST", wildcard)

    assert loopback_client.get("/api/status", headers={"Host": ATTACKER_HOST}).status_code == 400
    assert loopback_client.get("/api/status", headers={"Host": wildcard}).status_code == 400


def test_start_records_the_bound_host(monkeypatch):
    monkeypatch.setattr(wa.uvicorn, "run", lambda *args, **kwargs: None)

    wa.start(host="192.168.1.50", port=8080)

    assert "192.168.1.50" in wa._allowed_hosts()


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": ATTACKER_HOST, "Origin": ATTACKER_ORIGIN},
        {"Host": LOOPBACK_HOST, "Origin": "https://attacker.example"},
    ],
)
def test_websocket_rejects_foreign_host_and_origin(loopback_client, headers):
    with pytest.raises(WebSocketDisconnect):
        with loopback_client.websocket_connect("/ws", headers=headers):
            pass


def test_websocket_accepts_same_origin(loopback_client):
    headers = {"Host": LOOPBACK_HOST, "Origin": LOOPBACK_BASE_URL}

    with loopback_client.websocket_connect("/ws", headers=headers) as ws:
        assert ws.receive_json()["type"] == "status"
