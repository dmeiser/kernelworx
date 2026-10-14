import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './write_campaign_public_order_settings_fn.js';

// KW-PUBLIC-ORDERS-CAMPAIGN-CORE-1: the write pipeline's CampaignsDS step. One
// conditioned UpdateItem writes the whole publicOrders map onto the campaign
// item, merged over the stored blob, so a disable flips only `enabled` and the
// share token survives for URL stability.

function ctxFor(input, storedPublicOrders) {
    return {
        stash: {
            isOwner: true,
            profileId: 'PROFILE#p1',
            profile: { ownerAccountId: 'ACCOUNT#owner-1', profileId: 'PROFILE#p1' },
            publicSettingsCampaign: {
                profileId: 'PROFILE#p1',
                campaignId: 'CAMPAIGN#c1',
                campaignName: 'Fall',
                isActive: true,
                publicOrders: storedPublicOrders
            }
        },
        args: { input },
        identity: { sub: 'ACCOUNT#owner-1' }
    };
}

const ENABLE_INPUT = {
    campaignId: 'CAMPAIGN#c1',
    enabled: true,
    allowedPaymentMethods: ['Cash', 'Venmo'],
    acknowledgementsAccepted: true
};

function blobFor(input, stored) {
    return request(ctxFor(input, stored)).update.expressionValues[':publicOrders'];
}

