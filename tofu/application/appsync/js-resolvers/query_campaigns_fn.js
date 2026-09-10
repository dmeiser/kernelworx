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
    const request = {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ ':profileId': dbProfileId })
        }
    };

    const limit = ctx.args.limit;
    if (typeof limit === 'number' && limit > 0) {
        request.limit = limit;
    }
    if (ctx.args.nextToken) {
        request.nextToken = ctx.args.nextToken;
    }

    return request;
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If not authorized or profile not found, return empty connection
    if (!ctx.stash.authorized || ctx.stash.profileNotFound) {
        return { campaigns: [], nextToken: null };
    }

    // Return all campaigns (active and inactive) with default isActive value
    const items = ctx.result.items || [];
    for (const item of items) {
        // Set default value for null/undefined isActive (backward compatibility)
        if (item.isActive == null) {
            item.isActive = true;
        }
    }

    return {
        campaigns: items,
        nextToken: ctx.result.nextToken || null
    };
}
