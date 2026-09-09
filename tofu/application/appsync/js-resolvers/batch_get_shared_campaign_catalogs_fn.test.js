import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './batch_get_shared_campaign_catalogs_fn.js';

// The raw source keeps the Terraform templatefile() placeholder; in tests
// the table name stays the literal '${table_name}' string. The shared
// variant maps soft-deleted catalogs to null (treatDeletedAsNull = true);
// the Campaign variant and the pure mapping helpers are covered in
// batch_get_catalogs_fn.test.js and lib/batch_catalogs.test.js.
const TABLE = '${table_name}';

describe('batch_get_shared_campaign_catalogs_fn request', () => {
    it('issues a single BatchGetItem with de-duplicated keys', () => {
        const ctx = {
            prev: {
                result: [
                    { sharedCampaignCode: 'SC1', catalogId: 'CAT-A' },
                    { sharedCampaignCode: 'SC2', catalogId: 'CAT-B' },
                    { sharedCampaignCode: 'SC3', catalogId: 'CAT-A' },
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
        const campaigns = [{ sharedCampaignCode: 'SC1' }];
        const ctx = { prev: { result: campaigns } };

        const result = request(ctx);

        assert.strictEqual(result.operation, undefined);
        assert.deepStrictEqual(result, campaigns);
    });
});

describe('batch_get_shared_campaign_catalogs_fn response', () => {
    it('maps soft-deleted catalogs to null (shared VTL contract)', () => {
        const ctx = {
            prev: { result: [{ sharedCampaignCode: 'SC1', catalogId: 'CAT-DELETED' }] },
            result: {
                data: {
                    [TABLE]: [{ catalogId: 'CAT-DELETED', isDeleted: true }],
                },
            },
        };

        assert.deepStrictEqual(response(ctx), [
            { sharedCampaignCode: 'SC1', catalogId: 'CAT-DELETED', catalog: null },
        ]);
    });

    it('maps active catalogs normally and missing catalogIds to null', () => {
        const ctx = {
            prev: {
                result: [
                    { sharedCampaignCode: 'SC1', catalogId: 'CAT-A' },
                    { sharedCampaignCode: 'SC2', catalogId: 'CAT-MISSING' },
                ],
            },
            result: {
                data: {
                    [TABLE]: [{ catalogId: 'CAT-A', catalogName: 'Fall Sale' }],
                },
            },
        };

        assert.deepStrictEqual(response(ctx), [
            { sharedCampaignCode: 'SC1', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
            { sharedCampaignCode: 'SC2', catalogId: 'CAT-MISSING', catalog: null },
        ]);
    });
});
