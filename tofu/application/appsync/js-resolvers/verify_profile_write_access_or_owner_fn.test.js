import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_profile_write_access_or_owner_fn.js';

describe('verify_profile_write_access_or_owner_fn request', () => {
    it('queries the profileId-index GSI with a prefixed profileId', () => {
        const ctx = { args: { profileId: 'prof-1' }, stash: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#prof-1');
    });

    it('skips the query and denies when profileId is missing', () => {
        const ctx = { args: { profileId: undefined }, stash: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.skipGetItem, true);
    });
});

describe('verify_profile_write_access_or_owner_fn response', () => {
    it('grants write permission when caller is the owner', () => {
        const profile = { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#user-123' };
        const ctx = {
            identity: { sub: 'user-123' },
            stash: {},
            result: { items: [profile] }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.strictEqual(ctx.stash.hasWritePermission, true);
    });

    it('stashes the profile owner for the downstream stale-share check when not owner (#432)', () => {
        const profile = { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' };
        const ctx = {
            identity: { sub: 'user-123' },
            args: { profileId: 'PROFILE#prof-1' },
            stash: { profileId: 'PROFILE#prof-1' },
            result: { items: [profile] }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, profile);
        assert.strictEqual(ctx.stash.isOwner, false);
        // The current owner is stashed so check_write_permission_fn can reject
        // stale shares whose ownerAccountId no longer matches.
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#owner-1');
    });

    // The unprefixed non-owner branch is the only behavior #534 changed here:
    // before it, a bare profileId never reached check_write_permission_fn, so a
    // caller with a valid WRITE share was denied. Pin both halves of the hand-off.
    it('carries a BARE profileId through to the share check for a non-owner', () => {
        const profile = { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' };
        const ctx = {
            identity: { sub: 'user-123' },
            args: { profileId: 'prof-1' },
            stash: {},
            result: { items: [profile] }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, profile);
        assert.strictEqual(ctx.stash.isOwner, false);
        // Ownership is not granted - the grant still has to come from the share.
        assert.strictEqual(ctx.stash.hasWritePermission, undefined);
        // Normalized on the way to check_write_permission_fn...
        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-1');
        // ...and the share check must not be skipped.
        assert.strictEqual(ctx.stash.skipGetItem, undefined);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#owner-1');
    });

    it('leaves an already-prefixed profileId untouched on the way to the share check', () => {
        const profile = { profileId: 'PROFILE#prof-1', ownerAccountId: 'ACCOUNT#owner-1' };
        const ctx = {
            identity: { sub: 'user-123' },
            args: { profileId: 'PROFILE#prof-1' },
            stash: {},
            result: { items: [profile] }
        };

        response(ctx);

        assert.strictEqual(ctx.stash.profileId, 'PROFILE#prof-1');
        assert.strictEqual(ctx.stash.skipGetItem, undefined);
    });

    it('denies when the profile is not found', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { profileId: 'PROFILE#prof-1' },
            result: { items: [] }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.hasWritePermission, false);
    });

    it('denies when a DynamoDB error occurs', () => {
        const ctx = {
            identity: { sub: 'user-123' },
            stash: { profileId: 'PROFILE#prof-1' },
            error: { message: 'DynamoDB error', type: 'DynamoDBException' }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: false });
        assert.strictEqual(ctx.stash.isOwner, false);
    });
});
