import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_order_fulfillments_for_delete_fn.js';

// ARCH-1: `deleteOrder` takes the Order's fulfillment rows with it. This step is the read
// half: it supplies the keys of one window of one Order's history, and says whether the
// history continues past that window. A deleted Order would strand records nobody can
// reverse or reach, next to inventory movements that already moved stock.
const ORDER = { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1', fulfillmentVersion: 3 };

function ctxFor(order) {
    return { stash: { order: order } };
}

describe('get_order_fulfillments_for_delete_fn request', () => {
    it('reads the Order partition from the base table, strongly consistently', () => {
        const result = request(ctxFor(ORDER));

        assert.strictEqual(result.operation, 'Query');
        // The fulfillment partition is addressed by its own pk. `campaignId-createdAt-index`
        // is the only index this table declares, so any other index name is a read that
        // fails at runtime; and an index read is eventually consistent, so a record
        // written moments ago can be missing from the sweep.
        assert.strictEqual(result.index, null);
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.query, {
            expression: 'pk = :pk',
            expressionValues: { ':pk': 'ORDER#c1#o1' }
        });
    });

    it('carries one transaction window, leaving room for the pin and the Order row', () => {
        // TransactWriteItems caps at 100 item operations: at most 98 children, the
        // version pin, and the Order delete.
        assert.strictEqual(request(ctxFor(ORDER)).limit, 98);
    });

    it('issues no datastore call at all when the Order is already gone', () => {
        // `runtime.earlyReturn` is mocked as the identity in tests, so the marker of the
        // no-read path is the payload it carries plus the stash the next step reads. In
        // the runtime it skips the datasource call AND this file's response handler, so
        // the stash has to be set here.
        const ctx = ctxFor(null);
        const result = request(ctx);

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.fulfillmentKeys, null);
        assert.strictEqual(ctx.stash.fulfillmentSweepIncomplete, false);
        assert.ok(!Object.hasOwn(result || {}, 'operation'), 'an absent Order must not issue a Query');
    });
});

describe('get_order_fulfillments_for_delete_fn response', () => {
    function resultFor(items, nextToken) {
        const result = { items: items };
        if (nextToken !== undefined) {
            result.nextToken = nextToken;
        }
        return { stash: { order: ORDER }, result: result };
    }

    it('stashes every child key pair for the delete', () => {
        const ctx = resultFor([
            { pk: 'ORDER#c1#o1', sk: 'FULFILLMENT#2026-11-01T10:00:00+00:00#f1', quantity: 2 },
            { pk: 'ORDER#c1#o1', sk: 'REVERSAL#f1', quantity: 1 }
        ]);

        assert.deepStrictEqual(response(ctx), [
            { pk: 'ORDER#c1#o1', sk: 'FULFILLMENT#2026-11-01T10:00:00+00:00#f1' },
            { pk: 'ORDER#c1#o1', sk: 'REVERSAL#f1' }
        ]);
        assert.deepStrictEqual(ctx.stash.fulfillmentKeys.map(function (k) { return k.sk; }), [
            'FULFILLMENT#2026-11-01T10:00:00+00:00#f1',
            'REVERSAL#f1'
        ]);
        assert.strictEqual(ctx.stash.fulfillmentSweepIncomplete, false);
        assert.strictEqual(ctx.stash.fulfillmentContinuation, null);
    });

    it('reads continuation from the AppSync nextToken field, not the raw lastEvaluatedKey', () => {
        // The Query response handler receives `nextToken`; `lastEvaluatedKey` is the raw
        // DynamoDB name and is never present here. A resolver that checks the wrong one
        // reports every truncated read as a complete one and then deletes the Order on
        // top of an unswept history.
        const truncated = resultFor([{ pk: 'ORDER#p', sk: 'FULFILLMENT#a' }], { pk: 'ORDER#p', sk: 'FULFILLMENT#z' });
        response(truncated);
        assert.strictEqual(truncated.stash.fulfillmentSweepIncomplete, true);
        assert.deepStrictEqual(truncated.stash.fulfillmentContinuation, { pk: 'ORDER#p', sk: 'FULFILLMENT#z' });

        const complete = resultFor([{ pk: 'ORDER#p', sk: 'FULFILLMENT#a' }]);
        response(complete);
        assert.strictEqual(complete.stash.fulfillmentSweepIncomplete, false);

        const staleKeyOnly = {
            stash: { order: ORDER },
            result: { items: [{ pk: 'ORDER#p', sk: 'FULFILLMENT#a' }], lastEvaluatedKey: { pk: 'ORDER#p' } }
        };
        response(staleKeyOnly);
        assert.strictEqual(staleKeyOnly.stash.fulfillmentSweepIncomplete, false);
    });

    it('answers an empty history as a complete window, so the delete needs no transaction', () => {
        const ctx = resultFor([]);
        assert.deepStrictEqual(response(ctx), []);
        assert.strictEqual(ctx.stash.fulfillmentSweepIncomplete, false);
    });

    it('skips a row it cannot address rather than emitting a half-key delete', () => {
        const ctx = resultFor([{ pk: 'ORDER#p', sk: 'FULFILLMENT#a' }, { pk: 'ORDER#p' }, null, { sk: 'x' }]);
        assert.deepStrictEqual(response(ctx), [{ pk: 'ORDER#p', sk: 'FULFILLMENT#a' }]);
    });

    it('propagates a datasource error instead of answering an empty sweep', () => {
        assert.throws(
            () => response({ stash: { order: ORDER }, error: { message: 'Throttling', type: 'DynamoDB:ThrottlingException' } }),
            /DynamoDB:ThrottlingException: Throttling/
        );
    });
});
