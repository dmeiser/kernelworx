import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './batch_get_catalogs_fn.js';

// The raw source keeps the Terraform templatefile() placeholders; in tests
// the table name stays the literal '${table_name}' string and the deleted-
// catalog contract defaults to the Campaign variant (treat_deleted_as_null =
// "false"). The SharedCampaign variant is covered in lib/batch_catalogs.test.js.
const TABLE = '${table_name}';

describe('batch_get_catalogs_fn request', () => {
    it('issues a single BatchGetItem with de-duplicated keys', () => {
        const ctx = {
            prev: {
                result: [
                    { campaignId: 'C1', catalogId: 'CAT-A' },
                    { campaignId: 'C2', catalogId: 'CAT-B' },
                    { campaignId: 'C3', catalogId: 'CAT-A' },
                ],
            },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'BatchGetItem');
        assert.deepStrictEqual(result.tables[TABLE].keys, [
            { catalogId: 'CAT-A' },
            { catalogId: 'CAT-B' },
        ]);
    });

    it('skips the DynamoDB call when there are no catalogIds', () => {
        const campaigns = [{ campaignId: 'C1' }, { campaignId: 'C2' }];
        const ctx = { prev: { result: campaigns } };

        const result = request(ctx);

        assert.strictEqual(result.operation, undefined);
        assert.deepStrictEqual(result, campaigns);
    });

    it('returns early for an empty campaign list', () => {
        const ctx = { prev: { result: [] } };

        const result = request(ctx);

        assert.deepStrictEqual(result, []);
    });

    it('errors when more than 100 unique catalogs are requested', () => {
        const campaigns = [];
        for (let i = 0; i < 101; i++) {
            campaigns.push({ campaignId: 'C' + i, catalogId: 'CAT-' + i });
        }
        const ctx = { prev: { result: campaigns } };

        assert.throws(() => request(ctx), /BadRequest: Too many catalogs to batch fetch \(101\)/);
    });
});

describe('batch_get_catalogs_fn response', () => {
    it('maps each campaign to its catalog from the batch result', () => {
        const ctx = {
            prev: {
                result: [
                    { campaignId: 'C1', catalogId: 'CAT-A' },
                    { campaignId: 'C2', catalogId: 'CAT-B' },
                ],
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

        assert.deepStrictEqual(response(ctx), [
            { campaignId: 'C1', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
            { campaignId: 'C2', catalogId: 'CAT-B', catalog: { catalogId: 'CAT-B', catalogName: 'Spring Sale' } },
        ]);
    });

    it('maps missing catalogIds to null', () => {
        const ctx = {
            prev: { result: [{ campaignId: 'C1', catalogId: 'CAT-MISSING' }] },
            result: { data: { [TABLE]: [] } },
        };

        assert.deepStrictEqual(response(ctx), [
            { campaignId: 'C1', catalogId: 'CAT-MISSING', catalog: null },
        ]);
    });

    it('errors on unprocessed keys', () => {
        const ctx = {
            prev: { result: [{ campaignId: 'C1', catalogId: 'CAT-A' }] },
            result: {
                data: { [TABLE]: [] },
                unprocessedKeys: { [TABLE]: [{ catalogId: 'CAT-A' }] },
            },
        };

        assert.throws(() => response(ctx), /InternalError: Failed to fetch 1 catalog\(s\)/);
    });

    it('propagates resolver errors', () => {
        const ctx = {
            prev: { result: [] },
            error: { message: 'boom', type: 'DynamoDB:ProvisionedThroughputExceededException' },
        };

        assert.throws(() => response(ctx), /DynamoDB:ProvisionedThroughputExceededException: boom/);
    });
});
