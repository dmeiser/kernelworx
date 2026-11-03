import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './campaign_total_orders_resolver.js';

describe('campaign_total_orders_resolver request', () => {
    it('serves the denormalized counter with no datastore call when present (#746)', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1', totalOrders: 7 } });
        assert.strictEqual(result, 7);
    });

    it('serves a zero counter instead of falling back (#746)', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1', totalOrders: 0 } });
        assert.strictEqual(result, 0);
    });

    it('falls back to a COUNT Query for campaigns without the counter', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1' } });
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.select, 'COUNT');
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, { ':campaignId': 'CAMPAIGN#c1' });
    });

    it('falls back when the counter attribute is explicitly null', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1', totalOrders: null } });
        assert.strictEqual(result.operation, 'Query');
    });
});

describe('campaign_total_orders_resolver response', () => {
    it('returns the scanned count', () => {
        assert.strictEqual(response({ result: { scannedCount: 42 } }), 42);
    });

    it('propagates a data source error', () => {
        assert.throws(
            () => response({ error: { message: 'boom', type: 'DynamoDB:ValidationException' } }),
            /DynamoDB:ValidationException: boom/
        );
    });
});
