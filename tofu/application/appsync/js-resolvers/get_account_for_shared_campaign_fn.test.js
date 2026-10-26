import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_account_for_shared_campaign_fn.js';

describe('get_account_for_shared_campaign_fn request', () => {
    it('normalizes sub with ACCOUNT# prefix and builds GetItem request', () => {
        const ctx = {
            identity: { sub: 'user-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
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

describe('get_account_for_shared_campaign_fn response', () => {
    it('stashes account in ctx.stash.account and returns result when account exists', () => {
        const account = {
            accountId: 'ACCOUNT#user-123',
            email: 'scout@example.com',
            preferences: { paymentMethods: [] },
        };
        const ctx = {
            stash: {},
            result: account,
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, account);
        assert.deepStrictEqual(ctx.stash.account, account);
    });

    it('throws NOT_FOUND when account result is missing', () => {
        const ctx = {
            stash: {},
            result: null,
        };

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Account not found/
        );
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            stash: {},
            error: { message: 'Service unavailable', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: Service unavailable/
        );
    });
});
