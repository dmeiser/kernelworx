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

/** Every field name a document asks for, fragment definitions included. */
const selectedFields = (doc: DocumentNode): Set<string> => {
  const fields = new Set<string>();
  for (const definition of doc.definitions) {
    JSON.stringify(definition, (_key, value) => {
      if (value && value.kind === 'Field') fields.add(value.name.value);
      return value;
    });
  }
  return fields;
};

/** One browser document by the name it is exported under. */
const documentNamed = (name: string): DocumentNode =>
  namedDocuments.find((entry) => entry.name === name)?.doc as DocumentNode;

// The Stage 3 participant surface: the only documents a Scout's screen sends.
const PARTICIPANT_DOCUMENTS = [
  'SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT',
  'CANCEL_SHOW_AND_SELL_SIGNUP',
  'LIST_UNIT_CAMPAIGN_OPPORTUNITIES',
  'GET_SHOW_AND_SELL_OPPORTUNITY',
  'LIST_MY_SCOUT_COMMITMENTS',
  'GET_SIGNUP_CALENDAR_DATA',
];

// Fields that exist to answer "who did this to whom, and against how much stock".
// SEC-04 keeps them off the participant projections entirely.
const ADMINISTRATOR_ONLY_FIELDS = [
  'signedUpByAccountId',
  'confirmedByAccountId',
  'confirmedAt',
  'cancelledByAccountId',
  'cancellationReason',
  'createdByAccountId',
  'updatedByAccountId',
  'allocations',
  'productIds',
  'activeSignupCount',
];

