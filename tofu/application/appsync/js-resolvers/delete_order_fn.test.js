import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_order_fn.js';

describe('delete_order_fn request', () => {
  it('deletes an existing order with composite key', () => {
    const ctx = {
      stash: {
        order: { campaignId: 'CAMP#1', orderId: 'ORDER#1' },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'DeleteItem');
    assert.deepStrictEqual(result.key, { campaignId: 'CAMP#1', orderId: 'ORDER#1' });
  });

  it('returns a no-op query when order is missing for idempotency', () => {
    const ctx = { stash: {} };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Query');
    assert.strictEqual(result.index, 'orderId-index');
    assert.strictEqual(ctx.stash.skipDelete, true);
    assert.deepStrictEqual(result.query.expressionValues, { ':orderId': 'NOOP' });
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
