import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_profile_read_access_fn.js';

// #508: verify_profile_read_access_fn.js backs TWO aws_appsync_function
// resources (verify_profile_read_access and verify_profile_read_access_step2)
// that run back-to-back in the four profile-scoped read pipelines, so ownership
// is decided in two phases exactly like the write path (#438) and fetch_profile
// (#545):
//
//   Step 1 - strongly consistent base-table GetItem under {ownerAccountId:
//            <caller>, profileId}: existence alone proves ownership.
//   Step 2 - the profileId-index GSI query, run only for non-owners, purely as
//            a locator so check_share_read_permissions_fn.js can read the share.
//
// The regression these tests guard: the pre-fix function issued the GSI query
// from step 1 and compared its ownerAccountId to the caller, so for as long as
// the index lagged after an ownership transfer it both let the FORMER owner read
// the new owner's campaigns/orders and refused the NEW owner with
// profileNotFound. Both halves are asserted below.

function baseCtx(extra = {}) {
    return {
        identity: { sub: 'user-123' },
        args: { profileId: 'prof-456' },
        stash: {},
        ...extra
    };
}

const noopGetItem = {
    operation: 'GetItem',
    key: { ownerAccountId: 'NOOP', profileId: 'NOOP' }
};

describe('verify_profile_read_access_fn request (step 1: owner GetItem)', () => {
    it('issues a strongly consistent base-table GetItem keyed on the caller account + profileId', () => {
        const result = request(baseCtx());

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'ACCOUNT#user-123',
            profileId: 'PROFILE#prof-456'
        });
        assert.strictEqual(result.consistentRead, true);
    });

    it('does not query the eventually-consistent profileId-index GSI in step 1 (#508)', () => {
        const result = request(baseCtx());

        assert.strictEqual(result.index, undefined);
        assert.strictEqual(result.operation, 'GetItem');
    });

    it('preserves an already-prefixed profileId', () => {
        const result = request(baseCtx({ args: { profileId: 'PROFILE#prof-456' } }));

        assert.strictEqual(result.key.profileId, 'PROFILE#prof-456');
        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('normalizes a sub that already carries the ACCOUNT# prefix', () => {
        const result = request(baseCtx({ identity: { sub: 'ACCOUNT#user-123' } }));

        assert.strictEqual(result.key.ownerAccountId, 'ACCOUNT#user-123');
    });

    it('derives profileId from stash.campaign when args are absent (getCampaign / listCampaignsByProfile)', () => {
        const result = request(baseCtx({
            args: {},
            stash: { campaign: { profileId: 'cmp-prof' } }
        }));

        assert.strictEqual(result.key.profileId, 'PROFILE#cmp-prof');
    });

    it('derives profileId from stash.profileId for orders (getOrder / listOrdersByCampaign)', () => {
        const result = request(baseCtx({
            args: {},
            stash: { profileId: 'ord-prof' }
        }));

        assert.strictEqual(result.key.profileId, 'PROFILE#ord-prof');
    });

    it('throws INVALID_INPUT when no profileId can be resolved', () => {
        assert.throws(() => request(baseCtx({ args: {}, stash: {} })), /INVALID_INPUT/);
    });

    it('short-circuits with a no-op read when the campaign was not found', () => {
        const ctx = baseCtx({ stash: { campaignNotFound: true } });

        assert.deepStrictEqual(request(ctx), noopGetItem);
    });

    it('short-circuits with a no-op read when the order was not found', () => {
        const ctx = baseCtx({ stash: { orderNotFound: true } });

        assert.deepStrictEqual(request(ctx), noopGetItem);
    });
});

describe('verify_profile_read_access_fn request (step 2: branch on isOwner)', () => {
    it('issues no live read when step 1 already proved the caller is the owner', () => {
        const result = request(baseCtx({ stash: { isOwner: true, profile: { profileId: 'PROFILE#prof-456' } } }));

        assert.deepStrictEqual(result, noopGetItem);
    });

    it('falls back to the GSI query only for a non-owner', () => {
        const result = request(baseCtx({ stash: { isOwner: false } }));

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.deepStrictEqual(result.query.expressionValues, { ':profileId': 'PROFILE#prof-456' });
    });

    it('keeps the campaignNotFound / orderNotFound skips ahead of the isOwner branches', () => {
        assert.deepStrictEqual(
            request(baseCtx({ stash: { isOwner: false, campaignNotFound: true } })),
            noopGetItem
        );
        assert.deepStrictEqual(
            request(baseCtx({ stash: { isOwner: false, orderNotFound: true } })),
            noopGetItem
        );
    });
});

