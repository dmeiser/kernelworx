import { util } from '@aws-appsync/utils';
import { validatePhone, validateAddress } from './lib/validation.js';
import { enrichLineItems } from './lib/line_items.js';
import { fulfillmentVersionGuard, currentFulfillmentVersion, nextFulfillmentVersion } from './lib/fulfillment_version.js';
import { normalizeIdOrPrefix } from './lib/ids.js';

// The order lifecycle slice: the seller's "payment confirmed" transition.
// Deliberately narrow, and the only lifecycle write this resolver honors:
// CONFIRMED only in v1, PUBLIC orders only, one-way (an order already
// CONFIRMED is refused, so there is no path back). Authorization is NOT
// re-derived here: the updateOrder pipeline already runs the two-phase
// ownership read (verify_profile_write_access + _step2, #438) and
// check_share_permissions, which is what restricts this to the profile owner
// or a WRITE-share collaborator. Adding a second identity check here would be
// a second authorization architecture, not a guard.
//
// status, receiptToken and orderSource are never written by any other branch
// of this resolver, so an ordinary field edit can never clear them.
//
// `status` is a DynamoDB RESERVED WORD, so the SET clause must address it
// through an expression-attribute-name placeholder (#status): a bare
// `SET status = :status` fails at runtime with "Attribute name is a reserved
// keyword" - invisible to unit tests that only read the expression string.
//
// SEC-13: when confirming an order, also record confirmedBy (the confirming
// account's ID, normalized with ACCOUNT# prefix) and confirmedAt (ISO timestamp).
// Both prefixed (ACCOUNT#...) and unprefixed spellings are accepted at the
// boundary; we normalize to the prefixed form for storage.
function applyStatusUpdate(input, order, updates, exprValues, exprNames, ctx) {
    // Key presence, not the value: this runtime can surface an omitted nullable
    // input field as a null value (the #506 lesson from paymentMethod), and an
    // explicit null must never clear a CONFIRMED order's status.
    if (!Object.hasOwn(input, 'status')) {
        return true;
    }
    if (input.status === null) {
        util.error('status cannot be null; omit the field to leave the status unchanged', 'INVALID_INPUT');
        return false;
    }
    if (input.status !== 'CONFIRMED') {
        util.error('Only CONFIRMED can be set on an order status', 'INVALID_INPUT');
        return false;
    }
    if (!order || order.orderSource !== 'PUBLIC') {
        util.error('status can only be set on public orders', 'INVALID_INPUT');
        return false;
    }
    if (order.status === 'CONFIRMED') {
        util.error('Order is already confirmed; there is no path back from CONFIRMED', 'INVALID_INPUT');
        return false;
    }
    updates.push('#status = :status');
    exprValues[':status'] = input.status;
    exprNames['#status'] = 'status';
    
    // SEC-13: record confirmation attribution. ctx.identity.sub is the
    // Cognito user sub; normalizeIdOrPrefix accepts both prefixed and
    // unprefixed spellings at the boundary and keeps a well-formed placeholder
    // if the sub is absent (#534: lib/ids.js owns the prefix rule).
    const callerSub = ctx.identity && ctx.identity.sub ? ctx.identity.sub : '';
    const confirmedBy = normalizeIdOrPrefix(callerSub, 'ACCOUNT#');
    updates.push('#confirmedBy = :confirmedBy');
    exprValues[':confirmedBy'] = confirmedBy;
    exprNames['#confirmedBy'] = 'confirmedBy';
    
    updates.push('#confirmedAt = :confirmedAt');
    exprValues[':confirmedAt'] = util.time.nowISO8601();
    exprNames['#confirmedAt'] = 'confirmedAt';
    
    return true;
}

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'INVALID_INPUT');
        return false;
    }
    return true;
}

