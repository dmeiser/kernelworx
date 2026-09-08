import { util } from '@aws-appsync/utils';
import { validatePhone, validateAddress } from './lib/validation.js';

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'BadRequest');
        return;
    }
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
            util.error('Customer name cannot be empty', 'BadRequest');
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
                util.error(phoneResult.error, 'BadRequest');
                return;
            }
            updates.push('customerPhone = :customerPhone');
            exprValues[':customerPhone'] = phoneResult.value;
        }
    }
    if (input.customerAddress !== undefined && input.customerAddress !== null) {
        const addressResult = validateAddress(input.customerAddress);
        if (!addressResult.valid) {
            util.error(addressResult.error, 'BadRequest');
            return;
        }
        updates.push('customerAddress = :customerAddress');
        exprValues[':customerAddress'] = input.customerAddress;
    }
    if (input.paymentMethod !== undefined) {
        updates.push('paymentMethod = :paymentMethod');
        exprValues[':paymentMethod'] = input.paymentMethod;
    }
    if (input.orderDate !== undefined) {
        validateOrderDate(input.orderDate);
        updates.push('orderDate = :orderDate');
        exprValues[':orderDate'] = input.orderDate;
    }

    if (input.totalAmount !== undefined && input.lineItems === undefined) {
        util.error('totalAmount cannot be set directly without lineItems', 'BadRequest');
    }

    if (input.lineItems !== undefined) {
        if (!Array.isArray(input.lineItems) || input.lineItems.length === 0) {
            util.error('Order must have at least one line item', 'BadRequest');
        }

        if (!catalog) {
            util.error('Catalog not loaded for lineItems update', 'InternalError');
        }

        const productsMap = {};
        for (const product of catalog.products || []) {
            productsMap[product.productId] = product;
        }

        const enrichedLineItems = [];
        // Accumulate money in integer cents to avoid floating-point drift.
        let totalAmountCents = 0;

        for (const lineItem of input.lineItems) {
            const productId = lineItem.productId;
            const quantity = lineItem.quantity;

            if (quantity < 1) {
                util.error('Quantity must be at least 1 (got ' + quantity + ')', 'BadRequest');
            }

            if (!productsMap[productId]) {
                util.error('Product ' + productId + ' not found in catalog', 'BadRequest');
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

        updates.push('lineItems = :lineItems');
        exprValues[':lineItems'] = enrichedLineItems;

        updates.push('totalAmount = :totalAmount');
        exprValues[':totalAmount'] = totalAmountCents / 100;
    }

    if (input.notes !== undefined) {
        updates.push('notes = :notes');
        exprValues[':notes'] = input.notes;
    }

    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();

    if (updates.length === 0) {
        return order;
    }

    const updateExpression = 'SET ' + updates.join(', ');

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ campaignId: order.campaignId, orderId: order.orderId }),
        update: {
            expression: updateExpression,
            expressionNames: Object.keys(exprNames).length > 0 ? exprNames : undefined,
            expressionValues: util.dynamodb.toMapValues(exprValues)
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    const order = ctx.result;
    if (order && order.campaignId) {
        order.campaignId = order.campaignId;
    }
    return order;
}
