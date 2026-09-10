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
 *
 * AppSync JS runtime restrictions (APPSYNC_JS 1.0.0): no `continue`
 * statement, so the loops below use inclusive if-blocks instead.
 */

// AppSync BatchGetItem supports at most 100 keys per table; accounts with
// more distinct shared profiles than that fail with an explicit error rather
// than returning a truncated list (a pipeline function cannot loop chunks).
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
        const share = sharesByProfile[profileId];
        if (share) {
            keys.push(util.dynamodb.toMapValues({
                ownerAccountId: share.ownerAccountId,
                profileId: share.profileId
            }));
        }
    }

    if (keys.length > MAX_BATCH_KEYS) {
        util.error('listMyShares supports at most ' + MAX_BATCH_KEYS + ' distinct shared profiles per account; found ' + keys.length);
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
        const hasRequiredFields = profile && share
            && typeof profile.profileId === 'string'
            && profile.sellerName && profile.createdAt && profile.updatedAt;
        if (hasRequiredFields) {
            result.push({
                profileId: profile.profileId,
                ownerAccountId: normalizeAccountId(profile.ownerAccountId),
                sellerName: profile.sellerName,
                unitType: profile.unitType != null ? profile.unitType : null,
                unitNumber: profile.unitNumber != null ? profile.unitNumber : null,
                createdAt: profile.createdAt,
                updatedAt: profile.updatedAt,
                isOwner: profile.ownerAccountId === callerAccountId,
                permissions: share.permissions,
                // Denormalized pointer for the SharedProfile.latestCampaign
                // field resolver's GetItem fast path (#331); absent on
                // unmigrated rows, which fall back to the per-item Query.
                latestCampaignId: profile.latestCampaignId != null ? profile.latestCampaignId : null
            });
        }
    }
    return result;
}
