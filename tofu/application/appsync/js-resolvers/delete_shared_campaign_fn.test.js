import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './delete_shared_campaign_fn.js';

describe('delete_shared_campaign_fn request', () => {
    it('builds DeleteItem request with sharedCampaignCode from args', () => {
        const ctx = {
            args: { sharedCampaignCode: 'SHARE-123' },
        };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'DeleteItem');
        assert.deepStrictEqual(result.key, { sharedCampaignCode: 'SHARE-123' });
    });
});

describe('delete_shared_campaign_fn response', () => {
    it('returns true on successful deletion', () => {
        const ctx = {
            error: null,
        };

        const result = response(ctx);

        assert.strictEqual(result, true);
    });

    it('throws propagated DynamoDB error when ctx.error is set', () => {
        const ctx = {
            error: { message: 'Conditional check failed', type: 'ConditionalCheckFailedException' },
        };

        assert.throws(
            () => response(ctx),
            /ConditionalCheckFailedException: Conditional check failed/
        );
    });
});
