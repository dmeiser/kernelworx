import { util } from '@aws-appsync/utils';
import { validatePhone, validateAddress } from './lib/validation.js';
import { enrichLineItems } from './lib/line_items.js';

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
    if (input.paymentMethod !== undefined) {
        // #506: defense in depth — the write must not persist an explicit null
        // into the non-nullable Order.paymentMethod even if the pipeline's
        // validation step is reordered or removed.
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

        const { enrichedLineItems, totalAmountCents } = enrichLineItems(input.lineItems, catalog);

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
