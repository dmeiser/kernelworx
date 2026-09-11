"""Static wiring checks for the #355 retirement of the monolithic Lambda role.

#326 split the monolithic shared Lambda execution role into scoped per-domain
roles (campaign #351, profile/sharing #352, payment #353, account/reporting
#354) plus a dedicated role for the Cognito post-auth trigger (#355). #355
(chunk 5, final) removes the monolithic role entirely:

- the iam module declares no ``aws_iam_role.lambda_execution`` and no
  ``lambda_execution_role_arn`` output;
- the lambda module has no ``lambda_role_arn`` variable (no shared fallback —
  every non-admin function resolves through ``lambda_domain_role_arns`` and a
  missing entry fails the plan loudly);
- the cognito module has no legacy ``lambda_execution_role_arn`` fallback for
  the admin policy;
- every non-admin Lambda function key (app and trigger) has an entry in the
  ``lambda_domain_role_arns`` map of ALL THREE environments (dev, prod,
  ephemeral), so tofu plan can never hit the loud missing-entry failure;
- the recovery script no longer imports the retired role but does import the
  post-auth replacement.

These tests parse the OpenTofu configuration directly so the retirement
invariants hold regardless of what a future refactor does to the module
layout.
"""

import re
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
LAMBDA_TF = REPO_ROOT / "tofu" / "application" / "modules" / "lambda" / "main.tf"
IAM_TF = REPO_ROOT / "tofu" / "application" / "modules" / "iam" / "main.tf"
COGNITO_TF = REPO_ROOT / "tofu" / "application" / "modules" / "cognito" / "main.tf"
RECOVER_SH = REPO_ROOT / "scripts" / "ephemeral-recover-common.sh"
ENVIRONMENTS = ("dev", "prod", "ephemeral")


def _extract_map_keys(content: str, map_name: str) -> List[str]:
    """Return the quoted keys of a ``map_name = { ... }`` block ( brace-balanced)."""
    m = re.search(r"\b" + re.escape(map_name) + r"\s*=\s*\{", content)
    if not m:
        return []
    start = m.end() - 1
    depth = 0
    block = ""
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                block = content[start + 1 : i]
                break
    return re.findall(r'^\s*"([a-z0-9-]+)"\s*=', block, re.MULTILINE)


def _extract_list(content: str, list_name: str) -> List[str]:
    """Return the quoted items of a ``list_name = [...]`` local."""
    m = re.search(re.escape(list_name) + r"\s*=\s*\[([^\]]*)\]", content)
    if not m:
        return []
    return re.findall(r'"([^"]+)"', m.group(1))


class TestMonolithicRoleRemoved:
    """The monolithic role, its policies, and its plumbing are gone."""

    def test_iam_module_declares_no_monolithic_role(self) -> None:
        iam_tf = IAM_TF.read_text()
        assert 'resource "aws_iam_role" "lambda_execution"' not in iam_tf
        assert 'resource "aws_iam_role_policy_attachment" "lambda_basic"' not in iam_tf
        assert 'resource "aws_iam_role_policy" "lambda_dynamodb"' not in iam_tf
        assert 'resource "aws_iam_role_policy" "lambda_s3"' not in iam_tf
        assert 'resource "aws_iam_role_policy" "lambda_cloudfront"' not in iam_tf
        assert 'output "lambda_execution_role_arn"' not in iam_tf
        assert 'output "lambda_execution_role_name"' not in iam_tf
        assert "TODO(#75)" not in iam_tf

    def test_iam_module_declares_post_auth_role(self) -> None:
        iam_tf = IAM_TF.read_text()
        assert 'resource "aws_iam_role" "lambda_post_auth_execution"' in iam_tf
        assert 'output "lambda_post_auth_execution_role_arn"' in iam_tf
        # Scoped to the accounts table only: no S3/CloudFront/Cognito grants.
        post_auth_block = re.search(
            r'resource "aws_iam_role" "lambda_post_auth_execution".*?(?=\nresource|\Z)',
            iam_tf,
            re.DOTALL,
        )
        assert post_auth_block is not None

    def test_lambda_module_has_no_shared_fallback(self) -> None:
        lambda_tf = LAMBDA_TF.read_text()
        assert 'variable "lambda_role_arn"' not in lambda_tf
        # No fallback against a shared role anywhere in the resolution logic.
        assert "var.lambda_role_arn" not in lambda_tf

    def test_cognito_module_has_no_legacy_fallback(self) -> None:
        cognito_tf = COGNITO_TF.read_text()
        assert 'variable "lambda_execution_role_arn"' not in cognito_tf
        assert "coalesce(" not in cognito_tf


class TestEveryFunctionHasScopedRole:
    """Every non-admin function key resolves via lambda_domain_role_arns in all envs."""

    def _all_function_keys(self) -> List[str]:
        lambda_tf = LAMBDA_TF.read_text()
        admin_keys = set(_extract_list(lambda_tf, "admin_function_keys"))
        admin_keys |= set(_extract_list(lambda_tf, "admin_trigger_keys"))
        keys = _extract_map_keys(lambda_tf, "functions") + _extract_map_keys(lambda_tf, "trigger_functions")
        return [k for k in keys if k not in admin_keys]

    def test_all_non_admin_functions_have_domain_entries(self) -> None:
        function_keys = self._all_function_keys()
        assert len(function_keys) > 0
        for env in ENVIRONMENTS:
            env_tf = (REPO_ROOT / "tofu" / "application" / "environments" / env / "main.tf").read_text()
            domain_keys = set(_extract_map_keys(env_tf, "lambda_domain_role_arns"))
            missing = [k for k in function_keys if k not in domain_keys]
            assert not missing, f"{env}: functions missing a lambda_domain_role_arns entry: {missing}"
            assert "post-auth" in domain_keys, f"{env}: post-auth trigger must map to the scoped post-auth role"

    def test_environments_pass_no_monolithic_wiring(self) -> None:
        for env in ENVIRONMENTS:
            env_tf = (REPO_ROOT / "tofu" / "application" / "environments" / env / "main.tf").read_text()
            assert "lambda_execution_role_arn" not in env_tf, f"{env}: legacy monolithic wiring remains"
            assert "lambda_role_arn" not in env_tf, f"{env}: shared fallback wiring remains"
            assert "lambda_post_auth_execution_role_arn" in env_tf, f"{env}: post-auth role not wired"


class TestRecoveryImportsMatchRetirement:
    """The recovery script imports the post-auth role, not the retired one."""

    def test_recovery_imports(self) -> None:
        recover_sh = RECOVER_SH.read_text()
        assert "module.iam.aws_iam_role.lambda_execution" not in recover_sh
        assert "lambda_exec_role" not in recover_sh
        assert "module.iam.aws_iam_role.lambda_post_auth_execution" in recover_sh
        assert "module.iam.aws_iam_role_policy_attachment.lambda_post_auth_basic" in recover_sh
        assert "module.iam.aws_iam_role_policy.lambda_post_auth_dynamodb" in recover_sh
