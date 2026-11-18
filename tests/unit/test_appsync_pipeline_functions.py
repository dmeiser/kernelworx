"""Pipeline function-list contract for AppSync PIPELINE resolvers.

AppSync does not document duplicate function IDs in a resolver's
``pipeline_config.functions`` list as supported: the console refuses to add a
function that is already in a pipeline, so the service likely rejects such
configs at UpdateResolver time. #438's two-phase profile-write authorization
originally listed ``verify_profile_write_access`` twice in six write-mutation
pipelines; the second slot now uses a dedicated
``verify_profile_write_access_step2`` aws_appsync_function resource.

These tests parse the OpenTofu configuration into a semantic model (via
python-hcl2, the pattern established by test_edge_security.py and
test_monolithic_role_retirement.py) and assert the meaning of the contract:
every PIPELINE resolver's functions list references each
aws_appsync_function at most once.
"""

from __future__ import annotations

from tests.unit.test_edge_security import TF_APP, load_hcl

APPSYNC_DIR = TF_APP / "modules" / "appsync"

_RESOLVER_FILES = (
    "resolvers_mutations.tf",
    "resolvers_queries.tf",
)


def _pipeline_resolvers() -> list[tuple[str, str, list[str]]]:
    out = []
    for filename in _RESOLVER_FILES:
        path = APPSYNC_DIR / filename
        if not path.exists():
            continue
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type != "aws_appsync_resolver":
                    continue
                for name, attrs in instances.items():
                    if attrs.get("kind") != "PIPELINE":
                        continue
                    functions = []
                    for cfg in attrs.get("pipeline_config", []):
                        functions.extend(cfg.get("functions", []))
                    out.append((filename, name, functions))
    return out


def test_pipeline_function_ids_are_unique() -> None:
    failures = []
    for filename, name, functions in _pipeline_resolvers():
        seen: set[str] = set()
        for fn in functions:
            ref = fn if isinstance(fn, str) else str(fn)
            if ref in seen:
                failures.append(f"{filename}:{name} repeats {ref}")
            seen.add(ref)
    assert not failures, "duplicate pipeline function references:\n" + "\n".join(failures)


def _resolver_pipelines(resolver_file: str) -> dict[str, list[str]]:
    doc = load_hcl(APPSYNC_DIR / resolver_file)
    return {
        name: [fn for cfg in attrs.get("pipeline_config", []) for fn in cfg.get("functions", [])]
        for resource in doc.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_resolver"
        for name, attrs in instances.items()
    }


def test_two_phase_write_check_uses_distinct_functions() -> None:
    functions: set[str] = set()
    for path in sorted(APPSYNC_DIR.glob("functions_*.tf")):
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type == "aws_appsync_function":
                    functions.update(instances)
    assert "verify_profile_write_access" in functions
    assert "verify_profile_write_access_step2" in functions
    # #547: the pre-#438 single-step owner verifier is retired; the two
    # profile-share/invite queries now run the shared two-phase pair like the
    # write mutations do.
    assert "verify_profile_write_or_owner" not in functions
    step1 = "${aws_appsync_function.verify_profile_write_access.function_id}"
    step2 = "${aws_appsync_function.verify_profile_write_access_step2.function_id}"
    write_mutations = (
        "create_campaign",
        "update_campaign",
        "delete_campaign",
        "create_order",
        "update_order",
        "delete_order",
    )
    resolvers = _resolver_pipelines("resolvers_mutations.tf")
    for mutation in write_mutations:
        pipeline = resolvers[mutation]
        assert pipeline.index(step1) < pipeline.index(step2), (
            f"{mutation} must run the ownership read before the share-path lookup"
        )
    # #547: the profile-scoped read queries must decide ownership the same way -
    # the strongly consistent base-table GetItem (step 1) before the GSI locator
    # (step 2). Never the retired single-step GSI verifier.
    query_resolvers = _resolver_pipelines("resolvers_queries.tf")
    for query in ("list_shares_by_profile", "list_invites_by_profile"):
        pipeline = query_resolvers[query]
        assert pipeline.index(step1) < pipeline.index(step2), (
            f"{query} must decide ownership by the strongly consistent base-table "
            "GetItem (step 1) before the GSI locator (step 2)"
        )
        assert "${aws_appsync_function.verify_profile_write_or_owner.function_id}" not in pipeline


