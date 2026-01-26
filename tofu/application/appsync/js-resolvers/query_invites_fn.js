import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // OWNER-ONLY access (not shared users with WRITE)
    if (!ctx.stash.isOwner) {
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
    
    // OWNER-ONLY access (not shared users with WRITE)
    if (!ctx.stash.isOwner) {
        return [];
    }
    
    const items = ctx.result.items || [];
    const nowEpochSeconds = Math.floor(util.time.nowEpochSeconds());
    
    // Transform items to match GraphQL schema, filtering out expired and used invites
    // Note: AppSync JS runtime does not support 'continue', so we use filter logic instead
    const validItems = items.filter((item) => {
        // Skip expired invites (expiresAt is epoch seconds)
        if (item.expiresAt && item.expiresAt < nowEpochSeconds) {
            return false;
        }
        
        // Skip used invites (has used=true or usedAt set)
        if (item.used === true || item.usedAt) {
            return false;
        }
        
        return true;
    });
    
    const transformedItems = validItems.map((item) => {
        return {
            inviteCode: item.inviteCode,
            profileId: item.profileId, // Keep PROFILE# prefix
            permissions: item.permissions,
            // Convert epoch seconds to ISO 8601 string
            expiresAt: util.time.epochMilliSecondsToISO8601(item.expiresAt * 1000),
            createdAt: item.createdAt,
            // Map createdBy to createdByAccountId
            createdByAccountId: item.createdBy
        };
    });
    
    return transformedItems;
}
