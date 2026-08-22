import { util } from '@aws-appsync/utils';

function parseEmbeddedCampaignId(orderId) {
    if (typeof orderId !== 'string' || !orderId.startsWith('ORDER#')) {
        return null;
    }
    const parts = orderId.split('#');
    // New format: ORDER#<campaignId without CAMPAIGN# prefix>#<uuid>
    if (parts.length !== 3 || !parts[1] || !parts[2]) {
        return null;
    }
    return 'CAMPAIGN#' + parts[1];
}

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
        util.error('Order not found', 'NotFound');
    }
    // Store order in stash for next function
    ctx.stash.order = order;
    return order;
}
