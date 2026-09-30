import { util } from '@aws-appsync/utils';

/**
 * Shared order lookup, used by the getOrder query (query_order_fn) and the
 * createOrder pipeline (lookup_order_fn). Kept in lib/ so the GetItem request
 * is built in one place, so the consistentRead decision cannot drift between
 * the two callers.
 */

/**
 * Extract the embedded campaignId from a new-format order ID.
 *
 * New format: ORDER#<campaignId without the CAMPAIGN# prefix>#<uuid>, so the
 * base-table key (campaignId, orderId) is recoverable without the GSI. Legacy
 * order IDs (ORDER#<uuid>) have no embedded campaignId and return null, which
 * routes the caller to the GSI fallback.
 */
export function parseEmbeddedCampaignId(orderId) {
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

/**
 * Build the AppSync request that locates an order by its ID.
 *
 * New order IDs carry the campaignId, so use a strongly-consistent base-table
 * GetItem: the orderId-index GSI is only eventually consistent, which breaks
 * immediate read-after-write (getOrder right after createOrder). consistentRead
 * is required here - without it AppSync defaults to an eventually-consistent
 * read and a just-written order can come back missing.
 *
 * Legacy order IDs fall back to the GSI Query, since their campaignId is not
 * embedded in the ID.
 */
export function buildOrderLookupRequest(orderId) {
    const embeddedCampaignId = parseEmbeddedCampaignId(orderId);
    if (embeddedCampaignId) {
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ campaignId: embeddedCampaignId, orderId: orderId }),
            consistentRead: true
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
