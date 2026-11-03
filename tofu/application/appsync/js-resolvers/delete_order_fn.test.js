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
