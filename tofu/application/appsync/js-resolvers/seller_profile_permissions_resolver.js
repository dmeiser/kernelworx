import { util, runtime } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    if (ctx.source && ctx.source.permissions) {
        return runtime.earlyReturn(ctx.source.permissions);
    }

    const callerAccountId = ctx.identity && ctx.identity.sub;
    const ownerAccountId = ctx.source && ctx.source.ownerAccountId;
    const profileId = ctx.source && ctx.source.profileId;
    
    // Check ownership - handle both prefixed (ACCOUNT#xxx) and clean (xxx) ownerAccountId
    const expectedOwnerPrefixed = normalizeIdOrPrefix(callerAccountId, 'ACCOUNT#');
    if (expectedOwnerPrefixed === ownerAccountId || callerAccountId === ownerAccountId) {
        if (ctx.stash) {
            ctx.stash.isOwner = true;
        }
        return runtime.earlyReturn(['READ', 'WRITE']);
    }

    if (ctx.stash) {
        ctx.stash.ownerAccountId = ownerAccountId;
    }
    
    // Normalize profileId to ensure PROFILE# prefix for share lookup
    const dbProfileId = normalizeIdOrPrefix(profileId, 'PROFILE#');
    // Normalize targetAccountId to ensure ACCOUNT# prefix for share lookup
    const dbTargetAccountId = normalizeIdOrPrefix(callerAccountId, 'ACCOUNT#');
    
    // Query shares table for share record: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
            profileId: dbProfileId, 
            targetAccountId: dbTargetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If owner, return full permissions
    if (ctx.stash && ctx.stash.isOwner) {
        return ['READ', 'WRITE'];
    }
    
    if (ctx.error) {
        // Fail closed loudly: a swallowed datastore error is indistinguishable from
        // a real "no permissions" answer, so a throttle silently strips write access
        // from the UI and never reaches AppSync's resolver error metrics (#553).
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - return null
    if (!share || !share.profileId) {
        return null;
    }

    // Stale share check (#432): a share records the ownerAccountId from when it was
    // created. A profile ownership transfer updates third-party shares best-effort, so
    // stale shares outlive the old owner. Deny when the share's owner no longer matches
    // the profile's current owner, matching the Python auth layer (src/utils/auth.py
    // _is_share_valid) and check_share_permissions_fn.js. Shares without ownerAccountId
    // (legacy rows) are accepted, mirroring the backward-compat behavior there.
    const ownerAccountId = (ctx.source && ctx.source.ownerAccountId) || (ctx.stash && ctx.stash.ownerAccountId);
    if (share.ownerAccountId && ownerAccountId) {
        const shareOwner = normalizeIdOrPrefix(share.ownerAccountId, 'ACCOUNT#');
        const currentOwner = normalizeIdOrPrefix(ownerAccountId, 'ACCOUNT#');
        if (shareOwner !== currentOwner) {
            return [];
        }
    }
    
    // Return the permissions from the share
    if (share.permissions && Array.isArray(share.permissions)) {
        return share.permissions;
    }
    
    // Share exists but no valid permissions - return null
    return null;
}
