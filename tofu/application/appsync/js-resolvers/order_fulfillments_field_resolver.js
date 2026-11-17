import { util } from '@aws-appsync/utils';
import { normalizeIdOrPrefix } from './lib/ids.js';

// Order.fulfillments field resolver (Show & Sell wave 3, API §10.2).
//
// UNIT resolver on the OrderFulfillmentsDS data source. Authorization rides the
// parent: the Order row itself is authorized by its parent pipeline
// (getOrder / listOrdersByCampaign), and this field only projects that one
// Order's custody/quantity history. Because AppSync always executes an attached
// field resolver and its result OVERWRITES any pipeline-attached value (the
// #330 PaymentMethod.qrCodeUrl trap), no pipeline may attach `fulfillments` to
// an Order item — this resolver owns the field, so there is no earlyReturn.
//
// Layout (data model §6.5): one partition per Order — pk `ORDER#<orderId>`, sk
// `FULFILLMENT#<createdAt>#<fulfillmentId>` (a reversal takes the deterministic
// `REVERSAL#<reversalOfFulfillmentId>` sk). Order ids already carry the ORDER#
// prefix (the orders-table sort key), so the pk is the orderId guarded to
// EXACTLY ONE ORDER# prefix — the same rule the Python write path applies in
// src/utils/order_fulfillment_models.py, spelled identically here via the
// single normalization owner, lib/ids.js.
//
// The read contract (FUNC-4): a participant gets this Order's history, in the
// order the history happened, and never a silently shortened one.
//
// * Strongly consistent. A Scout who just had a line fulfilled opens the Order and
//   must see the record; an eventually consistent read answers "no history" to a
//   mutation she can see the effect of. §5.19's history is the record a participant
//   disputes against, so it is read the way it was written.
// * One page, and the page starts at the NEWEST sort key. The sort key groups the
//   two record types (`FULFILLMENT#...` then `REVERSAL#...`), so an ascending page is
//   precisely the page that can hold 25 fulfillments and hide every reversal. Reading
//   descending means a truncated window drops the oldest fulfillments, which is the
//   half a participant can reconstruct from the Order's own line quantities; a missing
//   reversal is invisible to her.
// * Chronological within the result. Sort-key order is type-grouped, not temporal:
//   the reversal of the first fulfillment sorts after the tenth fulfillment. The
//   participant contract is (createdAt, fulfillmentId), and createdAt is a canonical
//   UTC moment (same formatter on both write paths, `+00:00` offset, so a
//   lexicographic compare is a temporal one), so the page is sorted by the composite
//   `createdAt|fulfillmentId` before it is returned. `Array.prototype.sort` with no
//   comparator is the only sort the APPSYNC_JS runtime allows, and a string array is
//   exactly that.
// * Truncation is announced, not swallowed. The field type is a plain list with no
//   nextToken (§10.2), and the paginated surface is §2.4.5's `orderFulfillments`
//   admin query -- so when DynamoDB reports a last-evaluated key, this resolver says
//   so in the response's `errors` channel (`util.appendError` keeps the field value)
//   instead of answering a partial history as if it were the whole one.
const HISTORY_PAGE_LIMIT = 500;

// Fields that must never leave this resolver: the two §10.2 admin-audit
// attributes plus the DynamoDB key/entity plumbing. Delete-by-denylist, not
// allow-listed projection: an audit field added to the row later cannot leak
// into the participant type by omission from a hand-maintained allow list —
// and the ParticipantOrderFulfillment SDL type keeps anything undeclared
// unqueryable, so this list is defense in depth, not the only wall.
const HIDDEN_ADMIN_FIELDS = ['actorAccountId', 'inventoryMovementId', 'pk', 'sk', 'entityType'];

export function request(ctx) {
    // normalizeIdOrPrefix guarantees exactly one ORDER# prefix (already- and
    // unprefixed ids both land on `ORDER#<id>`; a falsy orderId yields the
    // bare `ORDER#` placeholder, which matches no fulfillment partition and
    // answers [] rather than emitting a null key attribute).
    const pk = normalizeIdOrPrefix(ctx.source.orderId, 'ORDER#');

    return {
        operation: 'Query',
        index: null, // base table: the fulfillment partition is addressed by its own key
        consistentRead: true, // read-your-own-write: the record follows the mutation the caller just saw
        scanForward: false, // newest sort keys first, so a truncated page drops old fulfillments, not reversals
        limit: HISTORY_PAGE_LIMIT,
        query: {
            expression: 'pk = :pk',
            expressionValues: util.dynamodb.toMapValues({ ':pk': pk }),
        },
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const items = ctx.result && Array.isArray(ctx.result.items) ? ctx.result.items : [];
    if (ctx.result && ctx.result.lastEvaluatedKey) {
        // Never a silent partial history: the list type has no cursor to carry the fact,
        // so the response says it. `appendError` adds to the response `errors` channel
        // WITHOUT discarding the field value, which is the only way a plain-list field
        // can tell the caller the page ended.
        util.appendError(
            'This fulfillment history is longer than one page, so the oldest records are not included. A Unit Admin reads the paginated orderFulfillments audit for the complete history.',
            'TRUNCATED',
            null,
            { truncated: true, returned: items.length }
        );
    }
    return chronological(items).map(toParticipantRow);
}

// (createdAt, fulfillmentId), oldest first. Built as sortable strings because the
// APPSYNC_JS runtime rejects a sort comparator; the composite is unique because
// fulfillmentId is, so the order is total and a retry answers identically.
function chronological(items) {
    const keyed = [];
    const byKey = {};
    for (const item of items) {
        const key = (item.createdAt == null ? '' : item.createdAt + '') + '|' + (item.fulfillmentId == null ? '' : item.fulfillmentId + '');
        keyed.push(key);
        byKey[key] = item;
    }
    keyed.sort();
    const ordered = [];
    for (const key of keyed) {
        ordered.push(byKey[key]);
    }
    return ordered;
}

// The participant projection: fulfillmentId, lineItemId, productId, recordType,
// quantity, source, reversalOfFulfillmentId, createdAt — everything the row
// carries EXCEPT the hidden admin/key fields.
function toParticipantRow(item) {
    const row = {};
    for (const key of Object.keys(item)) {
        if (HIDDEN_ADMIN_FIELDS.indexOf(key) === -1) {
            row[key] = item[key];
        }
    }
    return row;
}
