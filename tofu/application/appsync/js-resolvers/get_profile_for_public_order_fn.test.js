import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_profile_for_public_order_fn.js';

describe('get_profile_for_public_order request', () => {
    it('refuses a missing profileId as NOT_FOUND (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /NOT_FOUND: Order could not be placed/);
    });

    it('locates the profile on the profileId-index GSI', () => {
        const req = request({ stash: { profileId: 'PROFILE#p1' } });
        assert.deepStrictEqual(req, {
            operation: 'Query',
            index: 'profileId-index',
            query: { expression: 'profileId = :profileId', expressionValues: { ':profileId': 'PROFILE#p1' } },
            limit: 2,
        });
    });
});

describe('get_profile_for_public_order response', () => {
    it('propagates a datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('refuses zero and two projections identically (a transfer window is ambiguous)', () => {
        assert.throws(() => response({ result: { items: [] } }), /NOT_FOUND: Order could not be placed/);
        assert.throws(
            () => response({ result: { items: [{ ownerAccountId: 'a' }, { ownerAccountId: 'b' }] } }),
            /NOT_FOUND: Order could not be placed/
        );
    });

    it('stashes the candidate owner account from a single projection (sellerName comes from the step-2 consistent read)', () => {
        const stash = {};
        const res = response({ result: { items: [{ ownerAccountId: 'ACCOUNT#o1', sellerName: 'Stale GSI Name' }] }, stash });
        assert.deepStrictEqual(res, { located: true });
        assert.strictEqual(stash.ownerAccountId, 'ACCOUNT#o1');
        // The GSI projection is eventually consistent: the seller display name
        // must NOT be trusted from it (SEC-4). Step 2 re-reads it strongly.
        assert.strictEqual('sellerName' in stash, false);
    });

    it('refuses a projection whose owner account is missing or empty', () => {
        assert.throws(() => response({ result: { items: [{ sellerName: 'S' }] } }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response({ result: { items: [{ ownerAccountId: '' }] } }), /NOT_FOUND: Order could not be placed/);
    });
});
