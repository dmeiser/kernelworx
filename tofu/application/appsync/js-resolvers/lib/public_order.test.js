import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
    GLOBAL_PAYMENT_METHODS,
    PUBLIC_METHOD_UNAVAILABLE,
    PUBLIC_ORDER_CAP,
    PUBLIC_ORDER_UNAVAILABLE,
    canonicalCampaignId,
    composePublicOrderReceipt,
    isConditionFailure,
    validateAndMapPublicOrderInput
} from './public_order.js';

// The shared contract of the publicCreateOrder pipeline. Each step pins its own
// behavior colocated; this file pins the constants and helpers more than one
// step depends on, so a change here is visible at the owner.

describe('public order constants', () => {
    it('declares the lifetime cap the increment condition enforces', () => {
        assert.strictEqual(PUBLIC_ORDER_CAP, 500);
    });

    it('declares one NOT_FOUND message for every unavailable branch', () => {
        assert.strictEqual(PUBLIC_ORDER_UNAVAILABLE, 'Order could not be placed');
    });

    it('declares one payment-method message so the mutation is not an oracle', () => {
        assert.strictEqual(PUBLIC_METHOD_UNAVAILABLE, 'Payment method is not available for this seller');
    });

    it('treats Cash and Check as global pseudo-methods, lowercased for comparison', () => {
        assert.deepStrictEqual(GLOBAL_PAYMENT_METHODS, ['cash', 'check']);
    });
});

describe('isConditionFailure', () => {
    it('matches the datasource-prefixed spelling', () => {
        assert.strictEqual(isConditionFailure({ type: 'DynamoDB:ConditionalCheckFailedException', message: 'x' }), true);
    });

    it('matches the bare spelling', () => {
        assert.strictEqual(isConditionFailure({ type: 'ConditionalCheckFailedException', message: 'x' }), true);
    });

    it('matches a message-only spelling', () => {
        assert.strictEqual(isConditionFailure({ type: 'DynamoDB', message: 'ConditionalCheckFailed: no' }), true);
    });

    it('does not match an unrelated error', () => {
        assert.strictEqual(isConditionFailure({ type: 'DynamoDB:ThrottlingException', message: 'slow' }), false);
        assert.strictEqual(isConditionFailure(null), false);
    });
});

describe('canonicalCampaignId', () => {
    it('re-prefixes a bare id and leaves a canonical one alone', () => {
        assert.strictEqual(canonicalCampaignId('c1'), 'CAMPAIGN#c1');
        assert.strictEqual(canonicalCampaignId('CAMPAIGN#c1'), 'CAMPAIGN#c1');
        assert.strictEqual(canonicalCampaignId(null), null);
    });
});

describe('composePublicOrderReceipt', () => {
    it('splits the order id into the two receipt URL segments the route requires', () => {
        const receipt = composePublicOrderReceipt({
            orderId: 'ORDER#camp-1#order-2',
            campaignId: 'CAMPAIGN#camp-1',
            totalAmount: 12.5,
            customerEmail: 'b@example.com',
            receiptToken: 'tok-3'
        });

        assert.strictEqual(receipt.orderId, 'ORDER#camp-1#order-2');
        assert.strictEqual(receipt.receiptUrl, '/r/camp-1/order-2/tok-3');
        assert.ok(!receipt.receiptUrl.includes('#'), 'a # in a URL path would be cut at the fragment delimiter');
        assert.strictEqual(receipt.totalAmount, 12.5);
        assert.strictEqual(receipt.buyerEmailProvided, true);
    });

    it('is site-relative, because a JS resolver has no site origin to compose against', () => {
        const receipt = composePublicOrderReceipt({ orderId: 'ORDER#c#s', campaignId: 'CAMPAIGN#c', totalAmount: 1, receiptToken: 't' });
        assert.ok(receipt.receiptUrl.startsWith('/r/'));
    });

    it('never claims a confirmation email it did not send', () => {
        const receipt = composePublicOrderReceipt({ orderId: 'ORDER#c#s', campaignId: 'CAMPAIGN#c', totalAmount: 1, customerEmail: 'b@example.com', receiptToken: 't' });
        assert.strictEqual(receipt.confirmationEmailSent, false);
    });

    it('reports buyerEmailProvided from the stored attribute only', () => {
        const without = composePublicOrderReceipt({ orderId: 'ORDER#c#s', campaignId: 'CAMPAIGN#c', totalAmount: 1, receiptToken: 't' });
        assert.strictEqual(without.buyerEmailProvided, false);
    });

    it('drops the link rather than emitting a path from a legacy two-part order id', () => {
        const receipt = composePublicOrderReceipt({ orderId: 'ORDER#legacy', campaignId: 'CAMPAIGN#c', totalAmount: 1, receiptToken: 't' });
        assert.strictEqual(receipt.receiptUrl, null);
    });

    it('drops the link when no receipt token was minted', () => {
        const receipt = composePublicOrderReceipt({ orderId: 'ORDER#c#s', campaignId: 'CAMPAIGN#c', totalAmount: 1 });
        assert.strictEqual(receipt.receiptUrl, null);
    });

    it('fails loudly when there is no written row to describe', () => {
        assert.throws(() => composePublicOrderReceipt(null), /INTERNAL_ERROR: Order could not be written/);
    });
});

describe('validateAndMapPublicOrderInput', () => {
    const base = {
        firstName: 'Ada',
        lastName: 'Lovelace',
        phone: '5551234567',
        paymentMethod: 'Venmo',
        lineItems: [{ productId: 'p1', quantity: 1 }]
    };

    it('synthesizes an order date the buyer form does not carry', () => {
        assert.strictEqual(typeof validateAndMapPublicOrderInput(base).orderDate, 'string');
    });

    it('rejects a non-object input', () => {
        assert.throws(() => validateAndMapPublicOrderInput(null), /INVALID_INPUT: Order input is required/);
    });

    it('rejects a line item that is not an object', () => {
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...base, lineItems: ['p1'] }),
            /INVALID_INPUT: Line items must carry a product id and a quantity/
        );
    });

    it('rejects a non-numeric quantity', () => {
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...base, lineItems: [{ productId: 'p1', quantity: '2' }] }),
            /INVALID_INPUT: Quantity must be between 1 and 999/
        );
    });

    it('rejects an empty product id', () => {
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...base, lineItems: [{ productId: '', quantity: 1 }] }),
            /INVALID_INPUT: Product id must be between 1 and 200 characters/
        );
    });

    it('accepts an email with a multi-label domain and rejects a single-label one', () => {
        assert.strictEqual(validateAndMapPublicOrderInput({ ...base, email: 'a@b.co' }).customerEmail, 'a@b.co');
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, email: 'a@b' }), /INVALID_INPUT: Email address is not valid/);
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, email: 'a@@b.co' }), /INVALID_INPUT: Email address is not valid/);
    });

    it('accepts a 9-digit ZIP inside a complete address', () => {
        const mapped = validateAndMapPublicOrderInput({
            ...base,
            phone: null,
            address: { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '627011234' }
        });
        assert.strictEqual(mapped.customerAddress.zipCode, '627011234');
    });
});
