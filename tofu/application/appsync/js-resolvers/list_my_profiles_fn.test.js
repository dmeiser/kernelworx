import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_my_profiles_fn.js';

describe('list_my_profiles_fn request', () => {
    it('queries profiles by ownerAccountId with the default page size when no args are given', () => {
        const ctx = { identity: { sub: 'user-1' }, args: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'ownerAccountId = :accountId');
        assert.strictEqual(result.query.expressionValues[':accountId'].S, 'ACCOUNT#user-1');
        // Default page: 50 profiles -> worst case 1 + 5*50 = 251 resolver
        // invocations, safely under the 1000 resolver_count_limit (#328).
        assert.strictEqual(result.limit, 50);
        assert.strictEqual(result.nextToken, undefined);
    });

    it('falls back to the default page size for non-positive or non-numeric limits', () => {
        for (const limit of [0, -5, '10', null, Number.NaN]) {
            const ctx = { identity: { sub: 'user-1' }, args: { limit } };

            const result = request(ctx);

            assert.strictEqual(result.limit, 50, `limit ${String(limit)} should fall back to the default`);
        }
    });

    it('respects an explicit limit at or under the cap', () => {
        const ctx = { identity: { sub: 'user-1' }, args: { limit: 20, nextToken: 'tok-1' } };

        const result = request(ctx);

        assert.strictEqual(result.limit, 20);
        assert.strictEqual(result.nextToken, 'tok-1');
    });

    it('clamps an over-cap requested limit to the maximum page size', () => {
        const ctx = { identity: { sub: 'user-1' }, args: { limit: 5000 } };

        const result = request(ctx);

        // Cap: 100 profiles -> worst case 1 + 5*100 = 501 resolver
        // invocations, under the 1000 resolver_count_limit (#328).
        assert.strictEqual(result.limit, 100);
    });
});

describe('list_my_profiles_fn response', () => {
    it('wraps profiles in a connection and adds owner fields', () => {
        const ctx = {
            stash: {},
            result: {
                items: [{ profileId: 'PROFILE#p1', createdAt: '2024-01-01T00:00:00Z' }],
                nextToken: 'tok-1',
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.nextToken, 'tok-1');
        assert.strictEqual(result.profiles.length, 1);
        assert.strictEqual(result.profiles[0].profileId, 'PROFILE#p1');
        assert.strictEqual(result.profiles[0].isOwner, true);
        assert.deepStrictEqual(result.profiles[0].permissions, ['READ', 'WRITE']);
    });

    it('passes through unitType and unitNumber so owners can query their own unit details', () => {
        const ctx = {
            stash: {},
            result: {
                items: [
                    {
                        profileId: 'PROFILE#p1',
                        sellerName: 'Scout Name',
                        unitType: 'Troop',
                        unitNumber: 456,
                        createdAt: '2024-01-01T00:00:00Z',
                    },
                ],
                nextToken: null,
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.profiles.length, 1);
        assert.strictEqual(result.profiles[0].unitType, 'Troop');
        assert.strictEqual(result.profiles[0].unitNumber, 456);
    });

    it('passes through null unitType and unitNumber when profile has no unit details', () => {
        const ctx = {
            stash: {},
            result: {
                items: [{ profileId: 'PROFILE#p1', createdAt: '2024-01-01T00:00:00Z' }],
                nextToken: null,
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.profiles.length, 1);
        assert.strictEqual(result.profiles[0].unitType, undefined);
        assert.strictEqual(result.profiles[0].unitNumber, undefined);
    });

    it('filters out incomplete records and returns empty profiles', () => {
        const ctx = {
            stash: {},
            result: { items: [{ profileId: 'PROFILE#incomplete' }] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { profiles: [], nextToken: null });
    });
});
