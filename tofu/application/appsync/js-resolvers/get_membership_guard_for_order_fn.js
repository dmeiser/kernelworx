import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import { currentUnitCampaignId } from './lib/order_origin.js';
import {
    MODE_CONSUME_SCOUT_CUSTODY,
    parseFulfillmentMode,
    idempotencyKeyFor,
    markerKeysFor,
    custodyReadKeys
} from './lib/custody_sale.js';

// The membership guard read (§5.6): the single strongly consistent read that says
// which Unit Campaign a Scout Campaign is joined to at this moment. The Campaign
// row's own unitId/unitCampaignId pair cannot answer that -- removal keeps it --
// and the campaignId-index projection adds eventual consistency on top.
//
// Keyed by the campaign alone, so no pipeline step has to know the Unit Campaign
// to find out whether there is one.
//
// §2.4.2 gives this step a second job, and it is the only step that can carry it: a
// door-to-door sale (`createOrder(fulfillmentMode = CONSUME_SCOUT_CUSTODY)`) needs the
// Scout's custody rows and her idempotency marker before the Order write, and an AppSync
// pipeline function gets exactly one datastore call. createOrder's resolver already holds
// the 10 functions AppSync allows (ARCH-1), so there is no step to add. A BatchGetItem
// reads all three in one call, and it stays one call for every sale that is not a
// door-to-door sale: a NONE-mode order -- every order this pipeline wrote before Wave 3,
// and every public order -- still issues the single GetItem below, unchanged.
//
// The custody key uses the Campaign row's `unitCampaignId` (strongly read one step
// earlier) rather than the guard's answer, because the key has to exist before the guard
// answer arrives. That is sound for exactly as long as the join claim keeps writing both
// from one operation, and create_order_fn re-checks the two against each other before it
// consumes anything: see `saleCustodyScope` there.

const unitCampaignsTableName = '${unit_campaigns_table_name}';
const inventoryTableName = '${inventory_table_name}';
const orderFulfillmentsTableName = '${order_fulfillments_table_name}';

function guardKey(campaignId) {
    return util.dynamodb.toMapValues({
        pk: 'SCOUT_CAMPAIGN#' + campaignId,
        sk: 'MEMBERSHIP_GUARD'
    });
}

export function request(ctx) {
    const stash = ctx.stash || {};
    const campaignId = normalizeId(stash.campaignId, 'CAMPAIGN#');
    if (!campaignId) {
        util.error('campaignId is required to read the join guard', 'INVALID_INPUT');
    }

    const input = (ctx.args && ctx.args.input) || {};
    const mode = parseFulfillmentMode(input);
    if (mode !== MODE_CONSUME_SCOUT_CUSTODY) {
        return {
            operation: 'GetItem',
            key: guardKey(campaignId),
            consistentRead: true
        };
    }

    // A sale that cannot be made idempotent is refused here rather than at the write step:
    // the key is part of the read, so reading without it would leave a retry unable to find
    // the sale it is retrying.
    const idempotencyKey = idempotencyKeyFor(mode, input);
    const claims = ctx.identity && ctx.identity.claims ? ctx.identity.claims : null;
    const actorId = claims && typeof claims.sub === 'string' && claims.sub !== '' ? claims.sub : null;
    if (actorId === null) {
        util.error('A signed-in account is required to place a custody sale', 'UNAUTHORIZED');
    }

    const profileId = normalizeId(input.profileId || stash.profileId, 'PROFILE#');
    // The Campaign's latest link, from the strong read in the step before this one. Absent
    // means the campaign has never been joined, so there is no custody to read anywhere.
    const linkedUnitCampaignId = stash.campaign && stash.campaign.unitCampaignId != null ? stash.campaign.unitCampaignId + '' : null;
    const keys = custodyReadKeys(linkedUnitCampaignId, profileId, input.lineItems);

    const tables = {};
    tables[unitCampaignsTableName] = { keys: [guardKey(campaignId)], consistentRead: true };
    if (keys.length > 0) {
        tables[inventoryTableName] = { keys: keys, consistentRead: true };
    }
    tables[orderFulfillmentsTableName] = { keys: [guardMarkerKeyFor(actorId, campaignId, idempotencyKey)], consistentRead: true };

    ctx.stash.custodySaleRead = {
        unitCampaignId: linkedUnitCampaignId,
        profileId: profileId,
        idempotencyKey: idempotencyKey
    };

    return { operation: 'BatchGetItem', tables: tables };
}

function guardMarkerKeyFor(actorId, campaignId, idempotencyKey) {
    const keys = markerKeysFor(actorId, campaignId, idempotencyKey);
    return util.dynamodb.toMapValues({ pk: keys.pk, sk: keys.sk });
}

// A BatchGetItem answers `{ data: { <table>: [items] } }` and simply omits a row it did
// not find, so "no guard row" and "no custody rows" are both empty lists rather than
// errors -- which is exactly what an independent campaign and a Scout holding nothing are.
function rowsFor(result, tableName) {
    const data = result && result.data ? result.data : null;
    if (data === null) {
        return [];
    }
    const rows = Object.hasOwn(data, tableName) ? data[tableName] : [];
    return rows || [];
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    // Absent guard row is not an error: an independent campaign has none, and the
    // origin it produces is two nulls, which is the recorded fact.
    const wasBatch = !!(ctx.stash && ctx.stash.custodySaleRead);
    const guardRows = wasBatch ? rowsFor(ctx.result, unitCampaignsTableName) : ctx.result ? [ctx.result] : [];
    const guard = guardRows.length > 0 ? guardRows[0] : null;
    ctx.stash.membershipGuard = guard;
    ctx.stash.activeUnitCampaignId = currentUnitCampaignId(guard);
    if (wasBatch) {
        ctx.stash.custodyRows = rowsFor(ctx.result, inventoryTableName);
        const markers = rowsFor(ctx.result, orderFulfillmentsTableName);
        ctx.stash.idempotencyMarker = markers.length > 0 ? markers[0] : null;
    }
    return ctx.stash.activeUnitCampaignId;
}
