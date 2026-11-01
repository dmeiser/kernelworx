import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

export function request(ctx) {
    const profile = ctx.stash.profile;
    
    // Safety check - profile should be set by fetch_profile_fn.js
    if (!profile) {
        util.error('Profile not found in stash', 'INTERNAL_ERROR');
    }
    
    // Check if caller is owner first (ownerAccountId uses ACCOUNT# prefix).
    // Ownership check (#545):
    // Only trust ownership if verified by the strongly consistent base-table
    // GetItem in step 1 (ctx.stash.isOwner === true).
    // If ctx.stash.isOwner is undefined (e.g. standalone test), fall back to
    // checking profile.ownerAccountId for backward compatibility.
    const expectedOwner = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    const isOwner = ctx.stash.isOwner !== undefined
        ? ctx.stash.isOwner === true
        : profile.ownerAccountId === expectedOwner;
    if (isOwner) {
        ctx.stash.authorized = true;
        // No DB operation needed for owner - return a no-op that won't query the database
        return {
            version: '2017-02-28',
            operation: 'GetItem',
            key: {
                profileId: { S: 'NOOP' },
                targetAccountId: { S: 'NOOP' }
            }
        };
    }
    
    // Not owner - check for share
    ctx.stash.authorized = false;
    const profileId = profile.profileId;  // Use profile.profileId which has PROFILE# prefix
    const targetAccountId = normalizeIdOrPrefix(ctx.identity.sub, 'ACCOUNT#');
    
    // Check for share in shares table: profileId + targetAccountId
    return {
        version: '2017-02-28',
        operation: 'GetItem',
        key: {
            profileId: { S: profileId },
            targetAccountId: { S: targetAccountId }
        },
        consistentRead: true
    };
}

export function response(ctx) {
    // If already authorized (owner), return the profile
    if (ctx.stash.authorized) {
        const profile = ctx.stash.profile;
        profile.isOwner = true;
        profile.permissions = ["READ", "WRITE"];
        return profile;
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;

    // Access denied paths return null (query permissions model - don't error),
    // matching the documented contract (schema.graphql getProfile) and the
    // sibling read resolvers (return_campaign_fn.js, return_order_fn.js).
    // No share found - access denied
    if (!share || !share.profileId) {
        return null;
    }

    // Share exists - check for READ or WRITE permission
    if (!share.permissions || !Array.isArray(share.permissions)) {
        return null;
    }
    
    // Stale share check (#432): a share records the ownerAccountId from when it was
    // created. A profile ownership transfer updates third-party shares best-effort, so
    // stale shares outlive the old owner. Deny when the share's owner no longer matches
    // the profile's current owner, matching the Python auth layer (src/utils/auth.py
    // _is_share_valid) and check_share_permissions_fn.js. Shares without ownerAccountId
    // (legacy rows) are accepted, mirroring the backward-compat behavior there.
    const profile = ctx.stash.profile;
    const currentOwner = profile && profile.ownerAccountId;
    if (share.ownerAccountId && currentOwner && share.ownerAccountId !== currentOwner) {
        return null;
    }
    
    // Has READ or WRITE permission - authorized
    if (share.permissions.includes('READ') || share.permissions.includes('WRITE')) {
        const profile = ctx.stash.profile;
        profile.isOwner = false;
        profile.permissions = share.permissions;
        return profile;
    }
    
    // Share exists but no valid permissions
    return null;
}
