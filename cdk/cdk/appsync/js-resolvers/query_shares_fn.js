import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized, return empty query
    if (!ctx.stash.isOwner && !ctx.stash.hasWritePermission) {
        return {
        operation: 'Query',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ 
                ':profileId': 'NONEXISTENT'
            })
        }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Normalize profileId to ensure PROFILE# prefix
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // Query shares table directly by PK (profileId)
    return {
        operation: 'Query',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({ 
            ':profileId': dbProfileId
        })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Strip ACCOUNT# prefix from targetAccountId, keep profileId with PROFILE# prefix
    const items = ctx.result.items || [];
    return items.map(item => ({
        ...item,
        targetAccountId: item.targetAccountId && item.targetAccountId.startsWith('ACCOUNT#')
            ? item.targetAccountId.substring(8)
            : item.targetAccountId
    }));
}
