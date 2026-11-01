import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './fetch_profile_fn.js';

function baseCtx(extra = {}) {
    return {
        identity: { sub: 'user-123' },
        args: { profileId: 'prof-456' },
        stash: {},
        ...extra
    };
}

describe('fetch_profile_fn request (step 1: owner GetItem)', () => {
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
        const ctx = baseCtx({ args: { profileId: 'PROFILE#prof-456' } });
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

    it('derives profileId from stash.profileId when args.profileId is absent', () => {
        const ctx = baseCtx({
            args: {},
            stash: { profileId: 'prof-from-stash' }
        });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.profileId, 'PROFILE#prof-from-stash');
    });

    it('throws INVALID_INPUT when profileId is missing', () => {
        const ctx = baseCtx({ args: {}, stash: {} });

        assert.throws(() => request(ctx), /INVALID_INPUT: profileId is required/);
    });
});

describe('fetch_profile_fn request (step 2: branch on isOwner)', () => {
    it('issues a no-op GetItem when the owner was confirmed in step 1', () => {
        const ctx = baseCtx({ stash: { isOwner: true } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'NOOP',
            profileId: 'NOOP'
        });
    });

    it('issues the profileId-index GSI Query when the caller is a non-owner', () => {
        const ctx = baseCtx({ stash: { isOwner: false } });
        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#prof-456'
        });
    });
});

describe('fetch_profile_fn response (step 1)', () => {
    it('confirms ownership when the consistent GetItem returns an item under the caller key', () => {
        const ownerItem = {
            profileId: 'PROFILE#prof-456',
            ownerAccountId: 'ACCOUNT#user-123',
            sellerName: 'Alice'
        };
        const ctx = baseCtx({ result: ownerItem });

        const result = response(ctx);

        assert.deepStrictEqual(result, ownerItem);
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(ctx.stash.profile, ownerItem);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#user-123');
        assert.strictEqual(ctx.stash.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('treats a null result as non-owner and moves to the GSI step', () => {
        const ctx = baseCtx({ result: null });

        const result = response(ctx);

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.profile, undefined);
    });
});

describe('fetch_profile_fn response (step 2)', () => {
    it('passes the confirmed profile through for the owner path', () => {
        const ownerItem = {
            profileId: 'PROFILE#prof-456',
            ownerAccountId: 'ACCOUNT#user-123',
            sellerName: 'Alice'
        };
        const ctx = baseCtx({
            stash: { isOwner: true, profile: ownerItem },
            result: { ownerAccountId: 'NOOP', profileId: 'NOOP' }
        });

        const result = response(ctx);

        assert.deepStrictEqual(result, ownerItem);
    });

    it('stores the profile and flags non-owner from the GSI Query items for the share step', () => {
        const gsiProfile = {
            profileId: 'PROFILE#prof-456',
            ownerAccountId: 'ACCOUNT#bob',
            sellerName: 'Bob'
        };
        const ctx = baseCtx({
            stash: { isOwner: false },
            result: { items: [gsiProfile] }
        });

        const result = response(ctx);

        assert.deepStrictEqual(result, gsiProfile);
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.deepStrictEqual(ctx.stash.profile, gsiProfile);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#bob');
        assert.strictEqual(ctx.stash.ownerAccountId, 'ACCOUNT#bob');
    });

    it('raises NOT_FOUND when the GSI Query returns no items', () => {
        const ctx = baseCtx({
            stash: { isOwner: false },
            result: { items: [] }
        });

        assert.throws(() => response(ctx), /NOT_FOUND: Profile not found/);
    });
});

describe('fetch_profile_fn response (cross-cutting)', () => {
    it('propagates a data-source error', () => {
        const ctx = baseCtx({
            error: { message: 'DynamoDB error', type: 'DynamoDB:InternalServerError' }
        });

        assert.throws(() => response(ctx), /DynamoDB:InternalServerError: DynamoDB error/);
    });
});
