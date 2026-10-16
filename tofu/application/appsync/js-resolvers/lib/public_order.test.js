import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
    GLOBAL_PAYMENT_METHODS,
    MAX_NAME_LENGTH,
    PUBLIC_METHOD_UNAVAILABLE,
    PUBLIC_ORDER_CAP,
    PUBLIC_ORDER_UNAVAILABLE,
    composePublicOrderReceipt,
    isConditionFailure,
    validateAndMapPublicOrderInput,
} from './public_order.js';

describe('public_order constants', () => {
    it('pins the cap and the anonymous-write vocabulary', () => {
        assert.strictEqual(PUBLIC_ORDER_CAP, 500);
        assert.strictEqual(PUBLIC_ORDER_UNAVAILABLE, 'Order could not be placed');
        assert.strictEqual(PUBLIC_METHOD_UNAVAILABLE, 'Payment method is not available for this seller');
        assert.deepStrictEqual(GLOBAL_PAYMENT_METHODS, ['cash', 'check']);
        assert.ok(MAX_NAME_LENGTH > 0);
    });
});

describe('isConditionFailure', () => {
    it('is false for a missing or unrelated error', () => {
        assert.strictEqual(isConditionFailure(null), false);
        assert.strictEqual(isConditionFailure({ type: 'DynamoDB:InternalServerError', message: 'boom' }), false);
    });

    it('matches both the prefixed and bare ConditionalCheckFailed spellings', () => {
        assert.strictEqual(isConditionFailure({ type: 'DynamoDB:ConditionalCheckFailedException' }), true);
        assert.strictEqual(isConditionFailure({ type: 'ConditionalCheckFailedException' }), true);
    });

    it('falls back to the message when the type carries no name', () => {
        assert.strictEqual(isConditionFailure({ message: 'The conditional request failed: ConditionalCheckFailed' }), true);
    });
});

describe('validateAndMapPublicOrderInput', () => {
    const base = {
        firstName: 'Jane',
        lastName: 'Doe',
        phone: '5551234567',
        paymentMethod: 'Venmo',
        lineItems: [{ productId: 'p1', quantity: 1 }],
    };

    it('maps a minimal valid request (phone contact only)', () => {
        const mapped = validateAndMapPublicOrderInput(base);
        assert.strictEqual(mapped.customerFirstName, 'Jane');
        assert.strictEqual(mapped.customerLastName, 'Doe');
        assert.strictEqual(mapped.customerName, 'Jane Doe');
        assert.strictEqual(mapped.customerPhone, '+15551234567');
        assert.strictEqual(mapped.paymentMethod, 'Venmo');
        assert.deepStrictEqual(mapped.lineItems, [{ productId: 'p1', quantity: 1 }]);
        assert.strictEqual(typeof mapped.orderDate, 'string');
    });

    it('rejects a null input and missing required names', () => {
        assert.throws(() => validateAndMapPublicOrderInput(null), /INVALID_INPUT: Order input is required/);
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, firstName: '' }), /INVALID_INPUT: First name is required/);
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, lastName: '   ' }), /INVALID_INPUT: Last name is required/);
    });

    it('rejects a name over the cap', () => {
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...base, firstName: 'a'.repeat(MAX_NAME_LENGTH + 1) }),
            /INVALID_INPUT: First name must be at most/
        );
    });

    it('rejects when neither a phone nor an address is provided', () => {
        const { phone, ...noContact } = base;
        assert.throws(() => validateAndMapPublicOrderInput(noContact), /INVALID_INPUT: A phone number or a complete address is required/);
    });

    it('rejects a phone that is not a 10-digit US number', () => {
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, phone: '12345' }), /INVALID_INPUT: Phone number must be a valid 10-digit US number/);
    });

    it('accepts an 11-digit phone leading with 1', () => {
        const mapped = validateAndMapPublicOrderInput({ ...base, phone: '15551234567' });
        assert.strictEqual(mapped.customerPhone, '+15551234567');
    });

    it('rejects an address that is missing a required field', () => {
        const { phone, ...noPhone } = base;
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...noPhone, address: { street: '1 Main', city: 'T' } }),
            /INVALID_INPUT: Address is missing required fields/
        );
    });

    it('accepts a complete address and stores it', () => {
        const { phone, ...noPhone } = base;
        const mapped = validateAndMapPublicOrderInput({
            ...noPhone,
            address: { street: '1 Main', city: 'T', state: 'CA', zipCode: '94107' },
        });
        assert.deepStrictEqual(mapped.customerAddress, { street: '1 Main', city: 'T', state: 'CA', zipCode: '94107' });
    });

    it('rejects an over-long or malformed email, and stores a valid one', () => {
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, email: 'nope' }), /INVALID_INPUT: Email address is not valid/);
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...base, email: 'a@b.c' + 'x'.repeat(254) }),
            /INVALID_INPUT: Email address must be at most/
        );
        assert.strictEqual(validateAndMapPublicOrderInput({ ...base, email: 'buyer@example.com' }).customerEmail, 'buyer@example.com');
    });

    it('rejects over-long notes', () => {
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, notes: 'n'.repeat(501) }), /INVALID_INPUT: Notes must be at most/);
    });

    it('rejects empty, over-long, or malformed line items', () => {
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, lineItems: [] }), /INVALID_INPUT: Order must have at least one line item/);
        assert.throws(
            () => validateAndMapPublicOrderInput({ ...base, lineItems: Array.from({ length: 21 }, () => ({ productId: 'p1', quantity: 1 })) }),
            /INVALID_INPUT: Order must have at most/
        );
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, lineItems: [{ quantity: 1 }] }), /INVALID_INPUT: Product id must be between 1 and/);
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, lineItems: [{ productId: 'p1', quantity: 0 }] }), /INVALID_INPUT: Quantity must be between 1 and/);
    });

    it('rejects an empty payment method', () => {
        assert.throws(() => validateAndMapPublicOrderInput({ ...base, paymentMethod: '  ' }), /INVALID_INPUT: Payment method is required/);
    });
});

describe('composePublicOrderReceipt', () => {
    it('throws INTERNAL_ERROR when the written row has no order id', () => {
        assert.throws(() => composePublicOrderReceipt(null), /INTERNAL_ERROR: Order could not be written/);
        assert.throws(() => composePublicOrderReceipt({ totalAmount: 1 }), /INTERNAL_ERROR: Order could not be written/);
    });

    it('composes a site-relative receipt link and honest email flags', () => {
        const receipt = composePublicOrderReceipt({
            orderId: 'ORDER#c1#suffix123',
            receiptToken: 'tok123',
            campaignId: 'CAMPAIGN#c1',
            totalAmount: 12.5,
            customerEmail: 'buyer@example.com',
        });
        assert.deepStrictEqual(receipt, {
            orderId: 'ORDER#c1#suffix123',
            receiptUrl: '/r/c1/suffix123/tok123',
            totalAmount: 12.5,
            buyerEmailProvided: true,
            confirmationEmailSent: false,
        });
    });

    it('leaves receiptUrl null when the id, token, or campaign cannot be split', () => {
        assert.strictEqual(composePublicOrderReceipt({ orderId: 'ORDER', receiptToken: 't', campaignId: 'CAMPAIGN#c1' }).receiptUrl, null);
        assert.strictEqual(composePublicOrderReceipt({ orderId: 'ORDER#c1#s', campaignId: 'CAMPAIGN#c1' }).receiptUrl, null);
        assert.strictEqual(
            composePublicOrderReceipt({ orderId: 'ORDER#c1#s', receiptToken: 't', campaignId: 'CAMPAIGN#' }).receiptUrl,
            null
        );
    });
});
