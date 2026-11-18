import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_order_fn.js';

// The resolver is loaded through Terraform templatefile(); under node the table names are
// the literal placeholders, and every transaction action has to name its own table
// because AppSync does not default a TransactWriteItems action to the datasource's table.
const ORDERS_TABLE = '${orders_table_name}';
const FULFILLMENTS_TABLE = '${order_fulfillments_table_name}';

const ORDER = { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1', profileId: 'PROFILE#p1', totalAmount: 5.97, fulfillmentVersion: 2 };

function ctxFor(stash) {
    return { stash: stash };
}

describe('delete_order_fn request', () => {
    it('deletes an existing order with composite key, pinned to the version it read', () => {
        const ctx = ctxFor({ order: ORDER, fulfillmentKeys: [] });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1' });
        assert.deepStrictEqual(ctx.stash.totalsDelta, {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            count: -1,
            revenue: -5.97,
        });
    });

    it('stashes a count-only delta when the order has no totalAmount', () => {
        const ctx = ctxFor({ order: { campaignId: 'CAMP#1', orderId: 'ORDER#1', profileId: 'PROFILE#p1' }, fulfillmentKeys: [] });

        request(ctx);

        assert.deepStrictEqual(ctx.stash.totalsDelta, {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMP#1',
            count: -1,
            revenue: 0,
        });
    });

    it('issues no read and no write when the order is already gone', () => {
        // `runtime.earlyReturn(true)` is the identity in tests: the payload is the
        // mutation result, and in the runtime it skips the datasource call and this
        // file's response handler. There is no NOOP Query, because the step that would
        // answer the no-op used to point at an index the fulfillment table does not have.
        const ctx = ctxFor({ order: null, fulfillmentKeys: null, fulfillmentSweepIncomplete: false });

        assert.strictEqual(request(ctx), true);
        assert.strictEqual(ctx.stash.totalsDelta, undefined);
    });
});

describe('delete_order_fn version pin: no fulfillment slips into the gap', () => {
    function pinned(order) {
        return request(ctxFor({ order: order, fulfillmentKeys: [] })).condition;
    }

    it('pins the fulfillmentVersion the pipeline read, and requires the row', () => {
        const condition = pinned(ORDER);

        assert.strictEqual(condition.expression, '#fulfillmentVersion = :expectedFulfillmentVersion AND attribute_exists(#orderId)');
        assert.deepStrictEqual(condition.expressionNames, { '#fulfillmentVersion': 'fulfillmentVersion', '#orderId': 'orderId' });
        assert.deepStrictEqual(condition.expressionValues, { ':expectedFulfillmentVersion': 2 });
    });

    it('accepts a pre-Wave-3 row that carries no version, but still requires the row', () => {
        const condition = pinned({ campaignId: 'CAMP#1', orderId: 'ORDER#1' });

        assert.strictEqual(
            condition.expression,
            '(attribute_not_exists(#fulfillmentVersion) OR #fulfillmentVersion = :expectedFulfillmentVersion) AND attribute_exists(#orderId)'
        );
        assert.strictEqual(condition.expressionValues[':expectedFulfillmentVersion'], 0);
    });

    it('answers a failed pin as a retryable CONFLICT, with nothing deleted', () => {
        // A fulfillment recorded between this pipeline's read and its write advanced the
        // version. The delete's condition fails, the Order and its history are untouched,
        // and re-reading is the whole remedy.
        assert.throws(
            () => response({ stash: { sweepBatchOnly: false }, error: { message: 'The conditional check failed.', type: 'DynamoDB:ConditionalCheckFailedException' } }),
            /CONFLICT: This order changed while the delete was in flight; no order was deleted, re-read it and try again/
        );
    });

    it('passes any other datasource error through unchanged', () => {
        assert.throws(
            () => response({ stash: {}, error: { message: 'Throttling', type: 'DynamoDB:ProvisionedThroughputExceededException' } }),
            /DynamoDB:ProvisionedThroughputExceededException: Throttling/
        );
    });
});

describe('delete_order_fn request: the fulfillment children ride the delete', () => {
    function childKeys(count) {
        const keys = [];
        for (let i = 0; i < count; i = i + 1) {
            keys.push({ pk: 'ORDER#c1#o1', sk: 'FULFILLMENT#2026-11-0' + (i % 9) + 'T10:00:00+00:00#f' + i });
        }
        return keys;
    }

    it('names the fulfillment table on every child action and the orders table on the Order action', () => {
        const ctx = ctxFor({
            order: ORDER,
            fulfillmentKeys: [
                { pk: 'ORDER#c1#o1', sk: 'FULFILLMENT#2026-11-01T10:00:00+00:00#f1' },
                { pk: 'ORDER#c1#o1', sk: 'REVERSAL#f1' }
            ]
        });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'TransactWriteItems');
        assert.strictEqual(result.transactItems.length, 3);
        for (const item of result.transactItems) {
            assert.strictEqual(item.operation, 'DeleteItem', 'the transaction operation is DeleteItem');
            assert.ok(item.table === FULFILLMENTS_TABLE || item.table === ORDERS_TABLE, 'every action names its table');
        }
        assert.deepStrictEqual(
            result.transactItems.filter(function (item) { return item.table === FULFILLMENTS_TABLE; })
                .map(function (item) { return item.key.sk; }),
            ['FULFILLMENT#2026-11-01T10:00:00+00:00#f1', 'REVERSAL#f1']
        );
        // The Order itself is the last action of the same commit, and it carries the pin:
        // no instant exists in which the history is gone and the Order is not, or a
        // fulfillment can land between the two writes.
        const orderAction = result.transactItems[result.transactItems.length - 1];
        assert.strictEqual(orderAction.table, ORDERS_TABLE);
        assert.deepStrictEqual(orderAction.key, { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1' });
        assert.strictEqual(orderAction.condition.expressionValues[':expectedFulfillmentVersion'], 2);
    });

    it('keeps the single DeleteItem for an Order with no history', () => {
        const result = request(ctxFor({ order: ORDER, fulfillmentKeys: [] }));

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1' });
    });

    it('takes the exact window in one transaction: 98 children plus the Order is 99 actions', () => {
        const result = request(ctxFor({ order: ORDER, fulfillmentKeys: childKeys(98), fulfillmentSweepIncomplete: false }));

        assert.strictEqual(result.operation, 'TransactWriteItems');
        assert.strictEqual(result.transactItems.length, 99, 'TransactWriteItems caps at 100 item operations');
        assert.strictEqual(result.transactItems.filter(function (i) { return i.table === ORDERS_TABLE; }).length, 1);
        assert.strictEqual(result.transactItems[98].operation, 'DeleteItem');
    });

    it('sweeps a window and keeps the Order when the history continues past the window', () => {
        // Overflow boundary: 98 children were read AND the read reported a continuation,
        // so the history is wider than one commit. The pass deletes the window under the
        // same version pin and leaves the Order standing for the next pass.
        const ctx = ctxFor({ order: ORDER, fulfillmentKeys: childKeys(98), fulfillmentSweepIncomplete: true });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'TransactWriteItems');
        assert.strictEqual(result.transactItems.length, 99, 'the window plus the version pin, and no Order delete');
        assert.strictEqual(result.transactItems[0].table, ORDERS_TABLE);
        assert.strictEqual(result.transactItems[0].operation, 'ConditionCheck');
        assert.strictEqual(result.transactItems[0].condition.expressionValues[':expectedFulfillmentVersion'], 2);
        assert.strictEqual(
            result.transactItems.filter(function (i) { return i.table === ORDERS_TABLE; }).length,
            1,
            'a batch pass must not remove the Order it has not finished sweeping'
        );
        assert.strictEqual(ctx.stash.totalsDelta, undefined, 'the Order is still present, so the campaign counters do not move');
        assert.strictEqual(ctx.stash.sweepBatchOnly, true);
        assert.strictEqual(ctx.stash.sweptRecords, 98);
    });

    it('reports a swept-but-unfinished delete as a retryable RESOURCE_BUSY, not as success', () => {
        assert.throws(
            () => response({ stash: { sweepBatchOnly: true, sweptRecords: 98 } }),
            /RESOURCE_BUSY: This order has more fulfillment history than one delete can remove; 98 record\(s\) were just removed and the order is still present — delete it again to continue/
        );
    });

    it('answers true once the Order is gone', () => {
        assert.strictEqual(response({ stash: { sweepBatchOnly: false } }), true);
    });
});
