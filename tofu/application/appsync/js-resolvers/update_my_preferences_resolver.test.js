import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_my_preferences_resolver.js';

describe('update_my_preferences_resolver request', () => {
    it('builds UpdateItem request locked to the stashed preferences snapshot', () => {
        const preferences = { theme: 'dark', notifications: true };
        const readPreferences = { theme: 'dark', notifications: true, paymentMethods: [{ name: 'Cash App' }] };
        const ctx = {
            identity: { sub: 'user-uuid-1' },
            args: { preferences },
            stash: { readPreferencesExisted: true, readPreferences },
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
            expression: 'attribute_exists(accountId) AND preferences = :readPrefs',
            expressionValues: { ':readPrefs': readPreferences },
        });
    });

    it('uses attribute_not_exists condition when the account has no preferences yet', () => {
        const ctx = {
            identity: { sub: 'user-uuid-3' },
            args: { preferences: { showReadOnlyProfiles: false } },
            stash: { readPreferencesExisted: false },
        };
        const result = request(ctx);
        assert.deepStrictEqual(result.condition, {
            expression: 'attribute_exists(accountId) AND attribute_not_exists(preferences)',
            expressionValues: {},
        });
    });

    it('preserves already-prefixed ACCOUNT# in caller identity', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-uuid-2' },
            args: { preferences: { color: 'blue' } },
            stash: { readPreferencesExisted: false },
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

    it('maps ConditionalCheckFailedException to a retryable ConflictException', () => {
        const ctx = {
            error: {
                message: 'The conditional request failed',
                type: 'DynamoDB:ConditionalCheckFailedException',
            },
        };
        assert.throws(
            () => response(ctx),
            /ConflictException: Preferences were modified by another request\. Please retry\./
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
