import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner or skipAuth), skip this check
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    // Non-owner: check for WRITE share
    // Extract profileId using same logic as VerifyProfileWriteAccessFn
    let profileId = null;
    
    if (ctx.args.input && ctx.args.input.profileId) {
        profileId = ctx.args.input.profileId;
    } else if (ctx.stash && ctx.stash.order) {
        // Orders have profileId attribute - use it directly (not PK which is the campaign key)
        profileId = ctx.stash.order.profileId;
    } else if (ctx.stash && ctx.stash.campaign && ctx.stash.campaign.profileId) {
        // Campaigns have profileId attribute - use it directly (not PK which is composite)
        profileId = ctx.stash.campaign.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found for share check', 'BadRequest');
    }
    
    // Normalize profileId to ensure PROFILE# prefix for share lookup
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    const targetAccountId = ctx.identity.sub.startsWith('ACCOUNT#') ? ctx.identity.sub : `ACCOUNT#${ctx.identity.sub}`;

    // Look up share in shares table: profileId + targetAccountId
    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ 
        profileId: dbProfileId, 
        targetAccountId: targetAccountId 
        }),
        consistentRead: true
    };
}

export function response(ctx) {
    // If already authorized, return success
    if (ctx.stash.isOwner || ctx.stash.skipAuth) {
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.profileId) {
        util.error('Forbidden: Only profile owner or users with WRITE permission can perform this action (no share found)', 'Unauthorized');
    }
    
    // Share exists but doesn't have permissions field - deny
    if (!share.permissions || !Array.isArray(share.permissions)) {
        util.error('Forbidden: Share exists but permissions are invalid', 'Unauthorized');
    }
    
    // Check if caller has WRITE permission via share
    if (share.permissions.includes('WRITE')) {
        ctx.stash.share = share;
        return { authorized: true };
    }
    
    // Share exists but only has READ permission - access denied
    util.error('Forbidden: Only profile owner or users with WRITE permission can perform this action (share has READ only, permissions: ' + JSON.stringify(share.permissions) + ')', 'Unauthorized');
}
