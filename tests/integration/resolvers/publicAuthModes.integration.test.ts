import '../setup.ts';
/**
 * Multi-auth reachability contract for the public order surface.
 *
 * Every expectation here is MEASURED, live on a real ephemeral stack by the
 * KW-PUBLIC-ORDERS-SPIKE-1 experiment - none of it is inferred from AWS docs:
 *
 * 1. Directive exclusivity holds; there is no default-mode fall-through. A
 *    signed-in Cognito caller on a field marked `@aws_api_key` ONLY is refused at
 *    the AUTH layer: `data.<field>` is null and `errors[0]` carries
 *    `errorType: "Unauthorized"` with "Not Authorized to access <field> on type
 *    Query". That is not a resolver-level NOT_FOUND and not a plain null.
 * 2. Fields and types with NO directive are reachable only through the DEFAULT
 *    (Cognito) mode - verified against real production fields (`getOrder`,
 *    `getMyAccount`), not probes. That is the load-bearing rule that keeps the
 *    public API key out of every existing field, so it is pinned as a hard rule.
 * 3. Marking the ROOT FIELD is not sufficient: a marked root that returns an
 *    unmarked object type resolves the root but DENIES its sub-fields. The static
 *    closure guard (`tests/unit/check_public_api_key_surface.test.ts`) pins the
 *    directive on every public type; here the public fields still have no
 *    resolver (later slice), so the API-key side asserts only that the caller
 *    passes the auth gate.
 *
 * The input-type no-directive assumption stays unverified and is asserted
 * nowhere here.
 *
 * These assertions double as the post-apply check the schema needs: an auth-layer
 * "Not Authorized to access publicGetOrderOffer" error can only be produced if the
 * root type really carries the field (a dropped `extend type Query` field would
 * fail as an unknown-field validation error instead).
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { signInUser } from '../setup/cognitoAuth';

const ENDPOINT = process.env.TEST_APPSYNC_ENDPOINT!;

type GraphQLBody = {
  data?: Record<string, unknown> | null;
  errors?: { errorType?: string; message?: string; path?: string[] }[];
};

async function gql(
  query: string,
  headers: Record<string, string>,
): Promise<{ status: number; body: GraphQLBody }> {
  const response = await fetch(ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ query }),
  });
  return { status: response.status, body: (await response.json()) as GraphQLBody };
}

describe('public order auth modes (measured multi-auth reachability)', () => {
  let cognitoHeaders: Record<string, string>;
  let apiKeyHeaders: Record<string, string>;

  beforeAll(async () => {
    const apiKey = process.env.TEST_APPSYNC_API_KEY;
    if (!apiKey) {
      throw new Error(
        'TEST_APPSYNC_API_KEY is unset: the ephemeral stack output or the ephemeral-env.sh export is missing',
      );
    }
    apiKeyHeaders = { 'x-api-key': apiKey };

    const auth = await signInUser(
      process.env.TEST_OWNER_EMAIL!,
      process.env.TEST_OWNER_PASSWORD!,
      process.env.TEST_OWNER_TOTP_SECRET,
    );
    // AppSync Cognito auth expects the raw ID token, not a Bearer prefix.
    cognitoHeaders = { Authorization: auth.tokens.idToken };
  });

  it('refuses a Cognito caller on an @aws_api_key-only field at the auth layer', async () => {
    const { body } = await gql(
      '{ publicGetOrderOffer(profileId: "PROFILE#none", token: "none") { sellerName } }',
      cognitoHeaders,
    );

    expect(body.errors, 'expected an auth-layer error').toBeTruthy();
    expect(body.errors![0].errorType).toBe('Unauthorized');
    // Measured verbatim for this direction.
    expect(body.errors![0].message).toBe(
      'Not Authorized to access publicGetOrderOffer on type Query',
    );
    expect(body.data?.publicGetOrderOffer ?? null).toBeNull();
  });

  it('refuses a Cognito caller on the public mutation at the auth layer', async () => {
    const { body } = await gql(
      'mutation { publicCreateOrder(input: { profileId: "PROFILE#none", token: "none", campaignId: "CAMPAIGN#none", acknowledgementsAccepted: true, firstName: "A", lastName: "B", paymentMethod: "Cash", lineItems: [] }) { orderId } }',
      cognitoHeaders,
    );

    expect(body.errors![0].errorType).toBe('Unauthorized');
    expect(body.errors![0].message).toContain('publicCreateOrder');
  });

  it('denies an API-key caller on an unmarked field (the load-bearing converse rule)', async () => {
    const { body } = await gql('{ getMyAccount { accountId } }', apiKeyHeaders);

    // The denial shape AppSync emits for the API-key direction is asserted loosely
    // (an error of the auth-layer type and no value): the spike confirmed the
    // denial on real production fields, and only quoted the exact message for the
    // Cognito direction above.
    expect(body.errors, 'an API-key caller must not reach an unmarked field').toBeTruthy();
    expect(body.errors![0].errorType).toBe('Unauthorized');
    expect(body.data?.getMyAccount ?? null).toBeNull();
  });

  it('denies an API-key caller on a Cognito-only field', async () => {
    const { body } = await gql('{ listManagedCatalogs { catalogId } }', apiKeyHeaders);

    expect(body.errors, 'an API-key caller must not reach a Cognito-only field').toBeTruthy();
    expect(body.errors![0].errorType).toBe('Unauthorized');
    expect(body.data?.listManagedCatalogs ?? null).toBeNull();
  });

  it('admits the Cognito caller to the unmarked field (control for the rule above)', async () => {
    const { body } = await gql('{ getMyAccount { accountId } }', cognitoHeaders);

    expect(body.errors).toBeUndefined();
    expect((body.data?.getMyAccount as { accountId?: string } | null)?.accountId).toBeTruthy();
  });

  it('admits an API-key caller past the auth gate on the public fields', async () => {
    // The public resolvers land in a later slice, so the field may still resolve
    // to null or report a resolver-level error. What must NOT happen here is an
    // auth-layer refusal: the API-key mode is admitted to @aws_api_key fields.
    const { body } = await gql(
      '{ publicGetOrderOffer(profileId: "PROFILE#none", token: "none") { sellerName } }',
      apiKeyHeaders,
    );

    const authErrors = (body.errors ?? []).filter((e) => e.errorType === 'Unauthorized');
    expect(authErrors, 'the API-key caller was refused by the auth layer').toEqual([]);
  });
});
