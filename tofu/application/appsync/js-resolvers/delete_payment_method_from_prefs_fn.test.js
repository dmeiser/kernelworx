import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_payment_method_from_prefs_fn.js';

const CONFLICT_MESSAGE = 'Payment methods were modified by another request. Please retry.';

function baseStash() {
    const readPreferences = {
        paymentMethods: [{ name: 'Venmo', qrCodeUrl: null }, { name: 'PayPal' }],
    };
    return {
        accountId: 'user-123',
        nameLower: 'venmo',
        existingMethods: [{ name: 'Venmo', qrCodeUrl: null }, { name: 'PayPal' }],
        readPreferencesExisted: true,
        readPreferences,
    };
}

describe('delete_payment_method_from_prefs_fn request', () => {
    it('removes the target method case-insensitively and keeps the rest', () => {
        const stash = baseStash();
        const req = request({ stash });

        assert.deepStrictEqual(req.update.expressionValues[':methods'], [{ name: 'PayPal' }]);
    });

    it('uses the optimistic preferences condition when the read found preferences', () => {
        const stash = baseStash();
        const req = request({ stash });

        assert.strictEqual(req.operation, 'UpdateItem');
        assert.strictEqual(
            req.condition.expression,
            'attribute_exists(accountId) AND preferences = :readPrefs',
        );
        assert.deepStrictEqual(req.condition.expressionValues, {
            ':readPrefs': stash.readPreferences,
        });
    });

    it('uses attribute_not_exists(preferences) when the read found none', () => {
        const req = request({
            stash: {
                accountId: 'user-123',
                nameLower: 'venmo',
                existingMethods: [],
                readPreferencesExisted: false,
            },
        });

        assert.strictEqual(
            req.condition.expression,
            'attribute_exists(accountId) AND attribute_not_exists(preferences)',
        );
    });
});

describe('delete_payment_method_from_prefs_fn response', () => {
    it('returns true on success', () => {
        const ctx = { stash: {} };
        assert.strictEqual(response(ctx), true);
    });

    it('maps ConditionalCheckFailedException to a retryable ConflictException', () => {
        const ctx = {
            stash: {},
            error: {
                type: 'DynamoDB:ConditionalCheckFailedException',
                message: 'The conditional request failed',
            },
        };

        assert.throws(
            () => response(ctx),
            (err) => err.message === `ConflictException: ${CONFLICT_MESSAGE}`,
        );
    });

    it('propagates other errors', () => {
        const ctx = {
            stash: {},
            error: { type: 'DynamoDB:InternalServerError', message: 'boom' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: boom/,
        );
    });
});
