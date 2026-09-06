import { util } from '@aws-appsync/utils';

export function request(ctx) {
  if (!ctx.identity || !ctx.identity.sub) {
    util.error('Authentication required', 'Unauthorized');
  }

  const input = (ctx.args && ctx.args.input) || {};

  const allowedFields = ['givenName', 'familyName', 'city', 'state', 'unitType', 'unitNumber'];
  const provided = allowedFields.filter(f => input[f] !== undefined && input[f] !== null);
  if (provided.length === 0) {
    util.error('At least one field must be provided (givenName, familyName, city, state, unitType, or unitNumber)', 'BadRequest');
  }

  if (input.unitNumber !== undefined && input.unitNumber !== null) {
    if (typeof input.unitNumber !== 'number' || !Number.isFinite(input.unitNumber) || Math.floor(input.unitNumber) !== input.unitNumber || input.unitNumber < 1) {
      util.error('unitNumber must be a positive integer', 'BadRequest');
    }
  }

  const expNames = { '#updatedAt': 'updatedAt' };
  const expVals = { ':updatedAt': util.time.nowISO8601() };
  const sets = ['#updatedAt = :updatedAt'];

  for (const field of provided) {
    expNames['#' + field] = field;
    expVals[':' + field] = input[field];
    sets.push('#' + field + ' = :' + field);
  }

  return {
    operation: 'UpdateItem',
    key: util.dynamodb.toMapValues({ accountId: 'ACCOUNT#' + ctx.identity.sub }),
    update: {
      expression: 'SET ' + sets.join(', '),
      expressionNames: expNames,
      expressionValues: util.dynamodb.toMapValues(expVals)
    },
    condition: {
      expression: 'attribute_exists(accountId)'
    }
  };
}

export function response(ctx) {
  if (ctx.error) {
    if (ctx.error.type === 'DynamoDB:ConditionalCheckFailedException') {
      util.error('Account ' + ctx.identity.sub + ' not found', 'NotFound');
    }
    util.error(ctx.error.message, ctx.error.type);
  }

  return ctx.result;
}
