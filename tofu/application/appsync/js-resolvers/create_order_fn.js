import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args.input;
    const campaign = ctx.stash.campaign;
    const catalog = ctx.stash.catalog;
    
    console.log('CreateOrder: stash summary', {
        catalogId: ctx.stash && ctx.stash.catalogId,
        catalogPresent: !!ctx.stash && !!ctx.stash.catalog,
        campaignId: ctx.stash && ctx.stash.campaign && ctx.stash.campaign.campaignId,
    });

    let enrichedLineItems = [];
    let totalAmount = 0.0;

    // If catalog is missing, fall back to permissive creation: do not fail, but skip product validation/enrichment
    if (!catalog) {
        console.log('CreateOrder: stash.catalog missing, proceeding without catalog validation', {
            catalogId: ctx.stash && ctx.stash.catalogId,
            campaignId: ctx.stash && ctx.stash.campaign && ctx.stash.campaign.campaignId,
            inputCampaignId: input.campaignId
        });
        // Basic validation of line items (ensure at least one item and that quantities are valid)
        if (!input.lineItems || input.lineItems.length === 0) {
            util.error('Order must have at least one line item', 'BadRequest');
        }
        for (const lineItem of input.lineItems) {
            const quantity = lineItem.quantity;
            if (quantity < 1) {
                util.error('Quantity must be at least 1 (got ' + quantity + ')', 'BadRequest');
            }
            enrichedLineItems.push({
                productId: lineItem.productId,
                quantity: quantity,
                // Unknown product name/price because catalog unavailable
                productName: null,
                pricePerUnit: 0.0,
                subtotal: 0.0
            });
        }
        // totalAmount remains 0.0 when catalog is missing
    } else {
        // Validate lineItems is not empty
        if (!input.lineItems || input.lineItems.length === 0) {
            util.error('Order must have at least one line item', 'BadRequest');
        }
        
        // Build products lookup map and enrich line items as normal
        const productsMap = {};
        for (const product of catalog.products || []) {
            productsMap[product.productId] = product;
        }
        
        // Enrich line items with product details
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
    // Validate key attributes and sanitize line items to avoid malformed attribute shapes
    if (!campaignId || typeof campaignId !== 'string') {
        util.error('Invalid campaignId for PutItem: ' + JSON.stringify(campaignId), 'BadRequest');
    }
    if (!orderId || typeof orderId !== 'string') {
        util.error('Invalid orderId for PutItem: ' + JSON.stringify(orderId), 'BadRequest');
    }

    // Sanitize productName to ensure it's either a string or null. Non-string values (including empty objects)
    // can produce invalid DynamoDB attribute shapes when marshalled by AppSync.
    for (const li of enrichedLineItems) {
        if (typeof li.productName !== 'string') {
            li.productName = null;
        }
    }

    // Orders table schema (V2): partition_key = campaignId, sort_key = orderId
    // Validate and log keys clearly
    console.log('CreateOrder: PutItem keys', { campaignId: campaignId, orderId: orderId });


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
