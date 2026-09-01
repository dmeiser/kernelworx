import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_campaign_delete_propagation_fn.js';

describe('verify_campaign_delete_propagation_fn request', () => {
  it('queries campaignId-index for the deleted campaign', () => {
    const ctx = {
      stash: {
        campaign: { profileId: 'PROFILE#1', campaignId: 'CAMPAIGN#1' },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Query');
    assert.strictEqual(result.index, 'campaignId-index');
    assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
    assert.deepStrictEqual(result.query.expressionValues, { ':campaignId': 'CAMPAIGN#1' });
    assert.strictEqual(result.limit, 1);
  });

  it('returns a no-op query when campaign was not found', () => {
    const ctx = { stash: {} };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'Query');
    assert.strictEqual(result.index, 'campaignId-index');
    assert.deepStrictEqual(result.query.expressionValues, { ':campaignId': 'NOOP' });
  });
});

describe('verify_campaign_delete_propagation_fn response', () => {
  it('returns true when the GSI entry is gone', () => {
    const ctx = {
      stash: { campaign: { campaignId: 'CAMPAIGN#1' } },
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
      stash: { campaign: { campaignId: 'CAMPAIGN#1' } },
      result: { items: [{ campaignId: 'CAMPAIGN#1', profileId: 'PROFILE#1' }] },
    };

    assert.throws(
      () => response(ctx),
      /ConflictException: Campaign delete propagation pending; please retry/
    );
  });
});
