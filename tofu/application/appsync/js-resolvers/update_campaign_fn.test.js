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

  it('recomputes unitCampaignKey when unitNumber changes', () => {
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
          unitNumber: 159,
        },
      },
    };

    const result = request(ctx);
    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.match(result.update.expression, /unitNumber = :unitNumber/);
    assert.strictEqual(result.update.expressionValues[':unitNumber'], 159);
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Pack#159#Springfield#IL#Fall#2024'
    );
  });

  it('recomputes unitCampaignKey when city changes', () => {
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
          city: 'Decatur',
        },
      },
    };

    const result = request(ctx);
    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.match(result.update.expression, /city = :city/);
    assert.strictEqual(result.update.expressionValues[':city'], 'Decatur');
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Pack#158#Decatur#IL#Fall#2024'
    );
  });

  it('recomputes unitCampaignKey when unitType changes', () => {
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
          unitType: 'Troop',
        },
      },
    };

    const result = request(ctx);
    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.match(result.update.expression, /unitType = :unitType/);
    assert.strictEqual(result.update.expressionValues[':unitType'], 'Troop');
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Troop#158#Springfield#IL#Fall#2024'
    );
  });

  it('recomputes unitCampaignKey when campaignYear changes', () => {
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
          campaignYear: 2025,
        },
      },
    };

    const result = request(ctx);
    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.match(result.update.expression, /campaignYear = :campaignYear/);
    assert.strictEqual(result.update.expressionValues[':campaignYear'], 2025);
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Pack#158#Springfield#IL#Fall#2025'
    );
  });

  it('persists campaignYear without unitCampaignKey when no unit context exists', () => {
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
          campaignYear: 2025,
        },
      },
    };

    const result = request(ctx);
    assert.match(result.update.expression, /campaignYear = :campaignYear/);
    assert.strictEqual(result.update.expressionValues[':campaignYear'], 2025);
    assert.doesNotMatch(result.update.expression, /unitCampaignKey/);
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

  it('returns updated unitCampaignKey when unitNumber changes', () => {
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
          unitNumber: 159,
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.unitNumber, 159);
    assert.strictEqual(result.unitCampaignKey, 'Pack#159#Springfield#IL#Fall#2024');
  });

  it('returns updated unitCampaignKey when city changes', () => {
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
          city: 'Decatur',
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.city, 'Decatur');
    assert.strictEqual(result.unitCampaignKey, 'Pack#158#Decatur#IL#Fall#2024');
  });

  it('returns updated unitCampaignKey when unitType changes', () => {
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
          unitType: 'Troop',
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.unitType, 'Troop');
    assert.strictEqual(result.unitCampaignKey, 'Troop#158#Springfield#IL#Fall#2024');
  });

  it('returns updated unitCampaignKey when campaignYear changes', () => {
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
          campaignYear: 2025,
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.campaignYear, 2025);
    assert.strictEqual(result.unitCampaignKey, 'Pack#158#Springfield#IL#Fall#2025');
  });

  it('returns updated campaignYear without recomputing unitCampaignKey when no unit context exists', () => {
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
          campaignYear: 2025,
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.campaignYear, 2025);
    assert.strictEqual(result.unitCampaignKey, undefined);
  });

  it('returns updated unitCampaignKey when state changes', () => {
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
          state: 'IN',
        },
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.state, 'IN');
    assert.strictEqual(result.unitCampaignKey, 'Pack#158#Springfield#IN#Fall#2024');
  });
});
