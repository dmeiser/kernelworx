import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_profile_write_access_fn.js';

// Shared ctx helpers. Step 1 has stash.isOwner === undefined; step 2 has it
// set to true/false by the step-1 response.
function baseCtx(extra = {}) {
    return {
        identity: { sub: 'user-123' },
        info: { fieldName: 'createOrder' },
        args: { input: { profileId: 'prof-456' } },
        stash: {},
        ...extra
    };
}

describe('verify_profile_write_access_fn request (step 1: owner GetItem)', () => {
    it('issues a strongly consistent base-table GetItem keyed on the caller account + profileId', () => {
        const result = request(baseCtx());

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('preserves an already-prefixed profileId', () => {
        const ctx = baseCtx({ args: { input: { profileId: 'PROFILE#prof-456' } } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-456');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('normalizes a sub that already carries the ACCOUNT# prefix', () => {
        const ctx = baseCtx({ identity: { sub: 'ACCOUNT#user-123' } });
        const result = request(ctx);

        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('derives profileId from stash.order when input is absent', () => {
        const ctx = baseCtx({
            args: { input: {} },
            stash: { order: { profileId: 'ord-prof' } }
        });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#ord-prof');
    });

    it('derives profileId from stash.campaign when input and order are absent', () => {
        const ctx = baseCtx({
            args: { input: {} },
            stash: { campaign: { profileId: 'cmp-prof' } }
        });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#cmp-prof');
    });

    it('raises INVALID_INPUT when no profileId can be resolved', () => {
        const ctx = baseCtx({ args: { input: {} }, stash: {} });

        assert.throws(
            () => request(ctx),
            /INVALID_INPUT: Profile ID not found in request or stash/
        );
    });

    it('skips auth (no-op GetItem) for idempotent deleteOrder with a null stash.order', () => {
        const ctx = baseCtx({
            info: { fieldName: 'deleteOrder' },
            args: { input: {} },
            stash: { order: null }
        });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
        assert.strictEqual(ctx.stash.skipAuth, true);
    });

    it('skips auth for idempotent deleteCampaign with a null stash.campaign', () => {
        const ctx = baseCtx({
            info: { fieldName: 'deleteCampaign' },
            args: { input: {} },
            stash: { campaign: null }
        });

        const result = request(ctx);

        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
        assert.strictEqual(ctx.stash.skipAuth, true);
    });

    it('does NOT treat a non-null delete item as idempotent', () => {
        const ctx = baseCtx({
            info: { fieldName: 'deleteOrder' },
            args: { input: {} },
            stash: { order: { profileId: 'x' } }
        });

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#x');
        assert.strictEqual(ctx.stash.skipAuth, undefined);
    });
});

describe('verify_profile_write_access_fn request (step 2: branch on isOwner)', () => {
    it('issues a no-op GetItem when the owner was confirmed in step 1', () => {
        const ctx = baseCtx({ stash: { isOwner: true } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
    });

    it('issues the profileId-index GSI Query when the caller is a non-owner', () => {
        const ctx = baseCtx({ stash: { isOwner: false } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.deepStrictEqual(result.query, {
            expression: 'profileId = :profileId',
            expressionValues: { ':profileId': 'PROFILE#prof-456' }
        });
    });

    it('honors an already-set skipAuth flag in step 2', () => {
        const ctx = baseCtx({ stash: { skipAuth: true } });
        const result = request(ctx);

        assert.deepStrictEqual(result.key, { ownerAccountId: 'NOOP', profileId: 'NOOP' });
    });
});

describe('verify_profile_write_access_fn response (step 1)', () => {
    it('confirms ownership when the consistent GetItem returns an item under the caller key', () => {
        const profile = {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456',
            sellerName: 'Scout'
        };
        const ctx = baseCtx({ result: profile });

        const out = response(ctx);

        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#user-123');
        assert.deepStrictEqual(out, profile);
    });

    it('treats a null result as non-owner and moves to the GSI step', () => {
        const ctx = baseCtx({ result: null });

        const out = response(ctx);

        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(out, null);
    });

    it('does NOT require ownerAccountId to match sub: existence under the caller key is authoritative', () => {
        // Simulate the stale-GSI race: an item present under the caller key is
        // authoritative regardless of any attribute value.
        const profile = { ownerAccountId: 'UNRELATED-OWNER', profileId: 'PROFILE#prof-456' };
        const ctx = baseCtx({ result: profile });

        response(ctx);

        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(ctx.stash.profile, profile);
    });
});

describe('verify_profile_write_access_fn response (step 2)', () => {
    it('passes the confirmed profile through for the owner path', () => {
        const profile = { ownerAccountId: 'ACCOUNT#user-123', profileId: 'PROFILE#prof-456' };
        const ctx = baseCtx({ stash: { isOwner: true, profile } });

        assert.deepStrictEqual(response(ctx), profile);
    });

    it('stores the profile and flags non-owner from the GSI Query items for the share step', () => {
        const profile = { ownerAccountId: 'ACCOUNT#original-owner', profileId: 'PROFILE#prof-456' };
        const ctx = baseCtx({ stash: { isOwner: false }, result: { items: [profile] } });

        const out = response(ctx);

        assert.strictEqual(ctx.stash.isOwner, false);
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#original-owner');
        assert.deepStrictEqual(out, profile);
    });

    it('raises NOT_FOUND when the GSI Query returns no items', () => {
        const ctx = baseCtx({ stash: { isOwner: false }, result: { items: [] } });

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Profile not found/
        );
    });
});

describe('verify_profile_write_access_fn response (cross-cutting)', () => {
    it('returns authorized for the idempotent-delete skip path', () => {
        const ctx = baseCtx({ stash: { skipAuth: true } });
        assert.deepStrictEqual(response(ctx), { authorized: true });
    });

    it('propagates a data-source error', () => {
        const ctx = baseCtx({
            error: { message: 'DynamoDB: boom', type: 'DynamoDBException' },
            stash: { isOwner: undefined }
        });

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB: boom/
        );
    });
});
