import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_public_order_fn.js';

// #679 write slice, spec §10.1: the public order write. Reads the stash, shares
// the pricing core with the authenticated path, and mints the receipt token.

function mapped(overrides) {
    return {
        customerFirstName: 'Ada',
        customerLastName: 'Lovelace',
        customerName: 'Ada Lovelace',
        customerEmail: null,
        customerPhone: '+15551234567',
        customerAddress: null,
        notes: null,
        paymentMethod: 'Venmo',
        lineItems: [{ productId: 'prod-1', quantity: 2 }],
        orderDate: '2026-01-01T00:00:00Z',
        ...(overrides || {})
    };
}

function ctxWith(overrides) {
    return {
        stash: {
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            campaign: { campaignId: 'CAMPAIGN#c1', profileId: 'PROFILE#p1', catalogId: 'CATALOG#cat1', isActive: true },
            sellerName: 'Troop 42',
            catalog: {
                catalogId: 'CATALOG#cat1',
                isDeleted: false,
                products: [
                    { productId: 'prod-1', productName: 'Cookies', price: 4.5 },
                    { productId: 'prod-2', productName: 'Magazine', price: 3 }
                ]
            },
            publicOrder: mapped(),
            ...(overrides || {})
        },
        result: null,
        error: null
    };
}

describe('create_public_order_fn request', () => {
    it('PutItems the order under the campaign partition key', () => {
        const result = request(ctxWith());

        assert.strictEqual(result.operation, 'PutItem');
        assert.strictEqual(result.key.campaignId, 'CAMPAIGN#c1');
        assert.ok(result.key.orderId.startsWith('ORDER#c1#'), result.key.orderId);
        assert.strictEqual(result.attributeValues.orderId, result.key.orderId);
    });

    it('writes the public-order attributes with the enum spellings the schema declares', () => {
        const values = request(ctxWith()).attributeValues;

        assert.strictEqual(values.orderSource, 'PUBLIC');
        assert.strictEqual(values.status, 'NEW');
        assert.strictEqual(values.sellerName, 'Troop 42');
        assert.strictEqual(typeof values.receiptToken, 'string');
        assert.ok(values.receiptToken.length > 0);
    });

    it('writes an empty seller name rather than omitting the receipt display field', () => {
        const values = request(ctxWith({ sellerName: undefined })).attributeValues;
        assert.strictEqual(values.sellerName, '');
    });

    it('maps the split names, contact fields, and notes', () => {
        const values = request(
            ctxWith({
                publicOrder: mapped({
                    customerEmail: 'buyer@example.com',
                    customerAddress: { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '62701' },
                    notes: 'Leave at the door'
                })
            })
        ).attributeValues;

        assert.strictEqual(values.customerFirstName, 'Ada');
        assert.strictEqual(values.customerLastName, 'Lovelace');
        assert.strictEqual(values.customerName, 'Ada Lovelace');
        assert.strictEqual(values.customerEmail, 'buyer@example.com');
        assert.strictEqual(values.customerPhone, '+15551234567');
        assert.deepStrictEqual(values.customerAddress, { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '62701' });
        assert.strictEqual(values.notes, 'Leave at the door');
    });

    it('omits the contact attributes the buyer did not supply', () => {
        const values = request(ctxWith()).attributeValues;

        assert.ok(!Object.hasOwn(values, 'customerEmail'));
        assert.ok(!Object.hasOwn(values, 'customerAddress'));
        assert.ok(!Object.hasOwn(values, 'notes'));
    });

    it('prices the line items server-side through the shared core', () => {
        const values = request(ctxWith({ publicOrder: mapped({ lineItems: [{ productId: 'prod-1', quantity: 2 }, { productId: 'prod-2', quantity: 1 }] }) })).attributeValues;

        assert.deepStrictEqual(values.lineItems, [
            { productId: 'prod-1', productName: 'Cookies', quantity: 2, pricePerUnit: 4.5, subtotal: 9 },
            { productId: 'prod-2', productName: 'Magazine', quantity: 1, pricePerUnit: 3, subtotal: 3 }
        ]);
        assert.strictEqual(values.totalAmount, 12);
    });

    it('rejects a productId absent from the catalog and writes nothing', () => {
        assert.throws(
            () => request(ctxWith({ publicOrder: mapped({ lineItems: [{ productId: 'ghost', quantity: 1 }] }) })),
            /INVALID_INPUT: Product ghost not found in catalog/
        );
    });

    it('rejects a soft-deleted catalog', () => {
        assert.throws(
            () => request(ctxWith({ catalog: { catalogId: 'CATALOG#cat1', isDeleted: true, products: [] } })),
            /INVALID_INPUT: Catalog is not available for this campaign/
        );
    });

    it('fails loudly on a wiring fault rather than writing a partial row', () => {
        assert.throws(() => request(ctxWith({ publicOrder: null })), /INTERNAL_ERROR: Order could not be written/);
    });
});

describe('create_public_order_fn response', () => {
    it('composes the buyer receipt from the row that was written', () => {
        const ctx = ctxWith();
        ctx.result = {
            orderId: 'ORDER#c1#suffix-1',
            campaignId: 'CAMPAIGN#c1',
            totalAmount: 9,
            customerEmail: 'buyer@example.com',
            receiptToken: 'receipt-token-1'
        };

        const receipt = response(ctx);

        assert.deepStrictEqual(receipt, {
            orderId: 'ORDER#c1#suffix-1',
            receiptUrl: '/r/c1/suffix-1/receipt-token-1',
            totalAmount: 9,
            buyerEmailProvided: true,
            confirmationEmailSent: false
        });
    });

    it('reports buyerEmailProvided false when no address was given', () => {
        const ctx = ctxWith();
        ctx.result = { orderId: 'ORDER#c1#suffix-1', campaignId: 'CAMPAIGN#c1', totalAmount: 9, receiptToken: 'receipt-token-1' };
        assert.strictEqual(response(ctx).buyerEmailProvided, false);
    });

    it('never claims a confirmation email this slice cannot send', () => {
        const ctx = ctxWith();
        ctx.result = { orderId: 'ORDER#c1#s', campaignId: 'CAMPAIGN#c1', totalAmount: 1, customerEmail: 'b@example.com', receiptToken: 't' };
        assert.strictEqual(response(ctx).confirmationEmailSent, false);
    });

    it('drops the receipt link rather than emitting a malformed one', () => {
        const ctx = ctxWith();
        ctx.result = { orderId: 'ORDER#legacy-uuid', campaignId: 'CAMPAIGN#c1', totalAmount: 1, receiptToken: 't' };
        assert.strictEqual(response(ctx).receiptUrl, null);
    });

    it('surfaces a datastore error unchanged', () => {
        const ctx = ctxWith();
        ctx.error = { type: 'DynamoDB:ValidationException', message: 'item too large' };
        assert.throws(() => response(ctx), /ValidationException: item too large/);
    });
});
