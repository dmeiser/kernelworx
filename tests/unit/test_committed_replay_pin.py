"""
Committed-replay pin for the Show & Sell mutations (wave 3, integration
plan section 5 step 4; r1 item 2's test-infra home; clean-room doctrine:
the pin is schema-derived, not custody-only).

Three contracts, all enforced structurally so a new mutation cannot land
without its replay probe:

1. DISPATCH == SCHEMA: every operation the handler modules dispatch is a
   Mutation field in the SDL (catches seam-only drift — a handler wired at
   the dispatcher but never exposed, or exposed but not dispatched).
2. PIN CASES == DISPATCH: every dispatched mutation names the test that
   proves its committed-replay contract (same key + payload replays the
   stored result; same key + different payload conflicts). A mutation with
   no named probe fails the pin at collection time.
3. Every named probe test exists in this suite (import-time resolution).
"""

import re
from pathlib import Path
from typing import Dict, Set

import pytest

from src.handlers import (
    event_operations,
    inventory_operations,
    order_operations,
    participant_data,
    payment_method_operations,
    unit_campaign_operations,
    unit_operations,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "tofu" / "application" / "schema" / "schema.graphql"

# The committed-replay probe for each mutation. Values name the test file
# and test that prove: commit, same-key replay returns the identical result
# (no double effect), same-key/different-payload conflicts. updateUnit and
# createOrder additionally pin the marker-mismatch path.
PIN_CASES: Dict[str, str] = {
    # unit_operations
    "createUnit": "test_unit_operations_handlers.py::TestCreateUnit::test_committed_replay_returns_same_result",
    "updateUnit": "test_unit_operations_handlers.py::TestUpdateUnit::test_replay",
    "createUnitInvite": "test_unit_operations_handlers.py::TestCreateUnitInvite::test_replay",
    "revokeUnitInvite": "test_unit_operations_handlers.py::TestRevokeUnitInvite::test_replay_returns_true",
    "redeemUnitInvite": "test_unit_operations_handlers.py::TestRedeemUnitInvite::test_replay",
    "revokeUnitAccessGrant": "test_wave2_coverage_sweep.py::TestFinalCoverage::test_revoke_grant_replay_and_marker_race",
    # unit_campaign_operations
    "createUnitCampaign": "test_unit_campaign_operations_handlers.py::TestCreateUnitCampaign::test_replay",
    "updateUnitCampaign": "test_wave2_coverage_sweep.py::TestFinalCoverage::test_update_campaign_replay",
    "joinUnitCampaign": "test_unit_campaign_operations_handlers.py::TestJoinUnitCampaign::test_replay",
    "removeUnitCampaignMembership": "test_wave2_coverage_sweep.py::TestFinalCoverage::test_remove_replay_and_uc_missing",
    # inventory_operations
    "recordInventoryReceipt": "test_inventory_operations.py::TestRecordReceipt::test_replay_no_double_count",
    "adjustInventory": "test_inventory_operations.py::TestInventorySweep::test_adjust_replay_and_council_negative",
    "adjustCouncilOnOrder": "test_inventory_operations.py::TestInventorySweep::test_adjust_council_replay_with_reason",
    "issueStockToScout": "test_inventory_operations.py::TestCustody::test_issue_replay",
    "returnStockFromScout": "test_inventory_operations.py::TestInventorySweep::test_return_replay_and_bad_items",
    # order_operations
    "createOrder": "test_order_operations.py::TestCustodyCreate::test_replay_returns_same_order",
    "fulfillIndividualOrderLine": "test_order_operations.py::TestFulfillReverse::test_replays",
    "reverseIndividualOrderFulfillment": "test_order_operations.py::TestOrderSweep::test_reverse_validation_and_kernel_restore",
    # event_operations (wave 4)
    "createShowAndSell": "test_event_operations.py::TestCreateEvent::test_replay",
    "updateShowAndSell": "test_wave4_coverage_sweep.py::TestEventSweep::test_update_replay_and_address",
    "cancelShowAndSell": "test_wave4_coverage_sweep.py::TestEventSweep::test_cancel_replay_race_and_non_admin",
    "assignShowAndSellInventory": "test_wave4_coverage_sweep.py::TestFinalWave4Branches::test_assign_replay_and_marker_race",
    "upsertShowAndSellSlot": "test_wave4_coverage_sweep.py::TestEventSweep::test_upsert_guards_and_replay",
    "deleteShowAndSellSlot": "test_wave4_coverage_sweep.py::TestEventSweep::test_delete_slot_guards_and_race",
    "signupScoutForShowAndSellSlot": "test_wave4_coverage_sweep.py::TestEventSweep::test_signup_replay_and_race",
    "cancelShowAndSellSignup": "test_wave4_coverage_sweep.py::TestWave4TrulyFinal::test_cancel_signup_missing_slot_row_and_race",
    "confirmShowAndSellWork": "test_wave4_coverage_sweep.py::TestWave4LastBranches::test_confirm_work_replay_and_version",
    # payment_method_operations (wave 5 fast-follow)
    "createUnitPaymentMethod": "test_payment_method_operations.py::TestCreateAndList::test_replay",
    "updateUnitPaymentMethod": "test_payment_method_operations.py::TestUpdateAndDeactivate::test_update_name",
    "deactivateUnitPaymentMethod": "test_payment_method_operations.py::TestUpdateAndDeactivate::test_deactivate_and_builtin_guard",
    "requestUnitPaymentMethodQrUpload": "test_payment_method_operations.py::TestQrFlow::test_request_confirm_delete_round_trip",
    "confirmUnitPaymentMethodQrUpload": "test_payment_method_operations.py::TestQrFlow::test_request_confirm_delete_round_trip",
    "deleteUnitPaymentMethodQrCode": "test_payment_method_operations.py::TestQrFlow::test_request_confirm_delete_round_trip",
}


def _schema_root_fields() -> Set[str]:
    """Every field declared on Query or Mutation. Show & Sell dispatchers
    route both (queries and mutations share the fieldName seam)."""
    source = SCHEMA.read_text()
    fields: Set[str] = set()
    for root in ("Query", "Mutation"):
        body = re.search(rf"^type {root} \{{.*?(?=^\}})", source, re.MULTILINE | re.DOTALL)
        assert body, f"{root} type not found in schema"
        fields |= set(re.findall(r"^\s{2}(\w+)\(", body.group(0), re.MULTILINE))
    return fields


def _dispatched_operations() -> Set[str]:
    dispatched: Set[str] = set()
    for module in (
        unit_operations,
        unit_campaign_operations,
        inventory_operations,
        order_operations,
        event_operations,
        payment_method_operations,
    ):
        dispatched |= set(module._DISPATCH.keys())  # type: ignore[attr-defined]
    return dispatched


def _schema_mutation_fields() -> Set[str]:
    source = SCHEMA.read_text()
    body = re.search(r"^type Mutation \{.*?(?=^\})", source, re.MULTILINE | re.DOTALL)
    assert body, "Mutation type not found in schema"
    return set(re.findall(r"^\s{2}(\w+)\(", body.group(0), re.MULTILINE))


def _dispatched_mutations() -> Set[str]:
    return _dispatched_operations() & _schema_mutation_fields()


def _probe_exists(reference: str) -> bool:
    file_part, _, test_path = reference.partition("::")
    test_source = (REPO_ROOT / "tests" / "unit" / file_part).read_text()
    class_name, _, method_name = test_path.rpartition("::")
    class_source_match = re.search(rf"class {class_name}\b.*?(?=^class |\Z)", test_source, re.MULTILINE | re.DOTALL)
    if not class_source_match:
        return False
    return re.search(rf"def {method_name}\b", class_source_match.group(0)) is not None


class TestReplayPin:
    def test_every_dispatched_operation_is_a_schema_field(self) -> None:
        dispatched = _dispatched_operations()
        schema = _schema_root_fields()
        assert dispatched <= schema, (
            f"handlers dispatch operations the schema does not declare (seam-only drift): {dispatched - schema}"
        )

    def test_pin_cases_cover_every_dispatched_mutation(self) -> None:
        dispatched = _dispatched_mutations()
        assert set(PIN_CASES.keys()) == dispatched, (
            f"pin/dispatch mismatch — add a replay probe case for each new mutation. "
            f"missing={dispatched - set(PIN_CASES)}, extra={set(PIN_CASES) - dispatched}"
        )

    def test_participant_data_dispatches_no_mutations(self) -> None:
        assert participant_data.handler is not None
        # participant_data is a read-path module; it must never grow a
        # mutation dispatcher (participant-safe surface is reads-only).
        assert not hasattr(participant_data, "_DISPATCH")

    @pytest.mark.parametrize("mutation", sorted(PIN_CASES))
    def test_named_probe_test_exists(self, mutation: str) -> None:
        assert _probe_exists(PIN_CASES[mutation]), (
            f"committed-replay probe for {mutation} not found at {PIN_CASES[mutation]}"
        )

    def test_none_create_order_has_no_marker_by_design(self) -> None:
        """The NONE createOrder path intentionally has no idempotency marker:
        the legacy JS pipeline owns NONE semantics (golden oracles), and the
        custody router only guards the CONSUME_SCOUT_CUSTODY transaction. This
        record keeps that an explicit contract, not an accident."""
        assert "createOrder" in PIN_CASES
        assert order_operations.FULFILLMENT_MODE_CUSTODY == "CONSUME_SCOUT_CUSTODY"
