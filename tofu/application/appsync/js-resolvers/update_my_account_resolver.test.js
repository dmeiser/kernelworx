import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_my_account_resolver.js';

describe('update_my_account_resolver request', () => {
  it('rejects when identity is missing', () => {
    const ctx = {
      args: { input: { givenName: 'John' } },
    };

    assert.throws(
      () => request(ctx),
      /UNAUTHORIZED: Authentication required/
    );
  });

  it('rejects when identity.sub is missing', () => {
    const ctx = {
      identity: {},
      args: { input: { givenName: 'John' } },
    };

    assert.throws(
      () => request(ctx),
      /UNAUTHORIZED: Authentication required/
    );
  });

  it('rejects when input is empty', () => {
    const ctx = {
      identity: { sub: 'user-123' },
      args: { input: {} },
    };

    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: At least one field must be provided/
    );
  });

  it('rejects when args is empty or input is missing', () => {
    const ctx = {
      identity: { sub: 'user-123' },
      args: {},
    };

    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: At least one field must be provided/
    );
  });

  it('rejects when all allowed fields are null or undefined', () => {
    const ctx = {
      identity: { sub: 'user-123' },
      args: {
        input: {
          givenName: null,
          familyName: undefined,
          otherField: 'ignored',
        },
      },
    };

    assert.throws(
      () => request(ctx),
      /INVALID_INPUT: At least one field must be provided/
    );
  });

  it('rejects non-integer or non-number unitNumber', () => {
    const invalidValues = ['123', 1.5, 0, -1, NaN, Infinity];

    for (const val of invalidValues) {
      const ctx = {
        identity: { sub: 'user-123' },
        args: { input: { unitNumber: val } },
      };

      assert.throws(
        () => request(ctx),
        /INVALID_INPUT: unitNumber must be a positive integer/,
        `Expected unitNumber ${val} to be rejected`
      );
    }
  });

  it('builds UpdateItem request with all allowed fields including state alias', () => {
    const ctx = {
      identity: { sub: 'user-123' },
      args: {
        input: {
          givenName: 'Jane',
          familyName: 'Doe',
          city: 'Chicago',
          state: 'IL',
          unitType: 'Pack',
          unitNumber: 158,
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-123' });
    assert.deepStrictEqual(result.condition, { expression: 'attribute_exists(accountId)' });

    // Verify expression components
    assert.match(result.update.expression, /#updatedAt = :updatedAt/);
    assert.match(result.update.expression, /#givenName = :givenName/);
    assert.match(result.update.expression, /#familyName = :familyName/);
    assert.match(result.update.expression, /#city = :city/);
    assert.match(result.update.expression, /#state = :state/);
    assert.match(result.update.expression, /#unitType = :unitType/);
    assert.match(result.update.expression, /#unitNumber = :unitNumber/);

    // Verify expressionNames
    assert.strictEqual(result.update.expressionNames['#updatedAt'], 'updatedAt');
    assert.strictEqual(result.update.expressionNames['#givenName'], 'givenName');
    assert.strictEqual(result.update.expressionNames['#familyName'], 'familyName');
    assert.strictEqual(result.update.expressionNames['#city'], 'city');
    assert.strictEqual(result.update.expressionNames['#state'], 'state');
    assert.strictEqual(result.update.expressionNames['#unitType'], 'unitType');
    assert.strictEqual(result.update.expressionNames['#unitNumber'], 'unitNumber');

    // Verify expressionValues
    assert.strictEqual(result.update.expressionValues[':updatedAt'], '2024-01-01T00:00:00Z');
    assert.strictEqual(result.update.expressionValues[':givenName'], 'Jane');
    assert.strictEqual(result.update.expressionValues[':familyName'], 'Doe');
    assert.strictEqual(result.update.expressionValues[':city'], 'Chicago');
    assert.strictEqual(result.update.expressionValues[':state'], 'IL');
    assert.strictEqual(result.update.expressionValues[':unitType'], 'Pack');
    assert.strictEqual(result.update.expressionValues[':unitNumber'], 158);
  });

  it('builds UpdateItem request with a single field', () => {
    const ctx = {
      identity: { sub: 'user-456' },
      args: {
        input: {
          city: 'Springfield',
        },
      },
    };

    const result = request(ctx);

    assert.strictEqual(result.operation, 'UpdateItem');
    assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-456' });
    assert.strictEqual(
      result.update.expression,
      'SET #updatedAt = :updatedAt, #city = :city'
    );
    assert.deepStrictEqual(result.update.expressionNames, {
      '#updatedAt': 'updatedAt',
      '#city': 'city',
    });
    assert.deepStrictEqual(result.update.expressionValues, {
      ':updatedAt': '2024-01-01T00:00:00Z',
      ':city': 'Springfield',
    });
  });
});

describe('update_my_account_resolver response', () => {
  it('returns result on successful update', () => {
    const ctx = {
      result: {
        accountId: 'ACCOUNT#user-123',
        givenName: 'Jane',
        updatedAt: '2024-01-01T00:00:00Z',
      },
    };

    const result = response(ctx);
    assert.deepStrictEqual(result, ctx.result);
  });

  it('maps ConditionalCheckFailedException to NOT_FOUND with account id', () => {
    const ctx = {
      identity: { sub: 'user-123' },
      error: {
        type: 'DynamoDB:ConditionalCheckFailedException',
        message: 'Conditional check failed',
      },
    };

    assert.throws(
      () => response(ctx),
      /NOT_FOUND: Account user-123 not found/
    );
  });

  it('propagates other DynamoDB errors', () => {
    const ctx = {
      identity: { sub: 'user-123' },
      error: {
        type: 'DynamoDB:InternalServerError',
        message: 'Something went wrong',
      },
    };

    assert.throws(
      () => response(ctx),
      /DynamoDB:InternalServerError: Something went wrong/
    );
  });
});
