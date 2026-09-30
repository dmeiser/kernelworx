import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_my_preferences_resolver.js';

const IDENTITY = { sub: 'user-123' };

describe('update_my_preferences_resolver request', () => {
  it('stores the parsed preferences map, preserving keys like paymentMethods', () => {
    const blob = JSON.stringify({
      showReadOnlyProfiles: false,
      paymentMethods: [{ name: 'Cash', qrCodeUrl: null }],
    });

    const req = request({
      identity: IDENTITY,
      args: { preferences: blob, expectedPreferences: blob },
    });

    assert.strictEqual(req.operation, 'UpdateItem');
    assert.deepStrictEqual(req.key, { accountId: 'ACCOUNT#user-123' });
    // The stored attribute must remain a map; writing the raw AWSJSON string
    // would flip its shape and break payment-method reads (#510).
    assert.deepStrictEqual(req.update.expressionValues[':preferences'], {
      showReadOnlyProfiles: false,
      paymentMethods: [{ name: 'Cash', qrCodeUrl: null }],
    });
    assert.strictEqual(req.update.expression, 'SET preferences = :preferences, updatedAt = :updatedAt');
    assert.strictEqual(req.update.expressionValues[':updatedAt'], '2024-01-01T00:00:00Z');
  });

  it('conditions the write on the caller-read snapshot when provided', () => {
    const snapshot = JSON.stringify({ showReadOnlyProfiles: true });

    const req = request({
      identity: IDENTITY,
      args: { preferences: snapshot, expectedPreferences: snapshot },
    });

    assert.strictEqual(req.condition.expression, 'attribute_exists(accountId) AND preferences = :readPrefs');
    assert.deepStrictEqual(req.condition.expressionValues[':readPrefs'], { showReadOnlyProfiles: true });
  });

  it('allows only a first write when there is no snapshot', () => {
    const req = request({
      identity: IDENTITY,
      args: { preferences: JSON.stringify({ showReadOnlyProfiles: false }) },
    });

    assert.strictEqual(req.condition.expression, 'attribute_exists(accountId) AND attribute_not_exists(preferences)');
    assert.deepStrictEqual(req.condition.expressionValues, {});
  });

  it('two concurrent updates: the stale write is rejected instead of discarding the first', () => {
    // Both toggles were computed from the same read of the stored blob.
    const snapshot = {
      showReadOnlyProfiles: true,
      paymentMethods: [{ name: 'Cash', qrCodeUrl: null }],
    };
    const first = request({
      identity: IDENTITY,
      args: {
        preferences: JSON.stringify({ ...snapshot, showReadOnlyProfiles: false }),
        expectedPreferences: JSON.stringify(snapshot),
      },
    });
    const second = request({
      identity: IDENTITY,
      args: {
        preferences: JSON.stringify({ ...snapshot, showReadOnlyProfiles: true }),
        expectedPreferences: JSON.stringify(snapshot),
      },
    });

    // The first update lands: the stored blob is now its value, which no
    // longer matches the snapshot the second update still conditions on, so
    // DynamoDB rejects the second write instead of silently discarding the
    // first (and its paymentMethods).
    const storedAfterFirst = first.update.expressionValues[':preferences'];
    assert.notDeepStrictEqual(second.condition.expressionValues[':readPrefs'], storedAfterFirst);
    assert.throws(
      () =>
        response({
          error: { type: 'DynamoDB:ConditionalCheckFailedException', message: 'The conditional request failed' },
        }),
      /ConflictException: Preferences were modified by another request/,
    );
  });
});

describe('update_my_preferences_resolver response', () => {
  it('returns the result on success', () => {
    const result = { accountId: 'ACCOUNT#user-123' };
    assert.deepStrictEqual(response({ result }), result);
  });

  it('maps ConditionalCheckFailedException to a retryable ConflictException', () => {
    assert.throws(
      () =>
        response({
          error: { type: 'DynamoDB:ConditionalCheckFailedException', message: 'The conditional request failed' },
        }),
      /ConflictException: Preferences were modified by another request/,
    );
  });

  it('rethrows other errors unchanged', () => {
    assert.throws(
      () =>
        response({
          error: { type: 'DynamoDB:ProvisionedThroughputExceededException', message: 'throttled' },
        }),
      /ProvisionedThroughputExceededException: throttled/,
    );
  });
});
