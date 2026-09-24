"""Wiring contract for the smoke-test auto-confirm gate.

The e2e suites create native Cognito sign-ups with addresses shaped
``smoke+<random>@example-test.invalid``. Those suites have no mailbox, and
each signup makes Cognito send a confirmation email against the account's
50-emails/day Cognito email quota; once the quota is exhausted, ``SignUp``
itself fails with ``LimitExceededException`` and every signup-dependent test
fails or must be skipped.

The fix is a two-part gate on the pre-signup Lambda trigger
(``src/handlers/pre_signup.py``):

- the Lambda only auto-confirms when its ``AUTO_CONFIRM_SMOKE_USERS``
  environment variable is exactly ``"true"`` AND the email matches the smoke
  shape (behavior covered by ``tests/unit/test_pre_signup.py``);
- OpenTofu sets that variable on the pre-signup Lambda ONLY in the dev and
  ephemeral environments. These tests pin that wiring: the lambda module
  variable defaults to ``false`` (so any environment that forgets to opt in
  stays safe), dev and ephemeral pass ``true``, and prod passes an explicit
  ``false`` so a production signup can never be auto-confirmed by this path.
"""

from __future__ import annotations

from tests.unit.test_edge_security import TF_APP, load_hcl, modules

LAMBDA_DOC = load_hcl(TF_APP / "modules" / "lambda" / "main.tf")
ENVIRONMENTS = ("dev", "prod", "ephemeral")


def _module_var(doc: dict, module_name: str, var: str):
    values = [block[var] for block in modules(doc, module_name) if var in block]
    assert len(values) <= 1, f"{var} set more than once in one environment"
    return values[0] if values else None


def test_lambda_module_gate_defaults_off() -> None:
    """The module variable defaults to false: omitting it is always prod-safe."""
    for entry in LAMBDA_DOC.get("variable", []):
        if "auto_confirm_smoke_users" in entry:
            assert entry["auto_confirm_smoke_users"].get("default") is False
            return
    raise AssertionError("auto_confirm_smoke_users variable missing from lambda module")


def test_trigger_functions_merge_extra_env() -> None:
    """The trigger-function resource merges per-function extra_env into common_env."""
    for block in LAMBDA_DOC.get("resource", []):
        for label, body in block.get("aws_lambda_function", {}).items():
            if label == "trigger_functions":
                env = body["environment"][0]["variables"]
                assert "merge" in env
                assert "extra_env" in env
                return
    raise AssertionError("aws_lambda_function.trigger_functions not found")


def test_lambda_module_sets_flag_only_when_enabled() -> None:
    """The pre-signup trigger gets AUTO_CONFIRM_SMOKE_USERS only when the flag is on."""
    for entry in LAMBDA_DOC.get("locals", []):
        triggers = entry.get("trigger_functions")
        if not triggers or "pre-signup" not in triggers:
            continue
        # hcl2 parses the conditional expression as a raw interpolation
        # string; assert the flag drives it and the emitted key/value are
        # exactly the Lambda contract.
        expr = triggers["pre-signup"].get("extra_env")
        assert expr is not None, "pre-signup trigger lost its extra_env wiring"
        assert "var.auto_confirm_smoke_users" in expr
        assert 'AUTO_CONFIRM_SMOKE_USERS = "true"' in expr
        return
    raise AssertionError("pre-signup trigger not found in trigger_functions locals")


def test_dev_and_ephemeral_enable_smoke_auto_confirm() -> None:
    """Non-production environments opt in."""
    for env in ("dev", "ephemeral"):
        doc = load_hcl(TF_APP / "environments" / env / "main.tf")
        value = _module_var(doc, "lambda", "auto_confirm_smoke_users")
        assert value is True, f"{env} must enable smoke auto-confirm, got {value!r}"


def test_prod_explicitly_disables_smoke_auto_confirm() -> None:
    """Production pins the gate off; the variable must not be left to default silently."""
    doc = load_hcl(TF_APP / "environments" / "prod" / "main.tf")
    value = _module_var(doc, "lambda", "auto_confirm_smoke_users")
    assert value is False, f"prod must explicitly disable smoke auto-confirm, got {value!r}"
