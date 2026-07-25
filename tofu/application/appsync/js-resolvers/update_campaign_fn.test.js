import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_campaign_fn.js';

describe('update_campaign_fn request', () => {
  it('recomputes unitCampaignKey when campaignName changes', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
          campaignName: 'Fall',
          campaignYear: 2024,
          unitType: 'Pack',
          unitNumber: 158,
          city: 'Springfield',
          state: 'IL',
          unitCampaignKey: 'Pack#158#Springfield#IL#Fall#2024',
        },
      },
      args: {
        input: {
          campaignName: 'Spring',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.strictEqual(result.key.profileId, 'PROFILE#scout');
    assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Pack#158#Springfield#IL#Spring#2024'
    );
  });

  it('does not add unitCampaignKey when campaign changes but unit fields are absent', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
          campaignName: 'Fall',
          campaignYear: 2024,
        },
      },
      args: {
        input: {
          campaignName: 'Spring',
        },
      },
    };

    const result = request(ctx);
    assert.doesNotMatch(result.update.expression, /unitCampaignKey/);
  });

  it('does not add unitCampaignKey when campaignName is unchanged', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
          campaignName: 'Fall',
          campaignYear: 2024,
          unitType: 'Pack',
          unitNumber: 158,
          city: 'Springfield',
          state: 'IL',
          unitCampaignKey: 'Pack#158#Springfield#IL#Fall#2024',
        },
      },
      args: {
        input: {
          startDate: '2024-09-01',
        },
      },
    };

    const result = request(ctx);
    assert.doesNotMatch(result.update.expression, /unitCampaignKey/);
  });

  it('does not prefix null catalogId with CATALOG#', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
          campaignName: 'Fall',
          campaignYear: 2024,
        },
      },
      args: {
        input: {
          catalogId: null,
        },
      },
    };

    const result = request(ctx);
    assert.match(result.update.expression, /catalogId = :catalogId/);
    assert.strictEqual(result.update.expressionValues[':catalogId'], null);
  });
});

describe('update_campaign_fn response', () => {
  it('returns updated unitCampaignKey in the response when name changes', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
          campaignName: 'Fall',
          campaignYear: 2024,
          unitType: 'Pack',
          unitNumber: 158,
          city: 'Springfield',
          state: 'IL',
          unitCampaignKey: 'Pack#158#Springfield#IL#Fall#2024',
        },
      },
      args: {
        input: {
          campaignName: 'Spring',
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.campaignName, 'Spring');
    assert.strictEqual(result.unitCampaignKey, 'Pack#158#Springfield#IL#Spring#2024');
  });
});
