import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_token_fn.js';

describe('validate_public_token request', () => {
    it('refuses a malformed campaign id as NOT_FOUND', () => {
        assert.throws(() => request({ args: {}, stash: {} }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => request({ args: { input: {} }, stash: {} }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => request({ args: { input: { campaignId: '' } }, stash: {} }), /NOT_FOUND: Order could not be placed/);
    });

    it('locates by campaignId on the campaignId-index GSI and stashes the canonical id', () => {
        const stash = {};
        const req = request({ args: { input: { campaignId: 'c1' } }, stash });
        assert.strictEqual(stash.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(req, {
            operation: 'Query',
            index: 'campaignId-index',
            query: { expression: 'campaignId = :campaignId', expressionValues: { ':campaignId': 'CAMPAIGN#c1' } },
            limit: 2,
        });
    });

    it('passes an already-canonical campaign id through unchanged', () => {
        const stash = {};
        const req = request({ args: { input: { campaignId: 'CAMPAIGN#c1' } }, stash });
        assert.strictEqual(stash.campaignId, 'CAMPAIGN#c1');
        assert.deepStrictEqual(req.query.expressionValues, { ':campaignId': 'CAMPAIGN#c1' });
    });
});

describe('validate_public_token response', () => {
    it('propagates a datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('refuses zero and two projections identically', () => {
        assert.throws(() => response({ result: { items: [] } }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response({ result: { items: [{ profileId: 'a' }, { profileId: 'b' }] } }), /NOT_FOUND: Order could not be placed/);
    });

    it('stashes the partition key from a single projection', () => {
        const stash = {};
        const res = response({ result: { items: [{ profileId: 'PROFILE#p1', campaignId: 'c1' }] }, stash });
        assert.deepStrictEqual(res, { located: true });
        assert.strictEqual(stash.profileId, 'PROFILE#p1');
    });

    it('refuses a projection whose profileId is missing or empty', () => {
        assert.throws(() => response({ result: { items: [{ campaignId: 'c1' }] } }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response({ result: { items: [{ profileId: '' }] } }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response({ result: { items: [{ profileId: 7 }] } }), /NOT_FOUND: Order could not be placed/);
    });
});
