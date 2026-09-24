import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already owner or profile was invalid/not found, skip this check
    if (ctx.stash.isOwner || ctx.stash.skipGetItem) {
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    
    // Additional validation - if profileId is not set or invalid, skip
    if (!profileId || !profileId.startsWith('PROFILE#')) {
        ctx.stash.hasWritePermission = false;
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Get share from shares table using profileId + targetAccountId (caller's sub)
    const targetAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;
    
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
        profileId: profileId, 
        targetAccountId: targetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If owner, pass through with write permission set explicitly.
    if (ctx.stash.isOwner) {
        ctx.stash.hasWritePermission = true;
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - not authorized (check profileId instead of PK)
    if (!share || !share.profileId) {
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }
    
    // Stale share check (#432): a share records the ownerAccountId from when it was
    // created. A profile ownership transfer updates third-party shares best-effort, so
    // stale shares outlive the old owner. Deny when the share's owner no longer matches
    // the profile's current owner, matching the Python auth layer (src/utils/auth.py
    // _is_share_valid) and check_share_permissions_fn.js. Shares without ownerAccountId
    // (legacy rows) are accepted, mirroring the backward-compat behavior there.
    const profileOwner = ctx.stash.profileOwner;
    if (share.ownerAccountId && profileOwner && share.ownerAccountId !== profileOwner) {
        ctx.stash.hasWritePermission = false;
        return { authorized: false };
    }

    // Check for WRITE permission
    if (share.permissions && Array.isArray(share.permissions) && share.permissions.includes('WRITE')) {
        ctx.stash.hasWritePermission = true;
        return { authorized: true };
    }
    
    // Share exists but no WRITE permission
    ctx.stash.hasWritePermission = false;
    return { authorized: false };
}
