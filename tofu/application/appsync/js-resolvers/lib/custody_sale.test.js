import { describe, it } from 'node:test';
import assert from 'node:assert';
import {
    MODE_NONE,
    MODE_CONSUME_SCOUT_CUSTODY,
    MARKER_STATUS_COMPLETED,
    MARKER_TTL_SECONDS,
    parseFulfillmentMode,
    idempotencyKeyFor,
    markerKeysFor,
    requestFingerprint,
    replayDecision,
    canonicalMoment,
    custodyPartitionKey,
    custodySortKey,
    movementSortKey,
    fulfillmentPartitionKey,
    custodyReadKeys,
    planLineConsumption,
    custodyDecrementAction,
    saleFulfillmentAction,
    saleMovementAction,
    saleMarkerAction
} from './custody_sale.js';

// §2.4.2 — the arithmetic and the row shapes of a door-to-door sale, pinned with no AWS in
// the room. The pipeline wiring is pinned in create_order_fn.test.js; what lives here is
// the part that must not drift: how much of a line a sale may consume, what a consumed
// line's rows look like, and what the guard conditions say.

describe('parseFulfillmentMode', () => {
    it('reads an absent mode as NONE, which is every order written before Wave 3', () => {
        assert.strictEqual(parseFulfillmentMode({}), MODE_NONE);
        assert.strictEqual(parseFulfillmentMode({ fulfillmentMode: null }), MODE_NONE);
        assert.strictEqual(parseFulfillmentMode(undefined), MODE_NONE);
    });

    it('passes both contract modes through', () => {
        assert.strictEqual(parseFulfillmentMode({ fulfillmentMode: MODE_NONE }), MODE_NONE);
        assert.strictEqual(parseFulfillmentMode({ fulfillmentMode: MODE_CONSUME_SCOUT_CUSTODY }), MODE_CONSUME_SCOUT_CUSTODY);
    });

    it('refuses a mode that is not one of the two, rather than reading it as NONE', () => {
        // A typo that silently became NONE would create an unfulfilled order out of a sale
        // the Scout believes drew on her custody.
        assert.throws(() => parseFulfillmentMode({ fulfillmentMode: 'CONSUME_KERNEL' }), /INVALID_INPUT: Unknown fulfillmentMode: CONSUME_KERNEL/);
    });
});

describe('idempotencyKeyFor', () => {
    it('needs no key for a NONE sale, because nothing moves stock', () => {
        assert.strictEqual(idempotencyKeyFor(MODE_NONE, {}), null);
    });

    it('requires a key for a custody sale, which is the mode that consumes stock', () => {
        assert.throws(
            () => idempotencyKeyFor(MODE_CONSUME_SCOUT_CUSTODY, {}),
            /INVALID_INPUT: idempotencyKey is required when fulfillmentMode = CONSUME_SCOUT_CUSTODY/
        );
    });

    it('trims the key and refuses an empty, oversized, or unsafe one', () => {
        assert.strictEqual(idempotencyKeyFor(MODE_CONSUME_SCOUT_CUSTODY, { idempotencyKey: '  sale-7  ' }), 'sale-7');
        assert.throws(() => idempotencyKeyFor(MODE_CONSUME_SCOUT_CUSTODY, { idempotencyKey: '   ' }), /idempotencyKey is required/);
        assert.throws(() => idempotencyKeyFor(MODE_CONSUME_SCOUT_CUSTODY, { idempotencyKey: 'a'.repeat(129) }), /1-128 characters/);
        assert.throws(() => idempotencyKeyFor(MODE_CONSUME_SCOUT_CUSTODY, { idempotencyKey: 'sale 7' }), /1-128 characters/);
        assert.strictEqual(idempotencyKeyFor(MODE_CONSUME_SCOUT_CUSTODY, { idempotencyKey: 'a#b:c_d-e.f1' }), 'a#b:c_d-e.f1');
    });
});

