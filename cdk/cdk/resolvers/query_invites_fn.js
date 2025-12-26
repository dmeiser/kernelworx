import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized, return no-op
    if (!ctx.stash.isOwner && !ctx.stash.hasWritePermission) {
        return {
            operation: 'Query',
            index: 'profileId-index',
            query: {
                expression: 'profileId = :profileId',
                expressionValues: util.dynamodb.toMapValues({ ':profileId': 'NOOP' })
            }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Add PROFILE# prefix for DynamoDB query
    const dbProfileId = profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    
    // Query invites for this profile using profileId-index GSI
    return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({
                ':profileId': dbProfileId
            })
        },
        scanIndexForward: false  // Sort by SK descending (newest first if SK is timestamp-based)
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // If not authorized, return empty array
    if (!ctx.stash.isOwner && !ctx.stash.hasWritePermission) {
        return [];
    }
    
    const items = ctx.result.items || [];
    
    // Transform items to match GraphQL schema
    const transformedItems = [];
    for (const item of items) {
        const transformed = {
            inviteCode: item.inviteCode,
            profileId: item.profileId && item.profileId.startsWith('PROFILE#') 
                ? item.profileId.substring(8) 
                : item.profileId,
            permissions: item.permissions,
            // Convert epoch seconds to ISO 8601 string
            expiresAt: util.time.epochMilliSecondsToISO8601(item.expiresAt * 1000),
            createdAt: item.createdAt,
            // Map createdBy to createdByAccountId
            createdByAccountId: item.createdBy
        };
        transformedItems.push(transformed);
    }
    
    return transformedItems;
}
