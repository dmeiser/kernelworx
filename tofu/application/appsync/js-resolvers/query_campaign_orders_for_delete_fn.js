import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const campaign = ctx.stash.campaign;
    
    // If campaign doesn't exist, skip order query
    if (!campaign) {
        ctx.stash.ordersToDelete = [];
        ctx.stash.skipOrderQuery = true;
        return {
        operation: 'Query',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': 'NOOP' })
        }
        };
    }
    
    const campaignId = campaign.campaignId;
    
    // V2 schema: Direct PK query since PK=campaignId
    return {
        operation: 'Query',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        }
    };
}

export function response(ctx) {
    // If we skipped the query, just return empty
    if (ctx.stash.skipOrderQuery) {
        return [];
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    // Store orders to delete in stash (need campaignId and orderId for V2 schema)
    const orders = ctx.result.items || [];
    ctx.stash.ordersToDelete = orders;
    
    return orders;
}
