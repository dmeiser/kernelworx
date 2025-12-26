import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const profile = ctx.stash.profile;
    
    // Safety check - profile should be set by fetch_profile_fn.js
    if (!profile) {
        util.error('Profile not found in stash', 'InternalServerError');
    }
    
    // Check if caller is owner first (ownerAccountId uses ACCOUNT# prefix)
    const expectedOwner = 'ACCOUNT#' + ctx.identity.sub;
    if (profile.ownerAccountId === expectedOwner) {
        ctx.stash.authorized = true;
        // No DB operation needed, return no-op
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Not owner - check for share
    ctx.stash.authorized = false;
    const profileId = ctx.stash.profileId;
    
    // Check for share in shares table: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
        profileId: profileId, 
        targetAccountId: ctx.identity.sub 
        }),
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
    
    // No share found - access denied
    if (!share || !share.profileId) {
        util.error('Not authorized to access this profile', 'Unauthorized');
    }
    
    // Share exists - check for READ or WRITE permission
    if (!share.permissions || !Array.isArray(share.permissions)) {
        util.error('Not authorized to access this profile', 'Unauthorized');
    }
    
    // Has READ or WRITE permission - authorized
    if (share.permissions.includes('READ') || share.permissions.includes('WRITE')) {
        const profile = ctx.stash.profile;
        profile.isOwner = false;
        profile.permissions = share.permissions;
        return profile;
    }
    
    // Share exists but no valid permissions
    util.error('Not authorized to access this profile', 'Unauthorized');
}
