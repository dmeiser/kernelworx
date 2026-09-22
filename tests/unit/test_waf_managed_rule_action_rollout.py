"""#429: the AWS managed core rule set flips from Count to Block in prod.

The waf module stages AWSManagedRulesCommonRuleSet in Count via the
``managed_rule_action`` variable default, so SQLi/XSS/server-exploit
signatures only logged while the rollout was observed. This test resolves
each environment's *effective* managed-rule action from the environment's
module call combined with the module's dynamic ``override_action`` block,
and asserts the override AWS will actually render for the rule group:

- prod overrides the variable to ``Block`` -> rendered ``override_action { none {} }``,
  meaning the rule group's own per-signature ``Block`` actions take effect;
- dev and ephemeral do not override it -> the module default ``Count`` keeps
  dev in observe-only mode and ephemeral creates no WAF at all.

The flip is live prod edge behavior: traffic matching a core-ruleset
signature starts receiving 403s instead of being logged and allowed.
"""

from __future__ import annotations

import json
from pathlib import Path

import hcl2

REPO_ROOT = Path(__file__).resolve().parents[2]
TF_APP = REPO_ROOT / "tofu" / "application"
WAF_MODULE = TF_APP / "modules" / "waf" / "main.tf"


def _norm(key: str) -> str:
    if isinstance(key, str) and key.startswith('"') and key.endswith('"'):
        return key[1:-1]
    return key


def _clean(value):
    if isinstance(value, dict):
        return {_norm(k): _clean(v) for k, v in value.items() if k not in ("__is_block__", "__comments__")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, str) and value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def load_hcl(path: Path) -> dict:
    with path.open() as f:
        return _clean(hcl2.load(f))


def block(value):
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], dict):
        return value[0]
    return value


def env_waf_module(env: str) -> dict:
    doc = load_hcl(TF_APP / "environments" / env / "main.tf")
    for entry in doc.get("module", []):
        if _norm("waf") in entry:
            return entry["waf"]
    raise AssertionError(f"module waf not found in {env}/main.tf")


def module_default(doc: dict, name: str):
    for entry in doc.get("variable", []):
        if name in entry:
            return entry[name].get("default")
    raise AssertionError(f"variable {name} not found")


def override_subblocks_for(doc: dict, action: str) -> set[str]:
    """Resolve which override_action sub-blocks render for a given action value.

    The module expresses the choice as dynamic blocks keyed on
    ``var.managed_rule_action == "<value>" ? [1] : []``; a literal match on
    that key selects the sub-block, mirroring how tofu evaluates it.
    """
    acl = None
    for entry in doc.get("resource", []):
        for bodies in entry.get("aws_wafv2_web_acl", {}).items():
            acl = bodies[1]
    assert acl is not None, "aws_wafv2_web_acl.main not found"
    managed = next(
        r for e in acl["dynamic"] for r in e["rule"]["content"] if r["name"] == "aws-core-managed-rules"
    )
    selected = set()
    for dyn in block(managed["override_action"])["dynamic"]:
        for name, spec in dyn.items():
            for_each = spec["for_each"]
            if for_each == f'${{var.managed_rule_action == "{action}" ? [1] : []}}':
                selected.add(name)
    return selected


def effective_action(env: str) -> str:
    waf = load_hcl(WAF_MODULE)
    override = env_waf_module(env).get("managed_rule_action")
    return override if override is not None else module_default(waf, "managed_rule_action")


def test_prod_flips_managed_rule_action_to_block():
    assert effective_action("prod") == "Block"


def test_prod_renders_override_none_so_managed_rules_block():
    waf = load_hcl(WAF_MODULE)
    # override_action { none {} } leaves the rule group's own actions in
    # force: every CommonRuleSet signature ships with action Block.
    assert override_subblocks_for(waf, effective_action("prod")) == {"none"}


def test_dev_stays_in_count_and_renders_count_override():
    assert effective_action("dev") == "Count"
    waf = load_hcl(WAF_MODULE)
    assert override_subblocks_for(waf, effective_action("dev")) == {"count"}


def test_ephemeral_creates_no_waf_and_overrides_nothing():
    mod = env_waf_module("ephemeral")
    assert mod["create"] is False
    assert "managed_rule_action" not in mod


def test_module_default_remains_count_for_staged_rollout():
    waf = load_hcl(WAF_MODULE)
    assert module_default(waf, "managed_rule_action") == "Count"
