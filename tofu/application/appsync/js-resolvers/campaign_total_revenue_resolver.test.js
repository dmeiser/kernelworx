import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './campaign_total_revenue_resolver.js';

describe('campaign_total_revenue_resolver request', () => {
    it('serves the counter with no datastore call when present (#746)', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1', totalRevenue: 59.97 } });
        assert.strictEqual(result, 59.97);
    });

    it('serves a zero counter instead of falling back (#746)', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1', totalRevenue: 0 } });
        assert.strictEqual(result, 0);
    });

    it('rounds a counter carrying a sub-cent float tail (#746)', () => {
        const result = request({
            source: { campaignId: 'CAMPAIGN#c1', totalRevenue: 254.33999999999997 },
        });
        assert.strictEqual(result, 254.34);
    });

    it('falls back to a SUM Query for campaigns without the counter', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1' } });
        assert.strictEqual(result.operation, 'Query');
        assert.deepStrictEqual(result.projection, { expression: 'totalAmount' });
        assert.strictEqual(result.query.expression, 'campaignId = :campaignId');
        assert.deepStrictEqual(result.query.expressionValues, { ':campaignId': 'CAMPAIGN#c1' });
    });

    it('falls back when the counter attribute is explicitly null', () => {
        const result = request({ source: { campaignId: 'CAMPAIGN#c1', totalRevenue: null } });
        assert.strictEqual(result.operation, 'Query');
    });
});

describe('campaign_total_revenue_resolver response', () => {
    it('rounds float drift out of the summed fallback (#746)', () => {
        // 0.1 + 0.2 accumulates to 0.30000000000000004 in IEEE-754; the
        // assertion below proves the resolver rounds it back to 0.3.
        assert.notStrictEqual(0.1 + 0.2, 0.3);
        const result = response({
            result: { items: [{ totalAmount: 0.1 }, { totalAmount: 0.2 }] },
        });
        assert.strictEqual(result, 0.3);
    });

    it('keeps an exact sum intact', () => {
        assert.strictEqual(
            response({ result: { items: [{ totalAmount: 10 }, { totalAmount: 9.97 }] } }),
            19.97
        );
    });

    it('zero orders yields 0', () => {
        assert.strictEqual(response({ result: { items: [] } }), 0);
    });

    it('propagates a data source error', () => {
        assert.throws(
            () => response({ error: { message: 'boom', type: 'DynamoDB:ValidationException' } }),
            /DynamoDB:ValidationException: boom/
        );
    });
});
