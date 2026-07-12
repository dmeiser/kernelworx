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

function validateCustomer(input) {
    if (!input.customerName || (typeof input.customerName === 'string' && !input.customerName.trim())) {
        util.error('Customer name is required', 'BadRequest');
    }

    const hasPhone = input.customerPhone != null;
    const hasAddress = input.customerAddress != null;

    if (hasPhone) {
        const phoneResult = validatePhone(input.customerPhone);
        if (!phoneResult.valid) {
            util.error(phoneResult.error, 'BadRequest');
        }
    }

    if (hasAddress) {
        const addressResult = validateAddress(input.customerAddress);
        if (!addressResult.valid) {
            util.error(addressResult.error, 'BadRequest');
        }
    }
}

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'BadRequest');
    }
}

function normalizeId(value, prefix) {
    if (typeof value !== 'string' || !value) {
        return null;
    }
    return value.startsWith(prefix) ? value : prefix + value;
}

export function request(ctx) {
    const input = ctx.args.input;
    const campaign = ctx.stash.campaign;
    const catalog = ctx.stash.catalog;

    console.log('CreateOrder: stash summary', {
        catalogId: ctx.stash && ctx.stash.catalogId,
        catalogPresent: !!ctx.stash && !!ctx.stash.catalog,
        campaignId: ctx.stash && ctx.stash.campaign && ctx.stash.campaign.campaignId,
    });

    validateCustomer(input);
    validateOrderDate(input.orderDate);

    const profileIdRaw = input.profileId || ctx.stash.profileId;
    const profileId = normalizeId(profileIdRaw, 'PROFILE#');
    if (!profileId) {
        util.error('Invalid profileId', 'BadRequest');
    }

    const campaignIdRaw = input.campaignId || ctx.stash.campaignId;
    const campaignId = normalizeId(campaignIdRaw, 'CAMPAIGN#');
    if (!campaignId) {
        util.error('Invalid campaignId', 'BadRequest');
    }

    if (!campaign || !campaign.profileId) {
        util.error('Campaign profile association missing', 'BadRequest');
    }
    const normalizedCampaignProfileId = normalizeId(campaign.profileId, 'PROFILE#');
    if (normalizedCampaignProfileId !== profileId) {
        util.error('Campaign does not belong to the specified profile', 'Unauthorized');
    }

    if (!input.lineItems || input.lineItems.length === 0) {
        util.error('Order must have at least one line item', 'BadRequest');
    }

    if (!catalog) {
        util.error('Catalog could not be loaded for this campaign', 'BadRequest');
    }

    let enrichedLineItems = [];
    let totalAmount = 0.0;

    const productsMap = {};
    for (const product of catalog.products || []) {
        productsMap[product.productId] = product;
    }

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

    const orderId = `ORDER#${util.autoId()}`;
    const now = util.time.nowISO8601();

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

    if (input.customerPhone) {
        const phoneResult = validatePhone(input.customerPhone);
        if (phoneResult.valid) {
            orderItem.customerPhone = phoneResult.value;
        }
    }
    if (input.customerAddress) {
        orderItem.customerAddress = input.customerAddress;
    }
    if (input.notes) {
        orderItem.notes = input.notes;
    }

    if (!campaignId || typeof campaignId !== 'string') {
        util.error('Invalid campaignId for PutItem: ' + campaignId, 'BadRequest');
    }
    if (!orderId || typeof orderId !== 'string') {
        util.error('Invalid orderId for PutItem: ' + orderId, 'BadRequest');
    }

    for (const li of enrichedLineItems) {
        if (typeof li.productName !== 'string') {
            li.productName = null;
        }
    }

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
    const order = ctx.result;
    if (order && order.campaignId) {
        order.campaignId = order.campaignId;
    }
    return order;
}
