import { util } from '@aws-appsync/utils';
import { PUBLIC_ORDER_UNAVAILABLE } from './lib/public_order.js';

// Step 3 of the publicCreateOrder pipeline (public-orders abuse guard): a
// per-share-token fixed-window throttle on the anonymous write path. The WAF
// rate rule is account-wide and absent on ephemeral, so without this guard a
// caller holding one valid share URL could flood order creates (burning the
// campaign's 500-order cap and flooding seller/buyer inboxes) with no
// application-layer backpressure.
//
// The numbers, chosen as a deliberate trade-off and documented here: 5 creates
// per 60-second window per share token. A legitimate buyer submits once or
// twice (a retry after a network blip), so 5/min never blocks a real buyer,
// while it bounds a flood to ~5 orders/min/token before the 500-order cap even
// matters. The throttle counts the SERVER-side token validated in step 2
// (ctx.stash.publicOrderToken), so a caller cannot mint a fresh throttle
// identity by varying the token they submit.
//
// Shape: one small DynamoDB item per (token, window), keyed
// "<token>#<windowStartEpoch>", with a TTL attribute so expired windows clean
// themselves up. Each create is a single atomic UpdateItem: ADD 1 to the
// count with the condition attribute_not_exists(#n) OR #n < :limit, so
// concurrent creates race on the condition and the losers are rejected - no
// read-then-write overshoot. The window lives in the KEY, so a new window is
// simply a new item and there is no rollover logic to get wrong. DynamoDB TTL
// deletion is lazy (typically within 48h) but harmless: an expired window's
// item is never read again because the key carries its window.
//
// Rejection reuses the cap's public limit error shape
// (PUBLIC_ORDER_LIMIT_EXCEEDED, "This campaign has reached its public order
// limit"): the response must not disclose that this is a throttle rather than
// the campaign cap. It also emits the PUBLIC_ORDER_CAP_REJECTED marker so a
// sustained throttle rejection folds into the same public-cap-rejected
// CloudWatch alarm as genuine cap hits.
const WINDOW_SECONDS = 60;
const MAX_CREATES_PER_WINDOW = 5;
const ITEM_TTL_PADDING_SECONDS = 120;

export function request(ctx) {
    const stash = ctx.stash || {};
    const token = stash.publicOrderToken;

    if (!token) {
        // Wiring fault: step 2 always stashes the validated token.
        util.error(PUBLIC_ORDER_UNAVAILABLE, 'NOT_FOUND');
        return null;
    }

    const now = Math.floor(util.time.nowEpochSeconds());
    const windowStart = Math.floor(now / WINDOW_SECONDS) * WINDOW_SECONDS;

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ key: token + '#' + windowStart }),
        update: {
            expression: 'ADD #n :one SET #expiresAt = :expiresAt',
            expressionNames: { '#n': 'n', '#expiresAt': 'expiresAt' },
            expressionValues: util.dynamodb.toMapValues({
                ':one': 1,
                ':expiresAt': windowStart + ITEM_TTL_PADDING_SECONDS
            })
        },
        condition: {
            expression: 'attribute_not_exists(#n) OR #n < :limit',
            expressionValues: util.dynamodb.toMapValues({ ':limit': MAX_CREATES_PER_WINDOW })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        // Over the per-token window bound. Identical to the campaign-cap
        // rejection: the caller cannot tell a throttle from the cap, and a
        // flood of these lands in the public-cap-rejected alarm.
        console.error('PUBLIC_ORDER_CAP_REJECTED');
        util.error('This campaign has reached its public order limit', 'PUBLIC_ORDER_LIMIT_EXCEEDED');
        return null;
    }

    return { allowed: true };
}
