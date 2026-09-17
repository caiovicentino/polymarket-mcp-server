"""
Offline regression suite for k8s manifest/config parity (T-0225).

The k8s manifests must deliver EVERY field of PolymarketConfig to the pod:
- k8s/configmap.yaml covers all NON-credential fields (17),
- k8s/secret.yaml.template covers all credential fields (5): the wallet
  private key/address plus the L2 API key/secret/passphrase.

Baseline bug (main 89edfa9, proven RED pre-fix): parity was 17/22. Five
fields were UNREACHABLE from the pod (POLYMARKET_API_SECRET — whose absence
makes auth/client.py fall back to `api_secret or passphrase` and break HMAC
signing —, POLYMARKET_API_KEY_NAME, USDC_ADDRESS, CTF_EXCHANGE_ADDRESS,
CONDITIONAL_TOKEN_ADDRESS), the configmap carried the DEAD variable
RATE_LIMIT_ENABLED (zero occurrences in src/; config uses extra="ignore" so
it never breaks boot — just inert and misleading), three values diverged
from the code defaults (MAX_TOTAL_EXPOSURE_USD "10000" != 5000.0,
REQUIRE_CONFIRMATION_ABOVE_USD "100" != 500.0,
MAX_POSITION_SIZE_PER_MARKET "0.3" != 2000.0), the deployment carried two
stale `version: v0.1.0` labels (package is 0.2.0; anti-drift: removed, not
bumped), and k8s/README.md mixed namespaces (`-n polymarket` while the
manifests declare `namespace: default` — kubectl -n does NOT override the
manifest, so a secret created in `polymarket` stays invisible to the
deployment in `default`) and omitted POLYMARKET_API_SECRET from its
--from-literal route.

Anti-drift (lessons L-0023/P-0049): expected values are DERIVED from the
LIVE model_fields of PolymarketConfig (src/polymarket_mcp/config.py) at
runtime — never hardcoded. A future default change in config.py flips the
manifest tests RED until the manifest is updated, which is the designed
behavior. The credential classification itself is a domain fact of this
slice: values used to authenticate or sign (wallet key/address + L2 API
credentials); note config.to_dict() masks the four sensitive strings while
the wallet ADDRESS is shipped in the Secret per this slice's design.

Hermeticity: pyyaml-ONLY — kubectl does NOT validate offline (proven:
rc!=0 even with --validate=false), so kubectl is NEVER invoked. `yaml` is
imported via importorskip (pyyaml ships in the dev extra since T-0225;
venv local has 6.0.3). No network, no subprocess. deployment.yaml is
MULTI-DOCUMENT (Deployment + 2 PVCs) — a single safe_load raises
ParserError, hence safe_load_all with an isinstance(d, dict) guard.

Negação pareada (L-0056): every negative assertion is paired with a
positive one in the same test, so a truncated/misparsed file cannot pass
vacuously. Superset note (L-0094/L-0062 spirit): the namespace consistency
check covers ALL FOUR yaml manifests (configmap, secret template,
deployment, service) — service.yaml also declares namespace: default, so
the check is strictly stronger than the prescribed 3.
"""

