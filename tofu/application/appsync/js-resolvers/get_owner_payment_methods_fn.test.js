import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_owner_payment_methods_fn.js';

describe('get_owner_payment_methods_fn request', () => {
    it('reads the owner account by the already-prefixed stash key, consistently', () => {
        const ctx = { stash: { ownerAccountId: 'ACCOUNT#owner-9' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { accountId: 'ACCOUNT#owner-9' });
        assert.strictEqual(result.consistentRead, true);
    });

    it('does not re-prefix the stash key, so a raw sub stays raw', () => {
        // The ownerAccountId comes off the profile item and already carries the
        // ACCOUNT# key prefix; normalizing again would double it.
        const ctx = { stash: { ownerAccountId: 'ACCOUNT#ACCOUNT#owner-9' } };

        assert.deepStrictEqual(request(ctx).key, { accountId: 'ACCOUNT#ACCOUNT#owner-9' });
    });

    it('fails with INTERNAL_ERROR when the stash has no owner account id', () => {
        for (const ownerAccountId of [undefined, null, '']) {
            const ctx = { stash: { ownerAccountId } };

            assert.throws(
                () => request(ctx),
                /INTERNAL_ERROR: Owner account ID not found/,
                `missing ownerAccountId ${String(ownerAccountId)} must abort the pipeline`,
            );
        }
    });
});

describe('get_owner_payment_methods_fn response', () => {
    it('stashes and returns the owner custom methods', () => {
        const methods = [{ id: 'pm-1', name: 'Cash on delivery' }];
        const ctx = { result: { preferences: { paymentMethods: methods } }, stash: {} };

        assert.deepStrictEqual(response(ctx), methods);
        assert.strictEqual(ctx.stash.customPaymentMethods, methods);
    });

    it('yields an empty list when the owner account has no preferences', () => {
        for (const account of [undefined, null, {}, { preferences: null }]) {
            const ctx = { result: account, stash: {} };

            assert.deepStrictEqual(response(ctx), []);
            assert.deepStrictEqual(ctx.stash.customPaymentMethods, []);
        }
    });

    it('yields an empty list when preferences exist without paymentMethods', () => {
        const ctx = { result: { preferences: { notifications: true } }, stash: {} };

        assert.deepStrictEqual(response(ctx), []);
        assert.deepStrictEqual(ctx.stash.customPaymentMethods, []);
    });

    it('propagates a DynamoDB error unchanged', () => {
        const ctx = { error: { message: 'Throttling', type: 'RESOURCE_BUSY' }, stash: {} };

        assert.throws(() => response(ctx), /RESOURCE_BUSY: Throttling/);
        assert.strictEqual(ctx.stash.customPaymentMethods, undefined);
    });
});
