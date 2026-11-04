"""Deployment invariants: rendered manifests and compose must keep the security model intact."""
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def k8s():
    if shutil.which("kubectl") is None:
        pytest.skip("kubectl not installed")
    out = subprocess.run(["kubectl", "kustomize", str(ROOT / "infra/k8s/overlays/production")],
                         capture_output=True, text=True, check=True).stdout
    return {d["kind"]: d for d in yaml.safe_load_all(out) if d}


def test_api_pods_are_hardened(k8s):
    pod = k8s["Deployment"]["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    c = pod["containers"][0]
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert c["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert c["readinessProbe"]["httpGet"]["path"] == "/ready"
    assert c["livenessProbe"]["httpGet"]["path"] == "/health"
    assert "limits" in c["resources"]


def test_production_config_is_safe(k8s):
    data = k8s["ConfigMap"]["data"]
    assert data["APP_ENV"] == "production"
    assert data["AUTH_ENABLED"] == "true" and data["REQUIRE_RLS"] == "true"
    assert data["RATE_LIMIT_BACKEND"] == "redis"  # in-process limits are wrong with >1 replica
    assert k8s["ServiceAccount"]["automountServiceAccountToken"] is False
    assert k8s["HorizontalPodAutoscaler"]["spec"]["minReplicas"] >= 2
    assert k8s["PodDisruptionBudget"]["spec"]["minAvailable"] >= 1


def test_migrations_use_owner_role_not_app_role(k8s):
    job = k8s["Job"]["spec"]["template"]["spec"]["containers"][0]
    assert job["command"] == ["alembic", "upgrade", "head"]
    assert any(e["name"] == "AEGIS_MIGRATION_URL" for e in job["env"])


def test_compose_runs_api_as_non_superuser_app_role():
    compose = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text())
    api_env = compose["x-api-env"]
    assert api_env["POSTGRES_USER"] == "aegis_app" and api_env["AUTH_ENABLED"] == "true"
    assert compose["services"]["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    roles = (ROOT / "infra/compose/initdb/01-roles.sh").read_text()
    assert "aegis_app" in roles and "NOSUPERUSER NOBYPASSRLS" in roles


def test_pods_disable_service_links(k8s):
    """Service-link env vars (POSTGRES_PORT=tcp://...) would override app settings."""
    assert k8s["Deployment"]["spec"]["template"]["spec"]["enableServiceLinks"] is False
    assert k8s["Job"]["spec"]["template"]["spec"]["enableServiceLinks"] is False


def test_helm_chart_renders_hardened_and_hook_safe():
    if shutil.which("helm") is None:
        pytest.skip("helm not installed")
    out = subprocess.run(["helm", "template", "t", str(ROOT / "infra/helm/aegismem")],
                         capture_output=True, text=True, check=True).stdout
    docs = {d["kind"]: d for d in yaml.safe_load_all(out) if d}
    job = docs["Job"]
    assert job["metadata"]["annotations"]["helm.sh/hook"] == "pre-install,pre-upgrade"
    # pre-install hooks run before chart resources exist: must not reference the chart's SA
    assert "serviceAccountName" not in job["spec"]["template"]["spec"]
    for kind in ("Deployment", "Job"):
        spec = docs[kind]["spec"]["template"]["spec"]
        assert spec["enableServiceLinks"] is False
        assert spec["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True



def test_deployments_declare_every_store_backend(k8s):
    """Dev defaults are in-memory; every deployment must name real backends explicitly."""
    compose = yaml.safe_load((ROOT / "infra/compose/docker-compose.yml").read_text())["x-api-env"]
    helm = yaml.safe_load((ROOT / "infra/helm/aegismem/values.yaml").read_text())["config"]
    for cfg in (k8s["ConfigMap"]["data"], compose, helm):
        assert cfg["MEMORY_BACKEND"] == "postgres"
        assert cfg["VECTOR_BACKEND"] in ("pgvector", "qdrant")
        assert cfg["GRAPH_BACKEND"] in ("none", "neo4j")