const ADMINISTRATOR_FRAGMENTS = [
  'ShowAndSellSignupFields',
  'ShowAndSellAdminFields',
  'ShowAndSellAllocationFields',
  'ShowAndSellSlotFields',
  'ShowAndSellWorkPreviewFields',
];

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
      'GET_INVENTORY_POSITIONS',
      'GET_INVENTORY_MOVEMENTS',
      'GET_SCOUT_CUSTODY_BALANCES',
      'GET_ORDER_FULFILLMENTS',
      'LIST_UNIT_SCOUT_CAMPAIGN_ORDERS',
      'RECORD_INVENTORY_RECEIPT',
      'ADJUST_INVENTORY',
      'ADJUST_COUNCIL_ON_ORDER',
      'ISSUE_STOCK_TO_SCOUT',
      'RETURN_STOCK_FROM_SCOUT',
      'RECORD_CUSTODY_SALE',
      'FULFILL_INDIVIDUAL_ORDER_LINE',
      'REVERSE_INDIVIDUAL_ORDER_FULFILLMENT',
      'GET_SHOW_AND_SELL',
      'LIST_SHOW_AND_SELLS',
      'CREATE_SHOW_AND_SELL',
      'UPDATE_SHOW_AND_SELL',
      'CANCEL_SHOW_AND_SELL',
      'ASSIGN_SHOW_AND_SELL_INVENTORY',
      'LIST_EVENT_INVENTORY_ALLOCATIONS',
      'UPSERT_SHOW_AND_SELL_SLOT',
      'DELETE_SHOW_AND_SELL_SLOT',
      'LIST_SHOW_AND_SELL_SIGNUPS',
      'SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT',
      'CANCEL_SHOW_AND_SELL_SIGNUP',
      'CONFIRM_SHOW_AND_SELL_WORK',
      'LIST_UNIT_CAMPAIGN_OPPORTUNITIES',
      'GET_SHOW_AND_SELL_OPPORTUNITY',
      'LIST_MY_SCOUT_COMMITMENTS',
      'GET_SIGNUP_CALENDAR_DATA',
      'LIST_SCOUT_CAMPAIGN_JOINS',
    ]) {
      expect(names).toContain(required);
    }
  });

  it('attaches every Show & Sell fragment to the request that shows it', () => {
    const attached = new Set(operations.flatMap((entry) => collectFragmentNames(entry.doc)));

    // The defect this guards: a request spreads a fragment shape whose definition
    // it never interpolated, so the API rejects the document before resolvers run.
    for (const fragment of [
      'UnitFields',
      'UnitAccessGrantFields',
      'UnitInviteFields',
      'UnitCampaignFields',
      'UnitCampaignMembershipFields',
      'InventoryPositionFields',
      'InventoryMovementFields',
      'ScoutCustodyBalanceFields',
      'OrderFulfillmentFields',
      'UnitOrderFields',
      'OrderWriteState',
      'ShowAndSellAdminFields',
      'ShowAndSellAllocationFields',
      'ShowAndSellSlotFields',
      'ShowAndSellSignupFields',
      'ShowAndSellWorkPreviewFields',
      'ShowAndSellOpportunityFields',
      'ParticipantSignupFields',
    ]) {
      expect(attached).toContain(fragment);
    }
  });

  it('keeps the fulfillment audit in the one read entitled to it', () => {
    const named = (name: string): DocumentNode => namedDocuments.find((entry) => entry.name === name)?.doc as DocumentNode;

    // §10.2: the actor account and the inventory movement behind a fulfillment are
    // administrative audit. The browser makes exactly one fulfillment history read — the
    // Unit-Admin audit — and the Scout's preview of the same records is that page with both
    // fields removed, so the split lives in one place instead of in a second document that
    // could forget it.
    for (const auditField of ['actorAccountId', 'inventoryMovementId']) {
      expect(selectedFields(named('GET_ORDER_FULFILLMENTS'))).toContain(auditField);
    }

    // No browser document asks the participant projection for anything: an Unit Admin is
    // not authorized to read it, and the screen's preview is built by subtraction.
    const attached = new Set(operations.flatMap((entry) => collectFragmentNames(entry.doc)));
    expect(attached.has('ParticipantOrderFulfillmentFields'), 'no request selects the participant type').toBe(false);

    // The fulfillment writes echo only what the next write conditions on. A write result
    // that spread the full Order shape would carry the customer's contact details into a
    // stock screen that never reads them.
    const writeState = selectedFields(named('REVERSE_INDIVIDUAL_ORDER_FULFILLMENT'));
    for (const needed of ['fulfillmentVersion', 'lineItemId', 'fulfilledQuantity']) {
      expect(writeState).toContain(needed);
    }
    for (const notNeeded of ['customerPhone', 'address', 'notes']) {
      expect(writeState.has(notNeeded), `OrderWriteState.${notNeeded} is not part of fulfilling`).toBe(false);
    }
  });

  it.each(PARTICIPANT_DOCUMENTS)('%s selects no administrative field and spreads no administrative fragment (SEC-04)', (name) => {
    const fields = selectedFields(documentNamed(name));
    const spread = collectFragmentNames(documentNamed(name));
    for (const field of ADMINISTRATOR_ONLY_FIELDS) {
      expect(fields.has(field), `${name} selects ${field}`).toBe(false);
    }
    for (const fragment of ADMINISTRATOR_FRAGMENTS) {
      expect(spread.includes(fragment), `${name} spreads ${fragment}`).toBe(false);
    }
  });

  it('names the actors only in the administrative signup reads', () => {
    // The audit half of §3.4: who placed a place and who confirmed the work is a
    // Unit Admin's record. The participant's own writes answer `ParticipantSignup`,
    // which carries the version they need next and nobody's account id.
    for (const name of ['LIST_SHOW_AND_SELL_SIGNUPS', 'CONFIRM_SHOW_AND_SELL_WORK']) {
      const fields = selectedFields(documentNamed(name));
      expect(fields).toContain('signedUpByAccountId');
      expect(fields).toContain('confirmedByAccountId');
    }
    for (const name of ['SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT', 'CANCEL_SHOW_AND_SELL_SIGNUP']) {
      expect(selectedFields(documentNamed(name))).toContain('signupVersion');
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
