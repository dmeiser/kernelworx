import { util } from '@aws-appsync/utils';
import { validatePhone, validateAddress } from './lib/validation.js';
import { normalizeId } from './lib/ids.js';

function validateCustomer(input) {
    if (!input.customerName || (typeof input.customerName === 'string' && !input.customerName.trim())) {
        util.error('Customer name is required', 'INVALID_INPUT');
        return {};
    }

    const phoneValue = input.customerPhone != null ? `${input.customerPhone}`.trim() : '';
    const hasAddress = input.customerAddress != null;
    let customerPhone = undefined;

    if (phoneValue !== '') {
        const phoneResult = validatePhone(phoneValue);
        if (!phoneResult.valid) {
            util.error(phoneResult.error, 'INVALID_INPUT');
            return { customerPhone: undefined };
        }
        customerPhone = phoneResult.value;
    }

    if (hasAddress) {
        const addressResult = validateAddress(input.customerAddress);
        if (!addressResult.valid) {
            util.error(addressResult.error, 'INVALID_INPUT');
            return { customerPhone };
        }
    }

    return { customerPhone };
}

function validateOrderDate(orderDate) {
    if (!orderDate || typeof orderDate !== 'string' || !orderDate.trim()) {
        util.error('Order date is required', 'INVALID_INPUT');
        return;
    }
}

export function request(ctx) {
    const input = ctx.args.input;
    const campaign = ctx.stash.campaign;
    const catalog = ctx.stash.catalog;

    const { customerPhone } = validateCustomer(input);
    validateOrderDate(input.orderDate);

    const profileIdRaw = input.profileId || ctx.stash.profileId;
    const profileId = normalizeId(profileIdRaw, 'PROFILE#');
    if (!profileId) {
        util.error('Invalid profileId', 'INVALID_INPUT');
    }

    const campaignIdRaw = input.campaignId || ctx.stash.campaignId;
    const campaignId = normalizeId(campaignIdRaw, 'CAMPAIGN#');
    if (!campaignId) {
        util.error('Invalid campaignId', 'INVALID_INPUT');
    }

    if (!campaign || !campaign.profileId) {
        util.error('Campaign profile association missing', 'INVALID_INPUT');
    }
    const normalizedCampaignProfileId = normalizeId(campaign.profileId, 'PROFILE#');
    if (normalizedCampaignProfileId !== profileId) {
        util.error('Campaign does not belong to the specified profile', 'UNAUTHORIZED');
    }

    if (!input.lineItems || input.lineItems.length === 0) {
        util.error('Order must have at least one line item', 'INVALID_INPUT');
    }

    if (!catalog) {
        util.error('Catalog could not be loaded for this campaign', 'INVALID_INPUT');
    }

    let enrichedLineItems = [];
    // Accumulate money in integer cents to avoid floating-point drift.
    let totalAmountCents = 0;

    const productsMap = {};
    for (const product of catalog.products || []) {
        productsMap[product.productId] = product;
    }

    for (const lineItem of input.lineItems) {
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

    const totalAmount = totalAmountCents / 100;

    const campaignIdWithoutPrefix = campaignId.startsWith('CAMPAIGN#') ? campaignId.substring(9) : campaignId;
    const orderId = `ORDER#${campaignIdWithoutPrefix}#${util.autoId()}`;
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

    if (customerPhone) {
        orderItem.customerPhone = customerPhone;
    }
    if (input.customerAddress) {
        orderItem.customerAddress = input.customerAddress;
    }
    if (input.notes) {
        orderItem.notes = input.notes;
    }

    if (!campaignId || typeof campaignId !== 'string') {
        util.error('Invalid campaignId for PutItem: ' + campaignId, 'INVALID_INPUT');
    }
    if (!orderId || typeof orderId !== 'string') {
        util.error('Invalid orderId for PutItem: ' + orderId, 'INVALID_INPUT');
    }

    for (const li of enrichedLineItems) {
        if (typeof li.productName !== 'string') {
            li.productName = null;
        }
    }

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
