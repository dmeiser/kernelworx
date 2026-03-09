import { util } from '@aws-appsync/utils';

function claim(ctx, name) {
    const value = ctx.identity?.claims?.[name];
    return typeof value === 'string' ? value : '';
}

export function request(ctx) {
    // No-op when already found; response() will return ctx.prev.result.
    if (ctx.prev.result) {
        return {};
    }

    const accountId = `ACCOUNT#${ctx.identity.sub}`;
    const now = util.time.nowISO8601();

    return {
        operation: 'UpdateItem',
        key: util.dynamodb.toMapValues({ accountId }),
        update: {
            expression: 'SET #email = if_not_exists(#email, :email), #givenName = if_not_exists(#givenName, :givenName), #familyName = if_not_exists(#familyName, :familyName), #city = if_not_exists(#city, :city), #state = if_not_exists(#state, :state), #unitType = if_not_exists(#unitType, :unitType), #preferences = if_not_exists(#preferences, :preferences), #createdAt = if_not_exists(#createdAt, :createdAt), #updatedAt = if_not_exists(#updatedAt, :updatedAt)',
            expressionNames: {
                '#email': 'email',
                '#givenName': 'givenName',
                '#familyName': 'familyName',
                '#city': 'city',
                '#state': 'state',
                '#unitType': 'unitType',
                '#preferences': 'preferences',
                '#createdAt': 'createdAt',
                '#updatedAt': 'updatedAt'
            },
            expressionValues: util.dynamodb.toMapValues({
                ':email': claim(ctx, 'email'),
                ':givenName': claim(ctx, 'given_name'),
                ':familyName': claim(ctx, 'family_name'),
                ':city': '',
                ':state': '',
                ':unitType': '',
                ':preferences': { paymentMethods: [] },
                ':createdAt': now,
                ':updatedAt': now
            })
        }
    };
}

export function response(ctx) {
    if (ctx.error) {
        util.error(ctx.error.message, ctx.error.type);
    }

    return ctx.prev.result || ctx.result;
}
