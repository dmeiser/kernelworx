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

    it('reads the partition strongly, newest sort keys first, bounded', () => {
        const result = request({ source: { orderId: 'ORDER#camp-1#uuid-1' } });
        assert.strictEqual(result.index, null);
        // FUNC-4: the record follows the mutation. A participant who just had a line
        // fulfilled must see it, so this read is consistent with the write.
        assert.strictEqual(result.consistentRead, true);
        // The AppSync Query request field is `scanIndexForward`. A `scanForward` key is
        // unknown to the runtime and silently keeps the ascending default, which is
        // exactly the page that can hold N fulfillments and hide every reversal (the sort
        // key groups record TYPES: `FULFILLMENT#...` then `REVERSAL#...`).
        assert.strictEqual(result.scanIndexForward, false);
        assert.strictEqual(result.scanForward, undefined, 'the wrong field name would be ignored by AppSync');
        // PageInput documents 1-100 with a default of 50.
        assert.strictEqual(result.limit, 50);
        assert.strictEqual(result.nextToken, undefined);
    });

    it('honours a caller page size and clamps it to the PageInput contract', () => {
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: { page: { limit: 10 } } }).limit, 10);
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: { page: { limit: 5000 } } }).limit, 100);
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: { page: { limit: 0 } } }).limit, 50);
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: { page: { limit: -3 } } }).limit, 50);
    });

    it('continues from the caller cursor, so the whole history is reachable by this field', () => {
        // FUNC-5 (re-review): a participant pages her own Order's history. Without a
        // cursor the field can only ever show one page, and the omitted tail would be
        // reachable only through the Unit-Admin `orderFulfillments` audit she cannot query.
        const cursor = '{"pk":"ORDER#c#u","sk":"REVERSAL#f9"}';
        const result = request({ source: { orderId: 'ORDER#c#u' }, args: { page: { limit: 25, cursor: cursor } } });

        assert.strictEqual(result.nextToken, cursor);
        assert.strictEqual(result.limit, 25);
        assert.strictEqual(result.consistentRead, true);
        assert.strictEqual(result.scanIndexForward, false);
    });

    it('starts from the first page for an absent or empty cursor', () => {
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: { page: {} } }).nextToken, undefined);
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: { page: { cursor: '' } } }).nextToken, undefined);
        assert.strictEqual(request({ source: { orderId: 'ORDER#c#u' }, args: {} }).nextToken, undefined);
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

    function itemsOf(ctx) {
        return response(ctx).items;
    }

    it('drops actorAccountId, inventoryMovementId, and the pk/sk/entityType keys (#10.2)', () => {
        const items = itemsOf({ result: { items: [adminRow] } });
        assert.strictEqual(items.length, 1);
        for (const forbidden of ['actorAccountId', 'inventoryMovementId', 'pk', 'sk', 'entityType']) {
            assert.ok(!Object.hasOwn(items[0], forbidden), `${forbidden} must not reach the participant type`);
        }
        assert.deepStrictEqual(
            Object.keys(items[0]).sort(),
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
        assert.strictEqual(items[0].quantity, 2);
        assert.strictEqual(items[0].source, 'SCOUT_CUSTODY');
        assert.strictEqual(items[0].createdAt, '2026-11-01T10:00:00Z');
    });

    it('answers the empty page for an Order with no fulfillment rows', () => {
        // `items` is [ParticipantOrderFulfillment!]!: no history is [], never null,
        // and an empty page carries no cursor.
        assert.deepStrictEqual(response({ result: { items: [], scannedCount: 0 } }), {
            items: [],
            pageInfo: { endCursor: null, hasNextPage: false },
        });
        assert.deepStrictEqual(response({}).items, []);
        assert.strictEqual(response({}).pageInfo.endCursor, null);
    });

    it('propagates a data source error', () => {
        assert.throws(
            () => response({ error: { message: 'boom', type: 'DynamoDB:ValidationException' } }),
            /DynamoDB:ValidationException: boom/,
        );
    });
});