describe('markerKeysFor', () => {
    it('addresses actor + operation + campaign scope, then the caller key', () => {
        const keys = markerKeysFor('11111111-1111-4111-8111-111111111111', 'CAMPAIGN#c1', 'sale-7');
        assert.strictEqual(keys.pk, 'IDEM#11111111-1111-4111-8111-111111111111#createOrder#CAMPAIGN%23c1');
        assert.strictEqual(keys.sk, 'IDEM#sale-7');
    });

    it('escapes the delimiter inside a segment so two requests cannot share a marker', () => {
        // actor 'a#b' + operation 'c' must not collide with actor 'a' + operation 'b#c'.
        assert.notStrictEqual(markerKeysFor('a#b', 'c', 'k').pk, markerKeysFor('a', 'b#c', 'k').pk);
        assert.strictEqual(markerKeysFor('a#b', 'c', 'k').pk, 'IDEM#a%23b#createOrder#c');
    });
});

describe('requestFingerprint and replayDecision', () => {
    const values = () => ({
        mode: MODE_CONSUME_SCOUT_CUSTODY,
        profileId: 'PROFILE#a',
        campaignId: 'CAMPAIGN#c',
        customerName: 'Ada',
        customerPhone: null,
        customerAddress: null,
        orderDate: '2026-11-17T08:00:00Z',
        paymentMethod: 'Cash',
        notes: null,
        lineItems: [{ productId: 'P1', quantity: 2 }, { productId: 'P2', quantity: 1 }]
    });

    it('is stable for one request and changes when the request changes', () => {
        const one = requestFingerprint(values());
        assert.strictEqual(requestFingerprint(values()), one);
        const more = requestFingerprint({ ...values(), lineItems: [{ productId: 'P1', quantity: 3 }] });
        assert.notStrictEqual(one, more);
    });

    it('covers the fields an Order carries, not just its lines', () => {
        // A key reused with a different payment method, date, phone, address or note is a
        // different request, and answering it with the first Order would be a lie (API §3.1).
        const one = requestFingerprint(values());
        for (const change of [
            { paymentMethod: 'Card' },
            { orderDate: '2026-11-18T08:00:00Z' },
            { customerPhone: '555-0100' },
            { notes: 'gate code 4417' },
            { customerAddress: { street: '1 Main', city: 'Springfield', state: 'IL', zipCode: '62701' } }
        ]) {
            assert.notStrictEqual(requestFingerprint({ ...values(), ...change }), one, JSON.stringify(change));
        }
    });

    it('normalizes padding and treats an omitted address as no address', () => {
        const one = requestFingerprint(values());
        assert.strictEqual(requestFingerprint({ ...values(), customerName: '  Ada  ' }), one);
        assert.strictEqual(requestFingerprint({ ...values(), customerAddress: undefined }), one);
        assert.notStrictEqual(
            requestFingerprint({ ...values(), customerAddress: { street: '1 Main', city: 'Springfield', state: 'IL', zipCode: '62701' } }),
            requestFingerprint({ ...values(), customerAddress: { street: '2 Main', city: 'Springfield', state: 'IL', zipCode: '62701' } })
        );
    });

    it('proceeds when no marker exists', () => {
        assert.deepStrictEqual(replayDecision(null, 'fp'), { kind: 'ABSENT' });
    });

    it('reports an in-flight marker as a race rather than writing a second one', () => {
        assert.deepStrictEqual(replayDecision({ status: 'IN_FLIGHT' }, 'fp'), { kind: 'IN_FLIGHT' });
    });

    it('refuses the same key carrying a different body', () => {
        assert.deepStrictEqual(replayDecision({ status: MARKER_STATUS_COMPLETED, fingerprint: 'other', resultPayload: '{}' }, 'fp'), { kind: 'FINGERPRINT' });
    });

    it('calls a completed marker it cannot answer from corrupt, not absent', () => {
        assert.deepStrictEqual(replayDecision({ status: MARKER_STATUS_COMPLETED, fingerprint: 'fp' }, 'fp'), { kind: 'CORRUPT' });
        assert.deepStrictEqual(replayDecision({ status: 'TELLY_OFF', fingerprint: 'fp' }, 'fp'), { kind: 'CORRUPT' });
    });

    it('replays a completed marker whose fingerprint matches', () => {
        const marker = { status: MARKER_STATUS_COMPLETED, fingerprint: 'fp', resultPayload: '{"orderId":"ORDER#c#o1"}' };
        assert.deepStrictEqual(replayDecision(marker, 'fp'), { kind: 'REPLAY', marker: marker });
    });
});

