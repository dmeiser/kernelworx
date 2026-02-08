import { util } from '@aws-appsync/utils';

export function request(ctx) {
    // Only fetch catalog if lineItems are being updated
    if (!ctx.args.input.lineItems) {
        ctx.stash.skipCatalog = true;
        // Return no-op query (will return empty)
        return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
            expression: 'campaignId = :campaignId',
            expressionValues: util.dynamodb.toMapValues({ ':campaignId': 'NOOP' })
        },
        limit: 1
        };
    }
    
    // Get the campaign's catalogId from the order
    const order = ctx.stash.order;
    const campaignId = order.campaignId;
    
    // Query campaignId-index GSI to find campaign (V2 schema)
    return {
        operation: 'Query',
        index: 'campaignId-index',
        query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.stash.skipCatalog) {
        return null;
    }
    
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    
    const items = ctx.result.items || [];
    if (items.length === 0) {
        util.error('Campaign not found', 'NotFound');
    }
    
    const campaign = items[0];
    const catalogId = campaign.catalogId;
    
    if (!catalogId) {
        util.error('Campaign does not have a catalog assigned', 'BadRequest');
    }
    
    // Store catalogId in stash for next request
    ctx.stash.catalogId = catalogId;
    return campaign;
}