export function request(ctx) {
    const order = ctx.stash.order;
    const input = ctx.args.input || ctx.args;
    const catalog = ctx.stash.catalog;

    const updates = [];
    const exprValues = {};
    const exprNames = {};

    if (input.customerName !== undefined) {
        if (typeof input.customerName !== 'string' || !input.customerName.trim()) {
            util.error('Customer name cannot be empty', 'INVALID_INPUT');
            return;
        }
        updates.push('customerName = :customerName');
        exprValues[':customerName'] = input.customerName;
    }
    if (input.customerPhone !== undefined) {
        const phoneValue = input.customerPhone != null ? `${input.customerPhone}`.trim() : '';
        if (phoneValue === '') {
            // Explicitly clear a previously stored phone number when the client sends
            // null, empty string, or whitespace-only input.
            updates.push('customerPhone = :customerPhone');
            exprValues[':customerPhone'] = null;
        } else {
            const phoneResult = validatePhone(phoneValue);
            if (!phoneResult.valid) {
                util.error(phoneResult.error, 'INVALID_INPUT');
                return;
            }
            updates.push('customerPhone = :customerPhone');
            exprValues[':customerPhone'] = phoneResult.value;
        }
    }
    if (input.customerAddress !== undefined && input.customerAddress !== null) {
        const addressResult = validateAddress(input.customerAddress);
        if (!addressResult.valid) {
            util.error(addressResult.error, 'INVALID_INPUT');
            return;
        }
        updates.push('customerAddress = :customerAddress');
        exprValues[':customerAddress'] = input.customerAddress;
    }
    if (input && Object.hasOwn(input, 'paymentMethod')) {
        // #506: defense in depth — the write must not persist an explicit null
        // into the non-nullable Order.paymentMethod even if the pipeline's
        // validation step is reordered or removed. Key presence (not the
        // value) distinguishes an explicit null from an omitted field, whose
        // value may read as null in this runtime.
        if (input.paymentMethod === null) {
            util.error('paymentMethod cannot be null; omit the field to keep the current value', 'INVALID_INPUT');
            return;
        }
        updates.push('paymentMethod = :paymentMethod');
        exprValues[':paymentMethod'] = input.paymentMethod;
    }
    if (input.orderDate !== undefined) {
        if (!validateOrderDate(input.orderDate)) {
            return;
        }
        updates.push('orderDate = :orderDate');
        exprValues[':orderDate'] = input.orderDate;
    }

    if (input.totalAmount !== undefined && input.lineItems === undefined) {
        util.error('totalAmount cannot be set directly without lineItems', 'INVALID_INPUT');
    }

    if (input.lineItems !== undefined) {
        if (!Array.isArray(input.lineItems) || input.lineItems.length === 0) {
            util.error('Order must have at least one line item', 'INVALID_INPUT');
        }

        if (!catalog) {
            util.error('Catalog not loaded for lineItems update', 'INTERNAL_ERROR');
        }

        // §5.19 stable line identity: identity and the fulfilled count are
        // inherited from the stored lines, never re-minted. Re-minting them on
        // every edit would orphan any fulfillment already recorded against a
        // line and let a later edit quietly reset `fulfilledQuantity`, which is
        // exactly the accounting break the wave exists to prevent. An edit may
        // reduce a line's quantity only down to what that line has already
        // fulfilled (enforced inside enrichLineItems against this snapshot).
        const { enrichedLineItems, totalAmountCents } = enrichLineItems(
            input.lineItems,
            catalog,
            order && Array.isArray(order.lineItems) ? order.lineItems : []
        );

        updates.push('lineItems = :lineItems');
        exprValues[':lineItems'] = enrichedLineItems;

        const newTotal = totalAmountCents / 100;
        updates.push('totalAmount = :totalAmount');
        exprValues[':totalAmount'] = newTotal;

        // #746: denormalized-totals delta for sync_campaign_totals_fn. Only
        // lineItems change totalAmount; the subtraction runs in floats, so it
        // is rounded to cents here (all totals are cent-quantized) and the
        // sync step rounds again as defense in depth. A zero delta is not
        // stashed, so an amount-preserving edit costs no counter write.
        const oldTotal = order && typeof order.totalAmount === 'number' ? order.totalAmount : 0;
        const revenueDelta = Math.round((newTotal - oldTotal) * 100) / 100;
        if (revenueDelta !== 0) {
            ctx.stash.totalsDelta = {
                profileId: order.profileId,
                campaignId: order.campaignId,
                count: 0,
                revenue: revenueDelta
            };
        }
    }

    if (input.notes !== undefined) {
        updates.push('notes = :notes');
        exprValues[':notes'] = input.notes;
    }

    if (!applyStatusUpdate(input, order, updates, exprValues, exprNames, ctx)) {
        return;
    }

    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();

    if (updates.length === 0) {
        return order;
    }

    // FUNC-2: a line edit moves the Order's fulfillment facts too -- `fulfilledQuantity`
    // rides inside the line list, and a fulfillment may have been recorded between the read
    // that produced this edit and the write that saves it. Data model §5.19 already makes
    // `fulfillmentVersion` the serialization point for fulfill, reverse and edit, so the
    // edit takes the same guard the Python fulfillment path takes: the write lands only on
    // the version this pipeline read, and it advances that version by one.
    //
    // Without it, an edit that began before a fulfillment commits afterwards and writes the
    // OLD line list over the new one -- `fulfilledQuantity` says 0 while stock has already
    // moved, and the Order now under-states a quantity a fulfillment record contradicts.
    // The same guard answers the other order of the race: a fulfill that read version N
    // fails its own guard when the edit advanced N to N+1 first.
    const observedVersion = currentFulfillmentVersion(order);
    updates.push('fulfillmentVersion = :nextFulfillmentVersion');
    // The NEXT version, computed from the number the guard pins -- not from the row. The
    // helper takes a number; handing it the Order object reads as "no version yet" and
    // writes 1, so an edit at version 3 would move the Order BACKWARDS, and a fulfillment
    // holding version 3 would still pass its own guard against a row that now says 1.
    exprValues[':nextFulfillmentVersion'] = nextFulfillmentVersion(observedVersion);
    const versionGuard = fulfillmentVersionGuard(observedVersion);

    const updateExpression = 'SET ' + updates.join(', ');

    const update = {
        expression: updateExpression,
        expressionValues: util.dynamodb.toMapValues(exprValues)
    };
    if (Object.keys(exprNames).length > 0) {
        update.expressionNames = exprNames;
    }

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId }),
        update: update,
        condition: {
            expression: versionGuard.expression,
            expressionNames: versionGuard.expressionNames,
            expressionValues: util.dynamodb.toMapValues(versionGuard.expressionValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
            // This resolver writes exactly one condition, so a failed condition has exactly
            // one cause: something else moved this Order's fulfillment state (or deleted the
            // Order) between the read and the write. Nothing was written, and re-reading the
            // Order is the whole remedy, which is what makes this retryable rather than a
            // caller error.
            util.error(
                'This order changed while the edit was being saved; re-read it and try again',
                'CONFLICT'
            );
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
    }
    const order = ctx.result;
    return order;
}
