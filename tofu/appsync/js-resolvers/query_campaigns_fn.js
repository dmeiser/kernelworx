import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized or profile not found, return no-op
    if (!ctx.stash.authorized || ctx.stash.profileNotFound) {
        return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId AND campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': 'NOOP', ':campaignId': 'NOOP' })
        },
        limit: 1
        };
    }
    
    const profileId = ctx.args.profileId;
    // Add PROFILE# prefix for DynamoDB query
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // V2: Direct PK query on profileId (no GSI needed)
    return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If not authorized or profile not found, return empty array
    if (!ctx.stash.authorized || ctx.stash.profileNotFound) {
        return [];
    }
    
    // Return all campaigns (active and inactive) with default isActive value
    const items = ctx.result.items || [];
    for (const item of items) {
        // Set default value for null/undefined isActive (backward compatibility)
        if (item.isActive == null) {
            item.isActive = true;
        }
    }
    
    return items;
}
