import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './batch_get_shared_profiles_fn.js';

const TABLE = '${table_name}';

function stashWithShares(shares) {
    const sharesByProfile = {};
    const sharedProfileIds = [];
    for (const share of shares) {
        sharesByProfile[share.profileId] = share;
        sharedProfileIds.push(share.profileId);
    }
    return { sharesByProfile, sharedProfileIds };
}

describe('batch_get_shared_profiles_fn request', () => {
    it('builds a BatchGetItem request from stashed shares', () => {
        const ctx = {
            stash: stashWithShares([
                { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#owner-1', permissions: ['READ'] },
                { profileId: 'PROFILE#p2', ownerAccountId: 'ACCOUNT#owner-2', permissions: ['WRITE'] },
            ]),
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'BatchGetItem');
        assert.deepStrictEqual(Object.keys(result.tables), [TABLE]);
        assert.strictEqual(result.tables[TABLE].consistentRead, true);
        assert.deepStrictEqual(result.tables[TABLE].keys, [
            { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' },
            { ownerAccountId: 'ACCOUNT#owner-2', profileId: 'PROFILE#p2' },
        ]);
    });

    it('returns an early empty array when there are no shares', () => {
        const ctx = { stash: stashWithShares([]) };

        const result = request(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('caps the batch at 100 keys', () => {
        const shares = [];
        for (let i = 0; i < 105; i++) {
            shares.push({
                profileId: `PROFILE#p${i}`,
                ownerAccountId: 'ACCOUNT#owner-1',
                permissions: ['READ'],
            });
        }
        const ctx = { stash: stashWithShares(shares) };

        const result = request(ctx);

        assert.strictEqual(result.tables[TABLE].keys.length, 100);
    });
});

describe('batch_get_shared_profiles_fn response', () => {
    const STASH = stashWithShares([
        { profileId: 'PROFILE#p1', ownerAccountId: 'ACCOUNT#owner-1', permissions: ['READ'] },
        { profileId: 'PROFILE#p2', ownerAccountId: 'ACCOUNT#owner-2', permissions: ['READ', 'WRITE'] },
    ]);

    it('merges profiles with shares into the SharedProfile response shape', () => {
        const profiles = [
            {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#owner-1',
                sellerName: 'Alice',
                unitType: 'Kernel',
                unitNumber: 7,
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-02-01T00:00:00Z',
            },
            {
                profileId: 'PROFILE#p2',
                ownerAccountId: 'ACCOUNT#owner-2',
                sellerName: 'Bob',
                createdAt: '2024-01-05T00:00:00Z',
                updatedAt: '2024-02-05T00:00:00Z',
            },
        ];
        const ctx = { identity: { sub: 'user-123' }, stash: STASH, result: { data: { [TABLE]: profiles } } };

        const result = response(ctx);

        assert.deepStrictEqual(result, [
            {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#owner-1',
                sellerName: 'Alice',
                unitType: 'Kernel',
                unitNumber: 7,
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-02-01T00:00:00Z',
                isOwner: false,
                permissions: ['READ'],
            },
            {
                profileId: 'PROFILE#p2',
                ownerAccountId: 'ACCOUNT#owner-2',
                sellerName: 'Bob',
                unitType: null,
                unitNumber: null,
                createdAt: '2024-01-05T00:00:00Z',
                updatedAt: '2024-02-05T00:00:00Z',
                isOwner: false,
                permissions: ['READ', 'WRITE'],
            },
        ]);
    });

    it('normalizes unprefixed ownerAccountId and detects ownership from raw stored value', () => {
        const profiles = [
            {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'owner-1',
                sellerName: 'Alice',
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-02-01T00:00:00Z',
            },
            {
                profileId: 'PROFILE#p2',
                ownerAccountId: 'ACCOUNT#owner-2',
                sellerName: 'Bob',
                createdAt: '2024-01-05T00:00:00Z',
                updatedAt: '2024-02-05T00:00:00Z',
            },
        ];
        // Caller is owner-2; isOwner compares the raw stored ownerAccountId
        // against the prefixed caller sub, exactly like the former Lambda.
        const ctx = {
            identity: { sub: 'owner-2' },
            stash: STASH,
            result: { data: { [TABLE]: profiles } },
        };

        const result = response(ctx);

        assert.strictEqual(result.length, 2);
        assert.strictEqual(result[0].ownerAccountId, 'ACCOUNT#owner-1');
        assert.strictEqual(result[0].isOwner, false);
        assert.strictEqual(result[1].ownerAccountId, 'ACCOUNT#owner-2');
        assert.strictEqual(result[1].isOwner, true);
    });

    it('returns results in share query order regardless of batch response order', () => {
        const profiles = [
            {
                profileId: 'PROFILE#p2',
                ownerAccountId: 'ACCOUNT#owner-2',
                sellerName: 'Bob',
                createdAt: '2024-01-05T00:00:00Z',
                updatedAt: '2024-02-05T00:00:00Z',
            },
            {
                profileId: 'PROFILE#p1',
                ownerAccountId: 'ACCOUNT#owner-1',
                sellerName: 'Alice',
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-02-01T00:00:00Z',
            },
        ];
        const ctx = { identity: { sub: 'user-123' }, stash: STASH, result: { data: { [TABLE]: profiles } } };

        const result = response(ctx);

        assert.deepStrictEqual(result.map((r) => r.profileId), ['PROFILE#p1', 'PROFILE#p2']);
    });

    it('skips profiles missing required fields or not found in the batch', () => {
        const profiles = [
            { profileId: 'PROFILE#p1' }, // missing sellerName/createdAt/updatedAt
            {
                profileId: 'PROFILE#p-unknown',
                ownerAccountId: 'ACCOUNT#owner-9',
                sellerName: 'Ghost',
                createdAt: '2024-01-01T00:00:00Z',
                updatedAt: '2024-01-01T00:00:00Z',
            },
        ];
        const ctx = { identity: { sub: 'user-123' }, stash: STASH, result: { data: { [TABLE]: profiles } } };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('handles a missing batch table data gracefully', () => {
        const ctx = { identity: { sub: 'user-123' }, stash: STASH, result: {} };

        const result = response(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('throws error when ctx.error is present', () => {
        const ctx = {
            error: { message: 'DynamoDB error', type: 'InternalServerError' },
            stash: STASH,
        };

        assert.throws(() => response(ctx), /InternalServerError: DynamoDB error/);
    });
});
