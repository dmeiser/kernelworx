import { util } from '@aws-appsync/utils';

/**
 * Shared order line-item enrichment for the createOrder and updateOrder
 * pipelines (#535). Both resolvers previously carried their own copy of this
 * price/total math, so a one-character divergence (round vs floor, a dropped
 * `/ 100`) could make an order's total disagree with the other pipeline and
 * with the CSV/XLSX reports that reconcile against it. One owner for the money
 * math, pinned by lib/line_items.test.js.
 */

// Wave 3 (§5.19): a line's identity is minted once at creation and never
// rewritten, so a fulfillment of that line survives a later edit that
// re-orders or re-prices the list. `existingLineItems` is the stored list for
// an updateOrder call: identity is inherited from it, never from the caller
// alone, so a client cannot invent line identity or smuggle a different
// Scout's history. Matching prefers an explicit lineItemId when one is
// present, then falls back to the first unconsumed existing line with the
// same productId — the common "change the quantity of this line" shape.
// APPSYNC_JS bans continue/break/Set, so this walks for-of with early return
// and tracks consumption in a plain object keyed by lineItemId.

function hasExistingId(existingLineItems, lineItemId) {
    for (const existing of (existingLineItems || [])) {
        if (existing && typeof existing === 'object' && existing.lineItemId === lineItemId) {
            return true;
        }
    }
    return false;
}

function matchExistingLine(lineItem, existingLineItems, consumed) {
    for (const existing of (existingLineItems || [])) {
        if (existing && typeof existing === 'object') {
            if (typeof lineItem.lineItemId === 'string' && lineItem.lineItemId !== '') {
                if (existing.lineItemId === lineItem.lineItemId) {
                    return existing;
                }
            } else if (existing.lineItemId !== undefined && existing.lineItemId !== null
                && !Object.hasOwn(consumed, existing.lineItemId)
                && existing.productId === lineItem.productId) {
                return existing;
            }
        }
    }
    return null;
}

function resolveLineIdentity(lineItem, existingLineItems, consumed) {
    const existing = matchExistingLine(lineItem, existingLineItems, consumed);
    if (existing) {
        const existingFulfilled = typeof existing.fulfilledQuantity === 'number' ? existing.fulfilledQuantity : 0;
        if (lineItem.quantity < existingFulfilled) {
            util.error(
                'Quantity of ' + lineItem.quantity + ' is below the line\'s already-fulfilled amount of ' + existingFulfilled,
                'INVALID_INPUT'
            );
            return { lineItemId: existing.lineItemId, fulfilledQuantity: existingFulfilled };
        }
        consumed[existing.lineItemId] = true;
        return { lineItemId: existing.lineItemId, fulfilledQuantity: existingFulfilled };
    }
    return { lineItemId: util.autoId(), fulfilledQuantity: 0 };
}

export function enrichLineItems(lineItems, catalog, existingLineItems) {
    const productsMap = {};
    for (const product of (catalog && catalog.products) || []) {
        if (product && typeof product.productId === 'string') {
            productsMap[product.productId] = product;
        }
    }

    // A lineId the caller supplied that matches nothing is a lie, not a
    // legacy input: refuse it loudly instead of silently minting a second id
    // for a line that already has one.
    if (existingLineItems) {
        for (const lineItem of lineItems) {
            if (typeof lineItem.lineItemId === 'string' && lineItem.lineItemId !== ''
                && !hasExistingId(existingLineItems, lineItem.lineItemId)) {
                util.error('Unknown lineItemId ' + lineItem.lineItemId + ' for this order', 'INVALID_INPUT');
            }
        }
    }

    const enrichedLineItems = [];
    // Accumulate money in integer cents to avoid floating-point drift.
    let totalAmountCents = 0;
    const consumed = {};

    for (const lineItem of lineItems) {
        const productId = lineItem.productId;
        const quantity = lineItem.quantity;

        if (typeof quantity !== 'number' || !Number.isFinite(quantity) || quantity < 1) {
            util.error('Quantity must be at least 1 (got ' + quantity + ')', 'INVALID_INPUT');
        }

        if (!Object.hasOwn(productsMap, productId)) {
            util.error('Product ' + productId + ' not found in catalog', 'INVALID_INPUT');
        }

        const product = productsMap[productId];
        if (!product || typeof product.price !== 'number' || !Number.isFinite(product.price) || product.price < 0) {
            util.error('Product ' + productId + ' has no valid price', 'INVALID_INPUT');
        }
        const pricePerUnitCents = Math.round(product.price * 100);
        const pricePerUnit = pricePerUnitCents / 100;
        const subtotalCents = pricePerUnitCents * quantity;
        totalAmountCents += subtotalCents;
        const subtotal = subtotalCents / 100;

        const identity = resolveLineIdentity(lineItem, existingLineItems, consumed);

        enrichedLineItems.push({
            productId: productId,
            productName: product.productName,
            quantity: quantity,
            pricePerUnit: pricePerUnit,
            subtotal: subtotal,
            lineItemId: identity.lineItemId,
            fulfilledQuantity: identity.fulfilledQuantity
        });
    }

    return { enrichedLineItems: enrichedLineItems, totalAmountCents: totalAmountCents };
}
