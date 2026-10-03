import { describe, it } from 'node:test';
import assert from 'node:assert';
import { buildPaymentMethodWrite, mapPaymentMethodWriteError } from './prefs_optimistic_lock.js';

const CONFLICT_MESSAGE = 'Payment methods were modified by another request. Please retry.';

describe('buildPaymentMethodWrite', () => {
    it('returns an UpdateItem keyed on the account with the optimistic condition and update payload', () => {
        const readPreferences = { paymentMethods: [{ name: 'Venmo' }] };
        const updatedMethods = [{ name: 'Venmo' }, { name: 'Zelle', qrCodeUrl: null }];

        const req = buildPaymentMethodWrite('user-123', true, readPreferences, updatedMethods);

        assert.strictEqual(req.operation, 'UpdateItem');
        assert.deepStrictEqual(req.key, { accountId: 'ACCOUNT#user-123' });
        assert.strictEqual(
            req.condition.expression,
            'attribute_exists(accountId) AND preferences = :readPrefs',
        );
        assert.deepStrictEqual(req.condition.expressionValues, {
            ':readPrefs': readPreferences,
        });
        assert.strictEqual(req.update.expression, 'SET #prefs.#pm = :methods');
        assert.deepStrictEqual(req.update.expressionNames, {
            '#prefs': 'preferences',
            '#pm': 'paymentMethods',
        });
        assert.deepStrictEqual(req.update.expressionValues, { ':methods': updatedMethods });
    });

    it('leaves an already-prefixed account id alone instead of double-prefixing it', () => {
        // The key is built through normalizeIdOrPrefix from lib/ids.js, the same
        // owner the resolvers use, so a stash value that already carries the
        // ACCOUNT# form (as the validation steps stash it) targets the same row
        // rather than a phantom ACCOUNT#ACCOUNT# one.
        const req = buildPaymentMethodWrite('ACCOUNT#user-123', true, {}, []);

        assert.deepStrictEqual(req.key, { accountId: 'ACCOUNT#user-123' });
    });

    it('requires the account to exist and preferences to be absent when the read found none', () => {
        const req = buildPaymentMethodWrite('user-123', false, undefined, []);

        assert.strictEqual(
            req.condition.expression,
            'attribute_exists(accountId) AND attribute_not_exists(preferences)',
        );
        assert.deepStrictEqual(req.condition.expressionValues, {});
    });

    it('does not leak the snapshot value into the update expression values', () => {
        const readPreferences = { paymentMethods: [{ name: 'Venmo' }], other: 'kept' };
        const updatedMethods = [{ name: 'Zelle' }];

        const req = buildPaymentMethodWrite('user-123', true, readPreferences, updatedMethods);

        assert.deepStrictEqual(req.update.expressionValues, { ':methods': updatedMethods });
        assert.strictEqual(req.update.expressionValues[':readPrefs'], undefined);
    });
});

describe('mapPaymentMethodWriteError', () => {
    it('throws on success (no error) so the caller proceeds', () => {
        assert.doesNotThrow(() => mapPaymentMethodWriteError({}));
    });

    it('maps ConditionalCheckFailedException to a retryable ConflictException', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:ConditionalCheckFailedException',
                message: 'The conditional request failed',
            },
        };

        assert.throws(
            () => mapPaymentMethodWriteError(ctx),
            (err) => err.message === `ConflictException: ${CONFLICT_MESSAGE}`,
        );
    });

    it('propagates other errors', () => {
        const ctx = { error: { type: 'DynamoDB:InternalServerError', message: 'boom' } };

        assert.throws(
            () => mapPaymentMethodWriteError(ctx),
            /DynamoDB:InternalServerError: boom/,
        );
    });
});
