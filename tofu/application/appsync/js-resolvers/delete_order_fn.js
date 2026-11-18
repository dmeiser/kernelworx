import { util, runtime } from '@aws-appsync/utils';
import { fulfillmentVersionGuard, currentFulfillmentVersion } from './lib/fulfillment_version.js';

// ARCH-1: a hard Order delete takes its fulfillment history with it.
//
// `OrderFulfillment` rows are keyed by the Order and append-only (data model §6.5), and
// both the reversal path and the audit read re-load the Order to authorize themselves. An
// Order deleted on its own therefore strands records that cannot be reversed, cannot be
// read, and name inventory movements that already moved stock. The impact assessment
// (§7.1) requires children-first cleanup on every hard-delete path.
//
// The lifecycle that makes that true under concurrency (re-review finding ARCH-1):
//
// * Every write this resolver issues is a `TransactWriteItems`/`DeleteItem` that names
//   its own table — the contract for a cross-table transaction, where AppSync does not
//   default the datasource's table on a transaction action.
// * The Order row is deleted only by a write that also carries the §5.19
//   `fulfillmentVersion` guard for the version this pipeline READ. A fulfillment that
//   lands between the read and the delete advances that version, so the delete's own
//   condition fails and nothing at all is removed — no orphan, and no history lost. The
//   same condition includes `attribute_exists(#orderId)`, so a delete cannot resurrect a
//   row a concurrent delete already removed.
// * A history wider than one transaction (see `get_order_fulfillments_for_delete_fn`)
//   is swept in passes: each pass commits a window of children under the same version
//   pin and leaves the Order in place, then answers `RESOURCE_BUSY` so the caller
//   re-issues. Each pass is atomic, each pass makes progress, and the Order goes only in
//   the pass that found no continuation — so a failure mid-history leaves the remaining
//   records under an Order that is still there and still deletable, never stranded
//   beneath a gone one.
// * An Order that is already gone issues no read and no write (`runtime.earlyReturn`,
//   which also skips this file's response handler), which keeps `deleteOrder` idempotent
//   without pointing a Query at an index this table does not have.
//
// Only the declared placeholders may be interpolated here: this file is loaded through
// Terraform `templatefile()` (#570), and both table names are needed because the delete
// spans two tables.
const ordersTableName = '${orders_table_name}';
const orderFulfillmentsTableName = '${order_fulfillments_table_name}';

export function request(ctx) {
    const order = ctx.stash.order;
    if (!order) {
        // Nothing to delete and nothing to verify: the mutation answers true.
        return runtime.earlyReturn(true);
    }

    // #746: denormalized-totals delta for sync_campaign_totals_fn (the step
    // after this one). The order row's profileId/campaignId are the
    // campaigns-table key, so no lookup is needed to address the counter. A
    // missing totalAmount (never written by any order path) degrades to a
    // count-only decrement rather than failing the delete. Deliberately stashed
    // only for a pass that removes the Order: a batch pass leaves it present, so
    // the counters must not move.
    const revenue = typeof order.totalAmount === 'number' ? -order.totalAmount : 0;
    const sweepBatchOnly = ctx.stash.fulfillmentSweepIncomplete === true;
    if (!sweepBatchOnly) {
        ctx.stash.totalsDelta = {
            profileId: order.profileId,
            campaignId: order.campaignId,
            count: -1,
            revenue: revenue
        };
    }
    ctx.stash.sweepBatchOnly = sweepBatchOnly;

    const children = Array.isArray(ctx.stash.fulfillmentKeys) ? ctx.stash.fulfillmentKeys : [];
    const orderKey = util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId });
    const guard = versionCondition(currentFulfillmentVersion(order));

    const childDeletes = [];
    for (const child of children) {
        childDeletes.push({
            table: orderFulfillmentsTableName,
            operation: 'DeleteItem',
            key: util.dynamodb.toMapValues({ pk: child.pk, sk: child.sk })
        });
    }

    if (sweepBatchOnly) {
        // One window of the history, and the Order stays. The ConditionCheck is the
        // pin: the Order row is a different item from every child being deleted, so it
        // is allowed alongside them, and it fails the pass if the history moved since
        // this pipeline read it.
        ctx.stash.sweptRecords = childDeletes.length;
        return {
            operation: 'TransactWriteItems',
            transactItems: [{
                table: ordersTableName,
                operation: 'ConditionCheck',
                key: orderKey,
                condition: guard
            }].concat(childDeletes)
        };
    }

    if (childDeletes.length === 0) {
        // The overwhelmingly common case, and the pre-Wave-3 shape apart from the pin:
        // one Order, no history, one DeleteItem — still guarded, because a fulfillment
        // can land between the read that saw no history and this write.
        return {
            operation: 'DeleteItem',
            key: orderKey,
            condition: guard
        };
    }

    // Children and Order in one commit, children first in the action list: there is no
    // instant at which the history is gone and the Order is not, or the reverse.
    return {
        operation: 'TransactWriteItems',
        transactItems: childDeletes.concat([{
            table: ordersTableName,
            operation: 'DeleteItem',
            key: orderKey,
            condition: guard
        }])
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (isConditionFailure(ctx.error)) {
            // Exactly one condition is in play, so exactly one thing failed: a
            // fulfillment or reversal moved this Order's history while the delete was in
            // flight. Nothing was deleted, the Order is intact, and re-reading it is the
            // whole remedy — which is what makes this retryable rather than a caller
            // error.
            util.error(
                'This order changed while the delete was in flight; no order was deleted, re-read it and try again',
                'CONFLICT'
            );
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }
    if (ctx.stash && ctx.stash.sweepBatchOnly) {
        // The batch committed, so the mutation did NOT delete the Order, and reporting
        // `true` would be a lie. `util.error` runs after the datasource call, so the
        // swept window is already committed; the caller re-issues and the next pass finds
        // the rest. The rest of the pipeline (totals, propagation check) is skipped by
        // the error, which is correct while the Order is still present.
        util.error(
            'This order has more fulfillment history than one delete can remove; ' +
                (ctx.stash.sweptRecords || 0) + ' record(s) were just removed and the order is still present — delete it again to continue',
            'RESOURCE_BUSY'
        );
        return null;
    }
    // Always return true (idempotent)
    return true;
}

// The §5.19 version guard, in the shape AppSync asks for. Values go through
// `util.dynamodb.toMapValues` so a number is marshalled the way the datasource expects.
function versionCondition(observedVersion) {
    const guard = fulfillmentVersionGuard(observedVersion);
    return {
        expression: guard.expression,
        expressionNames: guard.expressionNames,
        expressionValues: util.dynamodb.toMapValues(guard.expressionValues)
    };
}

// The one condition this resolver can fail on. Spelled here rather than imported so the
// bundle Terraform interpolates stays free of unrelated helpers.
function isConditionFailure(error) {
    const type = error && error.type !== undefined ? error.type : '';
    const message = error && typeof error.message === 'string' ? error.message : '';
    return type === 'DynamoDB:ConditionalCheckFailedException'
        || type === 'ConditionalCheckFailedException'
        || message.indexOf('ConditionalCheckFailed') !== -1;
}
