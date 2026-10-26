import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_create_payment_method_fn.js';

describe('validate_create_payment_method_fn request', () => {
    it('throws UNAUTHORIZED when accountId (identity.sub) is missing', () => {
        const ctx = {
            args: { name: 'Zelle' },
            identity: {},
            stash: {},
        };
        assert.throws(
            () => request(ctx),
            /UNAUTHORIZED: Authentication required/
        );
    });

    it('throws INVALID_INPUT when name is missing or empty string', () => {
        const ctx = {
            args: { name: '   ' },
            identity: { sub: 'user-1' },
            stash: {},
        };
        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Payment method name is required/
        );
    });

    it('throws INVALID_INPUT when name exceeds 50 characters', () => {
        const ctx = {
            args: { name: 'A'.repeat(51) },
            identity: { sub: 'user-1' },
            stash: {},
        };
        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Payment method name must be 50 characters or less/
        );
    });

    it('throws INVALID_INPUT for reserved name Cash (case-insensitive)', () => {
        for (const reserved of ['Cash', 'cash', 'CASH']) {
            const ctx = {
                args: { name: reserved },
                identity: { sub: 'user-1' },
                stash: {},
            };
            assert.throws(
                () => request(ctx),
                /INVALID_INPUT: Cannot create payment method: ".*" is a reserved name/
            );
        }
    });

    it('throws INVALID_INPUT for reserved name Check (case-insensitive)', () => {
        for (const reserved of ['Check', 'check', 'CHECK']) {
            const ctx = {
                args: { name: reserved },
                identity: { sub: 'user-1' },
                stash: {},
            };
            assert.throws(
                () => request(ctx),
                /INVALID_INPUT: Cannot create payment method: ".*" is a reserved name/
            );
        }
    });

    it('builds GetItem with normalized key and consistent read for valid input', () => {
        const ctx = {
            args: { name: '  Venmo  ' },
            identity: { sub: 'user-uuid-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.paymentMethodName, 'Venmo');
        assert.strictEqual(ctx.stash.paymentMethodNameLower, 'venmo');
        assert.strictEqual(ctx.stash.accountId, 'user-uuid-1');
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-uuid-1' });
    });

    it('accepts name of exactly 50 characters and preserves already-prefixed ACCOUNT#', () => {
        const name50 = 'B'.repeat(50);
        const ctx = {
            args: { name: name50 },
            identity: { sub: 'ACCOUNT#user-uuid-2' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.paymentMethodName, name50);
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-uuid-2' });
    });
});

describe('validate_create_payment_method_fn response', () => {
    it('propagates DynamoDB errors', () => {
        const ctx = {
            error: { message: 'Throughput error', type: 'DynamoDB:ProvisionedThroughputExceededException' },
            stash: { paymentMethodName: 'Zelle', paymentMethodNameLower: 'zelle' },
        };
        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Throughput error/
        );
    });

    it('throws INVALID_INPUT when payment method name is a case-insensitive duplicate', () => {
        const ctx = {
            stash: { paymentMethodName: 'Venmo', paymentMethodNameLower: 'venmo' },
            result: {
                preferences: {
                    paymentMethods: [
                        { id: 'pm-1', name: 'VENMO' },
                    ],
                },
            },
        };
        assert.throws(
            () => response(ctx),
            /INVALID_INPUT: Payment method "Venmo" already exists/
        );
    });

    it('passes and stashes existing methods and readPreferences when no duplicate exists', () => {
        const existingMethods = [{ id: 'pm-1', name: 'Zelle' }];
        const preferences = { paymentMethods: existingMethods, theme: 'dark' };
        const ctx = {
            stash: { paymentMethodName: 'Venmo', paymentMethodNameLower: 'venmo' },
            result: {
                preferences,
            },
        };
        const result = response(ctx);
        assert.deepStrictEqual(result, {});
        assert.deepStrictEqual(ctx.stash.existingPaymentMethods, existingMethods);
        assert.strictEqual(ctx.stash.readPreferencesExisted, true);
        assert.deepStrictEqual(ctx.stash.readPreferences, preferences);
    });

    it('handles account with no preferences object (first payment method)', () => {
        const ctx = {
            stash: { paymentMethodName: 'Venmo', paymentMethodNameLower: 'venmo' },
            result: {
                accountId: 'ACCOUNT#user-1',
            },
        };
        const result = response(ctx);
        assert.deepStrictEqual(result, {});
        assert.deepStrictEqual(ctx.stash.existingPaymentMethods, []);
        assert.strictEqual(ctx.stash.readPreferencesExisted, false);
        assert.strictEqual(ctx.stash.readPreferences, undefined);
    });

    it('handles null result from DynamoDB', () => {
        const ctx = {
            stash: { paymentMethodName: 'Venmo', paymentMethodNameLower: 'venmo' },
            result: null,
        };
        const result = response(ctx);
        assert.deepStrictEqual(result, {});
        assert.deepStrictEqual(ctx.stash.existingPaymentMethods, []);
        assert.strictEqual(ctx.stash.readPreferencesExisted, false);
    });
});
