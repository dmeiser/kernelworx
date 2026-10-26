import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_my_preferences_resolver.js';

describe('update_my_preferences_resolver request', () => {
    it('builds UpdateItem request with normalized accountId and preferences payload', () => {
        const preferences = { theme: 'dark', notifications: true };
        const ctx = {
            identity: { sub: 'user-uuid-1' },
            args: { preferences },
        };
        const result = request(ctx);
        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-uuid-1' });
        assert.strictEqual(
            result.update.expression,
            'SET preferences = :preferences, updatedAt = :updatedAt'
        );
        assert.deepStrictEqual(result.update.expressionValues, {
            ':preferences': preferences,
            ':updatedAt': '2024-01-01T00:00:00Z',
        });
        assert.deepStrictEqual(result.condition, {
            expression: 'attribute_exists(accountId)',
        });
    });

    it('preserves already-prefixed ACCOUNT# in caller identity', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-uuid-2' },
            args: { preferences: { color: 'blue' } },
        };
        const result = request(ctx);
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-uuid-2' });
    });
});

describe('update_my_preferences_resolver response', () => {
    it('returns result item on success', () => {
        const updatedAccount = {
            accountId: 'ACCOUNT#user-uuid-1',
            preferences: { theme: 'dark' },
            updatedAt: '2024-01-01T00:00:00Z',
        };
        const ctx = {
            result: updatedAccount,
        };
        assert.strictEqual(response(ctx), updatedAccount);
    });

    it('maps ConditionalCheckFailedException to NOT_FOUND with user-friendly message', () => {
        const ctx = {
            error: {
                message: 'The conditional request failed',
                type: 'DynamoDB:ConditionalCheckFailedException',
            },
        };
        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Account not found\. Please sign out and sign in again\./
        );
    });

    it('propagates other DynamoDB errors unchanged', () => {
        const ctx = {
            error: {
                message: 'Provisioned throughput exceeded',
                type: 'DynamoDB:ProvisionedThroughputExceededException',
            },
        };
        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Provisioned throughput exceeded/
        );
    });
});
