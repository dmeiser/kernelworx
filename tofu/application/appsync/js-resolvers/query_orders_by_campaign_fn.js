import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // If campaign not found or not authorized, return empty query (will return empty array)
    if (ctx.stash.campaignNotFound || !ctx.stash.authorized) {
        return {
        operation: 'Query',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ 
                ':campaignId': 'NONEXISTENT'
            })
        }
        };
    }
    
    const campaignId = ctx.args.campaignId;
    // Direct PK query on orders table (V2 schema: PK=campaignId)
    const request = {
        operation: 'Query',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ 
            ':campaignId': campaignId
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
