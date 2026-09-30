import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './query_invites_fn.js';

// The schema documents listInvitesByProfile as owner-only. These tests pin
// that contract: a caller whose write access comes from a share is authorized
// upstream by check_write_permission_fn, but must still receive nothing here.
const WRITE_COLLABORATOR_STASH = {
    isOwner: false,
    hasWritePermission: true,
    profileId: 'PROFILE#prof-1'
};

function ownerStash(overrides = {}) {
    return { isOwner: true, hasWritePermission: true, profileId: 'PROFILE#prof-1', ...overrides };
}

describe('query_invites_fn request', () => {
    it('issues a no-op query that cannot match a profile for a WRITE collaborator', () => {
        const ctx = { args: { profileId: 'prof-1' }, stash: WRITE_COLLABORATOR_STASH };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'NOOP');
    });

    it('issues a no-op query for a caller with no share at all', () => {
        const ctx = { args: { profileId: 'prof-1' }, stash: { isOwner: false } };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':profileId'], 'NOOP');
    });

    it('queries the owner\'s profile with the PROFILE# prefix', () => {
        const ctx = { args: { profileId: 'prof-1' }, stash: ownerStash() };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#prof-1');
        assert.strictEqual(result.scanIndexForward, false);
    });

    it('does not double-prefix an already-prefixed profileId', () => {
        const ctx = { args: { profileId: 'PROFILE#prof-1' }, stash: ownerStash() };

        const result = request(ctx);

        assert.strictEqual(result.query.expressionValues[':profileId'], 'PROFILE#prof-1');
    });
});

describe('query_invites_fn response', () => {
    it('returns nothing for a WRITE collaborator even when items were read', () => {
        const ctx = {
            stash: WRITE_COLLABORATOR_STASH,
            result: { items: [{ inviteCode: 'CODE-1', profileId: 'PROFILE#prof-1', permissions: ['WRITE'] }] }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('throws when ctx.error is present', () => {
        const ctx = {
            stash: ownerStash(),
            error: { message: 'DynamoDB error', type: 'DynamoDBException' }
        };

        assert.throws(() => response(ctx), /DynamoDBException: DynamoDB error/);
    });

    it('maps invite fields for the owner and maps createdBy to createdByAccountId', () => {
        const ctx = {
            stash: ownerStash(),
            result: {
                items: [{
                    inviteCode: 'CODE-1',
                    profileId: 'PROFILE#prof-1',
                    permissions: ['WRITE'],
                    expiresAt: 1804067200,
                    createdAt: '2024-01-01T00:00:00Z',
                    createdBy: 'ACCOUNT#owner-1'
                }]
            }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, [{
            inviteCode: 'CODE-1',
            profileId: 'PROFILE#prof-1',
            permissions: ['WRITE'],
            expiresAt: new Date(1804067200 * 1000).toISOString(),
            createdAt: '2024-01-01T00:00:00Z',
            createdByAccountId: 'ACCOUNT#owner-1'
        }]);
    });

    it('filters expired and already-used invites for the owner', () => {
        const ctx = {
            stash: ownerStash(),
            result: {
                items: [
                    { inviteCode: 'EXPIRED', expiresAt: 1604067200 },
                    { inviteCode: 'USED', used: true },
                    { inviteCode: 'USED-AT', usedAt: '2024-01-01T00:00:00Z' }
                ]
            }
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('returns an empty array for an empty result set', () => {
        const ctx = { stash: ownerStash(), result: { items: [] } };

        assert.deepStrictEqual(response(ctx), []);
    });
});
