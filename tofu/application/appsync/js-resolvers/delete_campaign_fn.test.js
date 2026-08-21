import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_campaign_fn.js';

describe('delete_campaign_fn request', () => {
  it('returns DeleteItem when campaign exists', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'DeleteItem');
    assert.strictEqual(result.key.profileId, 'PROFILE#scout');
    assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
  });

  it('returns a no-op GetItem when campaign does not exist', () => {
    const ctx = {
      stash: {
        campaign: null,
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'GetItem');
    assert.strictEqual(ctx.stash.skipDelete, true);
  });
});

describe('delete_campaign_fn response', () => {
  it('returns true on success', () => {
    const ctx = {
      stash: {},
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result, true);
  });
});
