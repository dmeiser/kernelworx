from src.handlers import campaign_operations as co
from src.handlers import campaign_reporting as cr


def _assert_both_paths(module, attr_name: str, getter_fn, expected_table_name: str, dynamodb_table):
    # Branch when attr is set
    dummy = object()
    setattr(module, attr_name, dummy)
    assert getter_fn() is dummy

    # Branch when attr is None -> fallback to boto3/moto table
    setattr(module, attr_name, None)
    table = getter_fn()
    table_name = getattr(table, "table_name", "")
    # Accept either expected naming or a v2 variant - assert key part is present
    key_part = expected_table_name.split("-")[1]  # e.g., 'shares' or 'campaigns'
    assert key_part in table_name and table_name.endswith("-ue1-dev")


def test_campaign_operations_getters_cover_both_paths(dynamodb_table):
    _assert_both_paths(
        co, "campaigns_table", co._get_campaigns_table, "kernelworx-campaigns-v2-ue1-dev", dynamodb_table
    )
    _assert_both_paths(
        co,
        "shared_campaigns_table",
        co._get_shared_campaigns_table,
        "kernelworx-shared-campaigns-ue1-dev",
        dynamodb_table,
    )
    _assert_both_paths(co, "shares_table", co._get_shares_table, "kernelworx-shares-ue1-dev", dynamodb_table)
    _assert_both_paths(co, "profiles_table", co._get_profiles_table, "kernelworx-profiles-v2-ue1-dev", dynamodb_table)


def test_campaign_reporting_getters_cover_both_paths(dynamodb_table):
    _assert_both_paths(cr, "profiles_table", cr._get_profiles_table, "kernelworx-profiles-v2-ue1-dev", dynamodb_table)
    _assert_both_paths(
        cr, "campaigns_table", cr._get_campaigns_table, "kernelworx-campaigns-v2-ue1-dev", dynamodb_table
    )
    _assert_both_paths(cr, "orders_table", cr._get_orders_table, "kernelworx-orders-v2-ue1-dev", dynamodb_table)
