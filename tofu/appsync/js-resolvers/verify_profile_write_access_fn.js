import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // For idempotent delete operations ONLY, if item explicitly set to null by lookup function, skip auth
    // This preserves idempotent delete behavior (item already gone = success)
    // Check the correct field based on which operation
    const isDeleteOperation = ctx.info.fieldName === 'deleteOrder' || ctx.info.fieldName === 'deleteCampaign' || ctx.info.fieldName === 'deleteCampaign';
    const isDeletingOrder = ctx.info.fieldName === 'deleteOrder';
    const isDeletingCampaign = ctx.info.fieldName === 'deleteCampaign' || ctx.info.fieldName === 'deleteCampaign';
    
    const itemNotFound = (isDeletingOrder && ctx.stash.order === null) || 
                     (isDeletingCampaign && ctx.stash.campaign === null);
    
    if (isDeleteOperation && itemNotFound) {
        ctx.stash.skipAuth = true;
        // Return no-op request (won't be used)
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }
    
    // Extract profileId from various sources
    // For createOrder/updateOrder/deleteOrder: use order.profileId from stash or input
    // For updateCampaign/deleteCampaign: use campaign.profileId from stash  
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
        util.error('Profile ID not found in request or stash - debugging: ' + JSON.stringify({
        hasInput: !!ctx.args.input,
        hasOrder: !!(ctx.stash && ctx.stash.order),
        hasCampaign: !!(ctx.stash && ctx.stash.campaign),
        orderKeys: ctx.stash && ctx.stash.order ? Object.keys(ctx.stash.order) : []
        }), 'BadRequest');
    }
    
    // Normalize profileId to DB format: ensure it starts with PROFILE#
    const dbProfileId = (typeof profileId === 'string' && profileId.startsWith('PROFILE#')) ? profileId : 'PROFILE#' + profileId;
    
    // NEW STRUCTURE: Query profileId-index GSI to find profile
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        }
    };
}

export function response(ctx) {
    // If we skipped auth for idempotent delete, return success
    if (ctx.stash.skipAuth) {
        return { authorized: true };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        util.error('Profile not found', 'NotFound');
    }
    
    // Store profile in stash for later use
    ctx.stash.profile = profile;
    ctx.stash.profileOwner = profile.ownerAccountId;
    
    // Check if caller is owner (ownerAccountId is now ACCOUNT#sub format)
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    const isMatch = (profileOwner === callerAccountId);
    
    if (isMatch) {
        ctx.stash.isOwner = true;
        return profile;
    }
    
    // Not owner - need to check share permissions in next function
    ctx.stash.isOwner = false;
    return profile;
}
