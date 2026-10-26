import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './find_shared_campaigns_resolver.js';

describe('find_shared_campaigns_resolver request', () => {
    it('builds composite GSI2 unitCampaignKey query with string concatenation', () => {
        const ctx = {
            args: {
                unitType: 'Pack',
                unitNumber: 101,
                city: 'Austin',
                state: 'TX',
                campaignName: 'Popcorn 2024',
                campaignYear: 2024,
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'GSI2');
        assert.strictEqual(result.query.expression, 'unitCampaignKey = :unitCampaignKey');
        assert.strictEqual(
            result.query.expressionValues[':unitCampaignKey'],
            'Pack#101#Austin#TX#Popcorn 2024#2024'
        );
    });
});

describe('find_shared_campaigns_resolver response', () => {
    it('returns active shared campaigns and filters out inactive ones', () => {
        const ctx = {
            result: {
                items: [
                    { sharedCampaignCode: 'SHARE-1', isActive: true },
                    { sharedCampaignCode: 'SHARE-2', isActive: false },
                    { sharedCampaignCode: 'SHARE-3', isActive: true },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.length, 2);
        assert.strictEqual(result[0].sharedCampaignCode, 'SHARE-1');
        assert.strictEqual(result[1].sharedCampaignCode, 'SHARE-3');
    });

    it('defaults null or undefined isActive to true and includes them in result', () => {
        const ctx = {
            result: {
                items: [
                    { sharedCampaignCode: 'SHARE-NULL', isActive: null },
                    { sharedCampaignCode: 'SHARE-UNDEF' },
                    { sharedCampaignCode: 'SHARE-FALSE', isActive: false },
                ],
            },
        };

        const result = response(ctx);

        assert.strictEqual(result.length, 2);
        assert.strictEqual(result[0].sharedCampaignCode, 'SHARE-NULL');
        assert.strictEqual(result[0].isActive, true);
        assert.strictEqual(result[1].sharedCampaignCode, 'SHARE-UNDEF');
        assert.strictEqual(result[1].isActive, true);
    });

    it('returns empty array when items is empty or undefined', () => {
        assert.deepStrictEqual(response({ result: { items: [] } }), []);
        assert.deepStrictEqual(response({ result: {} }), []);
    });

    it('throws propagated error when ctx.error is present', () => {
        const ctx = {
            error: { message: 'GSI2 query throttled', type: 'INTERNAL_ERROR' },
        };

        assert.throws(
            () => response(ctx),
            /INTERNAL_ERROR: GSI2 query throttled/
        );
    });
});
