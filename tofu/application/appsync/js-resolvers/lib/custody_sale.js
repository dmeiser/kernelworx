import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './ids.js';

// §2.4.2 — `createOrder(fulfillmentMode = CONSUME_SCOUT_CUSTODY)`: the door-to-door sale.
//
// A Scout sells door-to-door out of the Kernels the Unit issued into her custody (§5.9).
// The sale is still an ordinary individual Order -- the existing createOrder pipeline owns
// it, and §2.4 says so ("Keep this under the Order/custody write owner") -- but it must
// consume what she is actually holding, record one `SCOUT_CUSTODY` fulfillment per line,
// and leave the remainder as unfulfilled Council demand. Data model §8.5 states the
// boundary in one sentence: capture the current joined scope, create the Order with
// `fulfillmentVersion = 0`, consume only available custody in that originating campaign,
// write the fulfillments, update custody and movements -- in ONE operation.
//
// Two rules from sequence diagram §8.2 shape everything below, and both are easy to get
// backwards:
//   * Kernel stock is NEVER decremented. Those Kernels already left the Unit's unassigned
//     balance when they were issued to the Scout; taking them from the balance again
//     counts one Kernel as two sales.
//   * Insufficient custody NEVER blocks the sale. A Scout who sold more than she is
//     holding made a stock error, and the answer is a partial fulfillment plus Council
//     numbers that show the gap -- not a refused sale that loses the customer's order.
//     Per line the sale takes `min(orderedQty, availableWithScoutQty)`, and a line that
//     finds nothing writes no fulfillment, no movement and no custody update at all.
//
// What the sale DOES refuse is a custody row that moved underneath it. The `version` pin
// on each decrement is what makes "she holds three" a statement about the row this request
// read rather than about a row that changed between the read and the commit, and the
// `withScoutQty >= <consumed>` floor in the same condition is CUST-04: With Scout can
// never go negative. A failed pin cancels the whole transaction, Order included.
//
// Why this is a library and not a pipeline step: an AppSync resolver is capped at 10
// pipeline functions and createOrder already carries exactly 10 (ARCH-1), so the work goes
// into the two steps that have room -- the join-guard read, which gains the custody and
// marker reads as one cross-table BatchGetItem, and the Order write, which gains the
// fulfillment, movement, custody and marker actions in the TransactWriteItems it already
// issues. Nothing here touches a datastore: every function is pure over the values its
// caller passes, which is what lets lib/custody_sale.test.js pin the arithmetic with no
// AWS. Table names are arguments rather than literals, so this file also carries no
// templatefile() placeholder (#570).
//
// APPSYNC_JS 1.0.0 rejects `try`/`catch`, `throw`, `continue`, the classic `for` loop,
// `++`, the `in` operator, regexes, and the `String()`/`Number()` conversion globals, and
// has no hash function. Every branch below is written in the subset the runtime accepts;
// tests/unit/check_appsync_js_compatibility.test.ts is the gate that keeps it that way.

export const MODE_NONE = 'NONE';
export const MODE_CONSUME_SCOUT_CUSTODY = 'CONSUME_SCOUT_CUSTODY';

// The §5.19 fulfillment taxonomy for a sale: the record type is always FULFILL (a sale
// never reverses itself; §2.4.4 owns that) and the source is always SCOUT_CUSTODY (the
// Kernels came out of the Scout's trunk, which is exactly why §2.4.3 refuses
// SCOUT_CUSTODY -- that screen would be consuming the same custody a second time).
export const RECORD_TYPE_FULFILL = 'FULFILL';
export const SOURCE_SCOUT_CUSTODY = 'SCOUT_CUSTODY';

// §5.8: the movement type that carries an individual sale's stock effect, and the only
// type whose allowed deltas are exactly the two this sale moves (Kernel 0, With Scout
// -consumed) while its required links are the Order and the fulfillment it belongs to.
export const MOVEMENT_INDIVIDUAL_FULFILL = 'INDIVIDUAL_FULFILL';