// FUNC-4 / FUNC-5: the participant history must be the history, in the order it happened,
// and must be reachable in full by the participant herself. Storage order is sort-key
// order, which groups record types rather than moments: the reversal of the FIRST
// fulfillment sorts after the TENTH fulfillment. So the resolver owns the temporal order
// within a page, and the cursor owns the rest of it.
describe('order_fulfillments_field_resolver response: chronological within the page, cursor beyond it', () => {
    function record(fulfillmentId, createdAt, recordType) {
        return { fulfillmentId: fulfillmentId, createdAt: createdAt, recordType: recordType, quantity: 1 };
    }

    it('orders a mixed history by (createdAt, fulfillmentId), not by sort key', () => {
        // Exactly what one Query returns for a fulfilled, then reversed, then fulfilled
        // Order: sk order puts the reversal last even though it happened second.
        const fulfillOld = record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL');
        const reversal = record('rev-1', '2026-11-01T11:00:00+00:00', 'REVERSAL');
        const fulfillNew = record('ful-2', '2026-11-01T12:00:00+00:00', 'FULFILL');

        const history = response({ result: { items: [fulfillOld, fulfillNew, reversal] } });

        assert.deepStrictEqual(history.items.map(function (row) { return row.fulfillmentId; }), ['ful-1', 'rev-1', 'ful-2']);
    });

    it('breaks a same-moment tie deterministically on fulfillmentId', () => {
        const b = record('ful-b', '2026-11-01T10:00:00+00:00', 'FULFILL');
        const a = record('ful-a', '2026-11-01T10:00:00+00:00', 'FULFILL');

        const history = response({ result: { items: [b, a] } });

        assert.deepStrictEqual(history.items.map(function (row) { return row.fulfillmentId; }), ['ful-a', 'ful-b']);
    });

    it('orders moments written with different fractional widths consistently', () => {
        // The JS sale path stores milliseconds and the Python fulfillment path stores
        // microseconds. A lexicographic compare of canonical UTC moments still compares
        // them correctly, and a retry answers with the same order.
        const ms = record('ful-ms', '2026-11-01T10:00:00.5+00:00', 'FULFILL');
        const micros = record('ful-us', '2026-11-01T10:00:00.500001+00:00', 'FULFILL');

        const history = response({ result: { items: [micros, ms] } });

        assert.deepStrictEqual(history.items.map(function (row) { return row.fulfillmentId; }), ['ful-ms', 'ful-us']);
    });

    it('carries the continuation the AppSync Query result reports, as this field own cursor', () => {
        // FUNC-5: the AppSync JS Query result names the continuation `nextToken`.
        // `lastEvaluatedKey` is the raw DynamoDB spelling and is never delivered here,
        // so a resolver that reads it reports every truncated page as a complete one.
        const token = { pk: 'ORDER#camp-1#uuid-1', sk: 'FULFILLMENT#2026-10-01T09:00:00+00:00#ful-old' };
        const history = response({ result: { items: [record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL')], nextToken: token } });

        assert.strictEqual(history.items.length, 1);
        assert.deepStrictEqual(history.pageInfo.endCursor, token);
        assert.strictEqual(history.pageInfo.hasNextPage, true);
    });

    it('reports no further page when the read finished', () => {
        const history = response({ result: { items: [record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL')] } });

        assert.strictEqual(history.pageInfo.endCursor, null);
        assert.strictEqual(history.pageInfo.hasNextPage, false);
    });

    it('ignores a raw lastEvaluatedKey, which is not the contract, rather than inventing a cursor', () => {
        const history = response({
            result: { items: [record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL')], lastEvaluatedKey: { pk: 'ORDER#c#u' } }
        });

        assert.strictEqual(history.pageInfo.endCursor, null);
        assert.strictEqual(history.pageInfo.hasNextPage, false);
    });

    it('round-trips the cursor: a second page continues from the first', () => {
        // The whole history is reachable without any administrative surface: page one
        // hands back a cursor, and the same field reads the rest from it.
        const first = response({ result: { items: [record('ful-2', '2026-11-01T12:00:00+00:00', 'FULFILL')], nextToken: 'PAGE-2' } });
        assert.strictEqual(first.pageInfo.endCursor, 'PAGE-2');

        const secondRequest = request({ source: { orderId: 'ORDER#camp-1#uuid-1' }, args: { page: { cursor: first.pageInfo.endCursor } } });
        assert.strictEqual(secondRequest.nextToken, 'PAGE-2');

        const second = response({ result: { items: [record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL')] } });
        assert.deepStrictEqual(second.items.map(function (row) { return row.fulfillmentId; }), ['ful-1']);
        assert.strictEqual(second.pageInfo.hasNextPage, false);
    });
});
