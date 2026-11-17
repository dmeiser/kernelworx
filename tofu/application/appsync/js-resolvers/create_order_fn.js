import { util, runtime } from '@aws-appsync/utils';
import { validatePhone, validateAddress } from './lib/validation.js';
import { normalizeId } from './lib/ids.js';
import { enrichLineItems } from './lib/line_items.js';
import { buildOrderKey } from './lib/order_keys.js';
import { orderOrigin, membershipGuardCurrencyCheck, cancelledTransactIndexes } from './lib/order_origin.js';
import {
    MODE_CONSUME_SCOUT_CUSTODY,
    MAX_SALE_TRANSACT_ACTIONS,
    MARKER_TTL_SECONDS,
    parseFulfillmentMode,
    idempotencyKeyFor,
    markerKeysFor,
    requestFingerprint,
    grantNamesUnit,
    replayDecision,
    canonicalMoment,
    planLineConsumption,
    custodyDecrementAction,
    saleFulfillmentAction,
    saleMovementAction,
    saleMarkerAction
} from './lib/custody_sale.js';

// Loaded via Terraform templatefile() (functions_orders.tf), like the public
// write step it clones: the Order write runs as a TransactWriteItems whenever
// a membership guard row was read (FUNC-3), and a TransactWriteItems item's
// `table` field is the literal AWS table name -- AppSync does not default it
// to the datasource's table. Only declared placeholders may be interpolated
// (#570; tests/unit/check_templatefile_escaping.test.ts), so this file carries
// no dollar-brace sequence outside the four constants below.
const ordersTableName = '${orders_table_name}';
const campaignsTableName = '${campaigns_table_name}';
const unitCampaignsTableName = '${unit_campaigns_table_name}';
const inventoryTableName = '${inventory_table_name}';
const orderFulfillmentsTableName = '${order_fulfillments_table_name}';

function validateCustomer(input) {
    if (!input.customerName || (typeof input.customerName === 'string' && !input.customerName.trim())) {
        util.error('Customer name is required', 'INVALID_INPUT');
        return {};
    }

    // `+ ''` rather than String(...): APPSYNC_JS has no String() global, and code
    // that calls it is refused at CreateFunction/UpdateFunction.
    const phoneValue = input.customerPhone != null ? (input.customerPhone + '').trim() : '';
    const hasAddress = input.customerAddress != null;
    let customerPhone = undefined;

    if (phoneValue !== '') {
        const phoneResult = validatePhone(phoneValue);
        if (!phoneResult.valid) {
            util.error(phoneResult.error, 'INVALID_INPUT');
            return { customerPhone: undefined };
        }
        customerPhone = phoneResult.value;
    }

    if (hasAddress) {
        const addressResult = validateAddress(input.customerAddress);
        if (!addressResult.valid) {
            util.error(addressResult.error, 'INVALID_INPUT');
            return { customerPhone };
        }
    }

    return { customerPhone };
}

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'INVALID_INPUT');
        return;
    }
}

// The Cognito subject of the caller, or null. The marker partition key starts with it, so
// an unauthenticated caller has nothing to key a sale against -- and `createOrder` is
// Cognito-only anyway (no @aws_api_key), so a null here means the request has no session.
function callerAccount(ctx) {
    const claims = ctx && ctx.identity ? ctx.identity.claims : null;
    return claims && typeof claims.sub === 'string' && claims.sub !== '' ? claims.sub : null;
}

// The §2.4.2 replay decision for a custody sale, before anything is written.
//
// A completed marker answers the original Order and writes nothing, which is the whole
// point of ORD-API-02-03: the Scout's Kernels were consumed once, and a retry that
// re-ran the plan would consume them again. `sync_campaign_totals_fn` then sees no
// `totalsDelta` and passes the answer through, so the campaign's counters move once too.
function replayAnswer(ctx, fingerprint) {
    const decision = replayDecision(ctx.stash.idempotencyMarker || null, fingerprint);
    if (decision.kind === 'ABSENT') {
        return null;
    }
    if (decision.kind === 'REPLAY') {
        return JSON.parse(decision.marker.resultPayload);
    }
    if (decision.kind === 'IN_FLIGHT') {
        util.error('This sale is still being processed for that idempotencyKey', 'RESOURCE_BUSY');
        return null;
    }
    if (decision.kind === 'FINGERPRINT') {
        util.error('That idempotencyKey was already used for a different order', 'INVALID_INPUT');
        return null;
    }
    // A COMPLETED marker with no readable payload is a fault in our own write, not a
    // caller error: the request did commit, and we cannot say what it produced.
    util.error('The recorded result of this sale could not be read back', 'INTERNAL_ERROR');
    return null;
}

