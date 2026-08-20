import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request } from './update_order_fn.js';

const baseCtx = (input) => ({
  stash: {
    order: { campaignId: 'CAMP#1', orderId: 'ORDER#1' },
    catalog: { products: [] },
  },
  args: { input },
});

describe('update_order_fn request', () => {
  it('rejects an empty lineItems array', () => {
    const ctx = baseCtx({ lineItems: [] });

    assert.throws(
      () => request(ctx),
      /BadRequest: Order must have at least one line item/
    );
  });

  it('rejects a non-array lineItems value', () => {
    const ctx = baseCtx({ lineItems: 'not-an-array' });

    assert.throws(
      () => request(ctx),
      /BadRequest: Order must have at least one line item/
    );
  });
});
