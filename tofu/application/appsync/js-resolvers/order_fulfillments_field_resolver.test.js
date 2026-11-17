import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './order_fulfillments_field_resolver.js';
import { appendedErrorsList, resetAppendedErrors } from '@aws-appsync/utils';

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
        // The sort key groups record TYPES (`FULFILLMENT#...` then `REVERSAL#...`), so an
        // ascending page is exactly the page that can hold N fulfillments and hide every
        // reversal. Descending means a truncated window drops old fulfillments instead.
        assert.strictEqual(result.scanForward, false);
        assert.ok(result.limit >= 100, 'a 25-record history is a routine Order, not a truncation case');
        // No page token: §2.4.5's orderFulfillments admin query is the paginated
        // surface; this field is the bounded participant projection, and a truncated page
        // is announced in the response errors instead.
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

// FUNC-4: the participant history must be the history, in the order it happened, and
// must never be a silently shortened one. Storage order is sort-key order, which groups
// record types rather than moments: the reversal of the FIRST fulfillment sorts after
// the TENTH fulfillment. So the resolver owns the temporal order.
describe('order_fulfillments_field_resolver response: chronological and complete-or-announced', () => {
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

        assert.deepStrictEqual(history.map(function (row) { return row.fulfillmentId; }), ['ful-1', 'rev-1', 'ful-2']);
    });

    it('breaks a same-moment tie deterministically on fulfillmentId', () => {
        const b = record('ful-b', '2026-11-01T10:00:00+00:00', 'FULFILL');
        const a = record('ful-a', '2026-11-01T10:00:00+00:00', 'FULFILL');

        const history = response({ result: { items: [b, a] } });

        assert.deepStrictEqual(history.map(function (row) { return row.fulfillmentId; }), ['ful-a', 'ful-b']);
    });

    it('orders moments written with different fractional widths consistently', () => {
        // The JS sale path stores milliseconds and the Python fulfillment path stores
        // microseconds. A lexicographic compare of canonical UTC moments still compares
        // them correctly, and a retry answers with the same order.
        const ms = record('ful-ms', '2026-11-01T10:00:00.5+00:00', 'FULFILL');
        const micros = record('ful-us', '2026-11-01T10:00:00.500001+00:00', 'FULFILL');

        const history = response({ result: { items: [micros, ms] } });

        assert.deepStrictEqual(history.map(function (row) { return row.fulfillmentId; }), ['ful-ms', 'ful-us']);
    });

    it('announces a truncated page instead of passing it off as the whole history', () => {
        resetAppendedErrors();
        const items = [record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL')];

        const history = response({
            result: { items: items, lastEvaluatedKey: { pk: 'ORDER#camp-1#uuid-1', sk: 'FULFILLMENT#x' } }
        });

        // The value survives: appendError does not interrupt the handler, which is the
        // only way a plain-list field can report a partial page.
        assert.strictEqual(history.length, 1);
        const appended = appendedErrorsList();
        assert.strictEqual(appended.length, 1);
        assert.match(appended[0].message, /longer than one page/);
        assert.deepStrictEqual(appended[0].errorInfo, { truncated: true, returned: 1 });
        resetAppendedErrors();
    });

    it('stays silent when the page is the whole partition', () => {
        resetAppendedErrors();

        response({ result: { items: [record('ful-1', '2026-11-01T10:00:00+00:00', 'FULFILL')] } });

        assert.deepStrictEqual(appendedErrorsList(), []);
    });
});
