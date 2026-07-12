import { util } from '@aws-appsync/utils';

function validatePhone(phone) {
    if (typeof phone !== 'string' || !phone.trim()) {
        return { valid: false, error: 'Phone number is required when provided' };
    }
    let cleaned = '';
    for (const c of phone) {
        if (c >= '0' && c <= '9') {
            cleaned += c;
        }
    }
    if (cleaned.length === 11 && cleaned[0] === '1') {
        cleaned = cleaned.substring(1);
    }
    if (cleaned.length !== 10) {
        return { valid: false, error: 'Phone number must be a valid 10-digit US number' };
    }
    return { valid: true, value: '+1' + cleaned };
}

function validateAddress(address) {
    if (!address || typeof address !== 'object') {
        return { valid: false, error: 'Address is missing required fields' };
    }
    const required = ['street', 'city', 'state', 'zipCode'];
    const missing = required.filter((field) => !address[field] || (typeof address[field] === 'string' && !address[field].trim()));
    if (missing.length > 0) {
        return { valid: false, error: 'Address is missing required fields: ' + missing.join(', ') };
    }
    const rawZip = address.zipCode;
    const zip = rawZip == null ? '' : `${rawZip}`.trim();
    let zipDigits = '';
    for (const c of zip) {
        if (c >= '0' && c <= '9') {
            zipDigits += c;
        }
    }
    if (zipDigits.length !== 5 && zipDigits.length !== 9) {
        return { valid: false, error: 'ZIP code must be 5 or 9 digits' };
    }
    return { valid: true };
}

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'BadRequest');
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
        }
        updates.push('customerName = :customerName');
        exprValues[':customerName'] = input.customerName;
    }
    if (input.customerPhone !== undefined && input.customerPhone !== null) {
        const phoneResult = validatePhone(input.customerPhone);
        if (!phoneResult.valid) {
            util.error(phoneResult.error, 'BadRequest');
        }
        updates.push('customerPhone = :customerPhone');
        exprValues[':customerPhone'] = phoneResult.value;
    }
    if (input.customerAddress !== undefined && input.customerAddress !== null) {
        const addressResult = validateAddress(input.customerAddress);
        if (!addressResult.valid) {
            util.error(addressResult.error, 'BadRequest');
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
        if (!catalog) {
            util.error('Catalog not loaded for lineItems update', 'InternalError');
        }

        const productsMap = {};
        for (const product of catalog.products || []) {
            productsMap[product.productId] = product;
        }

        const enrichedLineItems = [];
        let totalAmount = 0.0;

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
            const pricePerUnit = product.price;
            const subtotal = pricePerUnit * quantity;
            totalAmount += subtotal;

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
        exprValues[':totalAmount'] = totalAmount;
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
