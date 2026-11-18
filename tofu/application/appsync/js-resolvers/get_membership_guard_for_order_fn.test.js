import { describe, it } from 'node:test';
import assert from 'node:assert';
import { request, response } from './get_membership_guard_for_order_fn.js';

describe('get_membership_guard_for_order_fn request', () => {
    it('gets the guard addressed by the campaign alone, strongly', () => {
        const result = request({ stash: { campaignId: 'CAMPAIGN#c1' } });
        assert.strictEqual(result.operation, 'GetItem');
        assert.strictEqual(result.consistentRead, true);
        assert.deepStrictEqual(result.key, { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' });
    });

    it('normalizes an unprefixed campaignId to the stored DB form', () => {
        const result = request({ stash: { campaignId: 'c1' } });
        assert.strictEqual(result.key.pk, 'SCOUT_CAMPAIGN#CAMPAIGN#c1');
    });

    it('refuses to read a guard for a campaign it cannot name', () => {
        assert.throws(() => request({ stash: {} }), /INVALID_INPUT: campaignId is required to read the join guard/);
    });
});

describe('get_membership_guard_for_order_fn response', () => {
    it('stashes the guard and the Unit Campaign it points at', () => {
        const stash = {};
        const returned = response({ stash, result: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-1' } });
        assert.strictEqual(stash.activeUnitCampaignId, 'uc-1');
        assert.strictEqual(stash.membershipGuard.activeUnitCampaignId, 'uc-1');
        assert.strictEqual(returned, 'uc-1');
    });

    it('stashes no join when the guard row is absent, which is not an error', () => {
        // An independent campaign has no guard row. The Order it produces records
        // a null scope, so a later join cannot look like this sale's origin.
        const stash = {};
        assert.strictEqual(response({ stash, result: null }), null);
        assert.strictEqual(stash.membershipGuard, null);
        assert.strictEqual(stash.activeUnitCampaignId, null);
    });

    it('stashes no join for a guard whose pointer was cleared by removal', () => {
        const stash = {};
        response({ stash, result: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' } });
        assert.strictEqual(stash.activeUnitCampaignId, null);
    });

    it('surfaces a data source failure instead of reading it as no join', () => {
        assert.throws(
            () => response({ stash: {}, error: { message: 'throttled', type: 'THROTTLED' } }),
            /THROTTLED: throttled/
        );
    });
});

// §2.4.2 — the same step now also reads the custody rows and the idempotency marker for a
// door-to-door sale. The shape of this read is the constraint that decides the whole
// design: AppSync allows one datastore call per pipeline function and createOrder's
// resolver already carries the 10 functions AppSync allows, so the sale's three reads ride
// ONE cross-table BatchGetItem rather than adding a step. An order that is not a sale must
// keep issuing exactly the GetItem above.
describe('get_membership_guard_for_order_fn request: CONSUME_SCOUT_CUSTODY read', () => {
    const ACCOUNT = '11111111-1111-4111-8111-111111111111';
    const UNIT_CAMPAIGNS_TABLE = '${unit_campaigns_table_name}';
    const INVENTORY_TABLE = '${inventory_table_name}';
    const FULFILLMENTS_TABLE = '${order_fulfillments_table_name}';

    function saleCtx(options) {
        const opts = options || {};
        const stash = {
            campaignId: 'CAMPAIGN#c1',
            profileId: 'PROFILE#p1',
            // `unitId` is stored bare on both the Campaign row and the guard row; the
            // `UNIT#` spelling is the units table's partition key, not this attribute.
            campaign: { profileId: 'PROFILE#p1', unitId: 'pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' },
            // What the share step ahead of this one concluded. The Profile path is the
            // usual answer; the Unit Admin path is the case that needs the grant read.
            profileWriteAuthorized: opts.noProfileWrite !== true
        };
        if (opts.unlinked === true) {
            delete stash.campaign.unitCampaignId;
        }
        const input = Object.assign(
            {
                profileId: 'PROFILE#p1',
                campaignId: 'CAMPAIGN#c1',
                fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
                idempotencyKey: 'sale-1',
                lineItems: [{ productId: 'PROD#1', quantity: 4 }, { productId: 'PROD#2', quantity: 1 }, { productId: 'PROD#1', quantity: 2 }]
            },
            opts.input || {}
        );
        return { args: { input }, identity: { claims: { sub: ACCOUNT } }, stash };
    }

    it('reads guard, custody and marker in one strongly consistent call', () => {
        const result = request(saleCtx());
        assert.strictEqual(result.operation, 'BatchGetItem');
        const tableNames = Object.keys(result.tables);
        assert.deepStrictEqual(tableNames, [UNIT_CAMPAIGNS_TABLE, INVENTORY_TABLE, FULFILLMENTS_TABLE]);
        for (const name of tableNames) {
            assert.strictEqual(result.tables[name].consistentRead, true, `${name} must be strong: the sale's scope and version pins are both facts about now`);
        }
        assert.deepStrictEqual(result.tables[UNIT_CAMPAIGNS_TABLE].keys, [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' }]);
        assert.deepStrictEqual(result.tables[INVENTORY_TABLE].keys, [
            { pk: 'UNIT_CAMPAIGN#uc-pack-3149-fall-2026', sk: 'PRODUCT#PROD#1#CUSTODY#PROFILE#p1' },
            { pk: 'UNIT_CAMPAIGN#uc-pack-3149-fall-2026', sk: 'PRODUCT#PROD#2#CUSTODY#PROFILE#p1' }
        ]);
        assert.deepStrictEqual(result.tables[FULFILLMENTS_TABLE].keys, [{ pk: 'IDEM#' + ACCOUNT + '#createOrder#CAMPAIGN%23c1', sk: 'IDEM#sale-1' }]);
    });

    it('stashes what the write step must re-check before it consumes anything', () => {
        const ctx = saleCtx();
        request(ctx);
        assert.deepStrictEqual(ctx.stash.custodySaleRead, {
            unitCampaignId: 'uc-pack-3149-fall-2026',
            profileId: 'PROFILE#p1',
            idempotencyKey: 'sale-1',
            // The caller this batch read the Unit grant for. The authorization decision
            // this step makes has to be about that account, not about whatever the write
            // step later re-derives.
            actorAccountId: ACCOUNT
        });
    });

    it('reads no custody for a campaign that has never been joined, and still reads the marker', () => {
        // A campaign with no link has no Unit Campaign to hold custody, so the inventory
        // table simply is not part of the call.
        const result = request(saleCtx({ unlinked: true }));
        assert.deepStrictEqual(Object.keys(result.tables), [UNIT_CAMPAIGNS_TABLE, FULFILLMENTS_TABLE]);
    });

    it('refuses a sale with no key, before reading a marker it cannot name', () => {
        assert.throws(() => request(saleCtx({ input: { idempotencyKey: null } })), /INVALID_INPUT: idempotencyKey is required when fulfillmentMode = CONSUME_SCOUT_CUSTODY/);
    });

    it('refuses a sale with no session, because the marker is keyed by the caller', () => {
        const ctx = saleCtx();
        delete ctx.identity;
        assert.throws(() => request(ctx), /UNAUTHORIZED: A signed-in account is required to place a custody sale/);
    });

    it('leaves a NONE-mode order on the single GetItem it used before', () => {
        const result = request({ args: { input: { fulfillmentMode: null } }, stash: { campaignId: 'CAMPAIGN#c1' } });
        assert.strictEqual(result.operation, 'GetItem');
    });
});

describe('get_membership_guard_for_order_fn response: batched answer', () => {
    const UNIT_CAMPAIGNS_TABLE = '${unit_campaigns_table_name}';
    const INVENTORY_TABLE = '${inventory_table_name}';
    const FULFILLMENTS_TABLE = '${order_fulfillments_table_name}';

    function batchCtx(data) {
        return {
            stash: {
                custodySaleRead: { unitCampaignId: 'uc-1', profileId: 'PROFILE#p1', idempotencyKey: 'sale-1', actorAccountId: 'ACCOUNT#a-1' },
                // These fixtures are an authorized sale: the Profile half is the usual
                // answer. The Unit-Admin half has its own block below.
                profileWriteAuthorized: true
            },
            result: { data }
        };
    }

    it('splits the batch into guard, custody rows and marker', () => {
        const ctx = batchCtx({
            [UNIT_CAMPAIGNS_TABLE]: [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-1' }],
            [INVENTORY_TABLE]: [{ productId: 'PROD#1', withScoutQty: 7, version: 4 }],
            [FULFILLMENTS_TABLE]: [{ pk: 'IDEM#a#createOrder#CAMPAIGN%23c1', sk: 'IDEM#sale-1', status: 'COMPLETED' }]
        });
        const returned = response(ctx);
        const stash = ctx.stash;
        assert.strictEqual(returned, 'uc-1');
        assert.strictEqual(stash.membershipGuard.activeUnitCampaignId, 'uc-1');
        assert.deepStrictEqual(stash.custodyRows, [{ productId: 'PROD#1', withScoutQty: 7, version: 4 }]);
        assert.strictEqual(stash.idempotencyMarker.status, 'COMPLETED');
    });

    it('reads a missing guard, custody and marker as none of each, never an error', () => {
        // BatchGetItem omits what it did not find, which is exactly an unjoined campaign,
        // a Scout holding nothing, and a first attempt at this key.
        const ctx = batchCtx({});
        assert.strictEqual(response(ctx), null);
        const stash = ctx.stash;
        assert.strictEqual(stash.membershipGuard, null);
        assert.deepStrictEqual(stash.custodyRows, []);
        assert.strictEqual(stash.idempotencyMarker, null);
    });

    it('keeps the plain GetItem shape for a NONE-mode order', () => {
        const stash = {};
        response({ stash, result: { pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-9' } });
        assert.strictEqual(stash.activeUnitCampaignId, 'uc-9');
        assert.strictEqual(stash.custodyRows, undefined);
        assert.strictEqual(stash.idempotencyMarker, undefined);
    });

    it('surfaces a batch failure instead of reading it as no join', () => {
        assert.throws(() => batchThrowing(), /THROTTLED: throttled/);
    });

    function batchThrowing() {
        const ctx = batchCtx({});
        ctx.error = { message: 'throttled', type: 'THROTTLED' };
        return response(ctx);
    }
});

// A BatchGetItem that did not look at some keys is not an answer about them, and this read
// decides three things at once: whether the campaign is joined, what the Scout is holding,
// and whether this key already exists. Reading a non-answer as absence would let a sale
// stamp a null scope or under-consume custody, then preserve that answer in the COMPLETED
// marker for every retry. So a partial batch fails in the read step, before any write.
describe('get_membership_guard_for_order_fn response: an partly served batch is not an answer', () => {
    const UNIT_CAMPAIGNS_TABLE = '${unit_campaigns_table_name}';
    const INVENTORY_TABLE = '${inventory_table_name}';
    const FULFILLMENTS_TABLE = '${order_fulfillments_table_name}';

    function partial(unprocessedKeys) {
        const ctx = {
            stash: { custodySaleRead: { unitCampaignId: 'uc-1', profileId: 'PROFILE#p1', idempotencyKey: 'sale-1' } },
            result: {
                data: {
                    [UNIT_CAMPAIGNS_TABLE]: [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-1' }]
                },
                unprocessedKeys: unprocessedKeys
            }
        };
        return () => response(ctx);
    }

    it('refuses when the custody keys were not looked at', () => {
        assert.throws(partial({ [INVENTORY_TABLE]: [{ pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P1#CUSTODY#PROFILE#p1' }] }), /RESOURCE_BUSY: The sale reads were only partly served; no order was written/);
    });

    it('refuses when the guard row was not looked at, which would otherwise read as independent', () => {
        assert.throws(partial({ [UNIT_CAMPAIGNS_TABLE]: [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' }] }), /RESOURCE_BUSY/);
    });

    it('refuses when the marker was not looked at, which would otherwise consume custody twice', () => {
        assert.throws(partial({ [FULFILLMENTS_TABLE]: [{ pk: 'IDEM#a#createOrder#CAMPAIGN%23c1', sk: 'IDEM#sale-1' }] }), /RESOURCE_BUSY/);
    });

    it('refuses when several tables were partly served', () => {
        assert.throws(partial({
            [INVENTORY_TABLE]: [{ pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P1#CUSTODY#PROFILE#p1' }, { pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P2#CUSTODY#PROFILE#p1' }],
            [UNIT_CAMPAIGNS_TABLE]: [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD' }]
        }), /RESOURCE_BUSY/);
    });

    it('refuses on an entry that is not the documented key list, rather than reading it as zero', () => {
        // The raw DynamoDB wire shape wraps the list in `{ keys: [...] }`. Nothing in this
        // pipeline produces that shape, but an entry this code cannot count must never
        // read as "nothing was left unprocessed".
        assert.throws(partial({ [INVENTORY_TABLE]: { keys: [{ pk: 'UNIT_CAMPAIGN#uc-1', sk: 'PRODUCT#P1#CUSTODY#PROFILE#p1' }] } }), /RESOURCE_BUSY/);
    });

    it('accepts a fully served batch, and an empty unprocessedKeys entry', () => {
        const ctx = {
            stash: {
                custodySaleRead: { unitCampaignId: 'uc-1', profileId: 'PROFILE#p1', idempotencyKey: 'sale-1', actorAccountId: 'ACCOUNT#a-1' },
                profileWriteAuthorized: true
            },
            result: { data: {}, unprocessedKeys: { [INVENTORY_TABLE]: [] } }
        };
        assert.strictEqual(response(ctx), null);
    });
});

// SEC-1 (§2.4.2): a Unit Admin with no share on the Profile is still allowed to record
// the sale of her own Unit's custody. The share step hands its verdict down instead of
// ending the pipeline, and this step -- the only one with a datastore call left on a sale
// -- pays for the grant read that answers the other half.
describe('get_membership_guard_for_order_fn: the Unit Admin grant rides the sale batch', () => {
    const ACCOUNT = '11111111-1111-4111-8111-111111111111';
    const UNIT_CAMPAIGNS_TABLE = '${unit_campaigns_table_name}';
    const INVENTORY_TABLE = '${inventory_table_name}';
    const FULFILLMENTS_TABLE = '${order_fulfillments_table_name}';
    const UNITS_TABLE = '${units_table_name}';

    function ctx(noProfileWrite) {
        return {
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    campaignId: 'CAMPAIGN#c1',
                    fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
                    idempotencyKey: 'sale-1',
                    lineItems: [{ productId: 'PROD#1', quantity: 4 }]
                }
            },
            identity: { claims: { sub: ACCOUNT } },
            stash: {
                campaignId: 'CAMPAIGN#c1',
                profileId: 'PROFILE#p1',
                campaign: { profileId: 'PROFILE#p1', unitId: 'pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' },
                profileWriteAuthorized: noProfileWrite !== true
            }
        };
    }

    it('adds the grant key when the Profile half failed', () => {
        const result = request(ctx(true));

        assert.deepStrictEqual(result.tables[UNITS_TABLE], {
            keys: [{ pk: 'UNIT#pack-3149', sk: 'GRANT#' + ACCOUNT }],
            consistentRead: true
        });
    });

    it('reads no grant at all when the Profile half already authorized the sale', () => {
        const result = request(ctx(false));

        assert.ok(!Object.hasOwn(result.tables, UNITS_TABLE), 'a Profile WRITE is the whole answer; the units table is not part of the call');
    });

    it('reads no grant for a campaign that names no Unit, because there is no Unit Admin to ask', () => {
        const unlinked = ctx(true);
        delete unlinked.stash.campaign.unitId;

        assert.ok(!Object.hasOwn(request(unlinked).tables, UNITS_TABLE));
    });

    it('stashes the grant row so the write step can check it against the guard', () => {
        const grant = { pk: 'UNIT#pack-3149', sk: 'GRANT#' + ACCOUNT, role: 'UNIT_ADMIN' };
        const stashed = ctx(true);
        request(stashed);
        const answered = response({
            stash: stashed.stash,
            result: {
                data: {
                    [UNIT_CAMPAIGNS_TABLE]: [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026', unitId: 'pack-3149' }],
                    [INVENTORY_TABLE]: [{ productId: 'PROD#1', withScoutQty: 9, version: 2 }],
                    [UNITS_TABLE]: [grant]
                }
            }
        });

        assert.strictEqual(answered, 'uc-pack-3149-fall-2026');
        assert.deepStrictEqual(stashed.stash.unitAdminGrant, grant);
    });

    it('stashes a missing grant as null, and refuses the sale it found nothing for', () => {
        // The stash is set before the decision, so the read still records what it saw
        // even though the answer is a denial: a revoked admin reads as absent rather
        // than unknown, and the caller is refused.
        const stashed = ctx(true);
        request(stashed);
        assert.throws(
            () => response({ stash: stashed.stash, result: { data: {} } }),
            /FORBIDDEN: Forbidden: a custody sale needs the profile owner, an account with WRITE permission on the profile, or an admin of the campaign Unit/
        );

        assert.strictEqual(stashed.stash.unitAdminGrant, null);
    });
});

// SEC-1 (re-review): the composite answer is not only correct, it arrives EARLY. The share
// step defers its FORBIDDEN for a custody sale, so if the composite waited for the write
// step, `validate_payment_method` would run first and answer whether a named payment
// method exists on the Profile owner's account -- a yes/no oracle over another account for
// a caller who was never authorized. The read step is where the answer lands, so the
// pipeline puts payment validation behind it (pinned in Python by
// `test_custody_sale_authorization_precedes_payment_validation`).
describe('get_membership_guard_for_order_fn response: the sale is authorized at the read step', () => {
    const ACCOUNT = '11111111-1111-4111-8111-111111111111';
    const UNIT_CAMPAIGNS_TABLE = '${unit_campaigns_table_name}';
    const UNITS_TABLE = '${units_table_name}';
    const DENIED = /FORBIDDEN: Forbidden: a custody sale needs the profile owner, an account with WRITE permission on the profile, or an admin of the campaign Unit/;

    function answered(options) {
        const opts = options || {};
        const ctx = {
            stash: {
                campaignId: 'CAMPAIGN#c1',
                profileId: 'PROFILE#p1',
                campaign: { profileId: 'PROFILE#p1', unitId: 'pack-3149', unitCampaignId: 'uc-pack-3149-fall-2026' },
                profileWriteAuthorized: opts.profileWrite === true
            },
            identity: { claims: { sub: ACCOUNT } },
            args: {
                input: {
                    profileId: 'PROFILE#p1',
                    campaignId: 'CAMPAIGN#c1',
                    fulfillmentMode: 'CONSUME_SCOUT_CUSTODY',
                    idempotencyKey: 'sale-1',
                    lineItems: [{ productId: 'PROD#1', quantity: 4 }]
                }
            }
        };
        request(ctx);
        const data = {};
        if (opts.joined !== false) {
            data[UNIT_CAMPAIGNS_TABLE] = [{ pk: 'SCOUT_CAMPAIGN#CAMPAIGN#c1', sk: 'MEMBERSHIP_GUARD', activeUnitCampaignId: 'uc-pack-3149-fall-2026', unitId: 'pack-3149' }];
        }
        if (opts.grant) {
            data[UNITS_TABLE] = [opts.grant];
        }
        ctx.result = { data: data };
        return ctx;
    }

    it('refuses an account with neither half, before any payment-method verdict can run', () => {
        const ctx = answered({ profileWrite: false });

        assert.throws(() => response(ctx), DENIED);
    });

    it('refuses a caller whose grant is for a different Unit than the guard names', () => {
        const ctx = answered({
            profileWrite: false,
            grant: { pk: 'UNIT#pack-OTHER', sk: 'GRANT#' + ACCOUNT, role: 'UNIT_ADMIN' }
        });

        assert.throws(() => response(ctx), DENIED);
    });

    it('refuses a caller whose grant belongs to another account', () => {
        const ctx = answered({
            profileWrite: false,
            grant: { pk: 'UNIT#pack-3149', sk: 'GRANT#22222222-2222-4222-8222-222222222222', role: 'UNIT_ADMIN' }
        });

        assert.throws(() => response(ctx), DENIED);
    });

    it('refuses a sale whose campaign names no Unit, because there is no Unit Admin to ask', () => {
        const ctx = answered({ profileWrite: false, joined: false });

        assert.throws(() => response(ctx), DENIED);
    });

    it('admits the Profile owner or a WRITE share with no grant read at all', () => {
        const ctx = answered({ profileWrite: true });

        assert.strictEqual(response(ctx), 'uc-pack-3149-fall-2026');
        assert.strictEqual(ctx.stash.unitAdminGrant, null);
    });

    it('admits an admin of the Unit the guard names', () => {
        const ctx = answered({
            profileWrite: false,
            grant: { pk: 'UNIT#pack-3149', sk: 'GRANT#' + ACCOUNT, role: 'UNIT_ADMIN' }
        });

        assert.strictEqual(response(ctx), 'uc-pack-3149-fall-2026');
        assert.strictEqual(ctx.stash.unitAdminGrant.pk, 'UNIT#pack-3149');
    });

    it('refuses on the same wording whichever half failed, so the denial is not a probe', () => {
        const noGrant = answered({ profileWrite: false });
        const wrongUnit = answered({ profileWrite: false, grant: { pk: 'UNIT#nope', sk: 'GRANT#' + ACCOUNT } });

        let first = '';
        try {
            response(noGrant);
        } catch (error) {
            first = error.message;
        }
        let second = '';
        try {
            response(wrongUnit);
        } catch (error) {
            second = error.message;
        }
        assert.ok(first !== '' && first === second, 'one denial for both failures: ' + first);
    });
});
