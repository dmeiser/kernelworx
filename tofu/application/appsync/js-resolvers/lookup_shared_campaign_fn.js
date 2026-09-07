import { util } from '@aws-appsync/utils';

export function request(ctx) {
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const code = input.sharedCampaignCode;

    if (!code || (typeof code === 'string' && code.trim() === '')) {
        ctx.stash.skipSharedCampaign = true;
        return {
            operation: 'GetItem',
            key: util.dynamodb.toMapValues({ sharedCampaignCode: 'NOOP' }),
        };
    }

    return {
        operation: 'GetItem',
        key: util.dynamodb.toMapValues({ sharedCampaignCode: typeof code === 'string' ? code.trim() : code }),
        consistentRead: true,
    };
}

export function response(ctx) {
    if (ctx.stash && ctx.stash.skipSharedCampaign) {
        return null;
    }

    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    const sharedCampaign = ctx.result;
    const input = ctx.args && ctx.args.input ? ctx.args.input : {};
    const code = input.sharedCampaignCode;

    if (!sharedCampaign || !sharedCampaign.sharedCampaignCode) {
        util.error('Shared Campaign ' + code + ' not found', 'NotFound');
    }

    if (sharedCampaign.isActive === false) {
        util.error('Shared Campaign ' + code + ' is no longer active', 'InvalidInput');
    }

    ctx.stash.sharedCampaign = sharedCampaign;
    return sharedCampaign;
}
