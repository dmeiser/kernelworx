import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_campaign_orders_lambda_fn.js';

describe('delete_campaign_orders_lambda_fn request', () => {
  it('invokes the Lambda with the campaignId from stash', () => {
    const ctx = {
      stash: {
        campaign: {
          campaignId: 'CAMPAIGN#c1',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Invoke');
    assert.strictEqual(result.payload.arguments.campaignId, 'CAMPAIGN#c1');
  });

  it('early-returns when campaign is missing', () => {
    const ctx = {
      stash: {
        campaign: null,
      },
    };

    const result = request(ctx);

    assert.deepStrictEqual(result, { deletedCount: 0 });
  });
});

describe('delete_campaign_orders_lambda_fn response', () => {
  it('returns the Lambda result and stashes the deleted count', () => {
    const ctx = {
      stash: {},
      result: { deletedCount: 42 },
      error: null,
    };

    const result = response(ctx);

    assert.deepStrictEqual(result, { deletedCount: 42 });
    assert.strictEqual(ctx.stash.deletedOrdersCount, 42);
  });
});
