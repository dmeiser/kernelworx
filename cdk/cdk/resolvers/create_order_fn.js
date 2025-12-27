import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const campaign = ctx.stash.campaign;
    const catalog = ctx.stash.catalog;
    
    if (!catalog) {
        util.error('Catalog not found', 'NotFound');
    }
    
    // Bug #15 fix: Validate line items
    if (!input.lineItems || input.lineItems.length === 0) {
        util.error('Order must have at least one line item', 'BadRequest');
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
        
        // Bug #15 fix: Validate quantity
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
    
    // Generate order ID (prefixed)
    const orderId = `ORDER#${util.autoId()}`;
    const now = util.time.nowISO8601();
    
    // Normalize profileId and campaignId to DB format and build order item for orders table
    const profileIdRaw = input.profileId || ctx.stash.profileId;
    const profileId = (typeof profileIdRaw === 'string' && profileIdRaw.startsWith('PROFILE#')) ? profileIdRaw : `PROFILE#${profileIdRaw}`;

    const campaignIdRaw = input.campaignId || ctx.stash.campaignId;
    const campaignId = (typeof campaignIdRaw === 'string' && campaignIdRaw.startsWith('CAMPAIGN#')) ? campaignIdRaw : `CAMPAIGN#${campaignIdRaw}`;

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
        updatedAt: now
    };
    
    // Add optional fields
    if (input.customerPhone) {
        orderItem.customerPhone = input.customerPhone;
    }
    if (input.customerAddress) {
        orderItem.customerAddress = input.customerAddress;
    }
    if (input.notes) {
        orderItem.notes = input.notes;
    }
    
    // V2 schema: composite key (campaignId, orderId) - use normalized campaignId
    return {
        operation: 'PutItem',
        key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
        attributeValues: util.dynamodb.toMapValues(orderItem)
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
