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


def test_cognito_webauthn_and_mfa_configuration():
    doc = load_hcl(TF_APP / "modules" / "cognito" / "main.tf")
    user_pool = None
    client = None
    terraform_data_res = None

    for entry in doc.get("resource", []):
        for k, v in entry.items():
            clean_k = k.strip('"')
            if clean_k == "aws_cognito_user_pool":
                user_pool = v.get("main") or v.get('"main"')
            elif clean_k == "aws_cognito_user_pool_client":
                client = v.get("web") or v.get('"web"')
            elif clean_k == "terraform_data":
                terraform_data_res = v.get("webauthn_factor_configuration") or v.get('"webauthn_factor_configuration"')

    assert user_pool is not None, "aws_cognito_user_pool.main must exist"
    assert client is not None, "aws_cognito_user_pool_client.web must exist"
    assert terraform_data_res is not None, "terraform_data.webauthn_factor_configuration must exist"

    # Device configuration must be omitted to prevent TOTP suppression for admins
    assert "device_configuration" not in user_pool

    # Dynamic sign-in policy and WebAuthn configuration
    dynamics = user_pool.get("dynamic", [])
    web_authn_dynamic = None
    sign_in_policy_dynamic = None
    for d in dynamics:
        for dyn_k, dyn_v in d.items():
            clean_dyn_k = dyn_k.strip('"')
            if clean_dyn_k == "web_authn_configuration":
                web_authn_dynamic = dyn_v
            elif clean_dyn_k == "sign_in_policy":
                sign_in_policy_dynamic = dyn_v

    assert web_authn_dynamic is not None, "dynamic web_authn_configuration must exist"
    web_authn_content = web_authn_dynamic["content"][0]
    assert web_authn_content["user_verification"].strip('"') == "required"

    assert sign_in_policy_dynamic is not None, "dynamic sign_in_policy must exist"
    sign_in_content = sign_in_policy_dynamic["content"][0]
    allowed_factors = _normalize_list(sign_in_content["allowed_first_auth_factors"])
    assert "PASSWORD" in allowed_factors
    assert "WEB_AUTHN" in allowed_factors

    # App client explicit auth flows
    explicit_flows = _normalize_list(client["explicit_auth_flows"])
    assert "ALLOW_USER_AUTH" in explicit_flows

    # terraform_data workaround for FactorConfiguration=MULTI_FACTOR_WITH_USER_VERIFICATION
    triggers = _normalize_list(terraform_data_res["triggers_replace"])
    assert "${aws_cognito_user_pool.main.id}" in triggers
    assert "${var.web_authn_relying_party_id}" in triggers

    depends_on = _normalize_list(terraform_data_res["depends_on"])
    assert "${aws_cognito_user_pool.main}" in depends_on

    provisioner = terraform_data_res["provisioner"][0]
    local_exec = provisioner.get("local-exec") or provisioner.get('"local-exec"')
    cmd = local_exec["command"]
    assert "set-user-pool-mfa-config" in cmd
    assert "FactorConfiguration=MULTI_FACTOR_WITH_USER_VERIFICATION" in cmd
    assert "UserVerification=required" in cmd
