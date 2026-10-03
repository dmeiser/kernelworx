import { describe, it } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
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

  it('updates unit fields and recomputes unitCampaignKey', () => {
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
          unitType: 'Pack',
          unitNumber: 158,
          city: 'Springfield',
          state: 'IL',
        },
      },
    };

    const result = request(ctx);

    assert.match(result.update.expression, /#state = :state/);
    assert.strictEqual(result.update.expressionNames['#state'], 'state');
    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Pack#158#Springfield#IL#Fall#2024',
    );
  });

  it('recomputes unitCampaignKey when unit fields change', () => {
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
          unitNumber: 200,
        },
      },
    };

    const result = request(ctx);

    assert.match(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.strictEqual(
      result.update.expressionValues[':unitCampaignKey'],
      'Pack#200#Springfield#IL#Fall#2024',
    );
  });

  for (const field of ['campaignName', 'campaignYear', 'isActive', 'catalogId']) {
    it(`rejects explicit null for non-nullable output field ${field}`, () => {
      const ctx = {
        stash: {
          campaign: {
            profileId: 'PROFILE#scout',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            campaignYear: 2024,
            isActive: true,
          },
        },
        args: {
          input: {
            [field]: null,
          },
        },
      };

      let capturedError = null;
      const originalError = util.error;
      util.error = (message, type) => {
        capturedError = { message, type };
        throw new Error(message);
      };
      try {
        request(ctx);
      } catch (_err) {
        // expected
      } finally {
        util.error = originalError;
      }

      assert.ok(capturedError);
      assert.strictEqual(capturedError.type, 'INVALID_INPUT');
      assert.match(capturedError.message, new RegExp(`${field} cannot be null`));
    });
  }

  it('removes city and state when explicitly nulled', () => {
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
          city: null,
          state: null,
        },
      },
    };

    const result = request(ctx);

    assert.doesNotMatch(result.update.expression, /city = :city/);
    assert.doesNotMatch(result.update.expression, /#state = :state/);
    assert.match(result.update.expression, /REMOVE city, #state/);
    assert.strictEqual(result.update.expressionNames['#state'], 'state');
  });

  // The APPSYNC_JS runtime can surface an omitted nullable input field with a
  // null value, so omission (key absent) must not be treated as an explicit
  // null — this is the partial-update shape the ephemeral integration suite
  // exercises (issue #505).
  for (const field of ['campaignName', 'campaignYear', 'isActive', 'catalogId', 'city', 'state']) {
    it(`leaves ${field} untouched when it is omitted from the input`, () => {
      const ctx = {
        stash: {
          campaign: {
            profileId: 'PROFILE#scout',
            campaignId: 'CAMPAIGN#c1',
            campaignName: 'Fall',
            campaignYear: 2024,
            isActive: true,
            catalogId: 'CATALOG#c1',
            city: 'Springfield',
            state: 'IL',
          },
        },
        args: {
          input: {
            startDate: '2025-09-01T00:00:00Z',
          },
        },
      };

      const result = request(ctx);

      assert.doesNotMatch(result.update.expression, new RegExp(field));
      assert.doesNotMatch(result.update.expression, /REMOVE/);
    });
  }

  it('partial update omitting isActive and city/state succeeds and leaves them untouched', () => {
    const campaign = {
      profileId: 'PROFILE#scout',
      campaignId: 'CAMPAIGN#c1',
      campaignName: 'Fall',
      campaignYear: 2024,
      isActive: true,
      city: 'Springfield',
      state: 'IL',
      unitType: 'Pack',
      unitNumber: 158,
      unitCampaignKey: 'Pack#158#Springfield#IL#Fall#2024',
    };
    const ctx = {
      stash: { campaign },
      args: {
        input: {
          campaignName: 'Spring',
          campaignYear: 2026,
        },
      },
      error: null,
    };

    const req = request(ctx);

    assert.match(req.update.expression, /campaignName = :campaignName/);
    assert.match(req.update.expression, /campaignYear = :campaignYear/);
    assert.doesNotMatch(req.update.expression, /isActive/);
    assert.doesNotMatch(req.update.expression, /REMOVE/);

    const res = response(ctx);

    assert.strictEqual(res.campaignName, 'Spring');
    assert.strictEqual(res.campaignYear, 2026);
    assert.strictEqual(res.isActive, true);
    assert.strictEqual(res.city, 'Springfield');
    assert.strictEqual(res.state, 'IL');
    assert.strictEqual(res.unitCampaignKey, 'Pack#158#Springfield#IL#Spring#2026');
  });

  it('errors when unitType is provided without all unit fields', () => {
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
          unitType: 'Pack',
        },
      },
    };

    let capturedError = null;
    const originalError = util.error;
    util.error = (message, type) => {
      capturedError = { message, type };
      throw new Error(message);
    };
    try {
      request(ctx);
    } catch (_err) {
      // expected
    } finally {
      util.error = originalError;
    }

    assert.ok(capturedError);
    assert.match(capturedError.message, /unitNumber is required/i);
  });

  it('rejects unit field updates for shared campaigns', () => {
    const ctx = {
      stash: {
        campaign: {
          profileId: 'PROFILE#scout',
          campaignId: 'CAMPAIGN#c1',
          campaignName: 'Fall',
          campaignYear: 2024,
          sharedCampaignCode: 'SHARED-ABC',
        },
      },
      args: {
        input: {
          unitType: 'Pack',
          unitNumber: 158,
          city: 'Springfield',
          state: 'IL',
        },
      },
    };

    let capturedError = null;
    const originalError = util.error;
    util.error = (message, type) => {
      capturedError = { message, type };
      throw new Error(message);
    };
    try {
      request(ctx);
    } catch (_err) {
      // expected
    } finally {
      util.error = originalError;
    }

    assert.ok(capturedError);
    assert.match(capturedError.message, /cannot be changed for campaigns created from a shared campaign/i);
  });

  it('does not add unitCampaignKey when unit fields are cleared', () => {
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
          unitType: null,
          unitNumber: null,
          city: null,
          state: null,
        },
      },
    };

    const result = request(ctx);

    assert.match(result.update.expression, /unitType = :unitType/);
    assert.doesNotMatch(result.update.expression, /unitCampaignKey = :unitCampaignKey/);
    assert.match(result.update.expression, /REMOVE .*unitCampaignKey/);
  });

  it('rejects explicit null catalogId with INVALID_INPUT', () => {
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

    assert.throws(() => request(ctx), (err) => err.message === 'INVALID_INPUT: catalogId cannot be null');
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
  it('rejects clearing unitType while leaving other unit fields in place', () => {
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
          unitType: null,
        },
      },
    };

    let capturedError = null;
    const originalError = util.error;
    util.error = (message, type) => {
      capturedError = { message, type };
      throw new Error(message);
    };
    try {
      request(ctx);
    } catch (_err) {
      // expected
    } finally {
      util.error = originalError;
    }

    assert.ok(capturedError);
    assert.match(capturedError.message, /unitType is required when unit fields are present/i);
  });

  it('rejects unitNumber update without unitType', () => {
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
          unitNumber: 42,
        },
      },
    };

    let capturedError = null;
    const originalError = util.error;
    util.error = (message, type) => {
      capturedError = { message, type };
      throw new Error(message);
    };
    try {
      request(ctx);
    } catch (_err) {
      // expected
    } finally {
      util.error = originalError;
    }

    assert.ok(capturedError);
    assert.match(capturedError.message, /unitType is required when unit fields are present/i);
  });

  it('rejects non-positive unitNumber values', () => {
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
          unitType: 'Pack',
          unitNumber: 0,
          city: 'Springfield',
          state: 'IL',
        },
      },
    };

    let capturedError = null;
    const originalError = util.error;
    util.error = (message, type) => {
      capturedError = { message, type };
      throw new Error(message);
    };
    try {
      request(ctx);
    } catch (_err) {
      // expected
    } finally {
      util.error = originalError;
    }

    assert.ok(capturedError);
    assert.match(capturedError.message, /unitNumber must be a positive integer/i);
  });

  it('rejects decimal unitNumber values', () => {
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
          unitType: 'Pack',
          unitNumber: 1.5,
          city: 'Springfield',
          state: 'IL',
        },
      },
    };

    let capturedError = null;
    const originalError = util.error;
    util.error = (message, type) => {
      capturedError = { message, type };
      throw new Error(message);
    };
    try {
      request(ctx);
    } catch (_err) {
      // expected
    } finally {
      util.error = originalError;
    }

    assert.ok(capturedError);
    assert.match(capturedError.message, /unitNumber must be a positive integer/i);
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
