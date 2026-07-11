import { util } from '@aws-appsync/utils';

function validatePhone(phone) {
    if (typeof phone !== 'string' || !phone.trim()) {
        return { valid: false, error: 'Phone number is required when provided' };
    }
    const pattern = /^(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})$/;
    const match = phone.trim().match(pattern);
    if (!match) {
        return { valid: false, error: 'Phone number must be a valid 10-digit US number' };
    }
    return { valid: true, value: '+1' + match[1] + match[2] + match[3] };
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
    const zip = String(address.zipCode).trim();
    if (!/^\d{5}(-\d{4})?$/.test(zip)) {
        return { valid: false, error: 'ZIP code must be 5 or 9 digits' };
    }
    return { valid: true };
}

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'BadRequest');
    }
    const parsed = Date.parse(orderDate);
    if (Number.isNaN(parsed)) {
        util.error('Order date must be a valid date', 'BadRequest');
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
    if (input.customerPhone !== undefined) {
        const phoneResult = validatePhone(input.customerPhone);
        if (!phoneResult.valid) {
            util.error(phoneResult.error, 'BadRequest');
        }
        updates.push('customerPhone = :customerPhone');
        exprValues[':customerPhone'] = phoneResult.value;
    }
    if (input.customerAddress !== undefined) {
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
