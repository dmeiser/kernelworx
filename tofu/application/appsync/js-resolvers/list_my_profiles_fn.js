import { util } from '@aws-appsync/utils';

/**
 * Page-size budget for listMyProfiles (issue #328 follow-up).
 *
 * The API has resolver_count_limit = 1000. Worst-case fan-out for this query
 * is 1 query resolver + 5 per-item field resolvers (profileId, ownerAccountId,
 * isOwner, permissions, latestCampaign) for each returned SellerProfile:
 *
 *   invocations(pageSize) = 1 + 5 * pageSize
 *
 *   MAX_PAGE_LIMIT = 100  -> 501 invocations worst case (~2x headroom,
 *                            matching the measured basis in api.tf).
 *   DEFAULT_PAGE_LIMIT=50 -> 251 invocations (~4x headroom) for clients
 *                            that do not ask for a specific page size.
 *
 * The cap is enforced server-side: a client-requested limit above
 * MAX_PAGE_LIMIT is clamped, so a single response can never exceed the
 * resolver budget regardless of what the client asks for.
 */
const DEFAULT_PAGE_LIMIT = 50;
const MAX_PAGE_LIMIT = 100;

/**
 * Resolve the effective page size: clamp positive client limits to
 * MAX_PAGE_LIMIT and fall back to DEFAULT_PAGE_LIMIT otherwise.
 */
function effectiveLimit(requestedLimit) {
    if (typeof requestedLimit === 'number' && Number.isFinite(requestedLimit) && requestedLimit > 0) {
        return Math.min(requestedLimit, MAX_PAGE_LIMIT);
    }
    return DEFAULT_PAGE_LIMIT;
}

/**
 * List all profiles owned by the current user with pagination.
 * Query profiles table by ownerAccountId (partition key).
 */
export function request(ctx) {
    const accountId = `ACCOUNT#${ctx.identity.sub}`;

    // Using low-level DynamoDB API to query by partition key
    const request = {
        operation: 'Query',
        index: null,
        query: {
            expression: 'ownerAccountId = :accountId',
            expressionValues: {
                ':accountId': { S: accountId }
            }
        },
        limit: effectiveLimit(ctx.args.limit)
    };
    if (ctx.args.nextToken) {
        request.nextToken = ctx.args.nextToken;
    }

    return request;
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const items = ctx.result.items || [];

    // Filter out any incomplete/deleted records (must have createdAt)
    const validItems = items.filter(item => item.createdAt);

    // Convert from DynamoDB format and add computed fields
    return {
        profiles: validItems.map(item => ({
            ...item,
            isOwner: true,
            permissions: ["READ", "WRITE"]
        })),
        nextToken: ctx.result.nextToken || null
    };
}