// The sale's custody scope, decided from the two strongly consistent reads the pipeline
// already made -- and the reason both are needed:
//
//   * The membership guard answers "which Unit Campaign is this Scout Campaign joined to
//     RIGHT NOW", which is what §1.4.3 stamps on the Order and therefore what §8.5 means
//     by "that originating campaign". It cannot, however, key the custody read: the read
//     rides the same BatchGetItem that reads the guard, so the key must exist before the
//     answer arrives.
//   * The Campaign row's own `unitCampaignId` (strongly read one step earlier) is the
//     latest link, and the join claim writes it in the same operation that writes the
//     guard's pointer. So while a join is live, the two names are the same Unit Campaign,
//     and the link is a valid key for the read the guard then confirms.
//
// The two can still disagree -- a join or a removal landing between the two reads -- and
// that is the one case the sale refuses rather than guesses at. Consuming custody under a
// Unit Campaign the Order is not stamped with would move one Unit's stock for another
// Unit's demand, which is the exact cross-tenant class AUTH-U exists to prevent, so the
// request is a retryable CONFLICT with nothing written. A guard that names no join is not
// a refusal at all: an independent sale consumes no custody (API contract §10.1) and the
// Order stands with every line unfulfilled.
function saleCustodyScope(ctx, unitCampaignId) {
    const read = ctx.stash.custodySaleRead || null;
    if (unitCampaignId === null) {
        return null;
    }
    if (read === null || read.unitCampaignId !== unitCampaignId) {
        util.error('The campaign changed scope while this order was being placed; try again', 'CONFLICT');
        return null;
    }
    return read;
}

// SEC-1 (§2.4.2): a door-to-door custody sale moves the Unit's stock, and the Unit
// that lent the Scout that stock -- not the Profile that owns the Campaign -- is the
// tenant whose inventory moves. So §2.4.2 authorizes it two ways, and this is where the
// two are weighed, because it is the first step that has both answers in hand:
//
//   * Profile Owner/WRITE: `check_share_permissions` stopped answering FORBIDDEN for this
//     one field+mode and left its verdict on the stash, so an owner or a WRITE share takes
//     the sale with no further check -- the same path every order write used before Wave 3.
//   * Unit Admin: the `UNIT#<unitId> / GRANT#<accountId>` row data model §5.2 makes the
//     only Unit credential, read strongly by the guard step. Its existence IS the grant
//     (revocation deletes the row), matching `src/utils/unit_auth.py`.
//
// Fail-closed in every direction. Neither half is one FORBIDDEN, phrased the way the
// share step phrases its own denial so the two paths are not distinguishable to the
// caller. A sale whose Campaign names no Unit has no Unit Admin to authorize, so only the
// Profile path can carry it. And the grant must name the Unit the *guard* names -- the
// batch was keyed off the Campaign's retained link, so a link that disagrees with the
// live join can never turn a grant for Unit A into authority over Unit B's custody (the
// `saleCustodyScope` CONFLICT below catches the custody half of that disagreement).
// `role` is deliberately not checked: `unit_auth` does not check it either, and a second
// definition of "admin" is how two gates start disagreeing about the same person.
function authorizeCustodySale(ctx, origin, actorAccountId) {
    if (ctx.stash && ctx.stash.profileWriteAuthorized === true) {
        return;
    }
    const denied = 'Forbidden: a custody sale needs the profile owner, an account with WRITE permission on the profile, or an admin of the campaign Unit';
    if (origin === null || origin.unitId === null || actorAccountId === null) {
        util.error(denied, 'FORBIDDEN');
        return;
    }
    if (!grantNamesUnit(ctx.stash.unitAdminGrant, origin.unitId, actorAccountId)) {
        util.error(denied, 'FORBIDDEN');
    }
}

