import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If already authorized (owner), profile not found, campaign not found, or order not found, skip
    if (ctx.stash.authorized || ctx.stash.profileNotFound || ctx.stash.campaignNotFound || ctx.stash.orderNotFound) {
        // Use a no-op read
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ profileId: 'NOOP', targetAccountId: 'NOOP' })
        };
    }
    
    const profileId = ctx.stash.profileId;
    // Normalize profileId to ensure PROFILE# prefix
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
    // Normalize targetAccountId to ensure ACCOUNT# prefix
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
    // If already authorized, profile not found, campaign not found, or order not found, pass through
    if (ctx.stash.authorized || ctx.stash.profileNotFound || ctx.stash.campaignNotFound || ctx.stash.orderNotFound) {
        return { authorized: ctx.stash.authorized };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const share = ctx.result;
    
    // No share found - access denied
    if (!share || !share.profileId) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // Share exists - check for READ or WRITE permission
    if (!share.permissions || !Array.isArray(share.permissions)) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // Has READ or WRITE permission - authorized
    if (share.permissions.includes('READ') || share.permissions.includes('WRITE')) {
        ctx.stash.authorized = true;
        ctx.stash.share = share;
        return { authorized: true };
    }
    
    // Share exists but no valid permissions
    ctx.stash.authorized = false;
    return { authorized: false };
}