// Marker shape shared with the Python side (`src/utils/mutations.py`): the same key
// grammar, the same `expiresAtEpoch` TTL, the same two statuses. A createOrder marker is
// written already COMPLETED, because an APPSYNC_JS function gets one datastore call and
// has no second phase in which to back-fill its result -- so there is no IN_FLIGHT window
// to recover from, and a concurrent same-key attempt collides on the marker condition
// instead. `MAX_SALE_TRANSACT_ACTIONS` is the same 90-action budget as
// `WritePlan.max_actions` (data model §8.10): DynamoDB caps a transaction at 100 actions
// and the product contract refuses a plan that spends the margin.
export const MARKER_STATUS_COMPLETED = 'COMPLETED';
export const MARKER_STATUS_IN_FLIGHT = 'IN_FLIGHT';
export const MARKER_TTL_SECONDS = 7 * 24 * 60 * 60;
export const MAX_SALE_TRANSACT_ACTIONS = 90;

// The idempotency-key alphabet is `_KEY_SAFE` in src/utils/mutations.py, spelled out here
// because APPSYNC_JS has no regexes. `#` is legal in a key and is also the marker
// partition key's own segment delimiter, so it is escaped in a segment the same way
// `_escape_key_segment` does it ('%23', unambiguous because `%` is not a legal key
// character).
const KEY_SAFE_CHARACTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789#:_-.';
const CREATE_ORDER_OPERATION = 'createOrder';
const IDEMPOTENCY_KEY_MAX_CHARS = 128;

// --- Mode and key ------------------------------------------------------------------

// Default is NONE, and an absent field is the ordinary case: every order created before
// Wave 3, and every order that is not a door-to-door sale, reads exactly as it did before
// this field existed (§2.4 acceptance ORD-API-01-01).
export function parseFulfillmentMode(input) {
    const mode = input ? input.fulfillmentMode : null;
    if (mode == null) {
        return MODE_NONE;
    }
    if (mode !== MODE_NONE && mode !== MODE_CONSUME_SCOUT_CUSTODY) {
        util.error('Unknown fulfillmentMode: ' + mode, 'INVALID_INPUT');
        return MODE_NONE;
    }
    return mode;
}

// A custody sale requires a key, because it is the only order mode that moves stock: with
// no key, a retry of a sale that already committed would consume the Scout's Kernels
// again. A `NONE` sale has nothing to make idempotent -- it writes no stock effect -- and
// its behavior is unchanged, so a key on one is accepted and simply not used.
export function idempotencyKeyFor(mode, input) {
    if (mode !== MODE_CONSUME_SCOUT_CUSTODY) {
        return null;
    }
    const raw = input && input.idempotencyKey != null ? input.idempotencyKey + '' : '';
    const key = raw.trim();
    if (key === '') {
        util.error('idempotencyKey is required when fulfillmentMode = CONSUME_SCOUT_CUSTODY', 'INVALID_INPUT');
        return null;
    }
    if (key.length > IDEMPOTENCY_KEY_MAX_CHARS || !isKeySafe(key)) {
        util.error('idempotencyKey must be 1-128 characters of A-Z a-z 0-9 # : _ - .', 'INVALID_INPUT');
        return null;
    }
    return key;
}

function isKeySafe(value) {
    for (const character of value) {
        if (KEY_SAFE_CHARACTERS.indexOf(character) === -1) {
            return false;
        }
    }
    return true;
}

function escapeKeySegment(value) {
    // `split().join()` rather than `replace()`: the string form of replace changes only
    // the first occurrence, and a segment can carry several '#'.
    return (value + '').split('#').join('%23');
}

// The marker address, in the grammar `marker_partition_key`/`marker_sort_key` build on the
// Python side: actor + operation + resource scope, then the caller's key. The scope is the
// Scout Campaign the Order belongs to, so the same key used for a different campaign is
// genuinely a different request.
export function markerKeysFor(actorId, campaignId, idempotencyKey) {
    return {
        pk: 'IDEM#' + escapeKeySegment(actorId) + '#' + CREATE_ORDER_OPERATION + '#' + escapeKeySegment(campaignId),
        sk: 'IDEM#' + idempotencyKey
    };
}

