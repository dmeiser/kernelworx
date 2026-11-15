/**
 * Every GraphQL document the browser sends is validated against the SDL that
 * AppSync actually serves.
 *
 * Mocked Apollo tests are blind to a malformed document: a mocked link answers by
 * document equality, so a query that references a fragment it never includes, a
 * field the schema does not have, or a variable the operation does not declare
 * passes locally and is rejected by the API on the first real call. This test is
 * the check that a real request would survive validation.
 *
 * The two AppSync authorization directives are provided by the service rather
 * than declared in the SDL, so they are declared here before the schema is built;
 * nothing else about the schema is adjusted.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { buildSchema, type DocumentNode, parse, validate } from 'graphql';
import * as documents from '../src/lib/graphql';

const APPSYNC_DIRECTIVES = `
directive @aws_api_key on FIELD_DEFINITION | OBJECT | ARGUMENT_DEFINITION | INPUT_FIELD_DEFINITION
directive @aws_cognito_user_pools on FIELD_DEFINITION | OBJECT | ARGUMENT_DEFINITION | INPUT_FIELD_DEFINITION
`;

// The suite runs from the frontend package, so the served SDL sits one level up.
const schemaPath = resolve(process.cwd(), '../tofu/application/schema/schema.graphql');
const schema = buildSchema(APPSYNC_DIRECTIVES + readFileSync(schemaPath, 'utf8'));

const isDocument = (value: unknown): value is DocumentNode =>
  typeof value === 'object' && value !== null && (value as DocumentNode).kind === 'Document';

const namedDocuments = Object.entries(documents)
  .filter(([, value]) => isDocument(value))
  .map(([name, doc]) => ({ name, doc: doc as DocumentNode }));

// A fragment on its own is not a request, and graphql-js reports an unused
// fragment as an error; only documents that carry an operation are validated as
// the request they are. A fragment that no operation attaches is caught by the
// fragment-coverage test below, which is the failure this guard exists for.
const operations = namedDocuments.filter((entry) =>
  entry.doc.definitions.some((definition) => definition.kind === 'OperationDefinition'),
);

const collectFragmentNames = (doc: DocumentNode): string[] => {
  const names: string[] = [];
  for (const definition of doc.definitions) {
    JSON.stringify(definition, (_key, value) => {
      if (value && value.kind === 'FragmentSpread') names.push(value.name.value);
      return value;
    });
  }
  return names;
};

describe('browser GraphQL documents against the served SDL', () => {
  it('finds the Show & Sell documents to guard', () => {
    const names = namedDocuments.map((entry) => entry.name);
    for (const required of [
      'CREATE_UNIT',
      'UPDATE_UNIT',
      'MY_UNITS',
      'GET_UNIT',
      'LIST_UNIT_ADMINS',
      'LIST_UNIT_INVITES',
      'CREATE_UNIT_CAMPAIGN',
      'JOIN_UNIT_CAMPAIGN',
      'LIST_UNIT_CAMPAIGN_ROSTER',
    ]) {
      expect(names).toContain(required);
    }
  });

  it('attaches every Show & Sell fragment to the request that shows it', () => {
    const attached = new Set(operations.flatMap((entry) => collectFragmentNames(entry.doc)));

    // The defect this guards: a request spreads a fragment shape whose definition
    // it never interpolated, so the API rejects the document before resolvers run.
    for (const fragment of ['UnitFields', 'UnitAccessGrantFields', 'UnitInviteFields', 'UnitCampaignFields', 'UnitCampaignMembershipFields']) {
      expect(attached).toContain(fragment);
    }
  });

  it.each(operations.map((entry) => [entry.name, entry.doc]))('%s validates against the SDL', (_name, doc) => {
    expect(validate(schema, doc)).toEqual([]);
  });

  it('rejects a document that spreads a fragment it did not include', () => {
    const broken = parse(`
      mutation CreateUnit($input: CreateUnitInput!) {
        createUnit(input: $input) {
          unit {
            ...UnitFields
          }
        }
      }
    `);

    expect(validate(schema, broken).map((error) => error.message).join(' ')).toContain('Unknown fragment "UnitFields"');
  });
});
