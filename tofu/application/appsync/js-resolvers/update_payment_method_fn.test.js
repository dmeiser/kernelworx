import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './update_payment_method_fn.js';

const CONFLICT_MESSAGE = 'Payment methods were modified by another request. Please retry.';

function baseStash() {
    const readPreferences = {
        paymentMethods: [{ name: 'Venmo', qrCodeUrl: null }, { name: 'PayPal' }],
    };
    return {
        accountId: 'user-123',
        currentName: 'Venmo',
        newName: 'Cash App Card',
        existingMethods: [{ name: 'Venmo', qrCodeUrl: null }, { name: 'PayPal' }],
        readPreferencesExisted: true,
        readPreferences,
    };
}

describe('update_payment_method_fn request', () => {
    it('renames the target method and keeps the rest of the array intact', () => {
        const stash = baseStash();
        const req = request({ stash });

        assert.deepStrictEqual(req.update.expressionValues[':methods'], [
            { name: 'Cash App Card', qrCodeUrl: null },
            { name: 'PayPal' },
        ]);
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
                currentName: 'Venmo',
                newName: 'Zelle',
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

describe('update_payment_method_fn response', () => {
    it('returns the renamed payment method', () => {
        const ctx = { stash: { newName: 'Cash App Card' } };
        assert.deepStrictEqual(response(ctx), { name: 'Cash App Card', qrCodeUrl: null });
    });

    it('maps ConditionalCheckFailedException to a retryable ConflictException', () => {
        const ctx = {
            stash: { newName: 'Cash App Card' },
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
            stash: { newName: 'Cash App Card' },
            error: { type: 'DynamoDB:InternalServerError', message: 'boom' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDB:InternalServerError: boom/,
        );
    });
});