def test_two_phase_read_owner_check_uses_distinct_functions() -> None:
    # #508: the profile-scoped READ pipelines decided ownership off the
    # eventually-consistent profileId-index GSI alone, so after an ownership
    # transfer the former owner kept passing the gate (reading the new owner's
    # campaigns/orders) and the new owner was refused with profileNotFound until
    # the index caught up. They now mirror the write path: the strongly
    # consistent base-table GetItem (step 1) before the GSI locator (step 2).
    functions: set[str] = set()
    for path in sorted(APPSYNC_DIR.glob("functions_*.tf")):
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type == "aws_appsync_function":
                    functions.update(instances)
    assert "verify_profile_read_access" in functions
    assert "verify_profile_read_access_step2" in functions
    step1 = "${aws_appsync_function.verify_profile_read_access.function_id}"
    step2 = "${aws_appsync_function.verify_profile_read_access_step2.function_id}"
    # Every pipeline that used to authorize ownership from the GSI read.
    read_queries = (
        "get_campaign",
        "list_campaigns_by_profile",
        "get_order",
        "list_orders_by_campaign",
    )
    resolvers = _resolver_pipelines("resolvers_queries.tf")
    for query in read_queries:
        pipeline = resolvers[query]
        assert step1 in pipeline, f"{query} must keep the consistent ownership read"
        assert step2 in pipeline, (
            f"{query} must run the GSI locator as a second function so the owner "
            "decision comes from the strongly consistent base-table GetItem"
        )
        assert pipeline.index(step1) < pipeline.index(step2), f"{query} must decide ownership before the GSI locator"
        # The share check reads the profile the locator produced, so it must run
        # after both phases.
        share_check = "${aws_appsync_function.check_share_read_permissions.function_id}"
        assert pipeline.index(step2) < pipeline.index(share_check), (
            f"{query} must run the share check after the GSI locator"
        )


def test_order_write_pipelines_sync_campaign_totals() -> None:
    """#746: every order-write path keeps the denormalized
    Campaign.totalOrders / Campaign.totalRevenue counters in sync.

    The authenticated pipelines (createOrder, updateOrder, deleteOrder) run
    the sync_campaign_totals step AFTER the write step, which stashes the
    delta on ctx.stash.totalsDelta. publicCreateOrder cannot use that step:
    its resolver already carries 10 functions, AppSync's hard cap (the
    ephemeral apply fails with "A resolver can only be composed of 10
    functions"), so its totals update rides INSIDE create_public_order's
    TransactWriteItems instead - pinned by
    create_public_order_fn.test.js. If a pipeline loses its sync step, list
    views fall back to per-campaign COUNT/SUM queries - the 2*N pattern #746
    removed.
    """
    sync = "${aws_appsync_function.sync_campaign_totals.function_id}"
    write_step_by_pipeline = {
        "create_order": "${aws_appsync_function.create_order.function_id}",
        "update_order": "${aws_appsync_function.update_order.function_id}",
        "delete_order": "${aws_appsync_function.delete_order.function_id}",
    }
    resolvers = _resolver_pipelines("resolvers_mutations.tf")
    for pipeline_name, write_step in write_step_by_pipeline.items():
        pipeline = resolvers[pipeline_name]
        assert pipeline.count(sync) == 1, f"{pipeline_name} must list sync_campaign_totals exactly once"
        assert pipeline.index(write_step) < pipeline.index(sync), (
            f"{pipeline_name} must run sync_campaign_totals AFTER the order write "
            "(the delta is stashed by the write step)"
        )
    # publicCreateOrder is at AppSync's 10-function resolver cap; its totals
    # update must stay inside the write transaction, not a pipeline step.
    public_pipeline = resolvers["public_create_order"]
    assert sync not in public_pipeline, (
        "public_create_order is at AppSync's 10-function cap; the totals update must "
        "ride create_public_order's TransactWriteItems (see create_public_order_fn.js)"
    )
    # The delete pipeline verifies propagation after the delete; the counter
    # sync sits between the write and the verification, which reads the stash.
    delete_pipeline = resolvers["delete_order"]
    verify = "${aws_appsync_function.verify_order_delete_propagation.function_id}"
    assert delete_pipeline.index(sync) < delete_pipeline.index(verify)


