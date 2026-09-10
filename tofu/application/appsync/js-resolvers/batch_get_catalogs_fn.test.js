import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './batch_get_catalogs_fn.js';

// The raw source keeps the Terraform templatefile() placeholder; in tests
// the table name stays the literal '${table_name}' string. Since #362 the
// listCampaignsByProfile pipeline passes a CampaignConnection
// ({ campaigns, nextToken }) between functions; the SharedCampaign variant
// (plain arrays) and the pure mapping helpers are covered in
// batch_get_shared_campaign_catalogs_fn.test.js and lib/batch_catalogs.test.js.
const TABLE = '${table_name}';

describe('batch_get_catalogs_fn request', () => {
    it('issues a single BatchGetItem with de-duplicated keys for one page', () => {
        const ctx = {
            prev: {
                result: {
                    campaigns: [
                        { campaignId: 'C1', catalogId: 'CAT-A' },
                        { campaignId: 'C2', catalogId: 'CAT-B' },
                        { campaignId: 'C3', catalogId: 'CAT-A' },
                    ],
                    nextToken: 'token-1',
                },
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'BatchGetItem');
        assert.deepStrictEqual(result.tables[TABLE].keys, [
            { catalogId: 'CAT-A' },
            { catalogId: 'CAT-B' },
        ]);
    });

    it('skips the DynamoDB call when the page has no catalogIds', () => {
        const connection = { campaigns: [{ campaignId: 'C1' }, { campaignId: 'C2' }], nextToken: null };
        const ctx = { prev: { result: connection } };

        const result = request(ctx);

        assert.strictEqual(result.operation, undefined);
        assert.deepStrictEqual(result, connection);
    });

    it('returns early for an empty connection', () => {
        const ctx = { prev: { result: { campaigns: [], nextToken: null } } };

        const result = request(ctx);

        assert.deepStrictEqual(result, { campaigns: [], nextToken: null });
    });

    it('errors when more than 100 unique catalogs are requested', () => {
        const campaigns = [];
        for (let i = 0; i < 101; i++) {
            campaigns.push({ campaignId: 'C' + i, catalogId: 'CAT-' + i });
        }
        const ctx = { prev: { result: { campaigns: campaigns, nextToken: null } } };

        assert.throws(() => request(ctx), /BadRequest: Too many catalogs to batch fetch \(101\)/);
    });
});

describe('batch_get_catalogs_fn response', () => {
    it('maps each campaign to its catalog and preserves nextToken', () => {
        const ctx = {
            prev: {
                result: {
                    campaigns: [
                        { campaignId: 'C1', catalogId: 'CAT-A' },
                        { campaignId: 'C2', catalogId: 'CAT-B' },
                    ],
                    nextToken: 'token-1',
                },
            },
            result: {
                data: {
                    [TABLE]: [
                        { catalogId: 'CAT-A', catalogName: 'Fall Sale' },
                        { catalogId: 'CAT-B', catalogName: 'Spring Sale' },
                    ],
                },
            },
        };

        assert.deepStrictEqual(response(ctx), {
            campaigns: [
                { campaignId: 'C1', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
                { campaignId: 'C2', catalogId: 'CAT-B', catalog: { catalogId: 'CAT-B', catalogName: 'Spring Sale' } },
            ],
            nextToken: 'token-1',
        });
    });

    it('maps missing catalogIds to null', () => {
        const ctx = {
            prev: { result: { campaigns: [{ campaignId: 'C1', catalogId: 'CAT-MISSING' }], nextToken: null } },
            result: { data: { [TABLE]: [] } },
        };

        assert.deepStrictEqual(response(ctx), {
            campaigns: [{ campaignId: 'C1', catalogId: 'CAT-MISSING', catalog: null }],
            nextToken: null,
        });
    });

    it('errors on unprocessed keys', () => {
        const ctx = {
            prev: { result: { campaigns: [{ campaignId: 'C1', catalogId: 'CAT-A' }], nextToken: null } },
            result: {
                data: { [TABLE]: [] },
                unprocessedKeys: { [TABLE]: [{ catalogId: 'CAT-A' }] },
            },
        };

        assert.throws(() => response(ctx), /InternalError: Failed to fetch 1 catalog\(s\)/);
    });

    it('propagates resolver errors', () => {
        const ctx = {
            prev: { result: { campaigns: [], nextToken: null } },
            error: { message: 'boom', type: 'DynamoDB:ProvisionedThroughputExceededException' },
        };

        assert.throws(() => response(ctx), /DynamoDB:ProvisionedThroughputExceededException: boom/);
    });
});
