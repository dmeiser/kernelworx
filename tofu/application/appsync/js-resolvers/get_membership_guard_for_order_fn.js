import { util } from '@aws-appsync/utils';
import { normalizeId } from './lib/ids.js';
import { currentUnitCampaignId, orderOrigin } from './lib/order_origin.js';
import {
    MODE_CONSUME_SCOUT_CUSTODY,
    parseFulfillmentMode,
    idempotencyKeyFor,
    markerKeysFor,
    custodyReadKeys,
    unitAdminGrantKey,
    authorizeCustodySale
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
const unitsTableName = '${units_table_name}';

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

    // SEC-1 (§2.4.2: "Profile Owner/WRITE or Unit Admin"). The share step ahead of this
    // one records its verdict rather than ending the pipeline for a custody sale, so a
    // sale whose Profile half failed has to answer the Unit half, and this is the only
    // step with a datastore call left. ConsistentRead for the same reason unit_auth reads
    // strong: a revoked admin must not be authorized off a stale grant row.
    //
    // Keyed off the Campaign's retained `unitId` (the strong campaign read, one step
    // earlier) because the guard's answer does not exist yet. create_order_fn then
    // requires the grant to name the Unit the GUARD names, so a retained link that
    // disagrees with the live join denies instead of authorizing -- it cannot be used to
    // reach a different Unit's grant.
    if (stash.profileWriteAuthorized !== true) {
        const linkedUnitId = stash.campaign && stash.campaign.unitId != null ? stash.campaign.unitId + '' : null;
        if (linkedUnitId !== null) {
            tables[unitsTableName] = { keys: [util.dynamodb.toMapValues(unitAdminGrantKey(linkedUnitId, actorId))], consistentRead: true };
        }
    }

    ctx.stash.custodySaleRead = {
        unitCampaignId: linkedUnitCampaignId,
        profileId: profileId,
        idempotencyKey: idempotencyKey,
        // The composite authorization below is answered here, so the caller it
        // authorizes has to be the caller this request read the grant for.
        actorAccountId: actorId
    };

    return { operation: 'BatchGetItem', tables: tables };
}

function guardMarkerKeyFor(actorId, campaignId, idempotencyKey) {
    const keys = markerKeysFor(actorId, campaignId, idempotencyKey);
    return util.dynamodb.toMapValues({ pk: keys.pk, sk: keys.sk });
}

// A BatchGetItem answers `{ data: { <table>: [items] }, unprocessedKeys: { ... } }` and
// simply omits a row it did not find, so "no guard row" and "no custody rows" are both
// empty lists rather than errors -- which is exactly what an independent campaign and a
// Scout holding nothing are.
//
// `unprocessedKeys` is a different thing wearing the same shape: DynamoDB did not look at
// those keys at all (throttling, capacity, a hot partition). Reading them as absent would
// be reading a verdict out of a non-answer, and each table has a distinct way for that to
// do damage -- an unprocessed guard row makes a joined Scout's Order look independent (so
// it consumes no custody and stamps a null scope), and an unprocessed custody row makes a
// sale under-consume, after which the COMPLETED marker preserves that wrong answer for
// every retry of the key. So a partial batch fails here, in the read step, before the
// write step exists: nothing was written and the caller retries.
// The value under each table name is the list of keys themselves. This is the AppSync JS
// BatchGetItem result contract, not the raw DynamoDB wire shape, which wraps the same list
// in `{ keys: [...] }`: the documented result is `{ data: { <table>: [items] },
// unprocessedKeys: { <table>: [key] } }`, and `batch_get_catalogs_fn.js` in this directory
// reads it the same way. Reading `.keys.length` off the real response yields `undefined`
// for every table, so a genuinely partial batch counts as zero unprocessed keys and the
// guard below never fires -- the exact wrong-verdict-from-a-non-answer this step exists to
// refuse. Anything present but not a list is still a non-answer, so it counts as one.
function unprocessedKeyCount(result) {
    const unprocessed = result && result.unprocessedKeys ? result.unprocessedKeys : null;
    if (unprocessed === null) {
        return 0;
    }
    let count = 0;
    for (const tableName of Object.keys(unprocessed)) {
        const entry = unprocessed[tableName];
        if (Array.isArray(entry)) {
            count = count + entry.length;
        } else if (entry) {
            count = count + 1;
        }
    }
    return count;
}

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
    if (wasBatch && unprocessedKeyCount(ctx.result) > 0) {
        util.error('The sale reads were only partly served; no order was written', 'RESOURCE_BUSY');
    }
    const guardRows = wasBatch ? rowsFor(ctx.result, unitCampaignsTableName) : ctx.result ? [ctx.result] : [];
    const guard = guardRows.length > 0 ? guardRows[0] : null;
    ctx.stash.membershipGuard = guard;
    ctx.stash.activeUnitCampaignId = currentUnitCampaignId(guard);
    if (wasBatch) {
        ctx.stash.custodyRows = rowsFor(ctx.result, inventoryTableName);
        const markers = rowsFor(ctx.result, orderFulfillmentsTableName);
        ctx.stash.idempotencyMarker = markers.length > 0 ? markers[0] : null;
        const grants = rowsFor(ctx.result, unitsTableName);
        ctx.stash.unitAdminGrant = grants.length > 0 ? grants[0] : null;

        // SEC-1: the sale's authorization is DECIDED here, at the read step, and the
        // pipeline runs payment-method validation after this step. `check_share_permissions`
        // defers its denial for a custody sale so that a Unit Admin can still be authorized;
        // if the composite answer waited for the write step, the caller would first be told
        // whether a named payment method exists on the Profile owner's account, which is a
        // yes/no oracle over another account. This is the first step that holds both halves
        // of the answer (the share verdict on the stash, the grant row in this batch), and
        // the Order write asks the same helper again as defense in depth.
        //
        // It runs after the unprocessed-keys refusal above deliberately: a partly served
        // batch has no grant answer at all, and refusing an authorized Unit Admin with
        // FORBIDDEN because DynamoDB throttled would be a wrong verdict, not a safe one.
        authorizeCustodySale(ctx.stash, orderOrigin(guard), ctx.stash.custodySaleRead.actorAccountId);
    }
    return ctx.stash.activeUnitCampaignId;
}
