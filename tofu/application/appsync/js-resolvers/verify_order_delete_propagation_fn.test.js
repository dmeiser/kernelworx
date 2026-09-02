import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_order_delete_propagation_fn.js';

describe('verify_order_delete_propagation_fn request', () => {
  it('reads the base table with a strongly consistent read for the deleted order', () => {
    const ctx = {
      stash: {
        order: { campaignId: 'CAMPAIGN#1', orderId: 'ORDER#1' },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'GetItem');
    assert.deepStrictEqual(result.key, { campaignId: 'CAMPAIGN#1', orderId: 'ORDER#1' });
    assert.strictEqual(result.consistentRead, true);
  });

  it('returns a no-op read when order was not found', () => {
    const ctx = { stash: {} };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'GetItem');
    assert.deepStrictEqual(result.key, { campaignId: 'NOOP', orderId: 'NOOP' });
    assert.strictEqual(result.consistentRead, true);
  });
});

describe('verify_order_delete_propagation_fn response', () => {
  it('returns true when the order row is gone', () => {
    const ctx = {
      stash: { order: { orderId: 'ORDER#1' } },
      result: null,
    };

    const result = response(ctx);

    assert.strictEqual(result, true);
  });

  it('returns true when delete was skipped', () => {
    const ctx = {
      stash: {},
      result: null,
    };

    const result = response(ctx);

    assert.strictEqual(result, true);
  });

  it('throws ConflictException when the order row is still present', () => {
    const ctx = {
      stash: { order: { orderId: 'ORDER#1' } },
      result: { campaignId: 'CAMPAIGN#1', orderId: 'ORDER#1' },
    };

    assert.throws(
      () => response(ctx),
      /ConflictException: Order deletion could not be confirmed; please retry/
    );
  });
});
