import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './list_my_shared_campaigns_resolver.js';

describe('list_my_shared_campaigns_resolver request', () => {
    it('queries GSI1 on the normalized createdBy key, newest first', () => {
        const ctx = { identity: { sub: 'user-123' } };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.index, 'GSI1');
        assert.deepStrictEqual(result.query, {
            expression: 'createdBy = :createdBy',
            expressionValues: { ':createdBy': 'ACCOUNT#user-123' },
        });
        assert.strictEqual(result.scanIndexForward, false);
    });

    it('keeps an already-prefixed sub as one prefix', () => {
        const ctx = { identity: { sub: 'ACCOUNT#user-123' } };

        assert.strictEqual(request(ctx).query.expressionValues[':createdBy'], 'ACCOUNT#user-123');
    });
});

describe('list_my_shared_campaigns_resolver response', () => {
    it('drops deactivated shared campaigns and keeps the query order', () => {
        const items = [
            { sharedCampaignCode: 'SHARED-A', createdBy: 'ACCOUNT#user-1', isActive: true },
            { sharedCampaignCode: 'SHARED-B', createdBy: 'ACCOUNT#user-1', isActive: false },
            { sharedCampaignCode: 'SHARED-C', createdBy: 'ACCOUNT#user-1', isActive: true },
        ];

        assert.deepStrictEqual(
            response({ result: { items } }).map((item) => item.sharedCampaignCode),
            ['SHARED-A', 'SHARED-C'],
        );
    });

    it('treats a missing or null isActive as active and writes the default back', () => {
        const items = [
            { sharedCampaignCode: 'SHARED-A', createdBy: 'ACCOUNT#user-1' },
            { sharedCampaignCode: 'SHARED-B', createdBy: 'ACCOUNT#user-1', isActive: null },
        ];

        const kept = response({ result: { items } });

        assert.deepStrictEqual(kept.map((item) => item.sharedCampaignCode), ['SHARED-A', 'SHARED-B']);
        assert.strictEqual(kept[0].isActive, true);
        assert.strictEqual(kept[1].isActive, true);
    });

    it('serves createdBy without the DynamoDB key prefix', () => {
        const items = [{ sharedCampaignCode: 'SHARED-A', createdBy: 'ACCOUNT#user-1', isActive: true }];

        assert.strictEqual(response({ result: { items } })[0].createdBy, 'user-1');
    });

    it('leaves an unprefixed or missing createdBy untouched', () => {
        const items = [
            { sharedCampaignCode: 'SHARED-A', createdBy: 'user-1', isActive: true },
            { sharedCampaignCode: 'SHARED-B', isActive: true },
        ];

        const kept = response({ result: { items } });

        assert.strictEqual(kept[0].createdBy, 'user-1');
        assert.strictEqual(kept[1].createdBy, undefined);
    });

    it('returns an empty list when the query produced no items key', () => {
        for (const result of [{}, { items: null }, { items: [] }]) {
            assert.deepStrictEqual(response({ result }), []);
        }
    });

    it('propagates a DynamoDB error unchanged', () => {
        const ctx = { error: { message: 'Throttling', type: 'RESOURCE_BUSY' } };

        assert.throws(() => response(ctx), /RESOURCE_BUSY: Throttling/);
    });
});
