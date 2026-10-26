import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_shared_campaign_for_update_fn.js';

describe('get_shared_campaign_for_update_fn request', () => {
    it('reads the shared campaign by the code nested under input', () => {
        const ctx = { args: { input: { sharedCampaignCode: 'SHARED-XYZ789', isActive: false } }, identity: { sub: 'user-1' }, stash: {} };

        const result = request(ctx);

        assert.strictEqual(result.operation, 'GetItem');
        assert.deepStrictEqual(result.key, { sharedCampaignCode: 'SHARED-XYZ789' });
    });
});

describe('get_shared_campaign_for_update_fn response', () => {
    const owned = { sharedCampaignCode: 'SHARED-XYZ789', createdBy: 'ACCOUNT#user-1', isActive: true };

    it('authorizes the creator and stashes the item for the update step', () => {
        const ctx = { result: owned, identity: { sub: 'user-1' }, stash: {} };

        assert.strictEqual(response(ctx), owned);
        assert.strictEqual(ctx.stash.sharedCampaign, owned);
    });

    it('authorizes a creator whose sub already carries the ACCOUNT# prefix', () => {
        const ctx = { result: owned, identity: { sub: 'ACCOUNT#user-1' }, stash: {} };

        assert.strictEqual(response(ctx), owned);
    });

    it('denies a non-creator with FORBIDDEN and stashes nothing', () => {
        const ctx = { result: owned, identity: { sub: 'user-2' }, stash: {} };

        assert.throws(
            () => response(ctx),
            /FORBIDDEN: Only the creator can update this campaign sharedCampaign/,
        );
        assert.strictEqual(ctx.stash.sharedCampaign, undefined);
    });

    it('fails with NOT_FOUND before the ownership check when the item is missing', () => {
        const ctx = { result: null, identity: { sub: 'user-1' }, stash: {} };

        assert.throws(() => response(ctx), /NOT_FOUND: Shared Campaign not found/);
    });

    it('propagates a DynamoDB error unchanged', () => {
        const ctx = { error: { message: 'Service error', type: 'INTERNAL_ERROR' }, identity: { sub: 'user-1' }, stash: {} };

        assert.throws(() => response(ctx), /INTERNAL_ERROR: Service error/);
    });
});
