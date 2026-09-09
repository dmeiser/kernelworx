import { util, runtime } from '@aws-appsync/utils';

/**
 * listMyShares pipeline - function 2 of 2.
 * BatchGetItem the shared profiles from the Profiles table using the
 * ownerAccountId/profileId composite keys stashed by query_my_shares_fn,
 * then merges profile data with share permissions into the SharedProfile
 * response shape the former profile_sharing Lambda produced:
 *   - profiles missing sellerName/createdAt/updatedAt are skipped
 *   - ownerAccountId keeps the ACCOUNT# prefix; isOwner compares the raw
 *     stored ownerAccountId against the prefixed caller sub
 *   - permissions come from the share item, unitType/unitNumber from the profile
 *
 * WARNING: this file is loaded via Terraform templatefile() (see
 * modules/appsync/functions_sharing.tf), so every `${...}` below is
 * Terraform-interpolated, not a JS template literal. `${table_name}` is
 * the only intended placeholder; do NOT add other `${...}` sequences here —
 * Terraform will try to substitute them and the plan will fail or substitute
 * the wrong value. Use string concatenation instead of JS template literals.
 */

// AppSync BatchGetItem supports at most 100 keys per table; users with more
// shares than that get the first 100 (a pipeline function cannot loop chunks).
const MAX_BATCH_KEYS = 100;
const tableName = '${table_name}';

function normalizeAccountId(accountId) {
    if (typeof accountId !== 'string') {
        accountId = '';
    }
    return accountId.startsWith('ACCOUNT#') ? accountId : 'ACCOUNT#' + accountId;
}

export function request(ctx) {
    const sharesByProfile = (ctx.stash && ctx.stash.sharesByProfile) || {};
    const sharedProfileIds = (ctx.stash && ctx.stash.sharedProfileIds) || [];

    const keys = [];
    for (const profileId of sharedProfileIds) {
        if (keys.length >= MAX_BATCH_KEYS) {
            break;
        }
        const share = sharesByProfile[profileId];
        if (!share) {
            continue;
        }
        keys.push(util.dynamodb.toMapValues({
            ownerAccountId: share.ownerAccountId,
            profileId: share.profileId
        }));
    }

    if (keys.length === 0) {
        return runtime.earlyReturn([]);
    }

    return {
        operation: 'BatchGetItem',
        tables: {
            [tableName]: {
                keys: keys,
                consistentRead: true
            }
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const callerAccountId = normalizeAccountId(ctx.identity && ctx.identity.sub);
    const sharesByProfile = (ctx.stash && ctx.stash.sharesByProfile) || {};
    const sharedProfileIds = (ctx.stash && ctx.stash.sharedProfileIds) || [];
    const profiles = (ctx.result && ctx.result.data && ctx.result.data[tableName]) || [];

    const profilesById = {};
    for (const profile of profiles) {
        if (profile && typeof profile.profileId === 'string') {
            profilesById[profile.profileId] = profile;
        }
    }

    const result = [];
    for (const profileId of sharedProfileIds) {
        const profile = profilesById[profileId];
        const share = sharesByProfile[profileId];
        if (!profile || !share) {
            continue;
        }
        if (typeof profile.profileId !== 'string') {
            continue;
        }
        if (!profile.sellerName || !profile.createdAt || !profile.updatedAt) {
            continue;
        }
        result.push({
            profileId: profile.profileId,
            ownerAccountId: normalizeAccountId(profile.ownerAccountId),
            sellerName: profile.sellerName,
            unitType: profile.unitType != null ? profile.unitType : null,
            unitNumber: profile.unitNumber != null ? profile.unitNumber : null,
            createdAt: profile.createdAt,
            updatedAt: profile.updatedAt,
            isOwner: profile.ownerAccountId === callerAccountId,
            permissions: share.permissions
        });
    }
    return result;
}
