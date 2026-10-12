import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_token_fn.js';

// #679 write slice, spec §10.1: the create pipeline's GSI locator step. The GSI
// is a locator only - the token is the authorization, and step 2 re-reads the
// row consistently (#545).

function ctxWith(input) {
    return { args: { input }, stash: {}, result: null, error: null };
}

function located(ownerAccountId) {
    return { items: [{ ownerAccountId: ownerAccountId, profileId: 'PROFILE#p1', publicOrders: { token: 'secret-token' } }] };
}

describe('validate_public_token_fn request', () => {
    it('queries profileId-index for the normalized profile id', () => {
        const ctx = ctxWith({ profileId: 'p1', token: 't' });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.deepStrictEqual(result.query.expressionValues, { ':profileId': 'PROFILE#p1' });
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#p1');
    });

    it('does not re-prefix an id that already carries the prefix', () => {
        const ctx = ctxWith({ profileId: 'PROFILE#p1' });
        assert.deepStrictEqual(request(ctx).query.expressionValues, { ':profileId': 'PROFILE#p1' });
    });

    it('reads nothing and answers NOT_FOUND for a malformed profile id', () => {
        const ctx = ctxWith({ profileId: '', token: 't' });
        assert.throws(() => request(ctx), /NOT_FOUND: Order could not be placed/);
    });

    it('never consults identity - identity is null under the API-key mode', () => {
        const ctx = ctxWith({ profileId: 'p1', token: 't' });
        assert.strictEqual(ctx.identity, undefined);
        request(ctx);
    });
});

describe('validate_public_token_fn response', () => {
    it('stashes only the owner partition key, never the projected token', () => {
        const ctx = ctxWith({ profileId: 'p1' });
        request(ctx);
        ctx.result = located('ACCOUNT#owner-1');

        const result = response(ctx);

        assert.deepStrictEqual(result, { located: true });
        assert.strictEqual(ctx.stash.ownerAccountId, 'ACCOUNT#owner-1');
        assert.ok(!JSON.stringify(ctx.stash).includes('secret-token'));
    });

    it('answers the identical NOT_FOUND for zero projections', () => {
        const ctx = ctxWith({ profileId: 'p1' });
        request(ctx);
        ctx.result = { items: [] };
        assert.throws(() => response(ctx), /NOT_FOUND: Order could not be placed/);
    });

    it('answers the identical NOT_FOUND for a multi-projection transfer window', () => {
        const ctx = ctxWith({ profileId: 'p1' });
        request(ctx);
        ctx.result = { items: [{ ownerAccountId: 'ACCOUNT#old' }, { ownerAccountId: 'ACCOUNT#new' }] };
        assert.throws(() => response(ctx), /NOT_FOUND: Order could not be placed/);
    });

    it('answers NOT_FOUND for a projection without an owner key', () => {
        const ctx = ctxWith({ profileId: 'p1' });
        request(ctx);
        ctx.result = { items: [{ profileId: 'PROFILE#p1' }] };
        assert.throws(() => response(ctx), /NOT_FOUND: Order could not be placed/);
    });

    it('surfaces a datastore error unchanged', () => {
        const ctx = ctxWith({ profileId: 'p1' });
        ctx.error = { type: 'DynamoDB:ResourceNotFoundException', message: 'no index' };
        assert.throws(() => response(ctx), /ResourceNotFoundException/);
    });

    it('names no token value in any rejection message', () => {
        const ctx = ctxWith({ profileId: 'p1', token: 'secret-token' });
        request(ctx);
        ctx.result = { items: [] };
        try {
            response(ctx);
            assert.fail('expected NOT_FOUND');
        } catch (error) {
            assert.ok(!String(error.message).includes('secret-token'));
        }
    });
});
