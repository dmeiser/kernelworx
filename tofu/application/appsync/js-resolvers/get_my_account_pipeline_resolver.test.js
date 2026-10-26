import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_my_account_pipeline_resolver.js';

describe('get_my_account_pipeline_resolver request', () => {
    it('issues an empty request so the pipeline functions do the work', () => {
        const ctx = { args: {}, identity: { sub: 'user-123' }, stash: {} };

        assert.deepStrictEqual(request(ctx), {});
    });
});

describe('get_my_account_pipeline_resolver response', () => {
    it('fails with NOT_FOUND when the pipeline produced no account', () => {
        for (const missing of [undefined, null]) {
            const ctx = { prev: { result: missing } };

            assert.throws(
                () => response(ctx),
                /NOT_FOUND: Account not found/,
                `missing result ${String(missing)} must fail the query`,
            );
        }
    });

    it('forwards the account item from the previous pipeline step', () => {
        const account = { accountId: 'ACCOUNT#user-123', preferences: {} };
        const ctx = { prev: { result: account } };

        assert.strictEqual(response(ctx), account);
    });

    it('forwards a falsy-looking but present account object', () => {
        // An empty item is still an account row: only undefined/null mean "no
        // account", so the guard must not treat an empty object as a miss.
        const account = {};
        const ctx = { prev: { result: account } };

        assert.strictEqual(response(ctx), account);
    });
});
