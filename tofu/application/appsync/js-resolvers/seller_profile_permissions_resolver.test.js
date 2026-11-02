import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './seller_profile_permissions_resolver.js';

describe('seller_profile_permissions_resolver request', () => {
    it('returns runtime.earlyReturn with permissions when already resolved upstream', () => {
        const ctx = {
            identity: { sub: 'user-1' },
            source: {
                permissions: ['READ', 'WRITE'],
                ownerAccountId: 'owner-1',
                profileId: 'p-1',
            },
        };
        const result = request(ctx);
        assert.deepStrictEqual(result, ['READ', 'WRITE']);
        assert.strictEqual(result.operation, undefined);
    });

    it('returns runtime.earlyReturn with [READ, WRITE] without datastore call when caller owns profile with clean ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'owner-1' },
            source: { ownerAccountId: 'owner-1', profileId: 'p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(result, ['READ', 'WRITE']);
        assert.strictEqual(result.operation, undefined);
    });

    it('returns runtime.earlyReturn with [READ, WRITE] without datastore call when caller matches prefixed ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'owner-1' },
            source: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.deepStrictEqual(result, ['READ', 'WRITE']);
        assert.strictEqual(result.operation, undefined);
    });

    it('queries shares table with consistent read when caller is not owner', () => {
        const ctx = {
            identity: { sub: 'collaborator-1' },
            source: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.isOwner, undefined);
        assert.strictEqual(ctx.stash.ownerAccountId, 'ACCOUNT#owner-1');
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p-1',
            targetAccountId: 'ACCOUNT#collaborator-1',
        });
    });

    it('preserves already-prefixed identifiers for share lookup', () => {
        const ctx = {
            identity: { sub: 'ACCOUNT#collaborator-1' },
            source: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.deepStrictEqual(result.key, {
            profileId: 'PROFILE#p-1',
            targetAccountId: 'ACCOUNT#collaborator-1',
        });
    });
});

describe('seller_profile_permissions_resolver response', () => {
    it('returns [READ, WRITE] when caller is owner', () => {
        const ctx = {
            stash: { isOwner: true },
        };
        assert.deepStrictEqual(response(ctx), ['READ', 'WRITE']);
    });

    it('fails closed and throws when DynamoDB error is present (#553)', () => {
        const ctx = {
            stash: { isOwner: false },
            error: { message: 'Throttled', type: 'DynamoDB:ProvisionedThroughputExceededException' },
        };
        assert.throws(
            () => response(ctx),
            /DynamoDB:ProvisionedThroughputExceededException: Throttled/
        );
    });

    it('returns null when no share is found or result is null', () => {
        const ctx = {
            stash: { isOwner: false },
            result: null,
        };
        assert.strictEqual(response(ctx), null);
    });

    it('returns null when share result has no profileId', () => {
        const ctx = {
            stash: { isOwner: false },
            result: { targetAccountId: 'ACCOUNT#u1' },
        };
        assert.strictEqual(response(ctx), null);
    });

    it('returns empty array for a STALE share whose ownerAccountId no longer matches the profile owner (#432)', () => {
        const ctx = {
            source: { ownerAccountId: 'ACCOUNT#new-owner' },
            result: {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#old-owner',
                permissions: ['READ'],
            },
        };
        assert.deepStrictEqual(response(ctx), []);
    });

    it('returns empty array for a STALE share when ownerAccountId differs in prefix style (#432)', () => {
        const ctx = {
            source: { ownerAccountId: 'new-owner' },
            result: {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#old-owner',
                permissions: ['WRITE'],
            },
        };
        assert.deepStrictEqual(response(ctx), []);
    });

    it('accepts share when share ownerAccountId matches profile owner with different prefix style (#432)', () => {
        const ctx = {
            source: { ownerAccountId: 'owner-1' },
            result: {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#owner-1',
                permissions: ['READ'],
            },
        };
        assert.deepStrictEqual(response(ctx), ['READ']);
    });

    it('accepts legacy share without ownerAccountId (#432 back-compat)', () => {
        const ctx = {
            source: { ownerAccountId: 'ACCOUNT#new-owner' },
            result: {
                profileId: 'PROFILE#p1',
                permissions: ['READ'],
            },
        };
        assert.deepStrictEqual(response(ctx), ['READ']);
    });

    it('reads ownerAccountId from stash when source is absent for stale share check (#432)', () => {
        const ctx = {
            stash: { ownerAccountId: 'ACCOUNT#new-owner' },
            result: {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#old-owner',
                permissions: ['READ'],
            },
        };
        assert.deepStrictEqual(response(ctx), []);
    });

    it('returns permissions array when valid share is found', () => {
        const ctx = {
            stash: { isOwner: false },
            result: {
                profileId: 'PROFILE#p1',
                permissions: ['READ'],
            },
        };
        assert.deepStrictEqual(response(ctx), ['READ']);
    });

    it('returns null when share permissions is not an array', () => {
        const ctx = {
            stash: { isOwner: false },
            result: {
                profileId: 'PROFILE#p1',
                permissions: 'READ',
            },
        };
        assert.strictEqual(response(ctx), null);
    });
});
