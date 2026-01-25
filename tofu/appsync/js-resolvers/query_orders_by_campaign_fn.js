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
    return {
        operation: 'Query',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ 
            ':campaignId': campaignId
        })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const orders = ctx.result.items || [];
    // Map DynamoDB field campaignId to GraphQL field campaignId for each order
    return orders.map(order => {
        if (order && order.campaignId) {
            order.campaignId = order.campaignId;
        }
        return order;
    });
}
