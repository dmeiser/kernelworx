import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_payment_method_fn.js';

const CONFLICT_MESSAGE = 'Payment methods were modified by another request. Please retry.';

function baseStash() {
    const readPreferences = { paymentMethods: [{ name: 'Venmo' }] };
    return {
        accountId: 'user-123',
        paymentMethodName: 'Zelle',
        existingPaymentMethods: [{ name: 'Venmo' }],
        readPreferencesExisted: true,
        readPreferences,
    };
}

describe('create_payment_method_fn request', () => {
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
        // The update must not be affected by the condition values.
        assert.deepStrictEqual(req.update.expressionValues[':methods'], [
            { name: 'Venmo' },
            { name: 'Zelle', qrCodeUrl: null },
        ]);
    });

    it('uses attribute_not_exists(preferences) when the read found none', () => {
        const req = request({
            stash: {
                accountId: 'user-123',
                paymentMethodName: 'Zelle',
                existingPaymentMethods: [],
                readPreferencesExisted: false,
            },
        });

        assert.strictEqual(
            req.condition.expression,
            'attribute_exists(accountId) AND attribute_not_exists(preferences)',
        );
        assert.strictEqual(req.condition.expressionValues[':readPrefs'], undefined);
    });

    it('treats an absent readPreferencesExisted flag as "no preferences read"', () => {
        const req = request({
            stash: {
                accountId: 'user-123',
                paymentMethodName: 'Zelle',
                existingPaymentMethods: [],
            },
        });

        assert.strictEqual(
            req.condition.expression,
            'attribute_exists(accountId) AND attribute_not_exists(preferences)',
        );
    });
});

describe('create_payment_method_fn response', () => {
    it('returns the created payment method', () => {
        const ctx = {
            stash: { paymentMethodName: 'Zelle' },
        };
        assert.deepStrictEqual(response(ctx), { name: 'Zelle', qrCodeUrl: null });
    });

    it('maps ConditionalCheckFailedException to a retryable ConflictException', () => {
        const ctx = {
            stash: { paymentMethodName: 'Zelle' },
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
            stash: { paymentMethodName: 'Zelle' },
            error: { type: 'DynamoDB:InternalServerError', message: 'boom' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: boom/,
        );
    });
});
