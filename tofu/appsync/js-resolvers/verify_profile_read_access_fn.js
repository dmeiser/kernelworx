import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If campaign not found, skip this function
    if (ctx.stash.campaignNotFound) {
        // Return a no-op read
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }
    
    // If order not found, skip this function
    if (ctx.stash.orderNotFound) {
        // Return a no-op read
        return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ ownerAccountId: 'NOOP', profileId: 'NOOP' })
        };
    }
    
    // Extract profileId from args or stash
    let profileId = null;
    
    if (ctx.args.profileId) {
        profileId = ctx.args.profileId;
    } else if (ctx.stash && ctx.stash.campaign && ctx.stash.campaign.profileId) {
        profileId = ctx.stash.campaign.profileId;
    } else if (ctx.stash && ctx.stash.profileId) {
        // For orders, profileId is set directly in stash
        profileId = ctx.stash.profileId;
    }
    
    if (!profileId) {
        util.error('Profile ID not found in request', 'BadRequest');
    }
    
    // Store profileId in stash for next function
    ctx.stash.profileId = profileId;
    
    // Add PROFILE# prefix for DynamoDB query (field resolver strips it for API responses)
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
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
    // If campaign not found, pass through (will return null at end)
    if (ctx.stash.campaignNotFound) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // If order not found, pass through (will return null at end)
    if (ctx.stash.orderNotFound) {
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const profile = ctx.result.items && ctx.result.items[0];
    
    if (!profile) {
        // Profile doesn't exist - for getCampaign, we'll return null later
        // For listCampaignsByProfile, we'll return empty array
        ctx.stash.profileNotFound = true;
        ctx.stash.authorized = false;
        return { authorized: false };
    }
    
    // Check if caller is owner (ownerAccountId is now ACCOUNT#sub format)
    const callerAccountId = 'ACCOUNT#' + ctx.identity.sub;
    const profileOwner = profile.ownerAccountId;
    
    if (profileOwner === callerAccountId) {
        ctx.stash.isOwner = true;
        ctx.stash.authorized = true;
        // Store profile in stash for downstream functions (ensure PROFILE# prefix is used)
        ctx.stash.profile = profile;
        ctx.stash.profileId = profile.profileId;
        return { authorized: true };
    }
    
    // Not owner - need to check for share (READ or WRITE)
    ctx.stash.isOwner = false;
    // Store profile in stash so subsequent functions use the DB-prefixed profileId
    ctx.stash.profile = profile;
    ctx.stash.profileId = profile.profileId;
    return profile;
}