describe('write_campaign_public_order_settings_fn request', () => {
    it('UpdateItems the campaign item under the located key', () => {
        const result = request(ctxFor(ENABLE_INPUT, undefined));

        assert.strictEqual(result.operation, 'UpdateItem');
        assert.deepStrictEqual(result.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(result.update.expression, 'SET publicOrders = :publicOrders, updatedAt = :updatedAt');
    });

    it('conditions on the campaign still existing so a concurrent delete wins', () => {
        const input = { campaignId: 'CAMPAIGN#c1', enabled: false };
        const stored = { enabled: true, token: 'token-abc123', ackVersion: 1 };

        assert.strictEqual(request(ctxFor(input, stored)).condition.expression, 'attribute_exists(campaignId)');
    });

    it('mints a token on first enable and guards against a concurrent first enable', () => {
        const result = request(ctxFor(ENABLE_INPUT, undefined));

        assert.strictEqual(result.update.expressionValues[':publicOrders'].token, 'auto-generated-id');
        assert.strictEqual(
            result.condition.expression,
            'attribute_exists(campaignId) AND attribute_not_exists(publicOrders.#token)'
        );
        // TOKEN is a DynamoDB reserved word: the path must be escaped.
        assert.deepStrictEqual(result.condition.expressionNames, { '#token': 'token' });
    });

    it('keeps the stored token through a disable so the share URL stays stable', () => {
        const blob = blobFor({ campaignId: 'CAMPAIGN#c1', enabled: false }, {
            enabled: true,
            token: 'token-abc123',
            allowedPaymentMethods: ['Cash']
        });

        assert.strictEqual(blob.enabled, false);
        assert.strictEqual(blob.token, 'token-abc123');
        assert.deepStrictEqual(blob.allowedPaymentMethods, ['Cash']);
    });

    it('keeps the same token across disable then re-enable', () => {
        const blob = blobFor(
            { campaignId: 'CAMPAIGN#c1', enabled: true, allowedPaymentMethods: ['Cash'] },
            { enabled: false, token: 'token-abc123', allowedPaymentMethods: ['Cash'], ackVersion: 1 }
        );

        assert.strictEqual(blob.token, 'token-abc123');
    });

    it('rotates the token only on an explicit rotateToken', () => {
        const blob = blobFor({ campaignId: 'CAMPAIGN#c1', enabled: true, rotateToken: true, allowedPaymentMethods: ['Cash'] }, {
            enabled: true,
            token: 'token-abc123',
            allowedPaymentMethods: ['Cash'],
            ackVersion: 1
        });

        assert.strictEqual(blob.token, 'auto-generated-id');
    });

    it('allows rotateToken while parked (disable plus rotate)', () => {
        const blob = blobFor({ campaignId: 'CAMPAIGN#c1', enabled: false, rotateToken: true }, {
            enabled: false,
            token: 'token-abc123',
            allowedPaymentMethods: ['Cash']
        });

        assert.strictEqual(blob.enabled, false);
        assert.strictEqual(blob.token, 'auto-generated-id');
    });

    it('preserves unknown sub-attributes of the stored blob', () => {
        const blob = blobFor({ campaignId: 'CAMPAIGN#c1', enabled: false }, {
            enabled: true,
            token: 'token-abc123',
            allowedPaymentMethods: ['Cash'],
            futureField: 'kept'
        });

        assert.strictEqual(blob.futureField, 'kept');
    });

    it('keeps the stored method list when the field is omitted', () => {
        const blob = blobFor({ campaignId: 'CAMPAIGN#c1', enabled: true }, {
            enabled: true,
            token: 'token-abc123',
            allowedPaymentMethods: ['Venmo'],
            ackVersion: 1
        });

        assert.deepStrictEqual(blob.allowedPaymentMethods, ['Venmo']);
    });

    it('rejects an explicit null method list, which is not the same as omitting it', () => {
        const input = { campaignId: 'CAMPAIGN#c1', enabled: true, allowedPaymentMethods: null };

        assert.throws(
            () => request(ctxFor(input, { enabled: true, allowedPaymentMethods: ['Cash'] })),
            /INVALID_INPUT: allowedPaymentMethods cannot be null/
        );
    });

    it('rejects enabling with an empty method list', () => {
        const input = { ...ENABLE_INPUT, allowedPaymentMethods: [] };

        assert.throws(
            () => request(ctxFor(input, undefined)),
            /INVALID_INPUT: At least one payment method must be allowed/
        );
    });

    it('rejects a blank entry in the method list', () => {
        const input = { ...ENABLE_INPUT, allowedPaymentMethods: ['   '] };

        assert.throws(
            () => request(ctxFor(input, undefined)),
            /INVALID_INPUT: allowedPaymentMethods must be a list of non-empty names/
        );
    });

    it('stamps the acknowledgement only when the owner actually accepted it', () => {
        const blob = blobFor(ENABLE_INPUT, undefined);

        assert.strictEqual(blob.acknowledgedAt, '2024-01-01T00:00:00Z');
        assert.strictEqual(blob.ackVersion, 1);
    });

    it('requires the acknowledgement when the stored version is behind', () => {
        const input = { ...ENABLE_INPUT, acknowledgementsAccepted: false };

        assert.throws(
            () => request(ctxFor(input, { enabled: false, ackVersion: 0 })),
            /INVALID_INPUT: The public order acknowledgements must be accepted/
        );
    });

    it('does not re-prompt when the stored acknowledgement is current', () => {
        const input = { ...ENABLE_INPUT, acknowledgementsAccepted: false };
        const blob = blobFor(input, {
            enabled: false,
            ackVersion: 1,
            acknowledgedAt: '2023-01-01T00:00:00Z'
        });

        assert.strictEqual(blob.acknowledgedAt, '2023-01-01T00:00:00Z');
        assert.strictEqual(blob.ackVersion, 1);
    });

    it('re-stamps the acknowledgement to the last accepted value on a re-save of an already-enabled campaign', () => {
        const blob = blobFor(ENABLE_INPUT, {
            enabled: true,
            token: 'tok-1',
            ackVersion: 1,
            acknowledgedAt: '2023-01-01T00:00:00Z'
        });

        assert.strictEqual(blob.acknowledgedAt, '2024-01-01T00:00:00Z');
        assert.strictEqual(blob.ackVersion, 1);
    });

    it('refuses to build a key when no campaign was located', () => {
        const ctx = ctxFor(ENABLE_INPUT, undefined);
        delete ctx.stash.profileId;
        delete ctx.stash.publicSettingsCampaign;

        assert.throws(() => request(ctx), /NOT_FOUND: Campaign not found/);
    });
});

describe('write_campaign_public_order_settings_fn response', () => {
    it('maps a first-enable condition failure to a retryable CONFLICT', () => {
        const ctx = {
            error: {
                type: 'DynamoDB:ConditionalCheckFailedException',
                message: 'The conditional request failed'
            }
        };

        assert.throws(
            () => response(ctx),
            /CONFLICT: Public order settings were already saved; try again/
        );
    });

    it('propagates any other datasource error unchanged', () => {
        const ctx = { error: { type: 'DynamoDB:ThrottlingException', message: 'Throttled' } };

        assert.throws(() => response(ctx), /DynamoDB:ThrottlingException: Throttled/);
    });

    it('returns the updated item so the root can compose the saved settings', () => {
        const item = { campaignId: 'CAMPAIGN#c1', publicOrders: { enabled: true, token: 't' } };

        assert.deepStrictEqual(response({ result: item }), item);
    });
});
