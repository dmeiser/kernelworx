import { describe, it } from 'node:test';
import assert from 'node:assert';
import { parseEmbeddedCampaignId, buildOrderLookupRequest } from './order_lookup.js';

describe('parseEmbeddedCampaignId', () => {
    it('extracts the campaignId from a new-format order ID', () => {
        assert.strictEqual(
            parseEmbeddedCampaignId('ORDER#campaign-123#550e8400-e29b-41d4-a716-446655440000'),
            'CAMPAIGN#campaign-123'
        );
    });

    it('returns null for a legacy (two-part) order ID', () => {
        assert.strictEqual(
            parseEmbeddedCampaignId('ORDER#550e8400-e29b-41d4-a716-446655440000'),
            null
        );
    });

    it('returns null for a non-standard order ID', () => {
        assert.strictEqual(parseEmbeddedCampaignId('ORDER#non-existent-order'), null);
    });

    it('returns null for a non-string input', () => {
        assert.strictEqual(parseEmbeddedCampaignId(undefined), null);
        assert.strictEqual(parseEmbeddedCampaignId(null), null);
        assert.strictEqual(parseEmbeddedCampaignId(42), null);
    });
});

describe('buildOrderLookupRequest', () => {
    it('returns a strongly-consistent base-table GetItem for new order IDs', () => {
        const orderId = 'ORDER#campaign-123#550e8400-e29b-41d4-a716-446655440000';
        const result = buildOrderLookupRequest(orderId);

        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#campaign-123');
        assert.strictEqual(result.key.orderId, orderId);
        // The read-after-write guarantee: without this flag AppSync defaults to an
        // eventually-consistent read and a just-written order can come back missing.
        assert.strictEqual(result.consistentRead, true);
    });

    it('falls back to the GSI Query for legacy order IDs', () => {
        const orderId = 'ORDER#550e8400-e29b-41d4-a716-446655440000';
        const result = buildOrderLookupRequest(orderId);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'orderId-index');
        assert.strictEqual(result.limit, 1);
    });

    it('falls back to the GSI Query for non-standard order IDs', () => {
        const result = buildOrderLookupRequest('ORDER#non-existent-order');

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'orderId-index');
    });
});
