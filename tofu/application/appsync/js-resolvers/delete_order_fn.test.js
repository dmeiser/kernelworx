import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_order_fn.js';

describe('delete_order_fn request', () => {
  it('deletes an existing order with composite key', () => {
    const ctx = {
      stash: {
        order: { campaignId: 'CAMP#1', orderId: 'ORDER#1', profileId: 'PROFILE#p1', totalAmount: 5.97 },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'DeleteItem');
    assert.deepStrictEqual(result.key, { campaignId: 'CAMP#1', orderId: 'ORDER#1' });
    assert.deepStrictEqual(ctx.stash.totalsDelta, {
      profileId: 'PROFILE#p1',
      campaignId: 'CAMP#1',
      count: -1,
      revenue: -5.97,
    });
  });

  it('stashes a count-only delta when the order has no totalAmount', () => {
    const ctx = {
      stash: {
        order: { campaignId: 'CAMP#1', orderId: 'ORDER#1', profileId: 'PROFILE#p1' },
      },
    };

    request(ctx);

    assert.deepStrictEqual(ctx.stash.totalsDelta, {
      profileId: 'PROFILE#p1',
      campaignId: 'CAMP#1',
      count: -1,
      revenue: 0,
    });
  });

  it('returns a no-op query when order is missing for idempotency', () => {
    const ctx = { stash: {} };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Query');
    assert.strictEqual(result.index, 'orderId-index');
    assert.strictEqual(ctx.stash.skipDelete, true);
    assert.deepStrictEqual(result.query.expressionValues, { ':orderId': 'NOOP' });
    assert.strictEqual(ctx.stash.totalsDelta, undefined);
  });
});

describe('delete_order_fn response', () => {
  it('returns true on successful delete', () => {
    const result = response({ stash: {}, result: {} });
    assert.strictEqual(result, true);
  });

  it('returns true when delete was skipped', () => {
    const result = response({ stash: { skipDelete: true }, error: { message: 'ConditionalCheckFailed', type: 'DynamoDB' } });
    assert.strictEqual(result, true);
  });
});

// ARCH-1: the Order's fulfillment rows are keyed by the Order and are append-only, and
// the reversal and audit paths re-load the Order to authorize themselves. A delete that
// takes only the Order strands history nobody can reverse or reach, next to inventory
// movements that already moved stock. So the children ride the delete, in one transaction.
describe('delete_order_fn request: the fulfillment children ride the delete', () => {
    // The resolver is loaded through Terraform templatefile(); under node the table name
    // is the literal placeholder.
    const FULFILLMENTS_TABLE = '${order_fulfillments_table_name}';
    const order = { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1', totalAmount: 12.5 };

    it('deletes every child and the Order in one transaction', () => {
        const ctx = {
            stash: {
                order: order,
                fulfillmentKeys: [
                    { pk: 'ORDER#c1#o1', sk: 'FULFILLMENT#2026-11-01T10:00:00+00:00#f1' },
                    { pk: 'ORDER#c1#o1', sk: 'REVERSAL#f1' }
                ]
            }
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'TransactWriteItems');
        assert.strictEqual(result.transactItems.length, 3);
        const onFulfillments = result.transactItems.filter(function (item) {
            return item.table === FULFILLMENTS_TABLE;
        });
        assert.deepStrictEqual(
            onFulfillments.map(function (item) {
                return item.key.sk;
            }),
            ['FULFILLMENT#2026-11-01T10:00:00+00:00#f1', 'REVERSAL#f1']
        );
        for (const item of onFulfillments) {
            assert.strictEqual(item.operation, 'Delete');
        }
        // The Order itself is the last action, and it is the same commit: no window in
        // which the history is gone and the Order is not, or the other way round.
        const orderDeletes = result.transactItems.filter(function (item) {
            return item.table === undefined;
        });
        assert.strictEqual(orderDeletes.length, 1);
        assert.deepStrictEqual(orderDeletes[0].key, { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1' });
    });

    it('keeps the single DeleteItem for an Order with no history', () => {
        const ctx = { stash: { order: order, fulfillmentKeys: [] } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#o1' });
    });

    it('stays idempotent when the Order was already deleted', () => {
        const ctx = { stash: { order: null, fulfillmentKeys: null } };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':orderId'], 'NOOP');
        assert.strictEqual(response({ stash: { skipDelete: true } }), true);
    });
});