describe('key grammar', () => {
    it('spells the custody, movement and fulfillment keys the Python writers spell', () => {
        assert.strictEqual(custodyPartitionKey('uc-1'), 'UNIT_CAMPAIGN#uc-1');
        assert.strictEqual(custodySortKey('CATALOG#d#p1', 'PROFILE#a'), 'PRODUCT#CATALOG#d#p1#CUSTODY#PROFILE#a');
        assert.strictEqual(movementSortKey('P1', '2026-11-17T08:00:00+00:00', 'm1'), 'PRODUCT#P1#MOVEMENT#2026-11-17T08:00:00+00:00#m1');
    });

    it('prefixes the fulfillment partition only once, because order ids already carry ORDER#', () => {
        assert.strictEqual(fulfillmentPartitionKey('ORDER#c1#o1'), 'ORDER#c1#o1');
        assert.strictEqual(fulfillmentPartitionKey('c1#o1'), 'ORDER#c1#o1');
    });

    it('canonicalizes the moment that sits inside a sort key', () => {
        // 'Z' sorts after '+00:00' for the same instant, so one writer's spelling would
        // order a sale's history away from the fulfillment that corrected it.
        assert.strictEqual(canonicalMoment('2026-11-17T08:00:00Z'), '2026-11-17T08:00:00+00:00');
        assert.strictEqual(canonicalMoment('2026-11-17T08:00:00+00:00'), '2026-11-17T08:00:00+00:00');
        assert.strictEqual(canonicalMoment('2026-11-17T03:00:00-05:00'), '2026-11-17T03:00:00-05:00');
    });
});

