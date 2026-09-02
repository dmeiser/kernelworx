import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_campaign_delete_propagation_fn.js';

describe('verify_campaign_delete_propagation_fn request', () => {
  it('reads the base table with a strongly consistent read for the deleted campaign', () => {
    const ctx = {
      stash: {
        campaign: { profileId: 'PROFILE#1', campaignId: 'CAMPAIGN#1' },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'GetItem');
    assert.deepStrictEqual(result.key, { profileId: 'PROFILE#1', campaignId: 'CAMPAIGN#1' });
    assert.strictEqual(result.consistentRead, true);
  });

  it('returns a no-op read when campaign was not found', () => {
    const ctx = { stash: {} };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'GetItem');
    assert.deepStrictEqual(result.key, { profileId: 'NOOP', campaignId: 'NOOP' });
    assert.strictEqual(result.consistentRead, true);
  });
});

describe('verify_campaign_delete_propagation_fn response', () => {
  it('returns true when the campaign row is gone', () => {
    const ctx = {
      stash: { campaign: { campaignId: 'CAMPAIGN#1' } },
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

  it('throws ConflictException when the campaign row is still present', () => {
    const ctx = {
      stash: { campaign: { campaignId: 'CAMPAIGN#1' } },
      result: { campaignId: 'CAMPAIGN#1', profileId: 'PROFILE#1' },
    };

    assert.throws(
      () => response(ctx),
      /ConflictException: Campaign deletion could not be confirmed; please retry/
    );
  });
});
