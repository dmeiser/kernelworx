import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './batch_latest_campaigns_fn.js';

// The source is templatefile()'d at deploy time; in tests the placeholder
// stays literal, so BatchGetItem results are keyed by it.
const TABLE = '${campaigns_table_name}';

function profile(overrides) {
    return {
        profileId: 'PROFILE#p1',
        sellerName: 'Troop 1',
        ...overrides,
    };
}

describe('batch_latest_campaigns_fn request', () => {
    it('builds one BatchGetItem with a key per profile carrying latestCampaignId', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [
                        profile({ profileId: 'PROFILE#a', latestCampaignId: 'CAMPAIGN#1' }),
                        profile({ profileId: 'PROFILE#b', latestCampaignId: 'CAMPAIGN#2' }),
                    ],
                    nextToken: null,
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'BatchGetItem');
        const keys = result.tables[TABLE].keys;
        assert.strictEqual(keys.length, 2);
        assert.deepStrictEqual(keys[0], { profileId: 'PROFILE#a', campaignId: 'CAMPAIGN#1' });
        assert.deepStrictEqual(keys[1], { profileId: 'PROFILE#b', campaignId: 'CAMPAIGN#2' });
    });

    it('adds the PROFILE# prefix when the profile id is unprefixed', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [profile({ profileId: 'bare-id', latestCampaignId: 'CAMPAIGN#1' })],
                },
            },
        };

        const keys = request(ctx).tables[TABLE].keys;
        assert.deepStrictEqual(keys[0], { profileId: 'PROFILE#bare-id', campaignId: 'CAMPAIGN#1' });
    });

    it('skips profiles without latestCampaignId and early-returns when none have it', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [profile({ profileId: 'PROFILE#old' }), profile({ profileId: 'PROFILE#bare' })],
                    nextToken: 'tok',
                },
            },
        };

        const result = request(ctx);
        assert.deepStrictEqual(result, ctx.prev.result);
    });

    it('early-returns the connection through when profiles is empty', () => {
        const ctx = { prev: { result: { profiles: [], nextToken: null } } };
        assert.deepStrictEqual(request(ctx), ctx.prev.result);
    });
});

describe('batch_latest_campaigns_fn response', () => {
    it('attaches fetched campaigns to their profiles in one pass', () => {
        const campaign1 = { profileId: 'PROFILE#a', campaignId: 'CAMPAIGN#1', campaignName: 'Fall', isActive: true };
        const campaign2 = { profileId: 'PROFILE#b', campaignId: 'CAMPAIGN#2', campaignName: 'Spring', isActive: true };
        const ctx = {
            prev: {
                result: {
                    profiles: [
                        profile({ profileId: 'PROFILE#a', latestCampaignId: 'CAMPAIGN#1' }),
                        profile({ profileId: 'PROFILE#b', latestCampaignId: 'CAMPAIGN#2' }),
                    ],
                    nextToken: 'tok',
                },
            },
            result: { data: { [TABLE]: [campaign1, campaign2] } },
        };

        const result = response(ctx);

        assert.strictEqual(result.nextToken, 'tok');
        assert.strictEqual(result.profiles[0].latestCampaign, campaign1);
        assert.strictEqual(result.profiles[1].latestCampaign, campaign2);
    });

    it('leaves profiles without latestCampaignId untouched for the field-resolver fallback', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [
                        profile({ profileId: 'PROFILE#old' }),
                        profile({ profileId: 'PROFILE#a', latestCampaignId: 'CAMPAIGN#1' }),
                    ],
                },
            },
            result: { data: { [TABLE]: [{ profileId: 'PROFILE#a', campaignId: 'CAMPAIGN#1', isActive: true }] } },
        };

        const result = response(ctx);

        assert.strictEqual(result.profiles[0].latestCampaign, undefined);
        assert.strictEqual('latestCampaignId' in result.profiles[0], false);
        assert.ok(result.profiles[1].latestCampaign);
    });

    it('treats a missing campaign from the batch result as a miss (field resolver re-checks)', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [profile({ latestCampaignId: 'CAMPAIGN#gone' })],
                },
            },
            result: { data: { [TABLE]: [] } },
        };

        const result = response(ctx);
        assert.strictEqual(result.profiles[0].latestCampaign, undefined);
    });

    it('treats an inactive fetched campaign as a miss', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [profile({ latestCampaignId: 'CAMPAIGN#off' })],
                },
            },
            result: {
                data: {
                    [TABLE]: [{ profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#off', isActive: false }],
                },
            },
        };

        const result = response(ctx);
        assert.strictEqual(result.profiles[0].latestCampaign, undefined);
    });

    it('defaults a missing isActive on a fetched campaign to true', () => {
        const ctx = {
            prev: {
                result: {
                    profiles: [profile({ latestCampaignId: 'CAMPAIGN#legacy' })],
                },
            },
            result: {
                data: {
                    [TABLE]: [{ profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#legacy' }],
                },
            },
        };

        const result = response(ctx);
        assert.strictEqual(result.profiles[0].latestCampaign.isActive, true);
    });

    it('throws on datasource error', () => {
        const ctx = {
            prev: { result: { profiles: [] } },
            error: { message: 'boom', type: 'InternalError' },
        };
        assert.throws(() => response(ctx), /InternalError: boom/);
    });
});
