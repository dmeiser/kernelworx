// Order origin capture (§1.4.3, API-FIX-05; data model §5.6; API contract §10).
//
// A Scout Campaign row carries `unitId`/`unitCampaignId` as its *latest* joined
// scope, and removal deliberately retains that pair so joined history survives.
// Reading it back at sale time therefore answers a different question than the
// Order is asking: after a Scout leaves Unit A and joins Unit B, the campaign row
// says B, and every Order that asks the campaign where it was sold moves old
// demand -- and unfulfilled public Orders -- into Unit B's Council numbers.
//
// The membership guard (data model §5.6: `SCOUT_CAMPAIGN#<campaignId>` /
// `MEMBERSHIP_GUARD`) is the only current answer to "which Unit Campaign is this
// campaign joined to right now": `activeUnitCampaignId` is written only while a
// join is live, and removal clears it. The guard row ALSO carries the parent
// Unit's id beside the pointer -- written by the join claim, cleared by removal
// -- so the Order origin needs exactly one strongly consistent Get: the guard
// answers both halves of the scope with no second lookup.
//
// Rows written before the denormalization predate `unitId`: a guard that names
// a Unit Campaign but carries no Unit records the pointer it did name and no
// Unit, because neither half is invented.
//
// An independent campaign records both fields as null, which makes "independent"
// a recorded fact rather than an absence that later acquires a meaning.

import { util } from '@aws-appsync/utils';

// The Unit Campaign this campaign is joined to *now*, or null when it is joined to
// none. Plain concatenation rather than a template literal: esbuild inlines this
// module into resolvers Terraform loads with templatefile(), and a dollar-brace
// sequence there is parsed as a Terraform expression and fails every plan (#570).
export function currentUnitCampaignId(guard) {
    if (!guard || guard.activeUnitCampaignId == null) {
        return null;
    }
    return asText(guard.activeUnitCampaignId);
}

// The only string coercion these helpers need. Written as concatenation because
// APPSYNC_JS has no String() global: `String(x)` is refused at deploy time with
// `BadRequestException: The code contains one or more errors.` Deploy run
// 43759285075 rejected exactly the four bundles that carried it and accepted the
// 167 that did not.
function asText(value) {
    return typeof value === 'string' ? value : value + '';
}

// The joined scope to stamp on an Order. `guard` is the strongly read membership
// guard; the Unit rides on it, so there is no second row to name and no second
// argument to take. A caller that reaches for the Unit Campaign row or the
// campaign's retained pair is reaching for the stale or over-fetched answer:
// the guard alone is the current one.
export function orderOrigin(guard) {
    const unitCampaignId = currentUnitCampaignId(guard);
    const unitId = guard && guard.unitId != null ? asText(guard.unitId) : null;
    return { unitId: unitId, unitCampaignId: unitCampaignId };
}

// FUNC-3: an origin stamped from a strong read stops being a stale answer only
// when the write itself refuses if the guard moves between the read and the
// commit. This is the guard row's ConditionCheck for that transaction: it pins
// exactly what the read saw -- the same live join, or (row present, join
// already removed) still no live join at all. A removal, a move, or a rejoin
// to a different Unit Campaign fails the condition and cancels the whole
// transaction, so an Order never commits with a scope that was not current at
// commit.
//
// A guard ABSENT at the read has nothing to pin: the campaign was independent
// when the pipeline asked, an Order created in that window belongs to no Unit,
// and a join committing afterwards is later than the sale -- there is no old
// scope to follow into another Unit. DynamoDB's ConditionCheck also fails on a
// missing row, so an "absent" pin could only ever break independent orders.
// Returns null in that case, and the caller writes without the pin.
export function membershipGuardCurrencyCheck(unitCampaignsTable, campaignId, guard) {
    if (!guard) {
        return null;
    }
    const joinedTo = currentUnitCampaignId(guard);
    return {
        operation: 'ConditionCheck',
        table: unitCampaignsTable,
        key: util.dynamodb.toMapValues({ pk: 'SCOUT_CAMPAIGN#' + campaignId, sk: 'MEMBERSHIP_GUARD' }),
        condition:
            joinedTo !== null
                ? {
                      expression: 'activeUnitCampaignId = :joinedTo',
                      expressionValues: util.dynamodb.toMapValues({ ':joinedTo': joinedTo })
                  }
                : { expression: 'attribute_not_exists(activeUnitCampaignId)' }
    };
}

// Which transact items of a cancelled TransactWriteItems failed. DynamoDB
// reports the per-item cancellation reasons, in transactItems order, inside
// the message: "... for specific reasons [None, ConditionalCheckFailedException,
// None]". The index is what distinguishes the causes the single error type
// cannot: the campaigns bound, the membership pin, or (the PutItem has no
// condition) neither. Returns an empty list when the message carries no list,
// and the caller's fallback decides. Plain concatenation, never a template
// literal: this file is inlined into resolvers Terraform loads with
// templatefile() (#570).
//
// Known fragility, accepted because it is pinned rather than silent: the reason
// list is read out of a human-readable message, so if AWS rewords it this
// returns [] and a genuine membership-pin conflict degrades to the fallback's
// "cap rejected" answer — the write is still refused either way, only the
// reason the buyer is told goes wrong. lib/order_origin.test.js pins the
// current message shape, so a reword fails there instead of on dev.
//
// Read with indexOf/split/for-of only: APPSYNC_JS rejects a regex literal,
// `.match`, the classic `for (init; cond; afterthought)` loop and `++`, so the
// naive parse of this message is exactly the shape the runtime refuses.
export function cancelledTransactIndexes(error) {
    const indexes = [];
    const message = error && typeof error.message === 'string' ? error.message : '';
    const opened = message.indexOf('[');
    if (opened === -1) {
        return indexes;
    }
    const afterOpen = message.substring(opened + 1);
    const closed = afterOpen.indexOf(']');
    if (closed === -1) {
        return indexes;
    }
    let position = 0;
    for (const reason of afterOpen.substring(0, closed).split(',')) {
        const trimmed = reason.trim();
        if (trimmed !== '' && trimmed !== 'None' && trimmed !== 'null') {
            indexes.push(position);
        }
        position = position + 1;
    }
    return indexes;
}
