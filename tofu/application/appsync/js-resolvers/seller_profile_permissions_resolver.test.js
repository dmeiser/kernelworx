import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './seller_profile_permissions_resolver.js';

describe('seller_profile_permissions_resolver request', () => {
    it('sets stash.isOwner and returns NOOP GetItem when caller owns profile with clean ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'owner-1' },
            source: { ownerAccountId: 'owner-1', profileId: 'p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'NOOP',
            targetAccountId: 'NOOP',
        });
    });

    it('sets stash.isOwner and returns NOOP GetItem when caller matches prefixed ownerAccountId', () => {
        const ctx = {
            identity: { sub: 'owner-1' },
            source: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            profileId: 'NOOP',
            targetAccountId: 'NOOP',
        });
    });

    it('queries shares table with consistent read when caller is not owner', () => {
        const ctx = {
            identity: { sub: 'collaborator-1' },
            source: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'p-1' },
            stash: {},
        };
        const result = request(ctx);
        assert.strictEqual(ctx.stash.isOwner, undefined);
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
