"""Tests for Cognito callback and logout URL configurations across environments."""

from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
TF_APP = REPO_ROOT / "tofu" / "application"


def _clean(val):
    if isinstance(val, dict):
        return {k: _clean(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_clean(x) for x in val]
    return val


def load_hcl(path: Path) -> dict:
    with path.open() as f:
        return _clean(hcl2.load(f))


def get_locals(doc: dict) -> dict:
    combined = {}
    for entry in doc.get("locals", []):
        combined.update(entry)
    return combined


def _normalize_list(items: list) -> list[str]:
    return [x.strip('"') if isinstance(x, str) else x for x in items]


def test_dev_cognito_callback_and_logout_urls():
    doc = load_hcl(TF_APP / "environments" / "dev" / "main.tf")
    locs = get_locals(doc)
    callbacks = _normalize_list(locs.get("cognito_callback_urls", []))
    logouts = _normalize_list(locs.get("cognito_logout_urls", []))

    assert "https://${local.site_domain}" in callbacks
    assert "https://${local.site_domain}/" in callbacks
    assert "https://${local.site_domain}/callback" in callbacks
    assert "http://localhost:5173" in callbacks
    assert "http://localhost:5173/" in callbacks
    assert "http://localhost:5173/callback" in callbacks
    assert "https://local.dev.appworx.app:5173" in callbacks
    assert "https://local.dev.appworx.app:5173/" in callbacks
    assert "https://local.dev.appworx.app:5173/callback" in callbacks

    assert "https://${local.site_domain}" in logouts
    assert "https://${local.site_domain}/" in logouts
    assert "http://localhost:5173" in logouts
    assert "http://localhost:5173/" in logouts
    assert "https://local.dev.appworx.app:5173" in logouts
    assert "https://local.dev.appworx.app:5173/" in logouts


def test_prod_cognito_callback_and_logout_urls():
    doc = load_hcl(TF_APP / "environments" / "prod" / "main.tf")
    locs = get_locals(doc)
    callbacks = _normalize_list(locs.get("cognito_callback_urls", []))
    logouts = _normalize_list(locs.get("cognito_logout_urls", []))

    assert "https://${local.site_domain}" in callbacks
    assert "https://${local.site_domain}/" in callbacks
    assert "https://${local.site_domain}/callback" in callbacks

    assert "https://${local.site_domain}" in logouts
    assert "https://${local.site_domain}/" in logouts


def test_ephemeral_cognito_callback_and_logout_urls():
    doc = load_hcl(TF_APP / "environments" / "ephemeral" / "main.tf")
    locs = get_locals(doc)
    callbacks = _normalize_list(locs.get("cognito_callback_urls", []))
    logouts = _normalize_list(locs.get("cognito_logout_urls", []))

    assert "http://localhost:4173" in callbacks
    assert "http://localhost:4173/" in callbacks
    assert "http://localhost:4173/callback" in callbacks
    assert "http://localhost:5173" in callbacks
    assert "http://localhost:5173/" in callbacks
    assert "http://localhost:5173/callback" in callbacks

    assert "http://localhost:4173" in logouts
    assert "http://localhost:4173/" in logouts
    assert "http://localhost:5173" in logouts
    assert "http://localhost:5173/" in logouts


def test_cognito_module_allowed_oauth_scopes():
    doc = load_hcl(TF_APP / "modules" / "cognito" / "main.tf")
    for entry in doc.get("resource", []):
        if "aws_cognito_user_pool_client" in entry:
            client = entry["aws_cognito_user_pool_client"].get("web", {})
            scopes = _normalize_list(client.get("allowed_oauth_scopes", []))
            assert "aws.cognito.signin.user.admin" in scopes
            assert "openid" in scopes
            assert "email" in scopes
            assert "profile" in scopes
