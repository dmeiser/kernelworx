from typing import Callable, Dict

from aws_cdk import RemovalPolicy
from aws_cdk import aws_dynamodb as ddb
from constructs import Construct


def create_dynamodb_tables(stack: Construct, rn: Callable[[str], str]) -> Dict[str, ddb.Table]:
    """Create all DynamoDB tables used by the application and return them in a dict.

    Args:
        stack: CDK Construct (usually the Stack instance)
        rn: helper function to create resource names (rn(name: str) -> str)

    Returns:
        Mapping of table names to Table constructs
    """

    # PsmApp single-table (legacy)
    psm_table_name = rn("kernelworx-app")
    print(f"✓ Defining PsmApp table: {psm_table_name}")

    table = ddb.Table(
        stack,
        "PsmApp",
        table_name=psm_table_name,
        partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        stream=ddb.StreamViewType.NEW_AND_OLD_IMAGES,
    )

    # GSIs
    table.add_global_secondary_index(
        index_name="GSI1",
        partition_key=ddb.Attribute(name="GSI1PK", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="GSI1SK", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI2",
        partition_key=ddb.Attribute(name="GSI2PK", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="GSI2SK", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI3",
        partition_key=ddb.Attribute(name="GSI3PK", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="GSI3SK", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI4",
        partition_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI5",
        partition_key=ddb.Attribute(name="campaignId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI6",
        partition_key=ddb.Attribute(name="orderId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI7",
        partition_key=ddb.Attribute(name="campaignId", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI8",
        partition_key=ddb.Attribute(name="email", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    table.add_global_secondary_index(
        index_name="GSI9",
        partition_key=ddb.Attribute(name="inviteCode", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    # TTL for invites and shares in the PsmApp table
    cfn_table = table.node.default_child
    assert cfn_table is not None
    cfn_table.time_to_live_specification = ddb.CfnTable.TimeToLiveSpecificationProperty(
        attribute_name="expiresAt",
        enabled=True,
    )

    # --- Multi-table design ---
    accounts_table = ddb.Table(
        stack,
        "AccountsTable",
        table_name=rn("kernelworx-accounts"),
        partition_key=ddb.Attribute(name="accountId", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    accounts_table.add_global_secondary_index(
        index_name="email-index",
        partition_key=ddb.Attribute(name="email", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    catalogs_table = ddb.Table(
        stack,
        "CatalogsTable",
        table_name=rn("kernelworx-catalogs"),
        partition_key=ddb.Attribute(name="catalogId", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    catalogs_table.add_global_secondary_index(
        index_name="ownerAccountId-index",
        partition_key=ddb.Attribute(name="ownerAccountId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    catalogs_table.add_global_secondary_index(
        index_name="isPublic-createdAt-index",
        partition_key=ddb.Attribute(name="isPublicStr", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="createdAt", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    profiles_table = ddb.Table(
        stack,
        "ProfilesTableV2",
        table_name=rn("kernelworx-profiles"),
        partition_key=ddb.Attribute(name="ownerAccountId", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    profiles_table.add_global_secondary_index(
        index_name="profileId-index",
        partition_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    shares_table = ddb.Table(
        stack,
        "SharesTable",
        table_name=rn("kernelworx-shares"),
        partition_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="targetAccountId", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    shares_table.add_global_secondary_index(
        index_name="targetAccountId-index",
        partition_key=ddb.Attribute(name="targetAccountId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    invites_table = ddb.Table(
        stack,
        "InvitesTable",
        table_name=rn("kernelworx-invites"),
        partition_key=ddb.Attribute(name="inviteCode", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    invites_table.add_global_secondary_index(
        index_name="profileId-index",
        partition_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    cfn_invites = invites_table.node.default_child
    assert cfn_invites is not None
    cfn_invites.time_to_live_specification = ddb.CfnTable.TimeToLiveSpecificationProperty(
        attribute_name="expiresAt",
        enabled=True,
    )

    campaigns_table = ddb.Table(
        stack,
        "CampaignsTableV2",
        table_name=rn("kernelworx-campaigns"),
        partition_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="campaignId", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    campaigns_table.add_global_secondary_index(
        index_name="campaignId-index",
        partition_key=ddb.Attribute(name="campaignId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    campaigns_table.add_global_secondary_index(
        index_name="catalogId-index",
        partition_key=ddb.Attribute(name="catalogId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.KEYS_ONLY,
    )

    orders_table = ddb.Table(
        stack,
        "OrdersTableV2",
        table_name=rn("kernelworx-orders"),
        partition_key=ddb.Attribute(name="campaignId", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="orderId", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    orders_table.add_global_secondary_index(
        index_name="orderId-index",
        partition_key=ddb.Attribute(name="orderId", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    orders_table.add_global_secondary_index(
        index_name="profileId-index",
        partition_key=ddb.Attribute(name="profileId", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="createdAt", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    shared_campaigns_table = ddb.Table(
        stack,
        "SharedCampaignsTable",
        table_name=rn("kernelworx-shared-campaigns"),
        partition_key=ddb.Attribute(name="sharedCampaignCode", type=ddb.AttributeType.STRING),
        billing_mode=ddb.BillingMode.PAY_PER_REQUEST,
        point_in_time_recovery_specification=ddb.PointInTimeRecoverySpecification(
            point_in_time_recovery_enabled=True
        ),
        removal_policy=RemovalPolicy.RETAIN,
        deletion_protection=True,
    )
    shared_campaigns_table.add_global_secondary_index(
        index_name="GSI1",
        partition_key=ddb.Attribute(name="createdBy", type=ddb.AttributeType.STRING),
        sort_key=ddb.Attribute(name="createdAt", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )
    shared_campaigns_table.add_global_secondary_index(
        index_name="GSI2",
        partition_key=ddb.Attribute(name="unitCampaignKey", type=ddb.AttributeType.STRING),
        projection_type=ddb.ProjectionType.ALL,
    )

    return {
        "table": table,
        "accounts_table": accounts_table,
        "catalogs_table": catalogs_table,
        "profiles_table": profiles_table,
        "shares_table": shares_table,
        "invites_table": invites_table,
        "campaigns_table": campaigns_table,
        "orders_table": orders_table,
        "shared_campaigns_table": shared_campaigns_table,
    }