// One campaign counter ADD, the same shape sync_campaign_totals_fn issues for every other
// authenticated order write: ADD, and `attribute_exists(campaignId)` so a campaign deleted
// mid-mutation is a no-op rather than a recreated counter row. The revenue is already
// cent-quantized by lib/line_items.js (it is cents divided by 100), so it needs no
// re-rounding -- the trailing ADD would only re-round it for show.
function campaignTotalsAction(profileId, campaignId, revenue) {
    return {
        operation: 'UpdateItem',
        table: campaignsTableName,
        key: util.dynamodb.toMapValues({ profileId: profileId, campaignId: campaignId }),
        update: {
            expression: 'ADD #totalOrders :count, #totalRevenue :revenue',
            expressionNames: { '#totalOrders': 'totalOrders', '#totalRevenue': 'totalRevenue' },
            expressionValues: util.dynamodb.toMapValues({ ':count': 1, ':revenue': revenue })
        },
        condition: {
            expression: 'attribute_exists(campaignId)'
        }
    };
}

// The sale's custody, fulfillment and movement actions, or null when the sale consumes
// nothing. The line objects are annotated in place by planLineConsumption, so the Order
// row and the fulfillment records are built from one decision and cannot disagree about
// how much of a line was sold out of the Scout's trunk.
function custodySaleActions(scope, opts) {
    const plan = planLineConsumption(opts.enrichedLineItems, opts.custodyRows);
    if (plan.consumed.length === 0) {
        // Zero custody is not an error and writes nothing at all: no fulfillment record, no
        // movement, no custody update. The order still stands, and the whole quantity shows
        // up as unfulfilled Council demand -- which is the number a Unit Admin acts on.
        return null;
    }

    const actions = [];
    const custodyOffsets = [];
    for (const entry of plan.custody) {
        custodyOffsets.push(actions.length);
        actions.push(custodyDecrementAction(inventoryTableName, opts.unitCampaignId, entry.productId, scope.profileId, entry, opts.occurredAt));
    }
    for (const line of plan.consumed) {
        // One movement per consumed line, and the fulfillment names that movement's id.
        // `util.autoId()` mints a fresh value per call, so the pair is unique by
        // construction; §5.19's rule that a stock-moving fulfillment must name its
        // movement is satisfied by construction too, since both ids are made here.
        const movementId = util.autoId();
        const fulfillmentId = util.autoId();
        const fulfilled = {
            orderId: opts.orderId,
            fulfillmentId: fulfillmentId,
            movementId: movementId,
            campaignId: opts.campaignId,
            profileId: opts.profileId,
            unitId: opts.unitId,
            unitCampaignId: opts.unitCampaignId,
            lineItemId: line.lineItemId,
            productId: line.productId,
            quantity: line.quantity,
            actorAccountId: opts.actorAccountId,
            occurredAt: opts.occurredAt
        };
        actions.push(saleFulfillmentAction(orderFulfillmentsTableName, fulfilled));
        actions.push(
            saleMovementAction(inventoryTableName, {
                unitCampaignId: opts.unitCampaignId,
                productId: line.productId,
                movementId: movementId,
                occurredAt: opts.occurredAt,
                actorAccountId: opts.actorAccountId,
                idempotencyKey: opts.idempotencyKey,
                quantity: line.quantity,
                profileId: opts.profileId,
                orderId: opts.orderId,
                fulfillmentId: fulfillmentId
            })
        );
    }
    return { actions: actions, custodyOffsets: custodyOffsets };
}

