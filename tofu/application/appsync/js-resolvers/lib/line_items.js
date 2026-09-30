import { util } from '@aws-appsync/utils';

/**
 * Shared order line-item enrichment for the createOrder and updateOrder
 * pipelines (#535). Both resolvers previously carried their own copy of this
 * price/total math, so a one-character divergence (round vs floor, a dropped
 * `/ 100`) could make an order's total disagree with the other pipeline and
 * with the CSV/XLSX reports that reconcile against it. One owner for the money
 * math, pinned by lib/line_items.test.js.
 */
export function enrichLineItems(lineItems, catalog) {
    const productsMap = {};
    for (const product of (catalog && catalog.products) || []) {
        productsMap[product.productId] = product;
    }

    const enrichedLineItems = [];
    // Accumulate money in integer cents to avoid floating-point drift.
    let totalAmountCents = 0;

    for (const lineItem of lineItems) {
        const productId = lineItem.productId;
        const quantity = lineItem.quantity;

        if (quantity < 1) {
            util.error('Quantity must be at least 1 (got ' + quantity + ')', 'INVALID_INPUT');
        }

        if (!productsMap[productId]) {
            util.error('Product ' + productId + ' not found in catalog', 'INVALID_INPUT');
        }

        const product = productsMap[productId];
        const pricePerUnitCents = Math.round(product.price * 100);
        const pricePerUnit = pricePerUnitCents / 100;
        const subtotalCents = pricePerUnitCents * quantity;
        totalAmountCents += subtotalCents;
        const subtotal = subtotalCents / 100;

        enrichedLineItems.push({
            productId: productId,
            productName: product.productName,
            quantity: quantity,
            pricePerUnit: pricePerUnit,
            subtotal: subtotal
        });
    }

    return { enrichedLineItems: enrichedLineItems, totalAmountCents: totalAmountCents };
}
