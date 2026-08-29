import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If not authorized, return empty query (will return empty array)
    if (!ctx.stash.authorized) {
        return {
        operation: 'Query',
        index: 'profileId-index',
        query: {
            expression: 'profileId = :profileId',
            expressionValues: util.dynamodb.toMapValues({ 
                ':profileId': 'NONEXISTENT'
            })
        }
        };
    }
    
    const profileId = ctx.args.profileId;
    // Normalize profileId to PROFILE# for query
    const dbProfileId = profileId && profileId.startsWith('PROFILE#') ? profileId : `PROFILE#${profileId}`;
    // Query orders table using profileId-index GSI
    const request = {
        operation: 'Query',
        index: 'profileId-index',
        query: {
        expression: 'profileId = :profileId',
        expressionValues: util.dynamodb.toMapValues({ 
            ':profileId': dbProfileId
        })
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
    
    const orders = ctx.result.items || [];
    return {
        orders,
        nextToken: ctx.result.nextToken || null
    };
}
