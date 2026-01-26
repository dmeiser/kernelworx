import { util } from '@aws-appsync/utils';

export function request(ctx) {
  // Log initial context to help debug why stash is empty
  console.log('DiagnoseCatalogForOrder: request args=', JSON.stringify(ctx.args || {}));
  console.log('DiagnoseCatalogForOrder: request stash=', JSON.stringify(ctx.stash || {}));
  console.log('DiagnoseCatalogForOrder: identity=', JSON.stringify(ctx.identity || {}));

  const campaignId = ctx.args.input && ctx.args.input.campaignId;
  if (!campaignId) {
    // Return a benign no-op query so pipeline continues; we'll still have logs above
    return {
      operation: 'Query',
      index: 'campaignId-index',
      query: {
        expression: 'campaignId = :campaignId',
        expressionValues: util.dynamodb.toMapValues({ ':campaignId': 'NOOP' })
      },
      limit: 1
    };
  }

  // Query campaigns table by campaignId-index to fetch campaign row
  return {
    operation: 'Query',
    index: 'campaignId-index',
    query: {
      expression: 'campaignId = :campaignId',
      expressionValues: util.dynamodb.toMapValues({ ':campaignId': campaignId })
    },
    limit: 1
  };
}

export function response(ctx) {
  if (ctx.error) {
    // Log and rethrow error
    console.log('DiagnoseCatalogForOrder: query error=', ctx.error);
    util.error(ctx.error.message, ctx.error.type);
  }

  const items = ctx.result.items || [];
  console.log('DiagnoseCatalogForOrder: query items=', JSON.stringify(items));

  if (items.length > 0) {
    const campaign = items[0];
    // Normalize and stash catalogId for downstream functions
    const rawCatalogId = campaign.catalogId;
    const normalizedCatalogId = (typeof rawCatalogId === 'string' && rawCatalogId.startsWith('CATALOG#')) ? rawCatalogId : (rawCatalogId ? 'CATALOG#' + rawCatalogId : null);

    ctx.stash.campaign = campaign;
    if (normalizedCatalogId) {
      ctx.stash.catalogId = normalizedCatalogId;
      console.log('DiagnoseCatalogForOrder: stashed catalogId=', ctx.stash.catalogId);
    } else {
      console.log('DiagnoseCatalogForOrder: campaign has no catalogId');
    }

    // Return campaign so other functions can use it
    return campaign;
  }

  // Nothing found - just return null (pipeline continues)
  console.log('DiagnoseCatalogForOrder: no campaign found for campaignId in args');
  return null;
}
