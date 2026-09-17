"""
Day 4 tests: client config loader + multi-tenant behavior in /ingest.

The most important tests here aren't "does loading a valid config work" -
they're the two realistic failure modes a solutions engineer actually
hits when onboarding a new client (tenant_id/filename mismatch, an
out-of-range value), and the core multi-tenant claim itself: the SAME
document must produce a DIFFERENT `in_scope_for_tenant` result depending
on which tenant uploaded it.
"""

import os
import subprocess
import sys

import pytest
import yaml
from fastapi.testclient import TestClient

from app.main import app
from app.config.loader import (
    load_client_config,
    list_available_tenants,
    TenantNotFoundError,
    InvalidClientConfigError,
)

client = TestClient(app)

SAMPLE_DIR = "data/sample_docs"


@pytest.fixture(scope="module", autouse=True)
def ensure_sample_docs():
    if not os.path.exists(f"{SAMPLE_DIR}/medical_bill_sample.pdf"):
        subprocess.run([sys.executable, "scripts/generate_sample_docs.py"], check=True)


def test_lists_both_configured_tenants():
    tenants = list_available_tenants()
    assert "acme_insurance" in tenants
    assert "beta_insurance" in tenants


def test_loads_acme_config_correctly():
    config = load_client_config("acme_insurance")
    assert config.review_threshold == 0.85
    assert "medical_bill" in [t.value for t in config.accepted_document_types]


def test_loads_beta_config_with_different_settings():
    """Beta must genuinely differ from Acme, not just have a different name."""
    config = load_client_config("beta_insurance")
    assert config.review_threshold == 0.70
    assert "medical_bill" not in [t.value for t in config.accepted_document_types]


def test_unknown_tenant_raises():
    with pytest.raises(TenantNotFoundError):
        load_client_config("does_not_exist_corp")


def test_tenant_id_filename_mismatch_is_caught(tmp_path, monkeypatch):
    """Realistic onboarding mistake: copy-pasting another tenant's file and forgetting to update the internal tenant_id."""
    import app.config.loader as loader_module

    monkeypatch.setattr(loader_module, "CONFIG_DIR", tmp_path)
    bad_config = tmp_path / "client_gamma_insurance.yaml"
    bad_config.write_text(yaml.dump({
        "tenant_id": "beta_insurance",  # mismatch, deliberately
        "display_name": "Gamma Corp",
        "accepted_document_types": ["accident_report"],
        "review_threshold": 0.8,
    }))
    with pytest.raises(InvalidClientConfigError, match="filename and internal tenant_id must match"):
        loader_module.load_client_config("gamma_insurance", use_cache=False)


def test_invalid_threshold_value_is_caught(tmp_path, monkeypatch):
    import app.config.loader as loader_module

    monkeypatch.setattr(loader_module, "CONFIG_DIR", tmp_path)
    bad_config = tmp_path / "client_delta_insurance.yaml"
    bad_config.write_text(yaml.dump({
        "tenant_id": "delta_insurance",
        "display_name": "Delta Corp",
        "accepted_document_types": ["accident_report"],
        "review_threshold": 1.5,  # out of valid 0.0-1.0 range
    }))
    with pytest.raises(InvalidClientConfigError):
        loader_module.load_client_config("delta_insurance", use_cache=False)


def test_ingest_endpoint_requires_tenant_id():
    with open(f"{SAMPLE_DIR}/medical_bill_sample.pdf", "rb") as f:
        response = client.post("/ingest", files={"file": ("medical_bill_sample.pdf", f, "application/pdf")})
    assert response.status_code == 422  # FastAPI's missing-required-field response


def test_ingest_endpoint_rejects_unknown_tenant():
    with open(f"{SAMPLE_DIR}/medical_bill_sample.pdf", "rb") as f:
        response = client.post(
            "/ingest",
            files={"file": ("medical_bill_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "not_a_real_tenant"},
        )
    assert response.status_code == 404


def test_same_document_different_scope_per_tenant():
    """
    THE core multi-tenant test: the identical medical bill file must be
    in_scope for Acme (accepts medical bills) and NOT in_scope for Beta
    (doesn't) - same code path, same file, different config-driven outcome.
    """
    with open(f"{SAMPLE_DIR}/medical_bill_sample.pdf", "rb") as f:
        acme_response = client.post(
            "/ingest",
            files={"file": ("medical_bill_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "acme_insurance"},
        )
    with open(f"{SAMPLE_DIR}/medical_bill_sample.pdf", "rb") as f:
        beta_response = client.post(
            "/ingest",
            files={"file": ("medical_bill_sample.pdf", f, "application/pdf")},
            data={"tenant_id": "beta_insurance"},
        )

    assert acme_response.status_code == 200
    assert beta_response.status_code == 200

    acme_body = acme_response.json()
    beta_body = beta_response.json()

    # Same document, same classification...
    assert acme_body["document_type"] == beta_body["document_type"] == "medical_bill"

    # ...but different tenant-driven scope decision and threshold.
    assert acme_body["in_scope_for_tenant"] is True
    assert beta_body["in_scope_for_tenant"] is False
    assert acme_body["tenant_review_threshold"] != beta_body["tenant_review_threshold"]


def test_tenants_endpoint():
    response = client.get("/tenants")
    assert response.status_code == 200
    assert "acme_insurance" in response.json()["tenants"]


def test_tenant_config_endpoint():
    response = client.get("/tenants/acme_insurance")
    assert response.status_code == 200
    assert response.json()["review_threshold"] == 0.85


def test_tenant_config_endpoint_404_for_unknown():
    response = client.get("/tenants/nonexistent")
    assert response.status_code == 404
