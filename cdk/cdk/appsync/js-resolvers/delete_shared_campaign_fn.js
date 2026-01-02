import { util } from '@aws-appsync/utils';

export function request(ctx) {
    return {
        operation: 'DeleteItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: ctx.args.sharedCampaignCode, SK: 'METADATA' })
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }
    return true;
}