def test_custody_sale_authorization_precedes_payment_validation() -> None:
    """SEC-1: a custody sale's authorization is settled before any payment-method verdict.

    `check_share_permissions` defers its FORBIDDEN for
    `createOrder(fulfillmentMode = CONSUME_SCOUT_CUSTODY)` so a Unit Admin with no share
    on the Profile can still be authorized (§2.4.2). That deferral is only safe while the
    composite answer arrives before any step that can report a fact about someone else's
    account: `validate_payment_method` reads the Profile owner's stored methods and answers
    "Payment method 'X' does not exist for this account", so running it first turns the
    refusal into a yes/no oracle over another account's payment methods. The membership
    guard step is where the composite is answered (it holds the share verdict and the
    Unit grant row), so payment validation must sit behind it.

    This is a pipeline-order property, which no resolver unit test can see: the JS tests
    prove the denial exists, only this test proves it arrives early enough.
    """
    resolvers = _resolver_pipelines("resolvers_mutations.tf")
    pipeline = resolvers["create_order"]
    share = "${aws_appsync_function.check_share_permissions.function_id}"
    guard = "${aws_appsync_function.get_membership_guard_for_order.function_id}"
    payment = "${aws_appsync_function.validate_payment_method_appsync.function_id}"
    write = "${aws_appsync_function.create_order.function_id}"

    assert pipeline.count(guard) == 1 and pipeline.count(payment) == 1
    assert pipeline.index(share) < pipeline.index(guard), (
        "the deferred share verdict must be closed by the guard step, not left open"
    )
    assert pipeline.index(guard) < pipeline.index(payment), (
        "createOrder must settle the custody sale's authorization before validating the "
        "profile owner's payment methods (SEC-1 payment-method enumeration oracle)"
    )
    assert pipeline.index(guard) < pipeline.index(write)
    # AppSync's hard cap on a pipeline resolver: 10 functions. The reordering is not
    # allowed to answer SEC-1 by adding an eleventh step.
    assert len(pipeline) <= 10, f"createOrder carries {len(pipeline)} functions"


def test_delete_order_pipeline_sweeps_fulfillment_children_first() -> None:
    """ARCH-1: `deleteOrder` reads the Order's fulfillment children before it writes.

    The children-first rule of SHOW_AND_SELL_EXISTING_APPLICATION_IMPACT.md §7.1 is a
    pipeline property: `delete_order` can only take the children it was given, so the read
    step has to run first, and the totals sync and the propagation check have to run after
    the write (both read what the write stashed).
    """
    resolvers = _resolver_pipelines("resolvers_mutations.tf")
    pipeline = resolvers["delete_order"]
    lookup = "${aws_appsync_function.lookup_order_for_delete.function_id}"
    children = "${aws_appsync_function.get_order_fulfillments_for_delete.function_id}"
    write = "${aws_appsync_function.delete_order.function_id}"
    verify = "${aws_appsync_function.verify_order_delete_propagation.function_id}"

    assert pipeline.count(children) == 1
    assert pipeline.index(lookup) < pipeline.index(children), (
        "the children read is keyed off the Order row the lookup stashes"
    )
    assert pipeline.index(children) < pipeline.index(write), (
        "deleteOrder must read the fulfillment children before deleting the Order"
    )
    assert pipeline.index(write) < pipeline.index(verify)
    assert len(pipeline) <= 10, f"deleteOrder carries {len(pipeline)} functions"


def test_two_phase_fetch_profile_check_uses_distinct_functions() -> None:
    functions: set[str] = set()
    for path in sorted(APPSYNC_DIR.glob("functions_*.tf")):
        doc = load_hcl(path)
        for resource in doc.get("resource", []):
            for res_type, instances in resource.items():
                if res_type == "aws_appsync_function":
                    functions.update(instances)
    assert "fetch_profile" in functions
    assert "fetch_profile_step2" in functions
    step1 = "${aws_appsync_function.fetch_profile.function_id}"
    step2 = "${aws_appsync_function.fetch_profile_step2.function_id}"
    two_phase_queries = (
        "payment_methods_for_profile",
        "get_profile",
    )
    doc = load_hcl(APPSYNC_DIR / "resolvers_queries.tf")
    resolvers = {
        name: attrs
        for resource in doc.get("resource", [])
        for res_type, instances in resource.items()
        if res_type == "aws_appsync_resolver"
        for name, attrs in instances.items()
    }
    for query in two_phase_queries:
        attrs = resolvers[query]
        pipeline = [fn for cfg in attrs.get("pipeline_config", []) for fn in cfg.get("functions", [])]
        assert pipeline.index(step1) < pipeline.index(step2), (
            f"{query} must run the ownership read before the share-path lookup"
        )
