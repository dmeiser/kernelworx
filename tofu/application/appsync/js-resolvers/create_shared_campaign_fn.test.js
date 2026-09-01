import { describe, it } from 'node:test';
import assert from 'node:assert';
import { util } from '@aws-appsync/utils';
import { request, response } from './create_shared_campaign_fn.js';

function withAutoId(value, fn) {
  const original = util.autoId;
  util.autoId = () => value;
  try {
    return fn();
  } finally {
    util.autoId = original;
  }
}

describe('create_shared_campaign_fn request', () => {
  const baseInput = {
    catalogId: 'CATALOG#cat-1',
    campaignName: 'Cookie Sale',
    campaignYear: 2025,
    startDate: '2025-01-01',
    endDate: '2025-02-01',
    unitType: 'Troop',
    unitNumber: 123,
    city: 'Springfield',
    state: 'CA',
    creatorMessage: 'Join us!',
    description: 'Annual cookie sale',
  };

  const baseCtx = {
    args: { input: baseInput },
    identity: { sub: 'account-123' },
    stash: {
      account: {
        givenName: 'Alice',
        familyName: 'Anderson',
        email: 'alice@example.com',
      },
    },
  };

  it('generates a shared campaign code with deterministic prefix and random suffix', () => {
    const result = withAutoId('550e8400-e29b-41d4-a716-446655440000', () => request(baseCtx));

    assert.strictEqual(result.operation, 'PutItem');
    const code = result.key.sharedCampaignCode;
    assert.strictEqual(code, 'TROOP123-COOK-CA-25-550E84');
    assert.strictEqual(result.attributeValues.sharedCampaignCode, code);
  });

  it('uses the full campaign name when it is shorter than four characters', () => {
    const ctx = {
      ...baseCtx,
      args: { input: { ...baseInput, campaignName: 'AB' } },
    };

    const result = withAutoId('550e8400-e29b-41d4-a716-446655440000', () => request(ctx));
    assert.strictEqual(result.key.sharedCampaignCode, 'TROOP123-AB-CA-25-550E84');
  });

  it('trims trailing whitespace from the campaign abbreviation', () => {
    const ctx = {
      ...baseCtx,
      args: { input: { ...baseInput, campaignName: 'CO O' } },
    };

    const result = withAutoId('550e8400-e29b-41d4-a716-446655440000', () => request(ctx));
    assert.strictEqual(result.key.sharedCampaignCode, 'TROOP123-CO O-CA-25-550E84');
  });

  it('builds unitCampaignKey from unit and campaign fields', () => {
    const result = request(baseCtx);

    assert.strictEqual(
      result.attributeValues.unitCampaignKey,
      'Troop#123#Springfield#CA#Cookie Sale#2025'
    );
  });

  it('sets createdByName from account given and family names', () => {
    const result = request(baseCtx);
    assert.strictEqual(result.attributeValues.createdByName, 'Alice Anderson');
  });

  it('falls back to account email when name fields are absent', () => {
    const ctx = {
      ...baseCtx,
      stash: { account: { email: 'bob@example.com' } },
    };

    const result = request(ctx);
    assert.strictEqual(result.attributeValues.createdByName, 'bob@example.com');
  });

  it('uses Unknown when account has no identifiable name or email', () => {
    const ctx = {
      ...baseCtx,
      stash: { account: {} },
    };

    const result = request(ctx);
    assert.strictEqual(result.attributeValues.createdByName, 'Unknown');
  });

  it('stores createdBy with ACCOUNT# prefix', () => {
    const result = request(baseCtx);
    assert.strictEqual(result.attributeValues.createdBy, 'ACCOUNT#account-123');
  });

  it('includes optional startDate, endDate, and description when provided', () => {
    const result = request(baseCtx);
    assert.strictEqual(result.attributeValues.startDate, '2025-01-01');
    assert.strictEqual(result.attributeValues.endDate, '2025-02-01');
    assert.strictEqual(result.attributeValues.description, 'Annual cookie sale');
  });

  it('omits optional fields when not provided', () => {
    const ctx = {
      ...baseCtx,
      args: {
        input: {
          catalogId: 'CATALOG#cat-1',
          campaignName: 'Cookie Sale',
          campaignYear: 2025,
          unitType: 'Troop',
          unitNumber: 123,
          city: 'Springfield',
          state: 'CA',
        },
      },
    };

    const result = request(ctx);
    assert.strictEqual(result.attributeValues.startDate, undefined);
    assert.strictEqual(result.attributeValues.endDate, undefined);
    assert.strictEqual(result.attributeValues.description, undefined);
    assert.strictEqual(result.attributeValues.creatorMessage, undefined);
  });

  it('enforces attribute_not_exists condition on sharedCampaignCode', () => {
    const result = request(baseCtx);
    assert.strictEqual(result.condition.expression, 'attribute_not_exists(sharedCampaignCode)');
  });
});

describe('create_shared_campaign_fn response', () => {
  it('strips ACCOUNT# prefix from createdBy in the result', () => {
    const ctx = {
      result: {
        sharedCampaignCode: 'TROOP123-COOK-CA-25-ABC123',
        createdBy: 'ACCOUNT#account-123',
      },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.createdBy, 'account-123');
  });

  it('returns result unchanged when createdBy lacks ACCOUNT# prefix', () => {
    const ctx = {
      result: { sharedCampaignCode: 'TROOP123-COOK-CA-25-ABC123', createdBy: 'account-123' },
      error: null,
    };

    const result = response(ctx);
    assert.strictEqual(result.createdBy, 'account-123');
  });

  it('maps conditional check failure to a retryable conflict error', () => {
    const ctx = {
      error: { type: 'DynamoDB:ConditionalCheckFailedException', message: 'Conditional check failed' },
    };

    assert.throws(
      () => response(ctx),
      /ConflictException: A Shared Campaign with this code already exists. Please try again./
    );
  });

  it('passes through other errors', () => {
    const ctx = {
      error: { type: 'InternalServerError', message: 'DynamoDB error' },
    };

    assert.throws(() => response(ctx), /InternalServerError: DynamoDB error/);
  });
});
