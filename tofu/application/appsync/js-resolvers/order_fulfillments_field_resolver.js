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
// The sort key begins with createdAt, so scanForward true answers the history
// oldest-first. This field is a bounded projection, not the paginated surface:
// §2.4.5's `orderFulfillments` admin query is where paging (and the full
// actor/movement audit) lives, so the limit is fixed and the field type
// deliberately carries no nextToken. A row count beyond the cap is read
// honestly as the oldest 25 records; the admin query is the complete view.
const HISTORY_PAGE_LIMIT = 25;

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
        scanForward: true, // sk starts with createdAt, so ascending sk is chronological
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
    return items.map(toParticipantRow);
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