// Not a hash -- APPSYNC_JS has none -- but the same guarantee the Python fingerprint gives:
// the same key with a different body is a caller bug, and answering it with the first
// Order would be a silent lie. The canonical form is short and fixed-order on purpose: it
// is stored verbatim in the marker and compared verbatim on retry, so nothing has to be
// re-derived the same way twice.
export function requestFingerprint(input, mode, profileId, campaignId) {
    const lines = [];
    for (const line of (input && input.lineItems) || []) {
        lines.push(line.productId + '|' + line.quantity);
    }
    return JSON.stringify({
        mode: mode,
        profileId: profileId,
        campaignId: campaignId,
        customerName: input && input.customerName != null ? input.customerName : null,
        lineItems: lines
    });
}

// What a marker read means. Returning a decision rather than raising keeps the caller's
// error vocabulary its own (`RESOURCE_BUSY` for the in-flight race, `INVALID_INPUT` for
// the reused key, `INTERNAL_ERROR` for a marker it cannot answer from) and keeps this
// module free of control flow the runtime would refuse.
export function replayDecision(marker, fingerprint) {
    if (!marker) {
        return { kind: 'ABSENT' };
    }
    const status = marker.status;
    if (status === MARKER_STATUS_IN_FLIGHT) {
        return { kind: 'IN_FLIGHT' };
    }
    if (status !== MARKER_STATUS_COMPLETED) {
        return { kind: 'CORRUPT' };
    }
    if (marker.fingerprint !== fingerprint) {
        return { kind: 'FINGERPRINT' };
    }
    if (typeof marker.resultPayload !== 'string') {
        return { kind: 'CORRUPT' };
    }
    return { kind: 'REPLAY', marker: marker };
}

// --- Key grammar (mirrors src/utils/inventory_models.py and order_fulfillment_models.py) --

// The identity inside a composite sort key is stored exactly as written, so these helpers
// add only the '#'-delimited markers and never rewrite the id itself.
export function custodyPartitionKey(unitCampaignId) {
    return 'UNIT_CAMPAIGN#' + unitCampaignId;
}

export function custodySortKey(productId, profileId) {
    return 'PRODUCT#' + productId + '#CUSTODY#' + profileId;
}

export function movementSortKey(productId, moment, movementId) {
    return 'PRODUCT#' + productId + '#MOVEMENT#' + moment + '#' + movementId;
}

// Idempotent on purpose, exactly like `fulfillment_partition_key`: this application's Order
// ids already carry `ORDER#` (lib/order_keys.js `buildOrderKey`), and data model §6.5
// spells the fulfillment partition `ORDER#<orderId>`. Prefixing blindly would produce
// `ORDER#ORDER#...` and the history read would find nothing.
export function fulfillmentPartitionKey(orderId) {
    return normalizeIdOrPrefix(orderId, 'ORDER#');
}

// `#`-delimited sort key of one fulfillment: the moment is the sort dimension and the id
// only breaks a same-instant tie, so the moment must be canonicalized to one UTC spelling
// before it goes in the key. `util.time.nowISO8601()` writes a `Z`; the writers on the
// Python side (`normalize_moment`) canonicalize to `+00:00`, and a `Z` row sorts after
// every `+00:00` row for the same instant because 'Z' > '+'. No regex and no Date here --
// both are refused by the runtime.
export function canonicalMoment(iso8601) {
    const value = iso8601 + '';
    if (value.length > 1 && value.indexOf('Z') === value.length - 1) {
        return value.substring(0, value.length - 1) + '+00:00';
    }
    return value;
}

// --- The read the guard step issues -------------------------------------------------

