import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_payment_methods_fn.js';

describe('get_payment_methods_fn request', () => {
    it('reads the caller account consistently with a normalized ACCOUNT# key', () => {
        const ctx = { identity: { sub: 'user-123' }, stash: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-123' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('keeps an already-prefixed sub as one prefix', () => {
        const ctx = { identity: { sub: 'ACCOUNT#user-123' }, stash: {} };

        assert.deepStrictEqual(request(ctx).key, { accountId: 'ACCOUNT#user-123' });
    });

    it('fails with UNAUTHORIZED when the caller has no sub claim', () => {
        for (const identity of [{}, { sub: '' }, { sub: null }, undefined]) {
            const ctx = { identity: identity || {}, stash: {} };

            assert.throws(
                () => request(ctx),
                /UNAUTHORIZED: Authentication required/,
                `missing sub in ${JSON.stringify(identity)} must reject the caller`,
            );
        }
    });
});

describe('get_payment_methods_fn response', () => {
    it('stashes and returns only the custom methods from preferences', () => {
        const methods = [{ id: 'pm-1', type: 'CUSTOM' }];
        const ctx = { result: { preferences: { paymentMethods: methods, other: 1 } }, stash: {} };

        assert.deepStrictEqual(response(ctx), methods);
        assert.deepStrictEqual(ctx.stash.customPaymentMethods, methods);
    });

    it('yields an empty list for an account with no stored preferences', () => {
        for (const account of [undefined, null, {}, { preferences: null }]) {
            const ctx = { result: account, stash: {} };

            assert.deepStrictEqual(response(ctx), []);
            assert.deepStrictEqual(ctx.stash.customPaymentMethods, []);
        }
    });

    it('does not inject the global methods (cash, check) itself', () => {
        // Global methods are added downstream; this function must stay a pure
        // read of the stored list, or they would be double-counted.
        const ctx = { result: { preferences: { paymentMethods: [] } }, stash: {} };

        assert.deepStrictEqual(response(ctx), []);
    });

    it('propagates a DynamoDB error unchanged', () => {
        const ctx = { error: { message: 'Service unavailable', type: 'INTERNAL_ERROR' }, stash: {} };

        assert.throws(() => response(ctx), /INTERNAL_ERROR: Service unavailable/);
        assert.strictEqual(ctx.stash.customPaymentMethods, undefined);
    });
});
