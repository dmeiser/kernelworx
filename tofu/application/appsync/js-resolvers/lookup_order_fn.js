import { util } from '@aws-appsync/utils';
import { parseEmbeddedCampaignId } from './lib/ids.js';

export function request(ctx) {
    const orderId = ctx.args.orderId || ctx.args.input.orderId;
    const embeddedCampaignId = parseEmbeddedCampaignId(orderId);
    if (embeddedCampaignId) {
        // Strongly-consistent base-table lookup for new order IDs.
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ campaignId: embeddedCampaignId, orderId: orderId })
        };
    }
    // Fallback to GSI for legacy order IDs (ORDER#<uuid>)
    return {
        operation: 'Query',
        index: 'orderId-index',
        query: {
        expression: 'orderId = :orderId',
        expressionValues: util.dynamodb.toMapValues({ ':orderId': orderId })
        },
        limit: 1
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    let order = null;
    if (ctx.result && Array.isArray(ctx.result.items)) {
        // Query result (legacy fallback)
        order = ctx.result.items[0] || null;
    } else {
        // GetItem result
        order = ctx.result || null;
    }
    if (!order) {
        util.error('Order not found', 'NOT_FOUND');
    }
    // Store order in stash for next function
    ctx.stash.order = order;
    return order;
}
