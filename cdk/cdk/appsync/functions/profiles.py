"""
AppSync functions for profile operations.

This module contains all AppSync functions related to:
- Profile queries and authorization
- Profile deletion pipeline
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from ..api import RESOLVERS_DIR


def create_profile_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for profile query operations.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # === QUERY FUNCTIONS (PROFILE-RELATED) ===

    # FetchProfileFn
    functions["fetch_profile"] = appsync.AppsyncFunction(
        scope,
        "FetchProfileFn",
        name=f"FetchProfileFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "fetch_profile_fn.js")),
    )

    # CheckProfileReadAuthFn
    functions["check_profile_read_auth"] = appsync.AppsyncFunction(
        scope,
        "CheckProfileReadAuthFn",
        name=f"CheckProfileReadAuthFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_profile_read_auth_fn.js")),
    )

    # VerifyProfileWriteAccessOrOwnerFn
    functions["verify_profile_write_or_owner"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileWriteAccessOrOwnerFn",
        name=f"VerifyProfileWriteAccessOrOwnerFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(
            str(RESOLVERS_DIR / "verify_profile_write_access_or_owner_fn.js")
        ),
    )

    # CheckWritePermissionFn
    functions["check_write_permission"] = appsync.AppsyncFunction(
        scope,
        "CheckWritePermissionFn",
        name=f"CheckWritePermissionFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_write_permission_fn.js")),
    )

    # QuerySharesFn
    functions["query_shares"] = appsync.AppsyncFunction(
        scope,
        "QuerySharesFn",
        name=f"QuerySharesFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_shares_fn.js")),
    )

    # QueryInvitesFn
    functions["query_invites"] = appsync.AppsyncFunction(
        scope,
        "QueryInvitesFn",
        name=f"QueryInvitesFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_invites_fn.js")),
    )

    return functions


def create_profile_delete_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for deleteSellerProfile pipeline.

    These functions support the multi-step profile deletion process.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # LookupProfileForUpdateFn
    functions["lookup_profile_for_update"] = appsync.AppsyncFunction(
        scope,
        "LookupProfileForUpdateFn",
        name=f"LookupProfileForUpdateFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_profile_for_update_fn.js")),
    )

    # UpdateProfileFn
    functions["update_profile"] = appsync.AppsyncFunction(
        scope,
        "UpdateProfileFn",
        name=f"UpdateProfileFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "update_profile_fn.js")),
    )

    # VerifyProfileOwnerForDeleteFn
    functions["verify_profile_owner_for_delete"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForDeleteFn",
        name=f"VerifyProfileOwnerForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_delete_fn.js")),
    )

    # QueryProfileSharesForDeleteFn
    functions["query_profile_shares_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryProfileSharesForDeleteFn",
        name=f"QueryProfileSharesForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_profile_shares_for_delete_fn.js")),
    )

    # QueryProfileInvitesForDeleteFn
    functions["query_profile_invites_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryProfileInvitesForDeleteFn",
        name=f"QueryProfileInvitesForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "query_profile_invites_for_delete_fn.js")),
    )

    # DeleteProfileSharesFn
    functions["delete_profile_shares"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileSharesFn",
        name=f"DeleteProfileSharesFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_shares_fn.js")),
    )

    # DeleteProfileInvitesFn
    functions["delete_profile_invites"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileInvitesFn",
        name=f"DeleteProfileInvitesFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_invites_fn.js")),
    )

    # QueryProfileCampaignsForDeleteFn
    functions["query_profile_campaigns_for_delete"] = appsync.AppsyncFunction(
        scope,
        "QueryProfileCampaignsForDeleteFn",
        name=f"QueryProfileCampaignsForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(
            str(RESOLVERS_DIR / "query_profile_campaigns_for_delete_fn.js")
        ),
    )

    # DeleteProfileCampaignsFn
    functions["delete_profile_campaigns"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileCampaignsFn",
        name=f"DeleteProfileCampaignsFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_campaigns_fn.js")),
    )

    # DeleteProfileOwnershipFn (no-op in new design)
    functions["delete_profile_ownership"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileOwnershipFn",
        name=f"DeleteProfileOwnershipFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_ownership_fn.js")),
    )

    # DeleteProfileMetadataFn
    functions["delete_profile_metadata"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileMetadataFn",
        name=f"DeleteProfileMetadataFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_metadata_fn.js")),
    )

    # GetSharedCampaignForDeleteFn
    functions["get_shared_campaign_for_delete"] = appsync.AppsyncFunction(
        scope,
        "GetSharedCampaignForDeleteFn",
        name=f"GetSharedCampaignForDeleteFn_{env_name}",
        api=api,
        data_source=datasources["shared_campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "get_shared_campaign_for_delete_fn.js")),
    )

    # CheckCatalogUsageFn
    functions["check_catalog_usage"] = appsync.AppsyncFunction(
        scope,
        "CheckCatalogUsageFn",
        name=f"CheckCatalogUsageFn_{env_name}",
        api=api,
        data_source=datasources["campaigns"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_catalog_usage_fn.js")),
    )

    return functions
