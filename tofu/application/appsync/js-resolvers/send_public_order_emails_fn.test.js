import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response, SEND_ORDER_EMAILS_OPERATION } from './send_public_order_emails_fn.js';

const ORDER_ITEM = {
    orderId: 'ORDER#c1#s1',
    campaignId: 'CAMPAIGN#c1',
    customerFirstName: 'Ada',
    customerLastName: "O'Brien",
    customerEmail: 'ada@example.com',
    paymentMethod: 'Cash',
    lineItems: [{ productName: 'Cookies', quantity: 2, subtotal: 10 }],
    totalAmount: 10,
    receiptToken: 'rtok',
    sellerName: 'Troops R Us',
};

const STASH = {
    orderItem: ORDER_ITEM,
    sellerName: 'Troops R Us',
    ownerAccountId: 'ACCOUNT#a1',
    campaign: { campaignName: 'Fall Sale' },
};

const RECEIPT = {
    orderId: 'ORDER#c1#s1',
    receiptUrl: '/r/c1/s1/rtok',
    totalAmount: 10,
    buyerEmailProvided: true,
    confirmationEmailSent: false,
};

describe('send_public_order_emails request', () => {
    it('invokes the public-orders Lambda with the operation discriminator and payload data', () => {
        const req = request({ stash: STASH, prev: { result: RECEIPT } });
        assert.strictEqual(req.operation, 'Invoke');
        assert.strictEqual(req.payload.operation, SEND_ORDER_EMAILS_OPERATION);
        assert.strictEqual(req.payload.order, ORDER_ITEM);
        // sellerName is no longer forwarded: the mailer reads it from the order row.
        assert.strictEqual(req.payload.ownerAccountId, 'ACCOUNT#a1');
        assert.strictEqual(req.payload.campaignName, 'Fall Sale');
        assert.strictEqual(req.payload.receiptUrl, '/r/c1/s1/rtok');
    });

    it('never forwards identity (API-key callers have none)', () => {
        const req = request({ identity: { sub: 's' }, stash: STASH, prev: { result: RECEIPT } });
        assert.strictEqual(req.payload.identity, undefined);
    });

    it('degrades to the untouched receipt when the write step stashed no order', () => {
        const receipt = { ...RECEIPT };
        const req = request({ stash: {}, prev: { result: receipt } });
        assert.strictEqual(req.confirmationEmailSent, false);
    });

    it('tolerates a missing campaign blob with an empty campaign name', () => {
        const req = request({ stash: { orderItem: ORDER_ITEM }, prev: { result: RECEIPT } });
        assert.strictEqual(req.payload.campaignName, '');
    });
});

describe('send_public_order_emails response', () => {
    it('marks the receipt sent when the handler confirmed the buyer send', () => {
        const receipt = { ...RECEIPT };
        const res = response({ result: { configured: true, sellerEmailSent: true, confirmationEmailSent: true }, prev: { result: receipt } });
        assert.strictEqual(res.confirmationEmailSent, true);
        assert.strictEqual(res.orderId, 'ORDER#c1#s1');
    });

    it('marks the receipt failed on an invoke-level error (throttle/timeout)', () => {
        const receipt = { ...RECEIPT };
        const res = response({ error: { message: 'Rate limit exceeded', type: 'Lambda:ServiceException' }, prev: { result: receipt } });
        assert.strictEqual(res.confirmationEmailSent, false);
        assert.strictEqual(res.orderId, 'ORDER#c1#s1');
    });

    it('swallows a structured handler failure exactly like an invoke failure', () => {
        const receipt = { ...RECEIPT };
        const res = response({ result: { __isError: true, errorCode: 'INTERNAL_ERROR', message: 'boom' }, prev: { result: receipt } });
        assert.strictEqual(res.confirmationEmailSent, false);
    });

    it('reports not-sent when the buyer gave no email (attempted=false)', () => {
        const receipt = { ...RECEIPT, buyerEmailProvided: false };
        const res = response({ result: { configured: true, sellerEmailSent: true, confirmationEmailSent: false }, prev: { result: receipt } });
        assert.strictEqual(res.confirmationEmailSent, false);
    });

    it('fails loudly when there is no committed receipt to pass through', () => {
        assert.throws(() => response({ result: { configured: true }, prev: {} }), /INTERNAL_ERROR: Order could not be placed/);
    });
});
