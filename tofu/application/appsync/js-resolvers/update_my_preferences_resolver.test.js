import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_my_preferences_resolver.js';

const IDENTITY = { sub: 'user-123' };

// Minimal DynamoDB condition evaluator for this resolver's lock. A stored
// `preferences` attribute may be a map (M, the shape current writers store) or
// a string (S, legacy rows written by the pre-#510 resolver). DynamoDB
// compares `preferences = :v` by full attribute equality: S never equals M.
// Returns true when `account exists AND preferences matches the snapshot in
// one of the two compared shapes`.
const conditionPasses = (req, stored) => {
  if (!stored || stored.accountId === undefined) return false;
  const attr = stored.preferences;
  if (attr === undefined) return false;
  const mapValue = req.condition.expressionValues[':readPrefsMap'];
  const strValue = req.condition.expressionValues[':readPrefsStr'];
  if (mapValue === undefined || strValue === undefined) {
    throw new Error(`unsupported condition expression: ${req.condition.expression}`);
  }
  if (!req.condition.expression.includes(
    '(preferences = :readPrefsMap OR preferences = :readPrefsStr)',
  )) {
    throw new Error(`unsupported condition expression: ${req.condition.expression}`);
  }
  if (attr.M !== undefined) {
    return JSON.stringify(attr.M) === JSON.stringify(mapValue);
  }
  if (attr.S !== undefined) {
    return attr.S === strValue;
  }
  return false;
};

const buildStoredRow = (accountId, preferencesAttributeValue) => ({
  accountId,
  preferences: preferencesAttributeValue,
});

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

  it('conditions on both the parsed map and the raw string of the caller-read snapshot', () => {
    const snapshot = JSON.stringify({ showReadOnlyProfiles: true });

    const req = request({
      identity: IDENTITY,
      args: { preferences: snapshot, expectedPreferences: snapshot },
    });

    assert.strictEqual(
      req.condition.expression,
      'attribute_exists(accountId) AND (preferences = :readPrefsMap OR preferences = :readPrefsStr)',
    );
    assert.deepStrictEqual(req.condition.expressionValues[':readPrefsMap'], { showReadOnlyProfiles: true });
    assert.strictEqual(req.condition.expressionValues[':readPrefsStr'], snapshot);
  });

  it('allows only a first write when there is no snapshot', () => {
    const req = request({
      identity: IDENTITY,
      args: { preferences: JSON.stringify({ showReadOnlyProfiles: false }) },
    });

    assert.strictEqual(req.condition.expression, 'attribute_exists(accountId) AND attribute_not_exists(preferences)');
    assert.deepStrictEqual(req.condition.expressionValues, {});
  });

  it('lock matches a legacy row whose stored preferences is the raw AWSJSON string (S) — the toggle succeeds and self-normalizes', () => {
    // The pre-#510 resolver stored the raw AWSJSON string, so deployed dev/prod
    // rows hold preferences as an S attribute, not a map.
    const legacyRaw = JSON.stringify({ showReadOnlyProfiles: true });
    const storedRow = buildStoredRow('ACCOUNT#user-123', { S: legacyRaw });

    const req = request({
      identity: IDENTITY,
      args: {
        preferences: JSON.stringify({ showReadOnlyProfiles: false }),
        expectedPreferences: legacyRaw,
      },
    });

    assert.ok(conditionPasses(req, storedRow), 'legacy S row must satisfy the lock via the string alternative');
    // The written value is still the parsed map, so a successful toggle
    // self-normalizes the legacy row to the map shape.
    assert.strictEqual(req.update.expressionValues[':preferences'].showReadOnlyProfiles, false);
  });

  it('lock matches a current row whose stored preferences is a map (M) — the toggle succeeds', () => {
    const storedPrefs = { showReadOnlyProfiles: true, paymentMethods: [{ name: 'Cash', qrCodeUrl: null }] };
    const storedRow = buildStoredRow('ACCOUNT#user-123', { M: storedPrefs });

    const req = request({
      identity: IDENTITY,
      args: {
        preferences: JSON.stringify({ ...storedPrefs, showReadOnlyProfiles: false }),
        expectedPreferences: JSON.stringify(storedPrefs),
      },
    });

    assert.ok(conditionPasses(req, storedRow), 'current M row must satisfy the lock via the map alternative');
  });

  it('a concurrent write of either shape is refused: neither alternative matches', () => {
    const snapshot = { showReadOnlyProfiles: true, paymentMethods: [{ name: 'Cash', qrCodeUrl: null }] };
    const concurrentMapWrite = { ...snapshot, paymentMethods: [{ name: 'Card', qrCodeUrl: 's3://x' }] };
    const concurrentStringWrite = JSON.stringify({ showReadOnlyProfiles: false });

    const req = request({
      identity: IDENTITY,
      args: {
        preferences: JSON.stringify({ ...snapshot, showReadOnlyProfiles: false }),
        expectedPreferences: JSON.stringify(snapshot),
      },
    });

    assert.strictEqual(
      req.condition.expression,
      'attribute_exists(accountId) AND (preferences = :readPrefsMap OR preferences = :readPrefsStr)',
    );
    // A payment-method mutation concurrently rewrote the blob (map shape).
    assert.strictEqual(conditionPasses(req, buildStoredRow('ACCOUNT#user-123', { M: concurrentMapWrite })), false);
    // A legacy-shaped concurrent write stored the blob as a string.
    assert.strictEqual(conditionPasses(req, buildStoredRow('ACCOUNT#user-123', { S: concurrentStringWrite })), false);
    // A legacy row the snapshot was never taken from also fails.
    assert.strictEqual(conditionPasses(req, buildStoredRow('ACCOUNT#user-123', { S: '{} [' })), false);
  });

  it('string-vs-map near-misses never satisfy the lock', () => {
    const storedRow = buildStoredRow('ACCOUNT#user-123', { S: JSON.stringify({ showReadOnlyProfiles: true }) });

    // The snapshot parses to the same content but the snapshot string differs
    // from the stored legacy string: the string alternative must not match
    // through re-serialization.
    const req = request({
      identity: IDENTITY,
      args: {
        preferences: JSON.stringify({ showReadOnlyProfiles: false }),
        expectedPreferences: JSON.stringify({ showReadOnlyProfiles: false }),
      },
    });
    assert.strictEqual(conditionPasses(req, storedRow), false);
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
