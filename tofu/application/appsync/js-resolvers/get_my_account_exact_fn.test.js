import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_my_account_exact_fn.js';

describe('get_my_account_exact_fn request', () => {
    it('normalizes sub with ACCOUNT# prefix and issues strongly consistent GetItem', () => {
        const ctx = {
            identity: { sub: 'user-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-123' });
    });

    it('does not double-prefix when sub already carries ACCOUNT# prefix', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#user-456' },
        };

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#user-456' });
    });
});

describe('get_my_account_exact_fn response', () => {
    it('returns result when account exists', () => {
        const account = {
            accountId: 'ACCOUNT#user-123',
            email: 'test@example.com',
            preferences: { paymentMethods: [] },
        };
        const ctx = {
            result: account,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, account);
    });

    it('returns null when account is not found (result is null or undefined)', () => {
        assert.strictEqual(response({ result: null }), null);
        assert.strictEqual(response({ result: undefined }), null);
        assert.strictEqual(response({}), null);
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            error: { message: 'Internal error', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Internal error/
        );
    });
});
