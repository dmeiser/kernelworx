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
    return {
        operation: 'Query',
        index: 'profileId-index',
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
    
    const orders = ctx.result.items || [];
    // Map DynamoDB field campaignId to GraphQL field campaignId for each order
    return orders.map(order => {
        if (order && order.campaignId) {
            order.campaignId = order.campaignId;
        }
        return order;
    });
}
