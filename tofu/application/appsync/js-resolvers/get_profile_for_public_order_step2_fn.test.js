import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_profile_for_public_order_step2_fn.js';

describe('get_profile_for_public_order_step2 request', () => {
    it('refuses missing stash keys as NOT_FOUND (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => request({ stash: { profileId: 'PROFILE#p1' } }), /NOT_FOUND: Order could not be placed/);
    });

    it('reads the base table strongly consistently under the located owner key', () => {
        const req = request({ stash: { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#o1' } });
        assert.deepStrictEqual(req, {
            operation: 'GetItem',
            key: { ownerAccountId: 'ACCOUNT#o1', profileId: 'PROFILE#p1' },
            consistentRead: true,
        });
    });
});

describe('get_profile_for_public_order_step2 response', () => {
    it('propagates a datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('fails closed when the base row is gone (stale transfer-lag projection)', () => {
        // The GSI still projected the old-owner row but the base table no
        // longer holds it: ownership moved. No payment read, no email (SEC-4).
        assert.throws(
            () => response({ result: null, stash: { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#old' } }),
            /NOT_FOUND: Order could not be placed/
        );
    });

    it('fails closed when the base row disagrees with the located key', () => {
        assert.throws(
            () =>
                response({
                    result: { ownerAccountId: 'ACCOUNT#other', profileId: 'PROFILE#p1' },
                    stash: { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#old' },
                }),
            /NOT_FOUND: Order could not be placed/
        );
    });

    it('confirms ownership and stashes the seller name from the consistent base row', () => {
        const stash = { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#o1' };
        const res = response({
            result: { ownerAccountId: 'ACCOUNT#o1', profileId: 'PROFILE#p1', sellerName: 'My Shop' },
            stash,
        });
        assert.deepStrictEqual(res, { confirmed: true });
        assert.strictEqual(stash.sellerName, 'My Shop');
    });

    it('treats a non-string seller name as the empty display name', () => {
        const stash = { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#o1' };
        response({ result: { ownerAccountId: 'ACCOUNT#o1', profileId: 'PROFILE#p1' }, stash });
        assert.strictEqual(stash.sellerName, '');
    });
});
