import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_order_fulfillments_for_delete_fn.js';

// ARCH-1: a hard Order delete must not leave its fulfillment history behind, because the
// reversal path and the audit read both re-load the Order to authorize themselves. This
// step supplies the keys the delete step removes in the same transaction.
describe('get_order_fulfillments_for_delete_fn request', () => {
    it('reads the Order partition strongly and bounded', () => {
        const result = request({ stash: { order: { orderId: 'ORDER#camp-1#u1', campaignId: 'CAMPAIGN#camp-1' } } });

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, null);
        assert.strictEqual(result.consistentRead, true, 'the keys about to be deleted must be the keys that exist');
        assert.ok(result.limit <= 98, 'the delete is one TransactWriteItems, capped at 100 item operations');
        assert.deepStrictEqual(result.query.expressionValues, { ':pk': 'ORDER#camp-1#u1' });
    });

    it('guards the partition key to exactly one ORDER# prefix', () => {
        assert.deepStrictEqual(
            request({ stash: { order: { orderId: 'camp-1#u1' } } }).query.expressionValues,
            { ':pk': 'ORDER#camp-1#u1' }
        );
        assert.deepStrictEqual(
            request({ stash: { order: { orderId: 'ORDER#ORDER#c#u' } } }).query.expressionValues,
            { ':pk': 'ORDER#ORDER#c#u' }
        );
    });

    it('issues no read for an Order that is already gone, and marks the sweep as skipped', () => {
        const ctx = { stash: { order: null } };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.fulfillmentKeys, null);
        assert.strictEqual(result.query.expressionValues[':orderId'], 'NOOP');
    });
});

describe('get_order_fulfillments_for_delete_fn response', () => {
    it('stashes the child keys the delete step removes', () => {
        const ctx = { stash: {}, result: { items: [{ pk: 'ORDER#o', sk: 'FULFILLMENT#t#f1' }, { pk: 'ORDER#o', sk: 'REVERSAL#f1' }] } };

        assert.deepStrictEqual(response(ctx), [
            { pk: 'ORDER#o', sk: 'FULFILLMENT#t#f1' },
            { pk: 'ORDER#o', sk: 'REVERSAL#f1' }
        ]);
        assert.deepStrictEqual(ctx.stash.fulfillmentKeys, [
            { pk: 'ORDER#o', sk: 'FULFILLMENT#t#f1' },
            { pk: 'ORDER#o', sk: 'REVERSAL#f1' }
        ]);
    });

    it('stashes an empty list for an Order with no history, which is the common case', () => {
        const ctx = { stash: {}, result: { items: [] } };

        assert.deepStrictEqual(response(ctx), []);
        assert.deepStrictEqual(ctx.stash.fulfillmentKeys, []);
    });

    it('refuses an Order whose history does not fit one delete instead of sweeping part of it', () => {
        // Half a history deleted and half left behind is the defect this step exists to
        // close, so the window boundary is a refusal, not a truncation.
        const ctx = { stash: {}, result: { items: [{ pk: 'ORDER#o', sk: 'FULFILLMENT#t#f1' }], lastEvaluatedKey: { pk: 'ORDER#o', sk: 'x' } } };

        assert.throws(
            () => response(ctx),
            /CONFLICT: This order has more fulfillment history than one delete can remove; reverse its fulfillments first/
        );
    });

    it('leaves the no-op path alone', () => {
        const ctx = { stash: { fulfillmentKeys: null }, result: { items: [{ pk: 'a', sk: 'b' }] } };

        assert.strictEqual(response(ctx), null);
        assert.strictEqual(ctx.stash.fulfillmentKeys, null);
    });

    it('surfaces a data source failure rather than reading it as no history', () => {
        assert.throws(
            () => response({ stash: {}, error: { message: 'throttled', type: 'THROTTLED' } }),
            /THROTTLED: throttled/
        );
    });
});
