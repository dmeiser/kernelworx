import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './create_public_order_fn.js';

function makeStash(overrides = {}) {
    return Object.assign(
        {
            campaign: { campaignId: 'CAMPAIGN#c1' },
            catalog: { catalogId: 'CATALOG#cat1', isDeleted: false, products: [{ productId: 'p1', productName: 'P1', price: 10 }] },
            publicOrder: {
                customerName: 'Jane Doe',
                customerFirstName: 'Jane',
                customerLastName: 'Doe',
                paymentMethod: 'Venmo',
                orderDate: '2024-01-01T00:00:00Z',
                lineItems: [{ productId: 'p1', quantity: 1 }],
            },
            profileId: 'PROFILE#p1',
            campaignId: 'CAMPAIGN#c1',
            sellerName: 'My Shop',
        },
        overrides
    );
}

describe('create_public_order request', () => {
    it('refuses a partially-populated stash (wiring fault)', () => {
        assert.throws(() => request({ stash: {} }), /INTERNAL_ERROR: Order could not be written/);
        assert.throws(() => request({ stash: makeStash({ catalog: null }) }), /INTERNAL_ERROR: Order could not be written/);
    });

    it('refuses a soft-deleted catalog', () => {
        assert.throws(
            () => request({ stash: makeStash({ catalog: { isDeleted: true, products: [] } }) }),
            /INVALID_INPUT: Catalog is not available for this campaign/
        );
    });

    it('rejects a line item whose product is not in the catalog', () => {
        const stash = makeStash({ publicOrder: { customerName: 'J D', lineItems: [{ productId: 'missing', quantity: 1 }], paymentMethod: 'Venmo', orderDate: 'd' } });
        assert.throws(() => request({ stash }), /INVALID_INPUT: Product missing not found in catalog/);
    });

    it('uses TransactWriteItems with ConditionCheck on campaign and PutItem on orders', () => {
        const stash = makeStash();
        const req = request({ stash });
        assert.strictEqual(req.operation, 'TransactWriteItems');
        assert.strictEqual(req.transactItems.length, 2);

        // ARCH-1: each transact item MUST carry its own operation field -
        // AppSync rejects a TransactWriteItems item without one.
        // First item: UpdateItem on the campaigns table (#746) - maintains
        // the denormalized totalOrders/totalRevenue counters and, through its
        // condition, guards campaign existence (ARCH-1). DynamoDB forbids two
        // operations on one item in a transaction, so the guard is a
        // condition on this UpdateItem, not a separate ConditionCheck.
        // The source is templatefile()'d at deploy time; in tests the
        // placeholder stays literal, which also pins the real-name injection:
        // a hardcoded logical name here is what broke the deployed pipeline.
        const totalsUpdate = req.transactItems[0];
        assert.strictEqual(totalsUpdate.operation, 'UpdateItem');
        assert.strictEqual(totalsUpdate.table, '${campaigns_table_name}');
        assert.deepStrictEqual(totalsUpdate.key, { profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' });
        assert.strictEqual(totalsUpdate.update.expression, 'ADD #totalOrders :one, #totalRevenue :amount');
        assert.deepStrictEqual(totalsUpdate.update.expressionNames, {
            '#totalOrders': 'totalOrders',
            '#totalRevenue': 'totalRevenue',
        });
        assert.deepStrictEqual(totalsUpdate.update.expressionValues, { ':one': 1, ':amount': 10 });
        assert.strictEqual(totalsUpdate.condition.expression, 'attribute_exists(campaignId)');

        // Second item: PutItem on the orders table (placeholder stays literal
        // in tests; see the ConditionCheck item above).
        const putItem = req.transactItems[1];
        assert.strictEqual(putItem.operation, 'PutItem');
        assert.strictEqual(putItem.table, '${orders_table_name}');
        assert.strictEqual(putItem.key.orderId, 'ORDER#c1#auto-generated-id');
        assert.strictEqual(putItem.key.campaignId, 'CAMPAIGN#c1');

        // The exact row written is stashed for response()/the email step,
        // because a TransactWriteItems result carries only item keys.
        assert.strictEqual(stash.orderItem.orderId, 'ORDER#c1#auto-generated-id');
        assert.strictEqual(stash.orderItem.receiptToken, 'auto-generated-id');
        const item = putItem.attributeValues;
        assert.strictEqual(item.orderId, 'ORDER#c1#auto-generated-id');
        assert.strictEqual(item.campaignId, 'CAMPAIGN#c1');
        assert.strictEqual(item.orderSource, 'PUBLIC');
        assert.strictEqual(item.status, 'NEW');
        assert.strictEqual(item.sellerName, 'My Shop');
        assert.strictEqual(item.totalAmount, 10);
        assert.strictEqual(item.receiptToken, 'auto-generated-id');
        assert.deepStrictEqual(item.lineItems, [{ productId: 'p1', productName: 'P1', quantity: 1, pricePerUnit: 10, subtotal: 10 }]);

    });

    it('only writes the optional buyer fields that were provided', () => {
        const req = request({ stash: makeStash() });
        const item = req.transactItems[1].attributeValues;
        assert.ok(!('customerEmail' in item));
        assert.ok(!('customerPhone' in item));
        assert.ok(!('notes' in item));
    });
});

describe('create_public_order response', () => {
    it('maps TransactionCanceledException to NOT_FOUND (campaign deleted between increment and write)', () => {
        // ARCH-1: a cancellation at this step means the ConditionCheck found no
        // campaign row - the deleteCampaign raced in after step 6. No order row
        // was written, and the cap is enforced only by step 6, so this is
        // NOT_FOUND, not a limit error.
        assert.throws(
            () => response({ error: { type: 'DynamoDB:TransactionCanceledException', message: 'Transaction cancelled' } }),
            /NOT_FOUND: Campaign is no longer available/
        );
    });

    it('propagates any other datastore error', () => {
        assert.throws(() => response({ error: { message: 'boom', type: 'DynamoDB:InternalServerError' } }), /DynamoDB:InternalServerError: boom/);
    });

    it('composes the receipt from the stashed written row (TransactWriteItems result carries only keys)', () => {
        // A successful TransactWriteItems returns {keys: [...], cancellationReasons: null} -
        // written attributes are NOT returned, so response() reuses the row
        // request() stashed (atomicity makes the local copy exactly what stored).
        const ctx = {
            result: { keys: [{ profileId: 'PROFILE#p1', campaignId: 'CAMPAIGN#c1' }, { campaignId: 'CAMPAIGN#c1', orderId: 'ORDER#c1#auto-generated-id' }], cancellationReasons: null },
            stash: {
                orderItem: {
                    orderId: 'ORDER#c1#auto-generated-id',
                    receiptToken: 'auto-generated-id',
                    campaignId: 'CAMPAIGN#c1',
                    totalAmount: 0.1,
                },
            },
        };
        assert.deepStrictEqual(response(ctx), {
            orderId: 'ORDER#c1#auto-generated-id',
            receiptUrl: '/r/c1/auto-generated-id/auto-generated-id',
            totalAmount: 0.1,
            buyerEmailProvided: false,
            confirmationEmailSent: false,
        });
    });

    it('returns INTERNAL_ERROR when the stash carries no written order row', () => {
        assert.throws(() => response({ result: { keys: [] }, stash: {} }), /INTERNAL_ERROR: Order could not be written/);
    });
});
