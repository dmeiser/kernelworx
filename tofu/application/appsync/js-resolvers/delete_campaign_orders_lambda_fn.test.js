import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_campaign_orders_lambda_fn.js';

describe('delete_campaign_orders_lambda_fn request', () => {
  it('invokes the Lambda with the campaignId and caller identity', () => {
    const ctx = {
      stash: {
        campaign: {
          campaignId: 'CAMPAIGN#c1',
        },
      },
      identity: {
        sub: 'user-123',
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Invoke');
    assert.strictEqual(result.payload.arguments.campaignId, 'CAMPAIGN#c1');
    assert.strictEqual(result.payload.identity.sub, 'user-123');
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
