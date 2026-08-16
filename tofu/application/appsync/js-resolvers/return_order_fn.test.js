import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './return_order_fn.js';

describe('return_order_fn request', () => {
  it('returns an empty no-op request', () => {
    const result = request({});
    assert.deepStrictEqual(result, {});
  });
});

describe('return_order_fn response', () => {
  it('returns the order when authorized', () => {
    const order = { orderId: 'ORDER#1', campaignId: 'CAMP#1', customerName: 'Alice' };
    const result = response({ stash: { authorized: true, order } });
    assert.strictEqual(result, order);
  });

  it('returns null when order not found', () => {
    const result = response({ stash: { orderNotFound: true } });
    assert.strictEqual(result, null);
  });

  it('returns null when not authorized', () => {
    const result = response({ stash: { authorized: false } });
    assert.strictEqual(result, null);
  });
});