export function request(ctx) {
    const input = ctx.args.input;
    const campaign = ctx.stash.campaign;
    const catalog = ctx.stash.catalog;

    const mode = parseFulfillmentMode(input);

    // Authorization (§2.4.2: "Profile Owner/WRITE or Unit Admin") is decided by
    // `authorizeCustodySale` below, before the sale's marker is replayed or its custody is
    // planned. The Profile half is the three steps ahead of this one; the Unit half is the
    // grant row the guard step fetched into the batch this sale already issues.

    const { customerPhone } = validateCustomer(input);
    validateOrderDate(input.orderDate);

    const profileIdRaw = input.profileId || ctx.stash.profileId;
    const profileId = normalizeId(profileIdRaw, 'PROFILE#');
    if (!profileId) {
        util.error('Invalid profileId', 'INVALID_INPUT');
    }

    const campaignIdRaw = input.campaignId || ctx.stash.campaignId;
    const campaignId = normalizeId(campaignIdRaw, 'CAMPAIGN#');
    if (!campaignId) {
        util.error('Invalid campaignId', 'INVALID_INPUT');
    }

    // The key is validated against the mode before anything is minted, so a custody sale
    // that cannot be made idempotent fails without leaving an Order behind.
    const idempotencyKey = idempotencyKeyFor(mode, input);
    const actorAccountId = callerAccount(ctx);
    if (idempotencyKey !== null && actorAccountId === null) {
        // The marker partition key starts with the caller's subject. Without a session
        // there is no scope to key the sale against, so a retry could not find it -- and a
        // marker every account could guess into is not an idempotency guard at all.
        util.error('A signed-in account is required to place a custody sale', 'UNAUTHORIZED');
    }

    if (!campaign || !campaign.profileId) {
        util.error('Campaign profile association missing', 'INVALID_INPUT');
    }
    const normalizedCampaignProfileId = normalizeId(campaign.profileId, 'PROFILE#');
    if (normalizedCampaignProfileId !== profileId) {
        util.error('Campaign does not belong to the specified profile', 'UNAUTHORIZED');
    }

    if (!input.lineItems || input.lineItems.length === 0) {
        util.error('Order must have at least one line item', 'INVALID_INPUT');
    }

    if (!catalog) {
        util.error('Catalog could not be loaded for this campaign', 'INVALID_INPUT');
    }

    // Scope and authorization are settled before the idempotency replay, not after it: a
    // COMPLETED marker holds the committed Order, and answering a caller who is not
    // authorized with somebody else's stored Order would disclose it without writing
    // anything -- a read is enough to leak.
    const origin = orderOrigin(ctx.stash.membershipGuard);
    if (mode === MODE_CONSUME_SCOUT_CUSTODY) {
        authorizeCustodySale(ctx, origin, actorAccountId);
    }

    const { enrichedLineItems, totalAmountCents } = enrichLineItems(input.lineItems, catalog);

    // The fingerprint is the identity of the REQUEST, so it has to cover what the request
    // will actually write -- including the parts enrichment normalized. Computing it from
    // the raw arguments and then writing normalized values would let the same Order
    // fingerprint differently from the request that produced its marker, and a later
    // attempt that changed only, say, the payment method would replay the first Order
    // instead of being refused (API §3.1).
    const fingerprint = requestFingerprint({
        mode: mode,
        profileId: profileId,
        campaignId: campaignId,
        customerName: input.customerName,
        customerPhone: customerPhone,
        customerAddress: input.customerAddress,
        orderDate: input.orderDate,
        paymentMethod: input.paymentMethod,
        notes: input.notes,
        lineItems: enrichedLineItems
    });

    if (idempotencyKey !== null) {
        const replayed = replayAnswer(ctx, fingerprint);
        if (replayed !== null) {
            // Answered from the marker: no write at all. A sale's campaign counter rode
            // that committed transaction, so there is nothing left to add here either.
            return runtime.earlyReturn(replayed);
        }
    }

    const totalAmount = totalAmountCents / 100;

    // The ORDER#<campaign without prefix>#<suffix> grammar has one owner
    // (#534): lib/order_keys.js buildOrderKey, the exact shape parseOrderKey
    // and parseEmbeddedCampaignId read back.
    const orderId = buildOrderKey(campaignId, util.autoId());
    const now = util.time.nowISO8601();

    const orderItem = {
        orderId: orderId,
        profileId: profileId,
        campaignId: campaignId,
        customerName: input.customerName,
        orderDate: input.orderDate,
        paymentMethod: input.paymentMethod,
        lineItems: enrichedLineItems,
        totalAmount: totalAmount,
        createdAt: now,
        updatedAt: now,
        // §5.19: every fulfillment and reversal of this Order's lines increments
        // this version, so a Kernel fulfilling two lines from two screens cannot
        // double-spend one line's unfulfilled quantity. It is written as 0 at
        // creation rather than left absent: an absent attribute would make the
        // first fulfillment's version guard a different shape from every later
        // one, and an absent read is indistinguishable from a corrupt row.
        fulfillmentVersion: 0
    };

    // §1.4.3 (API-FIX-05): the joined scope is captured here and never derived
    // again -- which is only sound if it is captured from something that answers
    // the question *now*. The Campaign's own unitId/unitCampaignId pair is the
    // latest link and removal keeps it, so an Order written after the Scout left
    // would follow them into another Unit. The membership guard is the current
    // answer: the join claim denormalized the parent Unit beside the pointer,
    // so the guard alone names both halves of the scope with one strong read.
    orderItem.unitId = origin.unitId;
    orderItem.unitCampaignId = origin.unitCampaignId;

    if (customerPhone) {
        orderItem.customerPhone = customerPhone;
    }
    if (input.customerAddress) {
        orderItem.customerAddress = input.customerAddress;
    }
    if (input.notes) {
        orderItem.notes = input.notes;
    }

    if (!campaignId || typeof campaignId !== 'string') {
        util.error('Invalid campaignId for PutItem: ' + campaignId, 'INVALID_INPUT');
    }
    if (!orderId || typeof orderId !== 'string') {
        util.error('Invalid orderId for PutItem: ' + orderId, 'INVALID_INPUT');
    }

    for (const li of enrichedLineItems) {
        if (typeof li.productName !== 'string') {
            li.productName = null;
        }
    }

    // §2.4.2 (CONSUME_SCOUT_CUSTODY): the door-to-door sale. Data model §8.5 requires the
    // Order, the custody decrements, the fulfillment records, the movements and the marker
    // to commit as one operation, so they are staged here into the transaction this step
    // already issues rather than written afterwards. Kernel stock is not touched: those
    // Kernels left the unassigned balance when the Unit issued them to the Scout.
    let sale = null;
    if (mode === MODE_CONSUME_SCOUT_CUSTODY) {
        const scope = saleCustodyScope(ctx, origin.unitCampaignId);
        if (scope !== null) {
            sale = custodySaleActions(scope, {
                enrichedLineItems: enrichedLineItems,
                custodyRows: ctx.stash.custodyRows || [],
                orderId: orderId,
                campaignId: campaignId,
                profileId: profileId,
                unitId: origin.unitId,
                unitCampaignId: origin.unitCampaignId,
                actorAccountId: actorAccountId,
                idempotencyKey: idempotencyKey,
                occurredAt: canonicalMoment(now)
            });
        }
    }

    let markerAction = null;
    if (idempotencyKey !== null) {
        markerAction = saleMarkerAction(orderFulfillmentsTableName, markerKeysFor(actorAccountId, campaignId, idempotencyKey), {
            fingerprint: fingerprint,
            expiresAtEpoch: util.time.nowEpochSeconds() + MARKER_TTL_SECONDS,
            orderId: orderId,
            orderItem: orderItem
        });
    }

    // #746: the denormalized campaign counters. For an ordinary (NONE) order this stays a
    // delta stashed for sync_campaign_totals_fn, the step after this one -- the pre-Wave-3
    // shape, unchanged. For a CUSTODY SALE the counter rides the transaction instead, and
    // the reason is the marker: the sale's idempotent answer is the stored Order, so once
    // the Order/marker transaction has committed, a retry returns that Order WITHOUT
    // re-running the totals step. If the trailing counter ADD had failed the first time,
    // no later attempt could repair it and the campaign's totalOrders/totalRevenue would
    // be permanently one Order behind. Inside the transaction there is no window for that:
    // either the counter moved with the Order, or nothing committed and the retry repeats
    // the whole plan. (Same reasoning as publicCreateOrder, which already carries its ADD
    // inside the transaction because its resolver is at the same function cap.)
    let totalsAction = null;
    if (mode === MODE_CONSUME_SCOUT_CUSTODY) {
        totalsAction = campaignTotalsAction(profileId, campaignId, totalAmount);
    } else {
        ctx.stash.totalsDelta = { profileId: profileId, campaignId: campaignId, count: 1, revenue: totalAmount };
    }

    // FUNC-3: when a membership guard row was read, the Order write commits
    // with a ConditionCheck pinning that guard. A removal, move, or rejoin
    // between the strong guard read and this commit fails the pin and cancels
    // the transaction, so the joined scope this Order stamps was current at
    // commit -- or no Order committed at all. (The guard reads happen inside
    // the same pipeline run; only the totals counters trail, via
    // sync_campaign_totals_fn.) With no guard row -- the independent-campaign
    // shape -- there is nothing to pin and the plain PutItem is kept.
    const guardPin = membershipGuardCurrencyCheck(unitCampaignsTableName, campaignId, ctx.stash.membershipGuard);

    if (sale === null && markerAction === null && guardPin === null && totalsAction === null) {
        return {
            operation: 'PutItem',
            key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
            attributeValues: util.dynamodb.toMapValues(orderItem)
        };
    }

    // The §8.10 write budget is checked against the plan this request actually built, not
    // against a theoretical maximum: one action per Order row, guard pin, marker, custody
    // decrement, movement and fulfillment. A catalog large enough to overflow 90 actions is
    // refused before a single write, so a sale can never commit half of itself.
    const transactItems = [];
    // Marker first, as §8.2 spells it and as `IdempotentMutationRunner` requires on the
    // Python side. The order is not what makes the sale idempotent -- a DynamoDB
    // transaction is all-or-nothing whatever the item order -- but one documented shape for
    // "marker then the thing it marks" is what keeps the two write owners reviewable
    // against each other.
    const markerIndex = markerAction === null ? -1 : transactItems.length;
    if (markerAction !== null) {
        transactItems.push(markerAction);
    }
    transactItems.push({
        // PutItem: write the order row.
        operation: 'PutItem',
        table: ordersTableName,
        key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
        attributeValues: util.dynamodb.toMapValues(orderItem)
    });
    if (guardPin !== null) {
        transactItems.push(guardPin);
    }
    const totalsIndex = totalsAction === null ? -1 : transactItems.length;
    if (totalsAction !== null) {
        transactItems.push(totalsAction);
    }
    const custodyOffset = transactItems.length;
    if (sale !== null) {
        for (const action of sale.actions) {
            transactItems.push(action);
        }
    }
    if (transactItems.length > MAX_SALE_TRANSACT_ACTIONS) {
        util.error(
            'This order needs ' + transactItems.length + ' conditional writes; the limit is ' + MAX_SALE_TRANSACT_ACTIONS,
            'CONFLICT'
        );
    }
    // Which action failed is the only way to tell the caller why: a cancelled transaction
    // arrives as one error type, and "the Scout's custody moved", "this key is already in
    // flight" and "the join moved" need different answers. response() reads this back.
    const custodyIndexes = sale === null ? [] : sale.custodyOffsets.map(function (offset) { return custodyOffset + offset; });
    ctx.stash.orderWriteIndexes = { marker: markerIndex, custody: custodyIndexes, totals: totalsIndex };

    // TransactWriteItems returns only the written KEYS, not attributes, so
    // response() returns the stashed row -- the transaction is atomic, so it
    // is by construction exactly what was stored.
    ctx.stash.orderItem = orderItem;
    return {
        operation: 'TransactWriteItems',
        transactItems: transactItems
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:TransactionCanceledException') {
            const indexes = cancelledTransactIndexes(ctx.error);
            const written = (ctx.stash && ctx.stash.orderWriteIndexes) || { marker: -1, custody: [], totals: -1 };
            if (written.marker >= 0 && indexes.indexOf(written.marker) !== -1) {
                // Another request holding the same idempotencyKey committed between this
                // one's marker read and its write. Nothing committed here, so the retry is
                // answered from the marker that now exists.
                util.error('This sale is already being processed for that idempotencyKey', 'RESOURCE_BUSY');
                return null;
            }
            if (written.totals >= 0 && indexes.indexOf(written.totals) !== -1) {
                // attribute_exists(campaignId) failed: deleteCampaign removed the counter row
                // between the campaign read and this commit. Nothing committed, and the retry
                // finds no campaign to sell against.
                util.error('The campaign was removed while this order was being placed; try again', 'CONFLICT');
                return null;
            }
            for (const index of indexes) {
                if (written.custody.indexOf(index) !== -1) {
                    util.error('Scout custody changed while this order was being placed; try again', 'CONFLICT');
                    return null;
                }
            }
            // The only condition left is the guard pin, so a cancellation with no marker or
            // custody index has exactly one cause: the Scout's join moved while the order was
            // in flight and the scope it would stamp is stale. Nothing committed; a retry
            // re-reads the guard and stamps the scope that IS current.
            util.error('The campaign changed while this order was being placed; try again', 'CONFLICT');
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }
    if (ctx.stash && ctx.stash.orderItem) {
        return ctx.stash.orderItem;
    }
    const order = ctx.result;
    return order;
}
