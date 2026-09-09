import { describe, it } from 'node:test';
import assert from 'node:assert';
import { extractUniqueCatalogIds, attachCatalogs } from './batch_catalogs.js';

describe('extractUniqueCatalogIds', () => {
    it('collects catalogIds in first-seen order', () => {
        const campaigns = [
            { campaignId: 'C1', catalogId: 'CAT-A' },
            { campaignId: 'C2', catalogId: 'CAT-B' },
            { campaignId: 'C3', catalogId: 'CAT-A' },
        ];

        assert.deepStrictEqual(extractUniqueCatalogIds(campaigns), ['CAT-A', 'CAT-B']);
    });

    it('skips campaigns without a catalogId', () => {
        const campaigns = [
            { campaignId: 'C1' },
            null,
            { campaignId: 'C2', catalogId: 'CAT-A' },
        ];

        assert.deepStrictEqual(extractUniqueCatalogIds(campaigns), ['CAT-A']);
    });

    it('returns an empty array for an empty list', () => {
        assert.deepStrictEqual(extractUniqueCatalogIds([]), []);
    });
});

describe('attachCatalogs (Campaign variant, treatDeletedAsNull = false)', () => {
    it('maps each campaign to its catalog from the batch result', () => {
        const campaigns = [
            { campaignId: 'C1', catalogId: 'CAT-A' },
            { campaignId: 'C2', catalogId: 'CAT-B' },
        ];
        const tableData = [
            { catalogId: 'CAT-A', catalogName: 'Fall Sale' },
            { catalogId: 'CAT-B', catalogName: 'Spring Sale' },
        ];

        assert.deepStrictEqual(attachCatalogs(campaigns, tableData, false), [
            { campaignId: 'C1', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
            { campaignId: 'C2', catalogId: 'CAT-B', catalog: { catalogId: 'CAT-B', catalogName: 'Spring Sale' } },
        ]);
    });

    it('maps missing catalogIds to null and keeps soft-deleted catalogs (raw)', () => {
        const campaigns = [
            { campaignId: 'C1', catalogId: 'CAT-MISSING' },
            { campaignId: 'C2', catalogId: 'CAT-DELETED' },
        ];
        const tableData = [
            { catalogId: 'CAT-DELETED', isDeleted: true },
        ];

        assert.deepStrictEqual(attachCatalogs(campaigns, tableData, false), [
            { campaignId: 'C1', catalogId: 'CAT-MISSING', catalog: null },
            { campaignId: 'C2', catalogId: 'CAT-DELETED', catalog: { catalogId: 'CAT-DELETED', isDeleted: true } },
        ]);
    });
});

describe('attachCatalogs (SharedCampaign variant, treatDeletedAsNull = true)', () => {
    it('maps soft-deleted catalogs to null', () => {
        const campaigns = [{ campaignId: 'C1', catalogId: 'CAT-DELETED' }];
        const tableData = [{ catalogId: 'CAT-DELETED', isDeleted: true }];

        assert.deepStrictEqual(attachCatalogs(campaigns, tableData, true), [
            { campaignId: 'C1', catalogId: 'CAT-DELETED', catalog: null },
        ]);
    });

    it('maps missing catalogIds to null', () => {
        const campaigns = [{ campaignId: 'C1', catalogId: 'CAT-MISSING' }];

        assert.deepStrictEqual(attachCatalogs(campaigns, [], true), [
            { campaignId: 'C1', catalogId: 'CAT-MISSING', catalog: null },
        ]);
    });

    it('maps active catalogs normally', () => {
        const campaigns = [{ campaignId: 'C1', catalogId: 'CAT-A' }];
        const tableData = [{ catalogId: 'CAT-A', catalogName: 'Fall Sale' }];

        assert.deepStrictEqual(attachCatalogs(campaigns, tableData, true), [
            { campaignId: 'C1', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
        ]);
    });

    it('shares one catalog across campaigns with the same catalogId', () => {
        const campaigns = [
            { campaignId: 'C1', catalogId: 'CAT-A' },
            { campaignId: 'C2', catalogId: 'CAT-A' },
        ];
        const tableData = [{ catalogId: 'CAT-A', catalogName: 'Fall Sale' }];

        assert.deepStrictEqual(attachCatalogs(campaigns, tableData, true), [
            { campaignId: 'C1', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
            { campaignId: 'C2', catalogId: 'CAT-A', catalog: { catalogId: 'CAT-A', catalogName: 'Fall Sale' } },
        ]);
    });

    it('passes campaigns without catalogId through unchanged', () => {
        const campaigns = [{ campaignId: 'C1' }];

        assert.deepStrictEqual(attachCatalogs(campaigns, [], true), [{ campaignId: 'C1' }]);
    });
});
