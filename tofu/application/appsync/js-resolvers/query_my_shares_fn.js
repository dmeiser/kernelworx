import { util } from '@aws-appsync/utils';

/**
 * listMyShares pipeline - function 1 of 2.
 * Queries the Shares table GSI (targetAccountId-index) for every share
 * targeting the caller, then deduplicates by profileId and applies the same
 * defensive filters the former profile_sharing Lambda applied:
 *   - skip shares missing a string profileId/ownerAccountId
 *   - skip legacy shares with no accessible (READ/WRITE) permission (#242)
 *   - first share per profileId wins
 * The deduplicated map is stashed for the BatchGetItem function.
 *
 * AppSync JS runtime restrictions (APPSYNC_JS 1.0.0): no `continue`
 * statement and no Function.prototype.call, so the loop below uses a
 * single inclusive if-block and Object.hasOwn (the documented `in`
 * replacement).
 *
 * The Query is capped at MAX_PAGE_LIMIT items per page, mirroring the
 * listMyProfiles page cap (#369): a larger share list surfaces a nextToken,
 * which the response fails closed on, so a single invocation never exceeds
 * the resolver budget and the batch step's 100-key cap is the containment
 * boundary for both steps.
 */

const MAX_PAGE_LIMIT = 100;

function normalizeAccountId(accountId) {
    if (typeof accountId !== 'string') {
        accountId = '';
    }
    return accountId.startsWith('ACCOUNT#') ? accountId : `ACCOUNT#${accountId}`;
}

function hasAccessiblePermissions(permissions) {
    if (!Array.isArray(permissions) || permissions.length === 0) {
        return false;
    }
    for (const permission of permissions) {
        if (typeof permission === 'string' && ['READ', 'WRITE'].includes(permission.toUpperCase())) {
            return true;
        }
    }
    return false;
}

export function request(ctx) {
    const targetAccountId = normalizeAccountId(ctx.identity && ctx.identity.sub);
    return {
        operation: 'Query',
        index: 'targetAccountId-index',
        limit: MAX_PAGE_LIMIT,
        query: {
            expression: 'targetAccountId = :targetAccountId',
            expressionValues: util.dynamodb.toMapValues({ ':targetAccountId': targetAccountId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    if (ctx.result && ctx.result.nextToken) {
        util.error('listMyShares share list exceeds one page; accounts with this many shares are not supported');
    }

    const items = (ctx.result && ctx.result.items) || [];
    const sharesByProfile = {};
    const sharedProfileIds = [];
    for (const share of items) {
        const profileId = share.profileId;
        const ownerAccountId = share.ownerAccountId;
        const isValidShare = typeof profileId === 'string' && profileId.length > 0
            && typeof ownerAccountId === 'string' && ownerAccountId.length > 0
            && hasAccessiblePermissions(share.permissions)
            && !Object.hasOwn(sharesByProfile, profileId);
        if (isValidShare) {
            sharesByProfile[profileId] = {
                profileId: profileId,
                ownerAccountId: ownerAccountId,
                permissions: share.permissions
            };
            sharedProfileIds.push(profileId);
        }
    }

    ctx.stash.sharesByProfile = sharesByProfile;
    ctx.stash.sharedProfileIds = sharedProfileIds;
    return { count: sharedProfileIds.length };
}
