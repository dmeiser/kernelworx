import { util } from '@aws-appsync/utils';
import { validatePhone, validateAddress } from './lib/validation.js';
import { normalizeId } from './lib/ids.js';
import { enrichLineItems } from './lib/line_items.js';
import { buildOrderKey } from './lib/order_keys.js';
import { orderOrigin, membershipGuardCurrencyCheck } from './lib/order_origin.js';

// Loaded via Terraform templatefile() (functions_orders.tf), like the public
// write step it clones: the Order write runs as a TransactWriteItems whenever
// a membership guard row was read (FUNC-3), and a TransactWriteItems item's
// `table` field is the literal AWS table name -- AppSync does not default it
// to the datasource's table. Only declared placeholders may be interpolated
// (#570; tests/unit/check_templatefile_escaping.test.ts), so this file carries
// no dollar-brace sequence outside the two constants below.
const ordersTableName = '${orders_table_name}';
const unitCampaignsTableName = '${unit_campaigns_table_name}';

function validateCustomer(input) {
    if (!input.customerName || (typeof input.customerName === 'string' && !input.customerName.trim())) {
        util.error('Customer name is required', 'INVALID_INPUT');
        return {};
    }

    // `+ ''` rather than String(...): APPSYNC_JS has no String() global, and code
    // that calls it is refused at CreateFunction/UpdateFunction.
    const phoneValue = input.customerPhone != null ? (input.customerPhone + '').trim() : '';
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

    const { enrichedLineItems, totalAmountCents } = enrichLineItems(input.lineItems, catalog);

    const totalAmount = totalAmountCents / 100;

    // The ORDER#<campaign without prefix>#<suffix> grammar has one owner
    // (#534): lib/order_keys.js buildOrderKey, the exact shape parseOrderKey
    // and parseEmbeddedCampaignId read back.
    const orderId = buildOrderKey(campaignId, util.autoId());
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

    // §1.4.3 (API-FIX-05): the joined scope is captured here and never derived
    // again -- which is only sound if it is captured from something that answers
    // the question *now*. The Campaign's own unitId/unitCampaignId pair is the
    // latest link and removal keeps it, so an Order written after the Scout left
    // would follow them into another Unit. The membership guard is the current
    // answer: the join claim denormalized the parent Unit beside the pointer,
    // so the guard alone names both halves of the scope with one strong read.
    const origin = orderOrigin(ctx.stash.membershipGuard);
    orderItem.unitId = origin.unitId;
    orderItem.unitCampaignId = origin.unitCampaignId;

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

    // #746: stash the denormalized-totals delta for sync_campaign_totals_fn
    // (the step after this one). The order row's profileId/campaignId are the
    // campaigns-table key, so no lookup is needed to address the counter.
    ctx.stash.totalsDelta = { profileId: profileId, campaignId: campaignId, count: 1, revenue: totalAmount };

    // FUNC-3: when a membership guard row was read, the Order write commits
    // with a ConditionCheck pinning that guard. A removal, move, or rejoin
    // between the strong guard read and this commit fails the pin and cancels
    // the transaction, so the joined scope this Order stamps was current at
    // commit -- or no Order committed at all. (The guard reads happen inside
    // the same pipeline run; only the totals counters trail, via
    // sync_campaign_totals_fn.) With no guard row -- the independent-campaign
    // shape -- there is nothing to pin and the plain PutItem is kept.
    const guardPin = membershipGuardCurrencyCheck(unitCampaignsTableName, campaignId, ctx.stash.membershipGuard);
    if (guardPin === null) {
        return {
            operation: 'PutItem',
            key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
            attributeValues: util.dynamodb.toMapValues(orderItem)
        };
    }
    // TransactWriteItems returns only the written KEYS, not attributes, so
    // response() returns the stashed row -- the transaction is atomic, so it
    // is by construction exactly what was stored.
    ctx.stash.orderItem = orderItem;
    return {
        operation: 'TransactWriteItems',
        transactItems: [
            {
                // PutItem: write the order row.
                operation: 'PutItem',
                table: ordersTableName,
                key: util.dynamodb.toMapValues({ campaignId: campaignId, orderId: orderId }),
                attributeValues: util.dynamodb.toMapValues(orderItem)
            },
            guardPin
        ]
    };
}

export function response(ctx) {
    if (ctx.error) {
        if (ctx.error.type === 'DynamoDB:TransactionCanceledException') {
            // The only condition in this transaction is the guard pin, so a
            // cancellation has exactly one cause: the Scout's join moved while
            // the order was in flight and the scope it would stamp is stale.
            // Nothing committed; a retry re-reads the guard and stamps the
            // scope that IS current.
            util.error('The campaign changed while this order was being placed; try again', 'CONFLICT');
            return null;
        }
        util.error(ctx.error.message, ctx.error.type);
        return null;
    }
    if (ctx.stash && ctx.stash.orderItem) {
        return ctx.stash.orderItem;
    }
    const order = ctx.result;
    return order;
}