// One BatchGetItem key pair per DISTINCT product on the Order: two lines of the same
// product draw on one custody row, so one read and one versioned write cover both.
export function custodyReadKeys(unitCampaignId, profileId, lineItems) {
    const keys = [];
    const seen = {};
    if (typeof unitCampaignId !== 'string' || unitCampaignId === '') {
        // No link means no Unit Campaign holds this Scout's custody -- an independent
        // campaign, or one that has never been joined -- so the inventory table is simply
        // not part of the read. A key of `UNIT_CAMPAIGN#` would find nothing and would
        // also make the read look like a scoped sale it is not.
        return keys;
    }
    for (const line of lineItems || []) {
        if (line && typeof line.productId === 'string' && !Object.hasOwn(seen, line.productId)) {
            seen[line.productId] = true;
            keys.push(
                util.dynamodb.toMapValues({
                    pk: custodyPartitionKey(unitCampaignId),
                    sk: custodySortKey(line.productId, profileId)
                })
            );
        }
    }
    return keys;
}

// --- The plan ----------------------------------------------------------------------

function quantityOrZero(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

// `min(orderedQty, availableWithScoutQty)` per line, in the Order's own line order,
// drawing one shared availability per product. Two lines of the same product cannot each
// believe they hold the whole custody, so the first line's take reduces what the second
// can take.
//
// The plan also writes each consumed line's `fulfilledQuantity`, because that is the
// number the rest of the system reads: §5.19's per-line arithmetic, the Council demand a
// report computes, and §2.4.3's "quantity <= unfulfilled" guard all start from it. A sale
// that consumed 2 of 4 leaves 2 unfulfilled -- and that remainder is precisely the Council
// problem the Unit Admin then fulfills from Kernel stock or reverses.
export function planLineConsumption(enrichedLineItems, custodyRows) {
    const available = {};
    for (const row of custodyRows || []) {
        if (row && typeof row.productId === 'string') {
            available[row.productId] = {
                qty: quantityOrZero(row.withScoutQty),
                version: quantityOrZero(row.version)
            };
        }
    }

    const consumed = [];
    const perProduct = {};
    for (const line of enrichedLineItems) {
        const hold = Object.hasOwn(available, line.productId) ? available[line.productId] : null;
        const take = hold === null ? 0 : Math.min(quantityOrZero(line.quantity), hold.qty);
        if (take > 0) {
            line.fulfilledQuantity = take;
            consumed.push({ lineItemId: line.lineItemId, productId: line.productId, quantity: take });
            if (!Object.hasOwn(perProduct, line.productId)) {
                perProduct[line.productId] = {
                    productId: line.productId,
                    expectedVersion: hold.version,
                    delta: 0
                };
            }
            perProduct[line.productId].delta = perProduct[line.productId].delta - take;
            hold.qty = hold.qty - take;
        }
    }

    const custody = [];
    for (const productId of Object.keys(perProduct)) {
        custody.push(perProduct[productId]);
    }
    return { consumed: consumed, custody: custody };
}

// --- The write actions -------------------------------------------------------------

// One version-guarded decrement. The version pin and the non-negative floor are ONE
// condition, which is what makes the two guards indivisible: a transaction that could pass
// the floor while failing the pin would be reading a row it never read.
export function custodyDecrementAction(inventoryTable, unitCampaignId, productId, profileId, entry, occurredAt) {
    const floor = -entry.delta;
    const expressionValues = {
        ':one': 1,
        ':updatedAt': occurredAt,
        ':expectedVersion': entry.expectedVersion,
        ':scoutDelta': entry.delta
    };
    let condition = '#version = :expectedVersion';
    if (floor > 0) {
        expressionValues[':scoutFloor'] = floor;
        condition = condition + ' AND #withScoutQty >= :scoutFloor';
    }
    return {
        operation: 'UpdateItem',
        table: inventoryTable,
        key: util.dynamodb.toMapValues({
            pk: custodyPartitionKey(unitCampaignId),
            sk: custodySortKey(productId, profileId)
        }),
        update: {
            expression: 'SET #version = #version + :one, #updatedAt = :updatedAt, #withScoutQty = #withScoutQty + :scoutDelta',
            expressionNames: {
                '#version': 'version',
                '#updatedAt': 'updatedAt',
                '#withScoutQty': 'withScoutQty'
            },
            expressionValues: util.dynamodb.toMapValues(expressionValues)
        },
        condition: {
            expression: condition,
            expressionNames: {
                '#version': 'version',
                '#updatedAt': 'updatedAt',
                '#withScoutQty': 'withScoutQty'
            },
            expressionValues: util.dynamodb.toMapValues(expressionValues)
        }
    };
}

// The §5.19 append-only fulfillment row: positive quantity on a FULFILL record, the
// Order's immutable originating scope copied onto it (never re-derived later), and the id
// of the movement that moved the stock -- which for a custody sale is the custody
// decrement's own movement, minted together with this row so the two can never disagree.
export function saleFulfillmentAction(fulfillmentTable, opts) {
    const moment = opts.occurredAt;
    return {
        operation: 'PutItem',
        table: fulfillmentTable,
        key: util.dynamodb.toMapValues({
            pk: fulfillmentPartitionKey(opts.orderId),
            sk: 'FULFILLMENT#' + moment + '#' + opts.fulfillmentId
        }),
        attributeValues: util.dynamodb.toMapValues({
            entityType: 'OrderFulfillment',
            fulfillmentId: opts.fulfillmentId,
            orderId: opts.orderId,
            campaignId: opts.campaignId,
            profileId: opts.profileId,
            unitId: opts.unitId,
            unitCampaignId: opts.unitCampaignId,
            lineItemId: opts.lineItemId,
            productId: opts.productId,
            recordType: RECORD_TYPE_FULFILL,
            quantity: opts.quantity,
            source: SOURCE_SCOUT_CUSTODY,
            inventoryMovementId: opts.movementId,
            actorAccountId: opts.actorAccountId,
            createdAt: moment
        })
    };
}

// The §5.8 movement row for one consumed line. `kernelPhysicalQty` does not move, and the
// row says so with a zero delta rather than by omitting the attribute: every movement type
// carries the same five delta attributes, and a reader reconciling the trail adds the
// column, so a missing cell and a zero are not the same statement. `inventoryVersion` is
// absent because there is no aggregate balance version to point at -- the row that moved
// is the custody row, and its own version is what the pin guarded.
export function saleMovementAction(inventoryTable, opts) {
    const moment = opts.occurredAt;
    return {
        operation: 'PutItem',
        table: inventoryTable,
        key: util.dynamodb.toMapValues({
            pk: custodyPartitionKey(opts.unitCampaignId),
            sk: movementSortKey(opts.productId, moment, opts.movementId)
        }),
        attributeValues: util.dynamodb.toMapValues({
            entityType: 'InventoryMovement',
            unitCampaignId: opts.unitCampaignId,
            movementId: opts.movementId,
            productId: opts.productId,
            movementType: MOVEMENT_INDIVIDUAL_FULFILL,
            occurredAt: moment,
            actorAccountId: opts.actorAccountId,
            idempotencyKey: opts.idempotencyKey,
            kernelPhysicalDelta: 0,
            soldPossessionDelta: 0,
            withScoutDelta: -opts.quantity,
            assignedDelta: 0,
            councilOnOrderDelta: 0,
            profileId: opts.profileId,
            orderId: opts.orderId,
            fulfillmentId: opts.fulfillmentId
        })
    };
}

// The marker, written already COMPLETED with the Order it produced as its replayable
// result. `attribute_not_exists` on both key parts is the whole concurrency story: a second
// request carrying the same key cannot insert a second marker, so it cancels its own
// transaction instead of consuming the Scout's custody twice (ORD-API-02-03).
export function saleMarkerAction(fulfillmentTable, keys, opts) {
    return {
        operation: 'PutItem',
        table: fulfillmentTable,
        key: util.dynamodb.toMapValues({ pk: keys.pk, sk: keys.sk }),
        attributeValues: util.dynamodb.toMapValues({
            fingerprint: opts.fingerprint,
            status: MARKER_STATUS_COMPLETED,
            expiresAtEpoch: opts.expiresAtEpoch,
            resultId: opts.orderId,
            resultPayload: JSON.stringify(opts.orderItem)
        }),
        condition: {
            expression: 'attribute_not_exists(#pk) AND attribute_not_exists(#sk)',
            expressionNames: { '#pk': 'pk', '#sk': 'sk' }
        }
    };
}