describe('verify_profile_read_access_fn response (step 1)', () => {
    it('authorizes the caller from existence under their own partition key', () => {
        const ctx = baseCtx();
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#user-123' };

        const result = response({ ...ctx, result: profile });

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.strictEqual(ctx.stash.authorized, true);
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-456');
    });

    it('defers to the GSI locator step when the item is absent under the caller partition key', () => {
        const ctx = baseCtx();

        const result = response({ ...ctx, result: null });

        assert.strictEqual(result, null);
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.profile, undefined);
        assert.strictEqual(ctx.stash.profileNotFound, undefined);
    });

    it('propagates a datastore error', () => {
        const ctx = baseCtx();

        assert.throws(
            () => response({ ...ctx, result: null, error: { message: 'DynamoDB failure', type: 'DynamoDBException' } }),
            /DynamoDBException: DynamoDB failure/
        );
    });

    it('passes through with authorized=false when the campaign was not found', () => {
        const ctx = baseCtx({ stash: { campaignNotFound: true } });

        assert.deepStrictEqual(response({ ...ctx, result: null }), { authorized: false });
        assert.strictEqual(ctx.stash.authorized, false);
    });

    it('passes through with authorized=false when the order was not found', () => {
        const ctx = baseCtx({ stash: { orderNotFound: true } });

        assert.deepStrictEqual(response({ ...ctx, result: null }), { authorized: false });
        assert.strictEqual(ctx.stash.authorized, false);
    });
});

describe('verify_profile_read_access_fn response (step 2)', () => {
    it('returns the profile already confirmed by step 1 for the owner path', () => {
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#user-123' };
        const ctx = baseCtx({ stash: { isOwner: true, authorized: true, profile } });

        assert.deepStrictEqual(response({ ...ctx, result: null }), profile);
    });

    it('stashes the GSI-located profile for the share check without authorizing the caller', () => {
        const ctx = baseCtx({ stash: { isOwner: false } });
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#someone-else' };

        const result = response({ ...ctx, result: { items: [profile] } });

        assert.deepStrictEqual(result, profile);
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.profileNotFound, undefined);
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-456');
    });

    it('flags profileNotFound (not an error) when the GSI locator returns nothing', () => {
        const ctx = baseCtx({ stash: { isOwner: false } });

        const result = response({ ...ctx, result: { items: [] } });

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.profileNotFound, true);
        assert.strictEqual(ctx.stash.authorized, false);
    });
});

describe('verify_profile_read_access_fn end-to-end across an ownership transfer (#508)', () => {
    // Each test drives the pipeline the way AppSync does: request() then
    // response() per step, carrying one stash across both invocations.

    it('refuses the FORMER owner while the GSI still projects them (#508)', () => {
        const ctx = baseCtx({ identity: { sub: 'old-owner' } });
        // Step 1: strongly consistent GetItem under ACCOUNT#old-owner. After the
        // transfer the item lives under the new owner's partition, so nothing.
        request(ctx);
        response({ ...ctx, result: null });
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.authorized, undefined);

        // Step 2: the stale GSI row still says ACCOUNT#old-owner. It is used only
        // as a locator - the caller must NOT be re-authorized off it.
        const stale = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#old-owner' };
        const step2Request = request(ctx);
        assert.strictEqual(step2Request.operation, 'Query');

        const result = response({ ...ctx, result: { items: [stale] } });

        assert.strictEqual(ctx.stash.isOwner, false);
        assert.notStrictEqual(ctx.stash.authorized, true);
        assert.notStrictEqual(ctx.stash.profileNotFound, true);
        assert.deepStrictEqual(result, stale);
    });

    it('authorizes the NEW owner immediately, before the GSI catches up (#508)', () => {
        const ctx = baseCtx({ identity: { sub: 'new-owner' } });
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#new-owner' };

        const step1Request = request(ctx);
        assert.strictEqual(step1Request.consistentRead, true);

        const step1Result = response({ ...ctx, result: profile });
        assert.deepStrictEqual(step1Result, { authorized: true });
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.strictEqual(ctx.stash.profileNotFound, undefined);

        // Step 2 short-circuits: no GSI read for an already-confirmed owner.
        assert.deepStrictEqual(request(ctx), noopGetItem);
        assert.deepStrictEqual(response({ ...ctx, result: null }), profile);
    });

    it('keeps the shared-reader path working: non-owner located by the GSI is left to the share check', () => {
        const ctx = baseCtx({ identity: { sub: 'reader-9' } });
        const profile = { profileId: 'PROFILE#prof-456', ownerAccountId: 'ACCOUNT#owner-1' };

        request(ctx);
        response({ ...ctx, result: null });
        assert.strictEqual(ctx.stash.isOwner, false);

        const result = response({ ...ctx, result: { items: [profile] } });

        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.authorized, undefined);
        assert.deepStrictEqual(result, profile);
        // The share check downstream reads these two stashed values.
        assert.deepStrictEqual(ctx.stash.profile, profile);
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-456');
    });

    it('reports profileNotFound (empty/null result) for a caller with no share on a live profile', () => {
        const ctx = baseCtx({ identity: { sub: 'stranger-9' } });

        request(ctx);
        response({ ...ctx, result: null });
        const result = response({ ...ctx, result: { items: [] } });

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.profileNotFound, true);
        assert.strictEqual(ctx.stash.authorized, false);
    });
});