import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = str(REPO_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from polymarket_mcp.config import PolymarketConfig  # noqa: E402

K8S = REPO_ROOT / "k8s"
CONFIGMAP = K8S / "configmap.yaml"
SECRET_TEMPLATE = K8S / "secret.yaml.template"
DEPLOYMENT = K8S / "deployment.yaml"
SERVICE = K8S / "service.yaml"
README = K8S / "README.md"

MODEL_FIELDS = set(PolymarketConfig.model_fields)
CREDENTIAL_FIELDS = frozenset(
    {
        "POLYGON_PRIVATE_KEY",
        "POLYGON_ADDRESS",
        "POLYMARKET_API_KEY",
        "POLYMARKET_API_SECRET",
        "POLYMARKET_PASSPHRASE",
    }
)
NON_CREDENTIAL_FIELDS = MODEL_FIELDS - CREDENTIAL_FIELDS

# Sanity of the derivation itself (fail loud if the model drifts beyond
# the 22-field slice this suite was written against — the tests below
# would otherwise silently re-scope).
assert len(MODEL_FIELDS) == 22, f"config model drifted: {len(MODEL_FIELDS)} fields"


def _docs(path: Path) -> list:
    """safe_load_all with a dict guard; every doc must be a mapping."""
    docs = [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]
    assert docs, f"{path.name}: no parseable YAML documents"
    return docs


def test_configmap_covers_all_non_secret_fields():
    cm = _docs(CONFIGMAP)[0]
    data = cm["data"]
    assert set(data) == NON_CREDENTIAL_FIELDS


def test_configmap_values_match_code_defaults():
    cm = _docs(CONFIGMAP)[0]
    data = cm["data"]
    for name, actual in data.items():
        default = PolymarketConfig.model_fields[name].default
        if isinstance(default, bool):
            # case-insensitive normalization on both sides
            assert actual == str(default).lower(), name
        elif isinstance(default, int):
            assert int(actual) == default, name
        elif isinstance(default, float):
            assert float(actual) == pytest.approx(default), name
        elif default is None:
            # Optional[str] fields: empty string means "unset/auto-generate"
            assert actual == "", name
        else:
            assert actual == str(default), name


def test_dead_config_var_removed():
    cm = _docs(CONFIGMAP)[0]
    data = cm["data"]
    # paired positive: the real configmap is parsed (a live field is present)
    assert "DEMO_MODE" in data
    # the negative: RATE_LIMIT_ENABLED is dead (zero occurrences in src/) and
    # must be absent — extra="ignore" means it would boot inertly
    assert "RATE_LIMIT_ENABLED" not in data


def test_secret_template_covers_all_credentials():
    secret = _docs(SECRET_TEMPLATE)[0]
    assert set(secret["data"]) == CREDENTIAL_FIELDS


def test_secret_template_reuse_note():
    text = SECRET_TEMPLATE.read_text()
    header = text.split("apiVersion:", 1)[0]
    # the reuse note: API_SECRET and PASSPHRASE are DIFFERENT values —
    # reusing one for both breaks HMAC request signing (auth/client.py
    # falls back to `api_secret or passphrase` when the secret is absent)
    assert "DIFFERENT" in header
    assert "API_SECRET" in header
    assert "PASSPHRASE" in header
    assert "reuse" in header.lower()
    # paired positive: the kubectl command block in the header now lists
    # all five credential keys, every line a #-comment (the template must
    # stay YAML-parseable)
    assert "--from-literal=POLYMARKET_API_SECRET=" in header
    for line in header.splitlines():
        stripped = line.strip()
        assert stripped == "" or stripped.startswith("#"), line


def test_deployment_no_version_labels():
    text = DEPLOYMENT.read_text()
    # paired positive: functional labels intact (parsed, not grep-counted —
    # L-0002), so a broken file cannot pass the negative below vacuously
    deployment = _docs(DEPLOYMENT)[0]
    meta_labels = deployment["metadata"]["labels"]
    tmpl_labels = deployment["spec"]["template"]["metadata"]["labels"]
    assert meta_labels["app"] == "polymarket-mcp"
    assert tmpl_labels["app"] == "polymarket-mcp"
    assert "version" not in meta_labels
    assert "version" not in tmpl_labels
    # the negative: the stale pin is gone from the raw file too (catches
    # stray comments/mentions, not just structured keys)
    assert "v0.1.0" not in text


def test_readme_secret_route_includes_api_secret():
    text = README.read_text()
    block = None
    for fence in text.split("```"):
        if "--from-literal" in fence and "create secret" in fence:
            block = fence
            break
    assert block is not None, "README has no --from-literal secret route"
    for cred in sorted(CREDENTIAL_FIELDS):
        assert f"--from-literal={cred}=" in block, cred


def test_readme_namespace_consistent():
    text = README.read_text()
    assert "-n polymarket" not in text
    # paired positive: the correct namespace IS used in README commands
    assert "-n default" in text
    # every yaml manifest declares namespace: default (superset over the
    # prescribed 3: service.yaml is checked too — declared in header)
    for path in (CONFIGMAP, SECRET_TEMPLATE, DEPLOYMENT, SERVICE):
        for doc in _docs(path):
            assert doc["metadata"]["namespace"] == "default", path.name


def test_manifests_parse_multidoc():
    # single-document manifests
    for path, kind in (
        (CONFIGMAP, "ConfigMap"),
        (SECRET_TEMPLATE, "Secret"),
        (SERVICE, "Service"),
    ):
        docs = _docs(path)
        assert len(docs) == 1
        assert docs[0]["kind"] == kind
    # deployment.yaml is multi-document: Deployment + 2 PVCs
    dep_docs = _docs(DEPLOYMENT)
    assert [d["kind"] for d in dep_docs] == [
        "Deployment",
        "PersistentVolumeClaim",
        "PersistentVolumeClaim",
    ]
