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
// The read contract (FUNC-4, re-review): a participant gets this Order's history
// completely, in the order it happened, and never a shortened one she is not told
// about.
//
// * Strongly consistent. A Scout who just had a line fulfilled opens the Order and
//   must see the record; an eventually consistent read answers "no history" to a
//   mutation she can see the effect of. §5.19's history is the record a participant
//   disputes against, so it is read the way it was written.
// * Paginated, on the caller's own field. The field returns a page plus
//   `pageInfo`, and `page.cursor` continues it — so the complete history is
//   reachable by the participant herself, and an omitted tail is never a reason to
//   send her to the Unit-Admin `orderFulfillments` audit (§2.4.5), which is a
//   different, privileged projection she cannot query.
// * The page starts at the NEWEST sort key. `scanIndexForward` is the field the
//   AppSync Query request object documents; a `scanForward` key is simply unknown
//   to the runtime, so the read silently keeps the ascending default. The sort key
//   groups the two record types (`FULFILLMENT#...` then `REVERSAL#...`), so an
//   ascending first page is precisely the page that can hold 25 fulfillments and
//   hide every reversal. Reading descending puts the newest activity — including
//   reversals — on the page a participant reads first.
// * Chronological within a page. Sort-key order is type-grouped, not temporal: the
//   reversal of the first fulfillment sorts after the tenth fulfillment. The
//   participant contract is (createdAt, fulfillmentId), and createdAt is a canonical
//   UTC moment (same formatter on both write paths, `+00:00` offset, so a
//   lexicographic compare is a temporal one), so each page is sorted by the composite
//   `createdAt|fulfillmentId` before it is returned. `Array.prototype.sort` with no
//   comparator is the only sort the APPSYNC_JS runtime allows, and a string array is
//   exactly that.
// * Continuation is read from `nextToken`, the field the AppSync Query result
//   contract actually delivers — not the raw DynamoDB `lastEvaluatedKey`, which is
//   never present here and would make every truncated read look complete.
//
// Page size follows the shared `PageInput` contract (1-100, default 50); the limit
// is clamped rather than trusted. §5.19 keeps one Order's history small in practice,
// so one page normally is the whole history.
const MAX_PAGE_LIMIT = 100;
const DEFAULT_PAGE_LIMIT = 50;

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
    const page = ctx.args && ctx.args.page ? ctx.args.page : null;

    const queryRequest = {
        operation: 'Query',
        index: null, // base table: the fulfillment partition is addressed by its own key
        consistentRead: true, // read-your-own-write: the record follows the mutation the caller just saw
        scanIndexForward: false, // newest sort keys first; see the read contract above
        limit: pageLimit(page),
        query: {
            expression: 'pk = :pk',
            expressionValues: util.dynamodb.toMapValues({ ':pk': pk }),
        },
    };
    if (page && typeof page.cursor === 'string' && page.cursor !== '') {
        queryRequest.nextToken = page.cursor;
    }
    return queryRequest;
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const result = ctx.result || {};
    const items = Array.isArray(result.items) ? result.items : [];
    // The AppSync JS Query result delivers continuation as `nextToken`. Carrying it out
    // as `pageInfo.endCursor` is what makes the rest of the history reachable by this
    // same field: a caller who sees a cursor asks for the next page instead of being
    // told some of her own Order's records exist somewhere she cannot read.
    const endCursor = result.nextToken ? result.nextToken : null;

    return {
        items: chronological(items).map(toParticipantRow),
        pageInfo: {
            endCursor: endCursor,
            hasNextPage: endCursor !== null,
        },
    };
}

function pageLimit(page) {
    if (page && typeof page.limit === 'number' && page.limit > 0) {
        return Math.min(page.limit, MAX_PAGE_LIMIT);
    }
    return DEFAULT_PAGE_LIMIT;
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
