import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './order_fulfillments_field_resolver.js';

describe('order_fulfillments_field_resolver request', () => {
    it('keys the Query on the already-prefixed orderId with exactly one ORDER# (#10.2)', () => {
        // Order ids carry the ORDER# prefix at rest (the orders-table sort key),
        // so the pk must be the orderId byte-for-byte — never ORDER#ORDER#<id>.
        const result = request({ source: { orderId: 'ORDER#camp-1#uuid-1' } });
        assert.strictEqual(result.operation, 'Query');
        assert.strictEqual(result.query.expression, 'pk = :pk');
        assert.deepStrictEqual(result.query.expressionValues, { ':pk': 'ORDER#camp-1#uuid-1' });
    });

    it('adds the ORDER# prefix once for an unprefixed orderId', () => {
        const result = request({ source: { orderId: 'camp-1#uuid-1' } });
        assert.deepStrictEqual(result.query.expressionValues, { ':pk': 'ORDER#camp-1#uuid-1' });
    });

    it('treats a foreign prefix as part of the id instead of re-prefixing twice', () => {
        const result = request({ source: { orderId: 'ORDER#ORDER#c#u' } });
        assert.deepStrictEqual(result.query.expressionValues, { ':pk': 'ORDER#ORDER#c#u' });
    });

    it('keys a missing orderId on the bare placeholder and never on null', () => {
        // A null key attribute would fail the Query outright; `ORDER#` matches
        // no fulfillment partition and the field honestly answers [].
        const result = request({ source: {} });
        assert.deepStrictEqual(result.query.expressionValues, { ':pk': 'ORDER#' });
    });

    it('reads the base table oldest-first with the fixed bounded limit', () => {
        const result = request({ source: { orderId: 'ORDER#camp-1#uuid-1' } });
        assert.strictEqual(result.index, null);
        assert.strictEqual(result.scanForward, true);
        assert.strictEqual(result.limit, 25);
        // No page token: §2.4.5's orderFulfillments admin query is the
        // paginated surface; this field is the bounded participant projection.
        assert.strictEqual(result.nextToken, undefined);
    });
});

describe('order_fulfillments_field_resolver response', () => {
    const adminRow = {
        pk: 'ORDER#camp-1#uuid-1',
        sk: 'FULFILLMENT#2026-11-01T10:00:00Z#fulfill-1',
        entityType: 'OrderFulfillment',
        fulfillmentId: 'fulfill-1',
        orderId: 'ORDER#camp-1#uuid-1',
        campaignId: 'CAMPAIGN#camp-1',
        profileId: 'PROFILE#prof-1',
        unitCampaignId: 'uc-1',
        lineItemId: 'line-1',
        productId: 'PROD#p-1',
        recordType: 'FULFILL',
        quantity: 2,
        source: 'SCOUT_CUSTODY',
        inventoryMovementId: 'MOVEMENT#m-1',
        reversalOfFulfillmentId: null,
        actorAccountId: 'ACCOUNT#admin-1',
        createdAt: '2026-11-01T10:00:00Z',
    };

    it('drops actorAccountId, inventoryMovementId, and the pk/sk/entityType keys (#10.2)', () => {
        const result = response({ result: { items: [adminRow] } });
        assert.strictEqual(result.length, 1);
        for (const forbidden of ['actorAccountId', 'inventoryMovementId', 'pk', 'sk', 'entityType']) {
            assert.ok(!(forbidden in result[0]), `${forbidden} must not reach the participant type`);
        }
        assert.deepStrictEqual(
            Object.keys(result[0]).sort(),
            [
                'campaignId',
                'createdAt',
                'fulfillmentId',
                'lineItemId',
                'orderId',
                'productId',
                'profileId',
                'quantity',
                'recordType',
                'reversalOfFulfillmentId',
                'source',
                'unitCampaignId',
            ],
        );
        // The participant-visible facts survive the projection unchanged.
        assert.strictEqual(result[0].quantity, 2);
        assert.strictEqual(result[0].source, 'SCOUT_CUSTODY');
        assert.strictEqual(result[0].createdAt, '2026-11-01T10:00:00Z');
    });

    it('answers the empty list for an Order with no fulfillment rows', () => {
        // The SDL list is [ParticipantOrderFulfillment!]!: no history is [],
        // never null.
        assert.deepStrictEqual(response({ result: { items: [], scannedCount: 0 } }), []);
        assert.deepStrictEqual(response({}), []);
    });

    it('propagates a data source error', () => {
        assert.throws(
            () => response({ error: { message: 'boom', type: 'DynamoDB:ValidationException' } }),
            /DynamoDB:ValidationException: boom/,
        );
    });
});
