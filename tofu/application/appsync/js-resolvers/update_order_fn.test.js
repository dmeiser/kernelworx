import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request } from './update_order_fn.js';

describe('update_order_fn request', () => {
  it('rejects an empty lineItems array', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: {
          products: [
            { productId: 'PROD1', productName: 'Popcorn', price: 10.0 },
          ],
        },
      },
      args: {
        input: {
          lineItems: [],
        },
      },
    };

    assert.throws(
      () => request(ctx),
      /BadRequest: Order must have at least one line item/
    );
  });

  it('accepts a non-empty lineItems array', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: {
          products: [
            { productId: 'PROD1', productName: 'Popcorn', price: 10.0 },
          ],
        },
      },
      args: {
        input: {
          lineItems: [{ productId: 'PROD1', quantity: 2 }],
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
    assert.strictEqual(result.key.orderId, 'ORDER#o1');
    assert.match(result.update.expression, /lineItems = :lineItems/);
  });

  it('does not require lineItems when updating other fields', () => {
    const ctx = {
      stash: {
        order: {
          campaignId: 'CAMPAIGN#c1',
          orderId: 'ORDER#o1',
        },
        catalog: null,
      },
      args: {
        input: {
          customerName: 'Jane Doe',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.match(result.update.expression, /customerName = :customerName/);
  });
});
