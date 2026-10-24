import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './validate_public_token_step2_fn.js';

function makeCampaign(overrides = {}) {
    return Object.assign(
        {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            isActive: true,
            catalogId: 'CATALOG#cat1',
            publicOrderCount: 0,
            publicOrders: { enabled: true, token: 'tok', allowedPaymentMethods: ['venmo'] },
        },
        overrides
    );
}

const validInput = {
    token: 'tok',
    campaignId: 'CAMPAIGN#c1',
    acknowledgementsAccepted: true,
    firstName: 'Jane',
    lastName: 'Doe',
    phone: '5551234567',
    paymentMethod: 'Venmo',
    lineItems: [{ productId: 'p1', quantity: 1 }],
};

describe('validate_public_token_step2 request', () => {
    it('refuses a missing stash as NOT_FOUND (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => request({ stash: { campaignId: 'CAMPAIGN#c1' } }), /NOT_FOUND: Order could not be placed/);
    });

    it('reads the anchor campaign strongly consistently under the partition key', () => {
        const req = request({ stash: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' } });
        assert.deepStrictEqual(req, {
            operation: 'GetItem',
            key: { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' },
            consistentRead: true,
        });
    });
});

describe('validate_public_token_step2 response', () => {
    it('propagates a datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('refuses a missing anchor campaign as NOT_FOUND', () => {
        assert.throws(() => response({ args: { input: validInput }, result: null, stash: {} }), /NOT_FOUND: Order could not be placed/);
    });

    it('refuses a mismatched or missing token as NOT_FOUND', () => {
        const make = (blob, token) => ({
            args: { input: { ...validInput, token } },
            stash: {},
            result: makeCampaign({ publicOrders: blob }),
        });
        assert.throws(() => response(make({ enabled: false, token: 'tok' }, 'tok')), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response(make({ enabled: true, token: 'tok' }, 'wrong')), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response(make({ enabled: true, token: 'tok' }, undefined)), /NOT_FOUND: Order could not be placed/);
        assert.throws(() => response(make({}, 'tok')), /NOT_FOUND: Order could not be placed/);
    });

    it('refuses an inactive campaign as NOT_FOUND (back-compat: absence means active)', () => {
        const make = (isActive) => ({ args: { input: validInput }, stash: {}, result: makeCampaign(isActive === undefined ? {} : { isActive }) });
        assert.throws(() => response(make(false)), /NOT_FOUND: Order could not be placed/);
    });

    it('refuses a campaign at its cap with the limit error', () => {
        const ctx = { args: { input: validInput }, stash: {}, result: makeCampaign({ publicOrderCount: 500 }) };
        assert.throws(() => response(ctx), /PUBLIC_ORDER_LIMIT_EXCEEDED: This campaign has reached its public order limit/);
    });

    it('refuses a campaign with no catalog', () => {
        assert.throws(() => response({ args: { input: validInput }, stash: {}, result: makeCampaign({ catalogId: '' }) }), /INVALID_INPUT: Campaign has no catalog assigned/);
    });

    it('refuses a request that has not accepted the terms', () => {
        assert.throws(
            () => response({ args: { input: { ...validInput, acknowledgementsAccepted: false } }, stash: {}, result: makeCampaign() }),
            /INVALID_INPUT: The public order terms must be accepted/
        );
    });

    it('rejects anonymous input that fails the bounds', () => {
        assert.throws(() => response({ args: { input: { ...validInput, firstName: '' } }, stash: {}, result: makeCampaign() }), /INVALID_INPUT: First name is required/);
    });

    it('refuses a payment method off the seller allowlist without naming it', () => {
        assert.throws(
            () => response({ args: { input: { ...validInput, paymentMethod: 'PayPal' } }, stash: {}, result: makeCampaign() }),
            /INVALID_INPUT: Payment method is not available for this seller/
        );
    });

    it('stashes the campaign, normalized catalog id, and mapped order on success', () => {
        const stash = { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' };
        const ctx = { args: { input: validInput }, stash, result: makeCampaign() };
        assert.deepStrictEqual(response(ctx), { authorized: true });
        assert.strictEqual(stash.campaign, ctx.result);
        assert.strictEqual(stash.catalogId, 'CATALOG#cat1');
        assert.strictEqual(stash.publicOrder.customerName, 'Jane Doe');
        assert.strictEqual(stash.publicOrder.paymentMethod, 'Venmo');
    });
});
