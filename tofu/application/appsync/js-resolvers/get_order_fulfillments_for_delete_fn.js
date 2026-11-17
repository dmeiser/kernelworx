import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

// The fulfillment children an Order delete must take with it (ARCH-1).
//
// `OrderFulfillment` rows are append-only and keyed by the Order (data model §6.5: pk
// `ORDER#<orderId>`), and both the reversal path and the audit read reload the Order to
// authorize themselves — so an orphaned history is not merely untidy. A deleted Order
// leaves records nobody can reverse and nobody can reach, and the inventory movements
// they name have already moved stock. The impact assessment requires children-first
// cleanup on every hard-delete path; this step is the `deleteOrder` half of that, and
// `delete_order_fn` commits the children and the Order in one transaction so a partial
// cleanup is not reachable.
//
// The read is bounded because the delete it feeds is a conditional transaction, and
// `TransactWriteItems` accepts at most 100 item operations. 98 leaves room for the Order
// itself plus the campaign-counter write that rides the same delete. An Order past that
// window is refused rather than half-deleted: the caller reverses the fulfillments first,
// which is also the only sequence that undoes the stock movement correctly. (§5.19 keeps
// one Order's history small in practice — a line is fulfilled and reversed a handful of
// times — so this is a budget guard, not a user-facing limit.)
const CHILD_WINDOW = 98;

export function request(ctx) {
    const order = ctx.stash.order;
    if (!order) {
        // The delete is idempotent: an Order that is already gone has nothing to sweep,
        // and `delete_order_fn` answers the no-op. Issue no read.
        ctx.stash.fulfillmentKeys = null;
        return {
            operation: 'Query',
            index: 'orderId-index',
            query: {
                expression: 'orderId = :orderId',
                expressionValues: util.dynamodb.toMapValues({ ':orderId': 'NOOP' })
            },
            limit: 1
        };
    }

    // Exactly one `ORDER#` prefix, the same rule the fulfillment write and read paths
    // apply: these Order ids already carry it.
    const pk = normalizeIdOrPrefix(order.orderId, 'ORDER#');
    return {
        operation: 'Query',
        index: null,
        consistentRead: true,
        limit: CHILD_WINDOW,
        query: {
            expression: 'pk = :pk',
            expressionValues: util.dynamodb.toMapValues({ ':pk': pk })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    if (ctx.stash && ctx.stash.fulfillmentKeys === null) {
        return null;
    }
    const result = ctx.result || {};
    const items = Array.isArray(result.items) ? result.items : [];
    if (result.lastEvaluatedKey) {
        // Never a partial cleanup: deleting some of an Order's history and then the Order
        // would strand the rest, which is the defect this step exists to close.
        util.error(
            'This order has more fulfillment history than one delete can remove; reverse its fulfillments first',
            'CONFLICT'
        );
        return null;
    }

    const keys = [];
    for (const item of items) {
        if (item && typeof item.pk === 'string' && typeof item.sk === 'string') {
            keys.push({ pk: item.pk, sk: item.sk });
        }
    }
    ctx.stash.fulfillmentKeys = keys;
    return keys;
}
