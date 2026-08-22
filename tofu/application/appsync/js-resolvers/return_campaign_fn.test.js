import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './return_campaign_fn.js';

describe('return_campaign_fn request', () => {
  it('returns an empty no-op request', () => {
    const result = request({});
    assert.deepStrictEqual(result, {});
  });
});

describe('return_campaign_fn response', () => {
  it('returns the campaign when authorized', () => {
    const campaign = { campaignId: 'CAMP#1', campaignName: 'Fall 2024' };
    const result = response({ stash: { authorized: true, campaign } });
    assert.strictEqual(result, campaign);
  });

  it('returns null when campaign not found', () => {
    const result = response({ stash: { campaignNotFound: true } });
    assert.strictEqual(result, null);
  });

  it('returns null when not authorized', () => {
    const result = response({ stash: { authorized: false } });
    assert.strictEqual(result, null);
  });
});
