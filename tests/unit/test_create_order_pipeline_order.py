"""Pipeline-order pin for the createOrder custody router (r2 C-3v).

Structural guard: the custody router step MUST precede the legacy
create_order_fn write step in the createOrder pipeline. A later edit that
reorders or drops the router would let custody-mode input reach the NONE
writer — the JS refusal added in the same commit is the second layer, and
this test is the first: it fails at plan-file level, not at runtime.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVERS = REPO_ROOT / "tofu" / "application" / "modules" / "appsync" / "resolvers_mutations.tf"


def _pipeline_functions() -> list[str]:
    body = re.search(
        r'resource "aws_appsync_resolver" "create_order" \{.*?\n\}',
        RESOLVERS.read_text(),
        re.DOTALL,
    )
    assert body, "create_order resolver not found"
    return re.findall(r"aws_appsync_function\.(\w+)\.function_id", body.group(0))


class TestCreateOrderPipelineOrder:
    def test_custody_router_precedes_legacy_write(self) -> None:
        order = _pipeline_functions()
        assert "custody_router" in order, "custody router step missing from the createOrder pipeline"
        assert "create_order" in order, "legacy create_order_fn step missing"
        assert order.index("custody_router") < order.index("create_order"), (
            "custody router must run BEFORE the legacy NONE writer — a reorder would let "
            "custody input reach the plain write path"
        )

    def test_auth_steps_precede_the_router(self) -> None:
        order = _pipeline_functions()
        for required in ("verify_profile_write_access", "get_campaign_for_order", "get_catalog"):
            assert required in order, f"{required} missing from the createOrder pipeline"
            assert order.index(required) < order.index("custody_router"), (
                f"{required} must run before the custody router (auth and loads are the router's contract)"
            )

    def test_totals_sync_after_the_legacy_write(self) -> None:
        order = _pipeline_functions()
        assert order.index("sync_campaign_totals") > order.index("create_order")
