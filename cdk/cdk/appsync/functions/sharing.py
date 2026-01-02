"""
AppSync functions for profile sharing and invitations.

This module contains all AppSync functions related to:
- Profile sharing (invites, direct shares)
- Authorization checks for shared access
- Invite redemption
"""

from typing import Any

from aws_cdk import aws_appsync as appsync
from constructs import Construct

from ..api import RESOLVERS_DIR


def create_sharing_functions(
    scope: Construct,
    api: appsync.GraphqlApi,
    env_name: str,
    datasources: dict[str, Any],
) -> dict[str, appsync.AppsyncFunction]:
    """
    Create AppSync functions for profile sharing operations.

    Args:
        scope: CDK construct scope
        api: The AppSync GraphQL API
        env_name: Environment name
        datasources: Dictionary of datasource name to data source

    Returns:
        Dictionary of function name to AppSync function
    """
    functions: dict[str, appsync.AppsyncFunction] = {}

    # === PROFILE SHARING FUNCTIONS ===

    # VerifyProfileOwnerForInviteFn
    functions["verify_profile_owner_for_invite"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForInviteFn",
        name=f"VerifyProfileOwnerForInviteFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_invite_fn.js")),
    )

    # CreateInviteFn
    functions["create_invite"] = appsync.AppsyncFunction(
        scope,
        "CreateInviteFn",
        name=f"CreateInviteFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_invite_fn.js")),
    )

    # VerifyProfileOwnerForRevokeFn
    functions["verify_profile_owner_for_revoke"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForRevokeFn",
        name=f"VerifyProfileOwnerForRevokeFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_revoke_fn.js")),
    )

    # DeleteShareFn
    functions["delete_share"] = appsync.AppsyncFunction(
        scope,
        "DeleteShareFn",
        name=f"DeleteShareFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_share_fn.js")),
    )

    # DeleteProfileInviteFn
    functions["delete_profile_invite"] = appsync.AppsyncFunction(
        scope,
        "DeleteProfileInviteFn",
        name=f"DeleteProfileInviteFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_profile_invite_fn.js")),
    )

    # DeleteInviteItemFn
    functions["delete_invite_item"] = appsync.AppsyncFunction(
        scope,
        "DeleteInviteItemFn",
        name=f"DeleteInviteItemFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "delete_invite_item_fn.js")),
    )

    # === SHARED AUTHORIZATION FUNCTIONS ===

    # VerifyProfileWriteAccessFn
    functions["verify_profile_write_access"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileWriteAccessFn",
        name=f"VerifyProfileWriteAccessFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_write_access_fn.js")),
    )

    # CheckSharePermissionsFn
    functions["check_share_permissions"] = appsync.AppsyncFunction(
        scope,
        "CheckSharePermissionsFn",
        name=f"CheckSharePermissionsFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_share_permissions_fn.js")),
    )

    # VerifyProfileReadAccessFn
    functions["verify_profile_read_access"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileReadAccessFn",
        name=f"VerifyProfileReadAccessFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_read_access_fn.js")),
    )

    # CheckShareReadPermissionsFn
    functions["check_share_read_permissions"] = appsync.AppsyncFunction(
        scope,
        "CheckShareReadPermissionsFn",
        name=f"CheckShareReadPermissionsFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_share_read_permissions_fn.js")),
    )

    # === PROFILE SHARING (DIRECT) FUNCTIONS ===

    # VerifyProfileOwnerForShareFn
    functions["verify_profile_owner_for_share"] = appsync.AppsyncFunction(
        scope,
        "VerifyProfileOwnerForShareFn",
        name=f"VerifyProfileOwnerForShareFn_{env_name}",
        api=api,
        data_source=datasources["profiles"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "verify_profile_owner_for_share_fn.js")),
    )

    # LookupAccountByEmailFn
    functions["lookup_account_by_email"] = appsync.AppsyncFunction(
        scope,
        "LookupAccountByEmailFn",
        name=f"LookupAccountByEmailFn_{env_name}",
        api=api,
        data_source=datasources["accounts"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_account_by_email_fn.js")),
    )

    # CheckExistingShareFn
    functions["check_existing_share"] = appsync.AppsyncFunction(
        scope,
        "CheckExistingShareFn",
        name=f"CheckExistingShareFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "check_existing_share_fn.js")),
    )

    # CreateShareFn
    functions["create_share"] = appsync.AppsyncFunction(
        scope,
        "CreateShareFn",
        name=f"CreateShareFn_{env_name}",
        api=api,
        data_source=datasources["shares"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "create_share_fn.js")),
    )

    # === INVITE REDEMPTION FUNCTIONS ===

    # LookupInviteFn
    functions["lookup_invite"] = appsync.AppsyncFunction(
        scope,
        "LookupInviteFn",
        name=f"LookupInviteFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "lookup_invite_fn.js")),
    )

    # MarkInviteUsedFn
    functions["mark_invite_used"] = appsync.AppsyncFunction(
        scope,
        "MarkInviteUsedFn",
        name=f"MarkInviteUsedFn_{env_name}",
        api=api,
        data_source=datasources["invites"],
        runtime=appsync.FunctionRuntime.JS_1_0_0,
        code=appsync.Code.from_asset(str(RESOLVERS_DIR / "mark_invite_used_fn.js")),
    )

    return functions
