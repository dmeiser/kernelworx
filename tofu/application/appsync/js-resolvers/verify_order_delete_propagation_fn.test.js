import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_order_delete_propagation_fn.js';

describe('verify_order_delete_propagation_fn request', () => {
  it('queries orderId-index for the deleted order', () => {
    const ctx = {
      stash: {
        order: { campaignId: 'CAMP#1', orderId: 'ORDER#1' },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Query');
    assert.strictEqual(result.index, 'orderId-index');
    assert.strictEqual(result.query.expression, 'orderId = :orderId');
    assert.deepStrictEqual(result.query.expressionValues, { ':orderId': 'ORDER#1' });
    assert.strictEqual(result.limit, 1);
  });

  it('returns a no-op query when order was not found', () => {
    const ctx = { stash: {} };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Query');
    assert.strictEqual(result.index, 'orderId-index');
    assert.deepStrictEqual(result.query.expressionValues, { ':orderId': 'NOOP' });
  });
});

describe('verify_order_delete_propagation_fn response', () => {
  it('returns true when the GSI entry is gone', () => {
    const ctx = {
      stash: { order: { orderId: 'ORDER#1' } },
      result: { items: [] },
    };

    const result = response(ctx);

    assert.strictEqual(result, true);
  });

  it('returns true when delete was skipped', () => {
    const ctx = {
      stash: {},
      result: { items: [] },
    };

    const result = response(ctx);

    assert.strictEqual(result, true);
  });

  it('throws ConflictException when the GSI entry is still present', () => {
    const ctx = {
      stash: { order: { orderId: 'ORDER#1' } },
      result: { items: [{ orderId: 'ORDER#1', campaignId: 'CAMP#1' }] },
    };

    assert.throws(
      () => response(ctx),
      /ConflictException: Order delete propagation pending; please retry/
    );
  });
});
