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
    // Query shares table directly by PK (profileId)
    return {
        operation: 'Query',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({ 
            ':profileId': profileId
        })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    return ctx.result.items || [];
}
