import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const order = ctx.stash.order;
    const input = ctx.args.input || ctx.args;
    const catalog = ctx.stash.catalog;  // May be null if lineItems not being updated
    
    // Build update expression dynamically
    const updates = [];
    const exprValues = {};
    const exprNames = {};
    
    if (input.customerName !== undefined) {
        updates.push('customerName = :customerName');
        exprValues[':customerName'] = input.customerName;
    }
    if (input.customerPhone !== undefined) {
        updates.push('customerPhone = :customerPhone');
        exprValues[':customerPhone'] = input.customerPhone;
    }
    if (input.customerAddress !== undefined) {
        updates.push('customerAddress = :customerAddress');
        exprValues[':customerAddress'] = input.customerAddress;
    }
    if (input.paymentMethod !== undefined) {
        updates.push('paymentMethod = :paymentMethod');
        exprValues[':paymentMethod'] = input.paymentMethod;
    }
    if (input.totalAmount !== undefined) {
        updates.push('totalAmount = :totalAmount');
        exprValues[':totalAmount'] = input.totalAmount;
    }
    
    // Bug #16 fix: Enrich lineItems with product details from catalog
    if (input.lineItems !== undefined) {
        if (!catalog) {
        util.error('Catalog not loaded for lineItems update', 'InternalError');
        }
        
        // Build products lookup map
        const productsMap = {};
        for (const product of catalog.products || []) {
        productsMap[product.productId] = product;
        }
        
        // Enrich line items with product details
        const enrichedLineItems = [];
        let totalAmount = 0.0;
        
        for (const lineItem of input.lineItems) {
        const productId = lineItem.productId;
        const quantity = lineItem.quantity;
        
        // Validate quantity
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
        
        // Also update totalAmount
        updates.push('totalAmount = :totalAmount');
        exprValues[':totalAmount'] = totalAmount;
    }
    
    if (input.notes !== undefined) {
        updates.push('notes = :notes');
        exprValues[':notes'] = input.notes;
    }
    if (input.orderDate !== undefined) {
        updates.push('orderDate = :orderDate');
        exprValues[':orderDate'] = input.orderDate;
    }
    
    // Always update updatedAt
    updates.push('updatedAt = :updatedAt');
    exprValues[':updatedAt'] = util.time.nowISO8601();
    
    if (updates.length === 0) {
        return order; // No updates, return original
    }
    
    const updateExpression = 'SET ' + updates.join(', ');
    
    // V2 schema: composite key (campaignId, orderId)
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
    // Map DynamoDB field campaignId to GraphQL field campaignId
    const order = ctx.result;
    if (order && order.campaignId) {
        order.campaignId = order.campaignId;
    }
    return order;
}
