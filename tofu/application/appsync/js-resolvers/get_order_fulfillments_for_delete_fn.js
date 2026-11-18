import { util, runtime } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

// The fulfillment children an Order delete must take with it (ARCH-1).
//
// `OrderFulfillment` rows are append-only and keyed by the Order (data model §6.5: pk
// `ORDER#<orderId>`), and both the reversal path and the audit read reload the Order to
// authorize themselves — so an orphaned history is not merely untidy. A deleted Order
// leaves records nobody can reverse and nobody can reach, and the inventory movements
// they name have already moved stock. The impact assessment (§7.1) requires the children
// to go before the Order on every hard-delete path; this step is the read half of the
// `deleteOrder` path, and `delete_order_fn` commits each batch it supplies.
//
// ARCH-1 (re-review): the read is one window of a lifecycle, not the whole answer.
// `TransactWriteItems` accepts at most 100 item operations, and the delete spends that
// window on children plus the Order row itself, so 98 children is what one COMMITTED
// pass can carry. A history larger than that is not refused as unreachable: reversal
// cannot shrink it (a reversal appends a row), so the delete instead takes this window,
// leaves the Order standing, and asks the caller to re-issue — the same mutation,
// repeated, converges and never orphans a record, because the Order is only ever deleted
// in the pass that found no continuation. The Order's `fulfillmentVersion` is pinned in
// every pass (see `delete_order_fn`), so a fulfillment that lands between this read and
// that write fails the transaction instead of slipping into the gap.
//
// The window is read from the base table, not the `campaignId-createdAt-index` GSI: this
// table declares no other index, a GSI read is eventually consistent (a record written
// moments ago can be missing from the sweep), and a consistent read is not even allowed
// on an index.
const CHILD_WINDOW = 98;

export function request(ctx) {
    const order = ctx.stash.order;
    if (!order) {
        // The delete is idempotent: an Order that is already gone has nothing to sweep.
        // `runtime.earlyReturn` skips the datastore call AND this file's response
        // handler, so the stash is set here and the next step answers the no-op.
        ctx.stash.fulfillmentKeys = null;
        ctx.stash.fulfillmentSweepIncomplete = false;
        return runtime.earlyReturn(null);
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
    const result = ctx.result || {};
    const items = Array.isArray(result.items) ? result.items : [];
    // `nextToken` is the AppSync JS Query continuation field — the raw DynamoDB
    // `lastEvaluatedKey` is not what the response handler receives, and reading a field
    // that is never there reads every truncated read as a complete one.
    const continuation = result.nextToken ? result.nextToken : null;

    const keys = [];
    for (const item of items) {
        if (item && typeof item.pk === 'string' && typeof item.sk === 'string') {
            keys.push({ pk: item.pk, sk: item.sk });
        }
    }
    ctx.stash.fulfillmentKeys = keys;
    ctx.stash.fulfillmentSweepIncomplete = continuation !== null;
    ctx.stash.fulfillmentContinuation = continuation;
    return keys;
}
