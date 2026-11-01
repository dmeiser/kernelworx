import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './set_owner_account_id_in_stash_fn.js';

describe('set_owner_account_id_in_stash_fn request', () => {
    it('sets ctx.stash.ownerAccountId from ctx.identity.sub and returns empty object', () => {
        const ctx = {
            identity: { sub: 'sub-uuid-123' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.ownerAccountId, 'sub-uuid-123');
        assert.deepStrictEqual(result, {});
    });
});

describe('set_owner_account_id_in_stash_fn response', () => {
    it('passes through previous step result untouched', () => {
        const paymentMethods = [
            { id: 'pm-1', name: 'Cash' },
            { id: 'pm-2', name: 'Venmo', qrCodeUrl: 's3://bucket/qr.png' },
        ];
        const ctx = {
            prev: { result: paymentMethods },
        };
        assert.strictEqual(response(ctx), paymentMethods);
    });

    it('passes through empty array or null result from previous step', () => {
        assert.deepStrictEqual(response({ prev: { result: [] } }), []);
        assert.strictEqual(response({ prev: { result: null } }), null);
    });
});
