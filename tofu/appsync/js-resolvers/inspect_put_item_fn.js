import { util } from '@aws-appsync/utils';

export function request(ctx) {
  // No-op request (using None data source)
  return {};
}

export function response(ctx) {
  // Minimal logging: string-safe (avoid heavy serialization during deploy-time validation)
  console.log('InspectPutItem: prev.result exists=', !!(ctx.prev && ctx.prev.result));
  if (ctx.prev && ctx.prev.result && ctx.prev.result.operation === 'PutItem') {
    if (ctx.prev.result.key) console.log('InspectPutItem: key attributes present');
    if (ctx.prev.result.attributeValues) console.log('InspectPutItem: attributeValues present');
  }

  if (ctx.error) {
    util.error(ctx.error.message, ctx.error.type);
  }

  return ctx.prev && ctx.prev.result ? ctx.prev.result : null;
}