describe('custodyReadKeys', () => {
    it('reads one custody row per distinct product, strongly keyed by Scout and campaign', () => {
        const keys = custodyReadKeys('uc-1', 'PROFILE#a', [
            { productId: 'P1' },
            { productId: 'P2' },
            { productId: 'P1' }
        ]);
        assert.deepStrictEqual(keys, [
            { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P1#CUSTODY#PROFILE#a' },
            { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P2#CUSTODY#PROFILE#a' }
        ]);
    });

    it('reads no custody when the campaign has no Unit Campaign to hold it', () => {
        // An independent campaign, or one never joined, has no scoped custody row; a key
        // spelled from a null link would be a read for a scope this sale does not have.
        assert.deepStrictEqual(custodyReadKeys(null, 'PROFILE#a', [{ productId: 'P1' }]), []);
        assert.deepStrictEqual(custodyReadKeys('', 'PROFILE#a', [{ productId: 'P1' }]), []);
    });

    it('reads nothing for an order with no lines', () => {
        assert.deepStrictEqual(custodyReadKeys('uc-1', 'PROFILE#a', []), []);
        assert.deepStrictEqual(custodyReadKeys('uc-1', 'PROFILE#a', null), []);
    });
});

describe('planLineConsumption', () => {
    const lines = () => [
        { lineItemId: 'l1', productId: 'P1', quantity: 4, fulfilledQuantity: 0 },
        { lineItemId: 'l2', productId: 'P2', quantity: 2, fulfilledQuantity: 0 }
    ];
    const rows = [
        { productId: 'P1', withScoutQty: 3, version: 5 },
        { productId: 'P2', withScoutQty: 9, version: 2 }
    ];

    it('consumes min(ordered, available) per line and leaves the remainder unfulfilled', () => {
        const plan = planLineConsumption(lines(), rows);
        assert.deepStrictEqual(plan.consumed, [
            { lineItemId: 'l1', productId: 'P1', quantity: 3 },
            { lineItemId: 'l2', productId: 'P2', quantity: 2 }
        ]);
        assert.strictEqual(plan.custody.length, 2);
        assert.deepStrictEqual(plan.custody[0], { productId: 'P1', expectedVersion: 5, delta: -3 });
    });

    it('writes the consumed amount onto the line, which is what every later read starts from', () => {
        const enriched = lines();
        planLineConsumption(enriched, rows);
        assert.strictEqual(enriched[0].fulfilledQuantity, 3);
        // The remainder stays unfulfilled and is Council demand: §2.4.3 fulfills it from
        // Kernel stock, or §2.4.4 reverses it. It is never silently marked sold.
        assert.strictEqual(enriched[0].quantity, 4);
    });

    it('never blocks on insufficient custody: no row, no consumption, no writes', () => {
        const enriched = lines();
        const plan = planLineConsumption(enriched, []);
        assert.deepStrictEqual(plan.consumed, []);
        assert.deepStrictEqual(plan.custody, []);
        assert.strictEqual(enriched[0].fulfilledQuantity, 0);
    });

    it('draws two lines of one product on one shared availability', () => {
        // Two lines of the same product are two chances to spend the same three Kernels;
        // the second line sees what the first left.
        const enriched = [
            { lineItemId: 'l1', productId: 'P1', quantity: 2, fulfilledQuantity: 0 },
            { lineItemId: 'l2', productId: 'P1', quantity: 2, fulfilledQuantity: 0 }
        ];
        const plan = planLineConsumption(enriched, [{ productId: 'P1', withScoutQty: 3, version: 7 }]);
        assert.deepStrictEqual(plan.consumed, [
            { lineItemId: 'l1', productId: 'P1', quantity: 2 },
            { lineItemId: 'l2', productId: 'P1', quantity: 1 }
        ]);
        // One decrement for one row, pinned at the version that was read, so the
        // transaction never carries two operations on one item.
        assert.deepStrictEqual(plan.custody, [{ productId: 'P1', expectedVersion: 7, delta: -3 }]);
    });

    it('treats a zero-quantity custody row as nothing to consume', () => {
        const plan = planLineConsumption(lines(), [
            { productId: 'P1', withScoutQty: 0, version: 4 },
            { productId: 'P2', withScoutQty: 9, version: 2 }
        ]);
        assert.deepStrictEqual(plan.consumed, [{ lineItemId: 'l2', productId: 'P2', quantity: 2 }]);
    });
});

describe('custodyDecrementAction', () => {
    it('pins the version it read and the non-negative floor in one condition', () => {
        const action = custodyDecrementAction('inv-table', 'uc-1', 'P1', 'PROFILE#a', { productId: 'P1', expectedVersion: 5, delta: -3 }, '2026-11-17T08:00:00+00:00');
        assert.strictEqual(action.operation, 'UpdateItem');
        assert.strictEqual(action.table, 'inv-table');
        assert.deepStrictEqual(action.key, { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P1#CUSTODY#PROFILE#a' });
        assert.strictEqual(
            action.update.expression,
            'SET #version = #version + :one, #updatedAt = :updatedAt, #withScoutQty = #withScoutQty + :scoutDelta'
        );
        assert.strictEqual(action.condition.expression, '#version = :expectedVersion AND #withScoutQty >= :scoutFloor');
        assert.deepStrictEqual(action.condition.expressionValues[':expectedVersion'], 5);
        assert.deepStrictEqual(action.condition.expressionValues[':scoutFloor'], 3);
        assert.deepStrictEqual(action.update.expressionValues[':scoutDelta'], -3);
    });
});

describe('saleFulfillmentAction', () => {
    const opts = {
        orderId: 'ORDER#c1#o1',
        fulfillmentId: 'f1',
        movementId: 'm1',
        campaignId: 'CAMPAIGN#c1',
        profileId: 'PROFILE#a',
        unitId: 'unit-1',
        unitCampaignId: 'uc-1',
        lineItemId: 'l1',
        productId: 'P1',
        quantity: 3,
        actorAccountId: 'sub-1',
        occurredAt: '2026-11-17T08:00:00+00:00'
    };

    it('is the §5.19 FULFILL record of a SCOUT_CUSTODY sale, linked to its movement', () => {
        const action = saleFulfillmentAction('ful-table', opts);
        assert.strictEqual(action.table, 'ful-table');
        assert.deepStrictEqual(action.key, { pk: 'ORDER#c1#o1', sk: 'FULFILLMENT#2026-11-17T08:00:00+00:00#f1' });
        const item = action.attributeValues;
        assert.strictEqual(item.entityType, 'OrderFulfillment');
        assert.strictEqual(item.recordType, 'FULFILL');
        assert.strictEqual(item.source, 'SCOUT_CUSTODY');
        // A positive quantity on a FULFILL record: the direction is the record type, never
        // a signed number, so a reader cannot mis-add the history.
        assert.strictEqual(item.quantity, 3);
        assert.strictEqual(item.inventoryMovementId, 'm1');
        assert.strictEqual(item.actorAccountId, 'sub-1');
        // The Order's immutable originating scope, copied: a later roster join must not
        // move this sale's demand into another Unit (ORD-API-02-04).
        assert.strictEqual(item.unitId, 'unit-1');
        assert.strictEqual(item.unitCampaignId, 'uc-1');
        assert.strictEqual(item.fulfillmentVersion, undefined);
        assert.strictEqual(item.reversalOfFulfillmentId, undefined);
    });
});

describe('saleMovementAction', () => {
    const opts = {
        unitCampaignId: 'uc-1',
        productId: 'P1',
        movementId: 'm1',
        occurredAt: '2026-11-17T08:00:00+00:00',
        actorAccountId: 'sub-1',
        idempotencyKey: 'sale-7',
        quantity: 3,
        profileId: 'PROFILE#a',
        orderId: 'ORDER#c1#o1',
        fulfillmentId: 'f1'
    };

    it('moves With Scout down and Kernel stock not at all', () => {
        const action = saleMovementAction('inv-table', opts);
        assert.deepStrictEqual(action.key, { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P1#MOVEMENT#2026-11-17T08:00:00+00:00#m1' });
        const item = action.attributeValues;
        assert.strictEqual(item.movementType, 'INDIVIDUAL_FULFILL');
        assert.strictEqual(item.withScoutDelta, -3);
        // The Kernel balance already moved when the Unit issued these Kernels to the
        // Scout; a zero here is the record saying it moved again for no reason.
        assert.strictEqual(item.kernelPhysicalDelta, 0);
        assert.strictEqual(item.soldPossessionDelta, 0);
        assert.strictEqual(item.assignedDelta, 0);
        assert.strictEqual(item.councilOnOrderDelta, 0);
        assert.strictEqual(item.profileId, 'PROFILE#a');
        assert.strictEqual(item.orderId, 'ORDER#c1#o1');
        assert.strictEqual(item.fulfillmentId, 'f1');
        assert.strictEqual(item.idempotencyKey, 'sale-7');
        // No aggregate balance version exists for a custody-only move.
        assert.strictEqual(item.inventoryVersion, undefined);
    });
});

describe('saleMarkerAction', () => {
    it('records the completed Order and refuses a second insert on the same key', () => {
        const keys = markerKeysFor('sub-1', 'CAMPAIGN#c1', 'sale-7');
        const action = saleMarkerAction('ful-table', keys, {
            fingerprint: 'fp',
            expiresAtEpoch: 1704067200 + MARKER_TTL_SECONDS,
            orderId: 'ORDER#c1#o1',
            orderItem: { orderId: 'ORDER#c1#o1', fulfillmentVersion: 0 }
        });
        assert.deepStrictEqual(action.key, { pk: 'IDEM#sub-1#createOrder#CAMPAIGN%23c1', sk: 'IDEM#sale-7' });
        const item = action.attributeValues;
        assert.strictEqual(item.status, MARKER_STATUS_COMPLETED);
        assert.strictEqual(item.resultId, 'ORDER#c1#o1');
        assert.strictEqual(JSON.parse(item.resultPayload).orderId, 'ORDER#c1#o1');
        assert.strictEqual(item.expiresAtEpoch, 1704067200 + MARKER_TTL_SECONDS);
        assert.strictEqual(action.condition.expression, 'attribute_not_exists(#pk) AND attribute_not_exists(#sk)');
    });
});
