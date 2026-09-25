import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './verify_profile_write_access_fn.js';

describe('verify_profile_write_access_fn request', () => {
    it('throws clean INVALID_INPUT error without leaking stash keys when profileId is missing', () => {
        const errorLogs = [];
        const originalConsoleError = console.error;
        console.error = (...args) => {
            errorLogs.push(args.join(' '));
        };

        const ctx = {
            info: { fieldName: 'updateOrder' },
            args: { input: {} },
            stash: {
                order: {
                    campaignId: 'CAMPAIGN#c1',
                    orderId: 'ORDER#o1',
                },
                campaign: {
                    campaignId: 'CAMPAIGN#c1',
                },
            },
        };

        try {
            assert.throws(
                () => request(ctx),
                (err) => {
                    assert.strictEqual(err.message, 'INVALID_INPUT: Profile ID is required');
                    // Must not leak internal stash keys or pipeline structure to the client-facing error
                    assert.ok(!err.message.includes('orderKeys'), 'must not contain orderKeys');
                    assert.ok(!err.message.includes('hasInput'), 'must not contain hasInput');
                    assert.ok(!err.message.includes('hasOrder'), 'must not contain hasOrder');
                    assert.ok(!err.message.includes('hasCampaign'), 'must not contain hasCampaign');
                    assert.ok(!err.message.includes('debugging:'), 'must not contain debugging');
                    assert.ok(!err.message.includes('{'), 'must not contain json structure');
                    assert.ok(!err.message.includes('stash'), 'must not contain stash reference');
                    return true;
                }
            );

            // Verify diagnostic details were logged server-side only
            assert.strictEqual(errorLogs.length, 1);
            assert.ok(errorLogs[0].includes('Profile ID not found in request or stash'));
            assert.ok(errorLogs[0].includes('hasInput'));
            assert.ok(errorLogs[0].includes('hasOrder'));
            assert.ok(errorLogs[0].includes('orderKeys'));
        } finally {
            console.error = originalConsoleError;
        }
    });

    it('extracts profileId from args.input.profileId and prefixes with PROFILE#', () => {
        const ctx = {
            info: { fieldName: 'createOrder' },
            args: { input: { profileId: 'p123' } },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'profileId-index');
        assert.strictEqual(result.query.expression, 'profileId = :profileId');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#p123',
        });
    });

    it('preserves existing PROFILE# prefix in args.input.profileId', () => {
        const ctx = {
            info: { fieldName: 'createOrder' },
            args: { input: { profileId: 'PROFILE#p123' } },
            stash: {},
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#p123',
        });
    });

    it('extracts profileId from stash.order.profileId', () => {
        const ctx = {
            info: { fieldName: 'updateOrder' },
            args: {},
            stash: {
                order: { profileId: 'prof-order' },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#prof-order',
        });
    });

    it('extracts profileId from stash.campaign.profileId', () => {
        const ctx = {
            info: { fieldName: 'updateCampaign' },
            args: {},
            stash: {
                campaign: { profileId: 'PROFILE#prof-camp' },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.deepStrictEqual(result.query.expressionValues, {
            ':profileId': 'PROFILE#prof-camp',
        });
    });

    it('idempotent deleteOrder skips auth when order is null in stash', () => {
        const ctx = {
            info: { fieldName: 'deleteOrder' },
            stash: { order: null },
        };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.skipAuth, true);
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'NOOP',
            profileId: 'NOOP',
        });
    });

    it('idempotent deleteCampaign skips auth when campaign is null in stash', () => {
        const ctx = {
            info: { fieldName: 'deleteCampaign' },
            stash: { campaign: null },
        };

        const result = request(ctx);

        assert.strictEqual(ctx.stash.skipAuth, true);
        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, {
            ownerAccountId: 'NOOP',
            profileId: 'NOOP',
        });
    });
});

describe('verify_profile_write_access_fn response', () => {
    it('returns authorized: true when skipAuth is set for idempotent delete', () => {
        const ctx = {
            stash: { skipAuth: true },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, { authorized: true });
    });

    it('propagates ctx.error', () => {
        const ctx = {
            stash: {},
            error: { message: 'DynamoDB failure', type: 'DynamoDBException' },
        };

        assert.throws(
            () => response(ctx),
            /DynamoDBException: DynamoDB failure/
        );
    });

    it('throws NOT_FOUND when profile is not found', () => {
        const ctx = {
            stash: {},
            result: { items: [] },
        };

        assert.throws(
            () => response(ctx),
            /NOT_FOUND: Profile not found/
        );
    });

    it('authorizes caller and marks isOwner = true when caller is profile owner', () => {
        const profile = {
            profileId: 'PROFILE#p1',
            ownerAccountId: 'ACCOUNT#user-123',
        };
        const ctx = {
            identity: { sub: 'user-123' },
            stash: {},
            result: { items: [profile] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, profile);
        assert.strictEqual(ctx.stash.isOwner, true);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#user-123');
        assert.deepStrictEqual(ctx.stash.profile, profile);
    });

    it('marks isOwner = false when caller is not the owner', () => {
        const profile = {
            profileId: 'PROFILE#p1',
            ownerAccountId: 'ACCOUNT#other-user',
        };
        const ctx = {
            identity: { sub: 'user-123' },
            stash: {},
            result: { items: [profile] },
        };

        const result = response(ctx);

        assert.deepStrictEqual(result, profile);
        assert.strictEqual(ctx.stash.isOwner, false);
        assert.strictEqual(ctx.stash.profileOwner, 'ACCOUNT#other-user');
        assert.deepStrictEqual(ctx.stash.profile, profile);
    });
});
