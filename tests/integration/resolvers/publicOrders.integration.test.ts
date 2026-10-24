import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import {
  DynamoDBClient,
  GetItemCommand,
  UpdateItemCommand,
} from '@aws-sdk/client-dynamodb';
import {
  createAuthenticatedClient,
  createApiKeyClient,
  createUnauthenticatedClient,
} from '../setup/apolloClient';
import {
  TABLE_NAMES,
  deleteCatalogWithRetry,
  deleteCampaign,
  waitForGSIConsistency,
} from '../setup/testData';

/**
 * Integration tests for the public order surface (spec section 10.3).
 *
 * Test data setup:
 * - TEST_OWNER_EMAIL owns a dedicated profile, catalog and three campaigns.
 *   Three campaigns because the cap tests must each start from a known
 *   `publicOrderCount`, and the soft-deleted-catalog negative must not poison
 *   the campaign every other test reads.
 * - TEST_CONTRIBUTOR_EMAIL holds a WRITE share on the profile (the settings
 *   owner gate's interesting negative: it passes the write-access pair and is
 *   refused by the owner gate).
 * - TEST_READONLY_EMAIL is deliberately NOT shared: it is the stranger whose
 *   settings read must be FORBIDDEN. (The READ-share case takes the same pair
 *   branch as the stranger and is pinned in
 *   `verify_public_settings_owner_fn.test.js`.)
 *
 * Harness notes:
 * - The public fields carry `@aws_api_key` only, so they are reached with
 *   `createApiKeyClient()` (x-api-key, never an Authorization header) and the
 *   Cognito client must be REFUSED on them (directive exclusivity, measured in
 *   the KW-PUBLIC-ORDERS-SPIKE-1 spike, §10.3).
 * - The order cap is seeded with a raw `UpdateItem ADD` on the campaign item.
 *   Creating 499 orders through the nine-step pipeline is impractical and would
 *   itself trip AppSync's API-key throttle bucket.
 * - The offer and create pipelines locate the campaign through the
 *   eventually-consistent `campaignId-index` GSI, so every read after a create
 *   goes through `waitForGSIConsistency`.
 */

const dynamoClient = new DynamoDBClient({ region: process.env.TEST_REGION || 'us-east-1' });

// ---------------------------------------------------------------------------
// Setup documents
// ---------------------------------------------------------------------------

const CREATE_SELLER_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
    }
  }
`;

const CREATE_CATALOG = gql`
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      catalogId
      products {
        productId
        productName
        price
      }
    }
  }
`;

const CREATE_CAMPAIGN = gql`
  mutation CreateCampaign($input: CreateCampaignInput!) {
    createCampaign(input: $input) {
      campaignId
      campaignName
      catalogId
      isActive
    }
  }
`;

const GET_CAMPAIGN = gql`
  query GetCampaign($campaignId: ID!) {
    getCampaign(campaignId: $campaignId) {
      campaignId
      catalogId
      isActive
    }
  }
`;

const UPDATE_CAMPAIGN = gql`
  mutation UpdateCampaign($input: UpdateCampaignInput!) {
    updateCampaign(input: $input) {
      campaignId
      isActive
    }
  }
`;

const SHARE_PROFILE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      profileId
      targetAccountId
      permissions
    }
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const DELETE_ORDER = gql`
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

const LIST_ORDERS_BY_CAMPAIGN = gql`
  query ListOrdersByCampaign($campaignId: ID!) {
    listOrdersByCampaign(campaignId: $campaignId) {
      orders {
        orderId
        customerName
        status
      }
    }
  }
`;

const CREATE_ORDER = gql`
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      orderId
      status
      totalAmount
    }
  }
`;

const UPDATE_ORDER = gql`
  mutation UpdateOrder($input: UpdateOrderInput!) {
    updateOrder(input: $input) {
      orderId
      status
    }
  }
`;

const CREATE_PAYMENT_METHOD = gql`
  mutation CreatePaymentMethod($name: String!) {
    createPaymentMethod(name: $name) {
      name
    }
  }
`;

const DELETE_PAYMENT_METHOD = gql`
  mutation DeletePaymentMethod($name: String!) {
    deletePaymentMethod(name: $name)
  }
`;

const REQUEST_QR_UPLOAD = gql`
  mutation RequestPaymentMethodQRCodeUpload($paymentMethodName: String!) {
    requestPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName) {
      uploadUrl
      s3Key
      fields
    }
  }
`;

const CONFIRM_QR_UPLOAD = gql`
  mutation ConfirmPaymentMethodQRCodeUpload($paymentMethodName: String!, $s3Key: String!) {
    confirmPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName, s3Key: $s3Key) {
      name
      qrCodeUrl
    }
  }
`;

// ---------------------------------------------------------------------------
// Public-orders documents (owner side: Cognito; buyer side: API key)
// ---------------------------------------------------------------------------

const GET_PUBLIC_SETTINGS = gql`
  query GetCampaignPublicOrderSettings($campaignId: ID!) {
    getCampaignPublicOrderSettings(campaignId: $campaignId) {
      enabled
      campaignId
      campaignName
      campaignState
      allowedPaymentMethods
      shareToken
      publicOrderCount
      acknowledgedAt
      ackVersion
    }
  }
`;

const UPDATE_PUBLIC_SETTINGS = gql`
  mutation UpdateCampaignPublicOrderSettings($input: UpdateCampaignPublicOrderSettingsInput!) {
    updateCampaignPublicOrderSettings(input: $input) {
      enabled
      campaignId
      campaignState
      allowedPaymentMethods
      shareToken
      publicOrderCount
      acknowledgedAt
      ackVersion
    }
  }
`;

const PUBLIC_OFFER = gql`
  query PublicGetOrderOffer($campaignId: ID!, $token: String!) {
    publicGetOrderOffer(campaignId: $campaignId, token: $token) {
      sellerName
      campaignId
      campaignName
      products {
        productId
        productName
        price
        sortOrder
      }
      paymentMethods {
        name
        qrCodeUrl
      }
    }
  }
`;

const PUBLIC_CREATE_ORDER = gql`
  mutation PublicCreateOrder($input: PublicCreateOrderInput!) {
    publicCreateOrder(input: $input) {
      orderId
      receiptUrl
      totalAmount
      buyerEmailProvided
      confirmationEmailSent
    }
  }
`;

const PUBLIC_GET_RECEIPT = gql`
  query PublicGetOrderReceipt($campaignId: ID!, $orderSuffix: String!, $receiptToken: String!) {
    publicGetOrderReceipt(campaignId: $campaignId, orderSuffix: $orderSuffix, receiptToken: $receiptToken) {
      sellerName
      orderId
      orderDate
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      totalAmount
      paymentMethodName
      status
      buyerFirstName
      buyerLastName
    }
  }
`;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Mirrors PUBLIC_ORDER_CAP in `js-resolvers/lib/public_order.js`. */
const PUBLIC_ORDER_CAP = 500;

/** One message for every NOT_FOUND branch of the create path (lib/public_order.js). */
const PUBLIC_ORDER_UNAVAILABLE = 'Order could not be placed';

/** One message for both payment-method rejections (the no-oracle contract). */
const PUBLIC_METHOD_UNAVAILABLE = 'Payment method is not available for this seller';

/** The offer read's single NOT_FOUND message (`src/handlers/public_orders_offer.py`). */
const OFFER_UNAVAILABLE = /not available|could not be placed|not found/i;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Read the AppSync error code off a thrown Apollo error.
 *
 * Apollo Client 4 surfaces a failed operation as `CombinedGraphQLErrors`, whose
 * GraphQL errors live on `error.errors` (NOT the `graphQLErrors` field the 3.x
 * `ApolloError` used). Each entry carries AppSync's own fields: `errorType` for
 * `util.error(message, type)` and for the auth layer's `Unauthorized`, and
 * `errorInfo.errorCode` for the structured code the Lambda passthrough path
 * emits. `extensions.errorCode` / `extensions.code` are read as well, mirroring
 * `getErrorCode` in `frontend/src/lib/api-utils.ts`, and the 3.x shape is kept
 * as a fallback so the helper does not silently return `undefined` if the
 * harness's Apollo version changes.
 */
interface AppSyncGraphQLError {
  message?: string;
  errorType?: string;
  errorInfo?: { errorCode?: string } | null;
  extensions?: Record<string, unknown>;
}

function graphQLErrorsOf(error: unknown): AppSyncGraphQLError[] {
  const wrapped = error as { errors?: AppSyncGraphQLError[]; graphQLErrors?: AppSyncGraphQLError[] };
  return wrapped.errors ?? wrapped.graphQLErrors ?? [];
}

function errorCodeOf(error: unknown): string | undefined {
  const first = graphQLErrorsOf(error)[0];
  if (!first) {
    return undefined;
  }
  const structured = first.errorInfo?.errorCode;
  if (typeof structured === 'string') {
    return structured;
  }
  if (typeof first.errorType === 'string') {
    return first.errorType;
  }
  for (const key of ['errorCode', 'code', 'errorType']) {
    const value = first.extensions?.[key];
    if (typeof value === 'string') {
      return value;
    }
  }
  return undefined;
}

/** The first GraphQL error's message, or the thrown error's own message. */
function errorMessageOf(error: unknown): string {
  return graphQLErrorsOf(error)[0]?.message ?? String(error);
}

/**
 * Assert a mutation/query failed with the expected AppSync error code.
 *
 * The three keys read by `errorCodeOf` mirror `getErrorCode` in
 * `frontend/src/lib/api-utils.ts`. `messagePattern` is asserted too where the
 * resolver emits a fixed string: the message is what the buyer's page renders,
 * so pinning it is not redundant with pinning the code. Where AppSync refuses
 * outside the GraphQL error envelope there is no code to read, and the message
 * pattern becomes the pin.
 */
async function expectGraphQLError(
  operation: () => Promise<unknown>,
  expectedCode: string,
  messagePattern?: RegExp
): Promise<void> {
  let caught: unknown;
  try {
    await operation();
  } catch (error) {
    caught = error;
  }
  expect(caught, `${expectedCode} was expected but the call succeeded`).toBeDefined();
  const code = errorCodeOf(caught);
  if (code === undefined) {
    expect(
      errorMessageOf(caught),
      `no AppSync error code was returned; expected ${expectedCode}`
    ).toMatch(messagePattern ?? new RegExp(expectedCode, 'i'));
    return;
  }
  expect(code, `unexpected error code: ${errorMessageOf(caught)}`).toBe(expectedCode);
  if (messagePattern) {
    expect(errorMessageOf(caught)).toMatch(messagePattern);
  }
}

/**
 * Assert AppSync refused a request outright at the HTTP layer.
 *
 * With neither a Cognito token nor an API key there is no GraphQL error
 * envelope to read a code from, so only the transport-level refusal is
 * assertable — which is still the contract: the public fields are not open.
 */
async function expectDeniedAtTheHttpLayer(operation: () => Promise<unknown>): Promise<void> {
  let caught: unknown;
  try {
    await operation();
  } catch (error) {
    caught = error;
  }
  expect(caught, 'an unauthenticated call must not resolve').toBeDefined();
  expect(errorMessageOf(caught)).toMatch(/unauthorized|not authorized|missing credentials|401/i);
}

/** Strip the `CAMPAIGN#`/`PROFILE#` prefix the DB keys carry (the `toUrlId` form). */
function bareId(id: string): string {
  return id.split('#', 2)[1] ?? id;
}

/**
 * Seed a campaign's `publicOrderCount` with a raw `UpdateItem ADD`.
 *
 * ADD rather than SET: it is the same mechanism the pipeline's cap gate uses,
 * and it cannot clobber a counter the pipeline moved between the read and the
 * write. Creating 499 orders through the pipeline is not an option (spec 10.3).
 */
async function seedPublicOrderCount(
  profileId: string,
  campaignId: string,
  target: number
): Promise<void> {
  const current = await dynamoClient.send(
    new GetItemCommand({
      TableName: TABLE_NAMES.campaigns,
      Key: { profileId: { S: profileId }, campaignId: { S: campaignId } },
      ConsistentRead: true,
      AttributesToGet: ['publicOrderCount'],
    })
  );
  const stored = Number(current.Item?.publicOrderCount?.N ?? 0);
  await dynamoClient.send(
    new UpdateItemCommand({
      TableName: TABLE_NAMES.campaigns,
      Key: { profileId: { S: profileId }, campaignId: { S: campaignId } },
      UpdateExpression: 'ADD publicOrderCount :delta',
      ExpressionAttributeValues: { ':delta': { N: String(target - stored) } },
    })
  );
}

/** Strongly consistent read of the campaign's stored counter. */
async function readPublicOrderCount(profileId: string, campaignId: string): Promise<number> {
  const item = await dynamoClient.send(
    new GetItemCommand({
      TableName: TABLE_NAMES.campaigns,
      Key: { profileId: { S: profileId }, campaignId: { S: campaignId } },
      ConsistentRead: true,
      AttributesToGet: ['publicOrderCount'],
    })
  );
  return Number(item.Item?.publicOrderCount?.N ?? 0);
}

/** Strongly consistent read of a stored order row (raw DynamoDB, not GraphQL). */
async function readOrderRow(campaignId: string, orderId: string): Promise<Record<string, unknown>> {
  const item = await dynamoClient.send(
    new GetItemCommand({
      TableName: TABLE_NAMES.orders,
      Key: { campaignId: { S: campaignId }, orderId: { S: orderId } },
      ConsistentRead: true,
    })
  );
  return item.Item ?? {};
}

/** A minimal valid 1x1 PNG, uploaded through the presigned POST like the payment-methods suite. */
const ONE_PIXEL_PNG = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
  0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4,
  0x89, 0x00, 0x00, 0x00, 0x0a, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9c, 0x63, 0x00, 0x01, 0x00, 0x00,
  0x05, 0x00, 0x01, 0x0d, 0x0a, 0x2d, 0xb4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae,
  0x42, 0x60, 0x82,
]);

/** Give a payment method a real QR object so the offer presigns a GET URL for it. */
async function uploadQrCode(client: ApolloClient<NormalizedCacheObject>, methodName: string): Promise<void> {
  const { data: uploadData } = await client.mutate({
    mutation: REQUEST_QR_UPLOAD,
    variables: { paymentMethodName: methodName },
  });
  const upload = uploadData.requestPaymentMethodQRCodeUpload;

  const form = new FormData();
  for (const [key, value] of Object.entries(JSON.parse(upload.fields) as Record<string, string>)) {
    form.append(key, value);
  }
  form.append('file', new Blob([ONE_PIXEL_PNG], { type: 'image/png' }), 'qr.png');

  const uploaded = await fetch(upload.uploadUrl, { method: 'POST', body: form });
  expect(uploaded.ok || uploaded.status === 204, 'the presigned POST must accept the QR object').toBe(true);

  await client.mutate({
    mutation: CONFIRM_QR_UPLOAD,
    variables: { paymentMethodName: methodName, s3Key: upload.s3Key },
  });
}

/** Wait until the campaignId-index GSI projects a campaign (the locator step reads it). */
async function waitForCampaignInGSI(
  client: ApolloClient<NormalizedCacheObject>,
  campaignId: string
): Promise<void> {
  await waitForGSIConsistency(
    async () => {
      const res = await client.query({
        query: GET_CAMPAIGN,
        variables: { campaignId },
        fetchPolicy: 'network-only',
      });
      return res.data?.getCampaign ? [res.data.getCampaign] : [];
    },
    (items) => items.length > 0,
    30,
    1000
  );
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

describe('Public Orders Integration Tests', () => {
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let strangerClient: ApolloClient<NormalizedCacheObject>;
  let apiKeyClient: ApolloClient<NormalizedCacheObject>;
  let anonymousClient: ApolloClient<NormalizedCacheObject>;

  let profileId: string;
  let profileName: string;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let catalogId: string;
  let productId: string;
  let productName: string;
  let productPrice: number;
  let qrMethod: string;
  let plainMethod: string;

  /** Main campaign: settings, offer, create, receipt, status, counter lifecycle. */
  let campaignId: string;
  let shareToken: string;
  /** Cap-boundary campaign: seeded to 499, then one order in, then over the cap. */
  let capCampaignId: string;
  let capShareToken: string;
  /** Concurrency campaign: seeded to 499, then a simultaneous pair. */
  let raceCampaignId: string;
  let raceShareToken: string;
  /** Soft-deleted-catalog campaign: its own catalog so the delete cannot poison the others. */
  let deadCatalogCampaignId: string;
  let deadCatalogId: string;

  /** The order created by the happy-path create test, reused by receipt/status/cleanup. */
  let publicOrderId: string;
  let publicReceiptToken: string;

  beforeAll(async () => {
    const ownerAuth = await createAuthenticatedClient('owner');
    const contributorAuth = await createAuthenticatedClient('contributor');
    const strangerAuth = await createAuthenticatedClient('readonly');
    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    strangerClient = strangerAuth.client;
    ownerAccountId = ownerAuth.accountId;
    apiKeyClient = createApiKeyClient();
    anonymousClient = createUnauthenticatedClient();

    for (const client of [ownerClient, contributorClient, strangerClient]) {
      await client.cache.reset();
    }

    const suffix = `${Date.now()}`;
    profileName = `PO Integration Seller ${suffix}`;
    qrMethod = `PO-QR-${suffix}`;
    plainMethod = `PO-Plain-${suffix}`;

    const profileData = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: { input: { sellerName: profileName } },
    });
    profileId = profileData.data.createSellerProfile.profileId;

    const catalogData = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: `PO Integration Catalog ${suffix}`,
          isPublic: false,
          products: [
            {
              productName: `PO Product ${suffix}`,
              description: 'Integration product for the public order surface',
              price: 12.5,
              sortOrder: 1,
            },
          ],
        },
      },
    });
    catalogId = catalogData.data.createCatalog.catalogId;
    productId = catalogData.data.createCatalog.products[0].productId;
    productName = catalogData.data.createCatalog.products[0].productName;
    productPrice = Number(catalogData.data.createCatalog.products[0].price);

    // A second catalog, soft-deleted by the offer negative that needs it.
    const deadCatalogData = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: `PO Deleted Catalog ${suffix}`,
          isPublic: false,
          products: [{ productName: `PO Dead ${suffix}`, price: 1, sortOrder: 1 }],
        },
      },
    });
    deadCatalogId = deadCatalogData.data.createCatalog.catalogId;

    for (const [name, target] of [
      ['main', catalogId],
      ['cap', catalogId],
      ['race', catalogId],
      ['dead', deadCatalogId],
    ] as const) {
      const created = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId,
            campaignName: `PO ${name} ${suffix}`,
            campaignYear: 2026,
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId: target,
          },
        },
      });
      const id = created.data.createCampaign.campaignId;
      if (name === 'main') campaignId = id;
      if (name === 'cap') capCampaignId = id;
      if (name === 'race') raceCampaignId = id;
      if (name === 'dead') deadCatalogCampaignId = id;
    }

    // The offer and settings pipelines locate the campaign through the
    // eventually-consistent campaignId-index GSI.
    for (const id of [campaignId, capCampaignId, raceCampaignId, deadCatalogCampaignId]) {
      await waitForCampaignInGSI(ownerClient, id);
    }

    // WRITE share for the contributor; the readonly user stays unshared.
    const shared = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: { profileId, targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!, permissions: ['READ', 'WRITE'] },
      },
    });
    contributorAccountId = shared.data.shareProfileDirect.targetAccountId;

    // Payment methods are account-level, so the allowlist has something real to
    // intersect. The QR method carries a real object so the offer presigns.
    for (const name of [qrMethod, plainMethod]) {
      await ownerClient.mutate({ mutation: CREATE_PAYMENT_METHOD, variables: { name } });
    }
    await uploadQrCode(ownerClient, qrMethod);

    // Enable public orders on the three campaigns that need a live token.
    for (const id of [campaignId, capCampaignId, raceCampaignId]) {
      const enabled = await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: {
          input: {
            campaignId: id,
            enabled: true,
            allowedPaymentMethods: [qrMethod, plainMethod],
            acknowledgementsAccepted: true,
          },
        },
      });
      const token = enabled.data.updateCampaignPublicOrderSettings.shareToken;
      expect(token, 'enabling must mint a share token').toBeTruthy();
      if (id === campaignId) shareToken = token;
      if (id === capCampaignId) capShareToken = token;
      if (id === raceCampaignId) raceShareToken = token;
    }

    // The dead-catalog campaign is enabled too: the offer must fail on the
    // catalog, not on the settings.
    await ownerClient.mutate({
      mutation: UPDATE_PUBLIC_SETTINGS,
      variables: {
        input: {
          campaignId: deadCatalogCampaignId,
          enabled: true,
          allowedPaymentMethods: [qrMethod],
          acknowledgementsAccepted: true,
        },
      },
    });
  }, 240000);

  afterAll(async () => {
    for (const id of [campaignId, capCampaignId, raceCampaignId, deadCatalogCampaignId]) {
      if (!id) continue;
      try {
        const orders = await ownerClient.query({
          query: LIST_ORDERS_BY_CAMPAIGN,
          variables: { campaignId: id },
          fetchPolicy: 'network-only',
        });
        for (const order of orders.data?.listOrdersByCampaign?.orders ?? []) {
          await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: order.orderId } });
        }
      } catch (error) {
        console.warn('order cleanup failed', error);
      }
      try {
        await deleteCampaign(ownerClient, id);
      } catch (error) {
        console.warn('campaign cleanup failed', error);
      }
    }

    for (const id of [catalogId, deadCatalogId]) {
      if (!id) continue;
      try {
        await deleteCatalogWithRetry(ownerClient, id);
      } catch (error) {
        console.warn('catalog cleanup failed', error);
      }
    }

    for (const name of [qrMethod, plainMethod]) {
      try {
        await ownerClient.mutate({ mutation: DELETE_PAYMENT_METHOD, variables: { name } });
      } catch (error) {
        console.warn('payment method cleanup failed', error);
      }
    }

    try {
      await ownerClient.mutate({ mutation: REVOKE_SHARE, variables: { input: { profileId, targetAccountId: contributorAccountId } } });
    } catch (error) {
      console.warn('share revoke failed', error);
    }
    try {
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    } catch (error) {
      console.warn('profile cleanup failed', error);
    }
  }, 240000);

  // -------------------------------------------------------------------------
  // Settings (Cognito auth)
  // -------------------------------------------------------------------------

  describe('getCampaignPublicOrderSettings / updateCampaignPublicOrderSettings', () => {
    test('owner enable returns the token, count and campaign state', async () => {
      const { data } = await ownerClient.query({
        query: GET_PUBLIC_SETTINGS,
        variables: { campaignId },
        fetchPolicy: 'network-only',
      });
      const settings = data.getCampaignPublicOrderSettings;
      expect(settings.enabled).toBe(true);
      expect(settings.campaignId).toBe(campaignId);
      expect(settings.shareToken).toBe(shareToken);
      expect(settings.allowedPaymentMethods).toEqual(expect.arrayContaining([qrMethod, plainMethod]));
      expect(settings.publicOrderCount).toBe(0);
      expect(settings.campaignState).toBe('OK');
      expect(settings.ackVersion).toBe(1);
      expect(settings.acknowledgedAt).toBeTruthy();
    });

    test('a campaign that never enabled reads back disabled with no token', async () => {
      // deadCatalogCampaignId is enabled, so use a campaign created without any
      // public-orders write: the settings read must answer, not error.
      const created = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId,
            campaignName: `PO never ${Date.now()}`,
            campaignYear: 2026,
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId,
          },
        },
      });
      const neverId = created.data.createCampaign.campaignId;
      await waitForCampaignInGSI(ownerClient, neverId);

      const { data } = await ownerClient.query({
        query: GET_PUBLIC_SETTINGS,
        variables: { campaignId: neverId },
        fetchPolicy: 'network-only',
      });
      expect(data.getCampaignPublicOrderSettings.enabled).toBe(false);
      expect(data.getCampaignPublicOrderSettings.shareToken).toBeNull();
      expect(data.getCampaignPublicOrderSettings.allowedPaymentMethods).toEqual([]);

      await deleteCampaign(ownerClient, neverId);
    });

    test('rotating the token replaces it and keeps the URL otherwise stable', async () => {
      const { data } = await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: { input: { campaignId, enabled: true, rotateToken: true } },
      });
      const rotated = data.updateCampaignPublicOrderSettings.shareToken;
      expect(rotated).toBeTruthy();
      expect(rotated).not.toBe(shareToken);

      const reread = await ownerClient.query({
        query: GET_PUBLIC_SETTINGS,
        variables: { campaignId },
        fetchPolicy: 'network-only',
      });
      expect(reread.data.getCampaignPublicOrderSettings.shareToken).toBe(rotated);
      shareToken = rotated;
    });

    test('disabling keeps the token so re-enable keeps the same URL', async () => {
      const disabled = await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: { input: { campaignId, enabled: false } },
      });
      const keptToken = disabled.data.updateCampaignPublicOrderSettings.shareToken;
      expect(keptToken).toBe(shareToken);
      expect(disabled.data.updateCampaignPublicOrderSettings.enabled).toBe(false);

      const reEnabled = await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: { input: { campaignId, enabled: true } },
      });
      expect(reEnabled.data.updateCampaignPublicOrderSettings.enabled).toBe(true);
      expect(reEnabled.data.updateCampaignPublicOrderSettings.shareToken).toBe(shareToken);
    });

    test('an empty method list cannot enable public orders', async () => {
      await expectGraphQLError(
        () =>
          ownerClient.mutate({
            mutation: UPDATE_PUBLIC_SETTINGS,
            variables: { input: { campaignId, enabled: true, allowedPaymentMethods: [] } },
          }),
        'INVALID_INPUT',
        /at least one payment method/i
      );
    });

    test('enabling with an unaccepted acknowledgement is rejected while the ack is behind', async () => {
      // Park the campaign, then clear the stored ack by writing a fresh
      // campaign: a brand-new campaign has no ackVersion, so the enable must
      // demand acknowledgementsAccepted.
      const created = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId,
            campaignName: `PO ack gate ${Date.now()}`,
            campaignYear: 2026,
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId,
          },
        },
      });
      const freshId = created.data.createCampaign.campaignId;
      await waitForCampaignInGSI(ownerClient, freshId);
      try {
        await expectGraphQLError(
          () =>
            ownerClient.mutate({
              mutation: UPDATE_PUBLIC_SETTINGS,
              variables: { input: { campaignId: freshId, enabled: true, allowedPaymentMethods: [qrMethod] } },
            }),
          'INVALID_INPUT',
          /acknowledgements must be accepted/i
        );
      } finally {
        await deleteCampaign(ownerClient, freshId);
      }
    });

    test('a WRITE-share collaborator cannot read or change the settings', async () => {
      await expectGraphQLError(
        () => contributorClient.query({ query: GET_PUBLIC_SETTINGS, variables: { campaignId } }),
        'FORBIDDEN',
        /profile owner/i
      );
      await expectGraphQLError(
        () =>
          contributorClient.mutate({
            mutation: UPDATE_PUBLIC_SETTINGS,
            variables: { input: { campaignId, enabled: false } },
          }),
        'FORBIDDEN',
        /profile owner/i
      );
    });

    test('an unshared stranger is FORBIDDEN, not NOT_FOUND (no existence oracle)', async () => {
      await expectGraphQLError(
        () => strangerClient.query({ query: GET_PUBLIC_SETTINGS, variables: { campaignId } }),
        'FORBIDDEN',
        /profile owner/i
      );
    });

    test('a deactivated campaign reports campaignState INACTIVE', async () => {
      const created = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId,
            campaignName: `PO inactive ${Date.now()}`,
            campaignYear: 2026,
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId,
          },
        },
      });
      const inactiveId = created.data.createCampaign.campaignId;
      await waitForCampaignInGSI(ownerClient, inactiveId);
      try {
        await ownerClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: { input: { campaignId: inactiveId, isActive: false } },
        });
        const { data } = await ownerClient.query({
          query: GET_PUBLIC_SETTINGS,
          variables: { campaignId: inactiveId },
          fetchPolicy: 'network-only',
        });
        expect(data.getCampaignPublicOrderSettings.campaignState).toBe('INACTIVE');
      } finally {
        await deleteCampaign(ownerClient, inactiveId);
      }
    });

    test('a campaign update never clobbers publicOrderCount', async () => {
      await seedPublicOrderCount(profileId, campaignId, 3);
      await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: { input: { campaignId, campaignName: `PO renamed ${Date.now()}` } },
      });
      expect(await readPublicOrderCount(profileId, campaignId)).toBe(3);
      await seedPublicOrderCount(profileId, campaignId, 0);
    });
  });

  // -------------------------------------------------------------------------
  // Offer (API key + token)
  // -------------------------------------------------------------------------

  describe('publicGetOrderOffer', () => {
    test('an enabled campaign returns its products and exactly the allowlisted methods', async () => {
      const { data } = await apiKeyClient.query({
        query: PUBLIC_OFFER,
        variables: { campaignId: bareId(campaignId), token: shareToken },
        fetchPolicy: 'network-only',
      });
      const offer = data.publicGetOrderOffer;
      expect(offer.sellerName).toBe(profileName);
      expect(offer.campaignId).toBe(bareId(campaignId));
      expect(offer.products.map((p: { productId: string }) => p.productId)).toContain(productId);
      const names = offer.paymentMethods.map((m: { name: string }) => m.name);
      expect(names).toEqual(expect.arrayContaining([qrMethod, plainMethod]));
    });

    test('the QR method carries a pre-signed URL that actually fetches', async () => {
      const { data } = await apiKeyClient.query({
        query: PUBLIC_OFFER,
        variables: { campaignId: bareId(campaignId), token: shareToken },
        fetchPolicy: 'network-only',
      });
      const withQr = data.publicGetOrderOffer.paymentMethods.find(
        (m: { name: string }) => m.name === qrMethod
      );
      expect(withQr?.qrCodeUrl, 'the QR method must carry a pre-signed GET URL').toBeTruthy();
      const fetched = await fetch(withQr.qrCodeUrl);
      expect(fetched.ok, 'the pre-signed QR URL must serve the object').toBe(true);
    });

    test('a method the seller never allowlisted never reaches the offer', async () => {
      const removed = await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: { input: { campaignId, enabled: true, allowedPaymentMethods: [qrMethod] } },
      });
      expect(removed.data.updateCampaignPublicOrderSettings.allowedPaymentMethods).toEqual([qrMethod]);
      try {
        const { data } = await apiKeyClient.query({
          query: PUBLIC_OFFER,
          variables: { campaignId: bareId(campaignId), token: shareToken },
          fetchPolicy: 'network-only',
        });
        const names = data.publicGetOrderOffer.paymentMethods.map((m: { name: string }) => m.name);
        expect(names).toContain(qrMethod);
        expect(names).not.toContain(plainMethod);
      } finally {
        await ownerClient.mutate({
          mutation: UPDATE_PUBLIC_SETTINGS,
          variables: { input: { campaignId, enabled: true, allowedPaymentMethods: [qrMethod, plainMethod] } },
        });
      }
    });

    test('a wrong token, a never-enabled campaign and a disabled campaign are the same NOT_FOUND', async () => {
      await expectGraphQLError(
        () => apiKeyClient.query({
          query: PUBLIC_OFFER,
          variables: { campaignId: bareId(campaignId), token: 'deadbeefdeadbeefdeadbeefdeadbeef' },
        }),
        'NOT_FOUND',
        OFFER_UNAVAILABLE
      );

      const created = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId,
            campaignName: `PO never offer ${Date.now()}`,
            campaignYear: 2026,
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId,
          },
        },
      });
      const neverId = created.data.createCampaign.campaignId;
      await waitForCampaignInGSI(ownerClient, neverId);
      try {
        // A campaign that never enabled the feature answers identically to a bad
        // token, so probing cannot tell the two apart.
        await expectGraphQLError(
          () => apiKeyClient.query({ query: PUBLIC_OFFER, variables: { campaignId: bareId(neverId), token: shareToken } }),
          'NOT_FOUND',
          OFFER_UNAVAILABLE
        );
      } finally {
        await deleteCampaign(ownerClient, neverId);
      }

      const disabled = await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: { input: { campaignId: capCampaignId, enabled: false } },
      });
      const disabledToken = disabled.data.updateCampaignPublicOrderSettings.shareToken;
      try {
        await expectGraphQLError(
          () => apiKeyClient.query({ query: PUBLIC_OFFER, variables: { campaignId: bareId(capCampaignId), token: disabledToken } }),
          'NOT_FOUND',
          OFFER_UNAVAILABLE
        );
      } finally {
        await ownerClient.mutate({
          mutation: UPDATE_PUBLIC_SETTINGS,
          variables: { input: { campaignId: capCampaignId, enabled: true } },
        });
      }
    });

    test('a soft-deleted catalog makes the offer NOT_FOUND', async () => {
      // Soft-delete the catalog with a raw UpdateItem rather than through
      // deleteCatalog: that mutation refuses a catalog still referenced by a
      // campaign, and the campaign must stay in place for the offer to reach
      // the catalog guard at all. afterAll deletes the campaign first, then the
      // catalog through the API.
      await dynamoClient.send(
        new UpdateItemCommand({
          TableName: TABLE_NAMES.catalogs,
          Key: { catalogId: { S: deadCatalogId } },
          UpdateExpression: 'SET isDeleted = :yes',
          ExpressionAttributeValues: { ':yes': { BOOL: true } },
        })
      );
      const { data: settings } = await ownerClient.query({
        query: GET_PUBLIC_SETTINGS,
        variables: { campaignId: deadCatalogCampaignId },
        fetchPolicy: 'network-only',
      });
      const token = settings.getCampaignPublicOrderSettings.shareToken;
      await expectGraphQLError(
        () => apiKeyClient.query({
          query: PUBLIC_OFFER,
          variables: { campaignId: bareId(deadCatalogCampaignId), token },
        }),
        'NOT_FOUND',
        OFFER_UNAVAILABLE
      );
    });

    test('no credentials at all is refused', async () => {
      await expectDeniedAtTheHttpLayer(() =>
        anonymousClient.query({ query: PUBLIC_OFFER, variables: { campaignId: bareId(campaignId), token: shareToken } })
      );
    });

    test('a Cognito session cannot reach the API-key-only fields (directive exclusivity)', async () => {
      // Measured in KW-PUBLIC-ORDERS-SPIKE-1: an @aws_api_key-only field refuses
      // the default (Cognito) mode with Unauthorized, not a resolver NOT_FOUND.
      await expectGraphQLError(
        () => ownerClient.query({ query: PUBLIC_OFFER, variables: { campaignId: bareId(campaignId), token: shareToken } }),
        'Unauthorized'
      );
      // The input must be COMPLETE: a missing NonNull field (e.g.
      // acknowledgementsAccepted: Boolean!) is rejected by variable validation
      // before auth resolution, which would mask the auth refusal behind a
      // coercion error and prove nothing about directive exclusivity.
      await expectGraphQLError(
        () =>
          ownerClient.mutate({
            mutation: PUBLIC_CREATE_ORDER,
            variables: {
              input: {
                campaignId: bareId(campaignId),
                token: shareToken,
                acknowledgementsAccepted: true,
                firstName: 'Cognito',
                lastName: 'Caller',
                paymentMethod: plainMethod,
                lineItems: [{ productId, quantity: 1 }],
              },
            },
          }),
        'Unauthorized'
      );
    });

    test('the API key cannot reach the Cognito-only profile fields', async () => {
      await expectGraphQLError(
        () => apiKeyClient.query({ query: gql`query { getProfile(profileId: "${profileId}") { sellerName } }` }),
        'Unauthorized'
      );
    });
  });

  // -------------------------------------------------------------------------
  // Public create (API key + token)
  // -------------------------------------------------------------------------

  describe('publicCreateOrder', () => {
    const baseInput = () => ({
      campaignId: bareId(campaignId),
      token: shareToken,
      acknowledgementsAccepted: true,
      firstName: 'Ivy',
      lastName: 'Buyer',
      phone: '5551234567',
      paymentMethod: plainMethod,
      lineItems: [{ productId, quantity: 2 }],
    });

    test('a full valid order returns the receipt and writes the public order row', async () => {
      const buyerEmail = `po-integration-${Date.now()}@example.com`;
      const { data } = await apiKeyClient.mutate({
        mutation: PUBLIC_CREATE_ORDER,
        variables: {
          input: {
            ...baseInput(),
            email: buyerEmail,
            notes: 'Leave at the door',
            address: { street: '1 Main St', city: 'Springfield', state: 'IL', zipCode: '62701' },
          },
        },
      });
      const receipt = data.publicCreateOrder;
      publicOrderId = receipt.orderId;
      // ORDER#<bare campaign id>#<suffix>: that split is what the receipt route's
      // two path segments are built from.
      const orderIdParts = receipt.orderId.split('#');
      expect(orderIdParts).toHaveLength(3);
      expect(orderIdParts[0]).toBe('ORDER');
      expect(orderIdParts[1]).toBe(bareId(campaignId));
      expect(orderIdParts[2]).toBeTruthy();
      expect(receipt.totalAmount).toBeCloseTo(productPrice * 2, 2);
      expect(receipt.buyerEmailProvided).toBe(true);
      // Three honest states: this stack sends mail only where SES is configured,
      // and a send failure must never fail the order, so the flag is asserted as
      // a boolean rather than as a fixed value.
      expect(typeof receipt.confirmationEmailSent).toBe('boolean');
      expect(receipt.receiptUrl).toMatch(/^\/r\/[^/]+\/[^/]+\/[^/]+$/);
      publicReceiptToken = receipt.receiptUrl.split('/')[4];

      const row = await readOrderRow(campaignId, publicOrderId);
      expect(row.orderSource).toEqual({ S: 'PUBLIC' });
      expect(row.status).toEqual({ S: 'NEW' });
      expect((row.customerEmail as { S: string }).S).toBe(buyerEmail);
      expect(row.customerFirstName).toEqual({ S: 'Ivy' });
      expect(row.customerLastName).toEqual({ S: 'Buyer' });
      // Stored E.164-normalized: validatePhone in
      // tofu/application/appsync/js-resolvers/lib/validation.js returns
      // '+1' + cleaned digits, so the raw input is not what lands in the row.
      expect(row.customerPhone).toEqual({ S: '+15551234567' });
      expect(row.receiptToken).toBeTruthy();
      expect((row.receiptToken as { S: string }).S).toBe(publicReceiptToken);

      expect(await readPublicOrderCount(profileId, campaignId)).toBe(1);
    });

    test('the public order appears in listOrdersByCampaign with a NEW status', async () => {
      const { data } = await ownerClient.query({
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId },
        fetchPolicy: 'network-only',
      });
      const row = data.listOrdersByCampaign.orders.find((o: { orderId: string }) => o.orderId === publicOrderId);
      expect(row, 'the public order must be visible to the owner').toBeTruthy();
      expect(row.status).toBe('NEW');
    });

    test('receiptToken is never selectable on the Order type', async () => {
      // The capability is carried only in the buyer's receipt link; a query that
      // could read it back through the authenticated API would defeat that.
      await expect(
        ownerClient.query({
          query: gql`
            query ProbeOrderToken($orderId: ID!) {
              getOrder(orderId: $orderId) {
                orderId
                receiptToken
              }
            }
          `,
          variables: { orderId: publicOrderId },
        })
      ).rejects.toThrow(/receiptToken|Cannot query field/i);
    });

    test('an authenticated order never touches the counter and carries no status', async () => {
      const before = await readPublicOrderCount(profileId, campaignId);
      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId,
            campaignId,
            customerName: 'Authenticated Buyer',
            customerPhone: '5551234567',
            // CreateOrderInput.orderDate is NonNull (AWSDateTime!): omitting it
            // coerces to null and the operation is rejected before it runs.
            orderDate: new Date().toISOString(),
            paymentMethod: plainMethod,
            lineItems: [{ productId, quantity: 1 }],
          },
        },
      });
      const authenticatedOrderId = data.createOrder.orderId;
      expect(data.createOrder.status ?? null).toBeNull();

      const row = await readOrderRow(campaignId, authenticatedOrderId);
      expect(row.orderSource).toBeUndefined();
      expect(row.status).toBeUndefined();
      expect(row.receiptToken).toBeUndefined();
      expect(await readPublicOrderCount(profileId, campaignId)).toBe(before);

      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: authenticatedOrderId } });
    });

    test('deleting a public order leaves the counter unchanged (it counts deleted orders)', async () => {
      const before = await readPublicOrderCount(profileId, campaignId);
      const { data } = await apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: baseInput() } });
      const counted = await readPublicOrderCount(profileId, campaignId);
      expect(counted).toBe(before + 1);

      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: data.publicCreateOrder.orderId } });
      expect(await readPublicOrderCount(profileId, campaignId)).toBe(counted);
    });

    test('a case-variant of an allowlisted method is accepted', async () => {
      const { data } = await apiKeyClient.mutate({
        mutation: PUBLIC_CREATE_ORDER,
        variables: { input: { ...baseInput(), paymentMethod: plainMethod.toUpperCase() } },
      });
      expect(data.publicCreateOrder.orderId).toBeTruthy();
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: data.publicCreateOrder.orderId } });
    });

    test('not-allowlisted and deleted-from-account methods share one message (no name oracle)', async () => {
      await expectGraphQLError(
        () => apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: { ...baseInput(), paymentMethod: 'NotOnThisAccount' } } }),
        'INVALID_INPUT',
        new RegExp(PUBLIC_METHOD_UNAVAILABLE)
      );

      // A method that WAS allowlisted and is then deleted from the account must
      // produce the identical message, so iterating the mutation cannot
      // enumerate the owner's stored method names.
      const extra = `PO-Gone-${Date.now()}`;
      await ownerClient.mutate({ mutation: CREATE_PAYMENT_METHOD, variables: { name: extra } });
      await ownerClient.mutate({
        mutation: UPDATE_PUBLIC_SETTINGS,
        variables: { input: { campaignId, enabled: true, allowedPaymentMethods: [qrMethod, plainMethod, extra] } },
      });
      await ownerClient.mutate({ mutation: DELETE_PAYMENT_METHOD, variables: { name: extra } });
      try {
        await expectGraphQLError(
          () => apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: { ...baseInput(), paymentMethod: extra } } }),
          'INVALID_INPUT',
          new RegExp(PUBLIC_METHOD_UNAVAILABLE)
        );
      } finally {
        await ownerClient.mutate({
          mutation: UPDATE_PUBLIC_SETTINGS,
          variables: { input: { campaignId, enabled: true, allowedPaymentMethods: [qrMethod, plainMethod] } },
        });
      }
    });

    test('every anonymous-input bound is enforced', async () => {
      const cases: Array<[string, Record<string, unknown>, RegExp]> = [
        ['unknown product', { lineItems: [{ productId: 'no-such-product', quantity: 1 }] }, /product/i],
        ['no phone and no address', { phone: undefined }, /phone number or a complete address/i],
        ['malformed phone', { phone: '12345' }, /phone/i],
        ['acknowledgements refused', { acknowledgementsAccepted: false }, /terms must be accepted/i],
        ['zero line items', { lineItems: [] }, /at least one line item/i],
        [
          'more than twenty line items',
          { lineItems: Array.from({ length: 21 }, () => ({ productId, quantity: 1 })) },
          /at most 20 line items/i,
        ],
        ['quantity above the bound', { lineItems: [{ productId, quantity: 1000 }] }, /between 1 and 999/i],
        ['oversized notes', { notes: 'x'.repeat(501) }, /notes must be at most 500/i],
        ['blank first name', { firstName: '   ' }, /first name is required/i],
        // Values the AWSEmail scalar accepts but the public path's own check
        // rejects: the public resolver is the authorization boundary for
        // anonymous input, so it re-checks rather than trusting the transport
        // scalar (spec D7).
        ['email with no domain label', { email: 'buyer@nodot' }, /email address is not valid/i],
        ['oversized email', { email: `${'a'.repeat(248)}@example.com` }, /email address must be at most 254/i],
      ];
      for (const [, override, pattern] of cases) {
        await expectGraphQLError(
          () => apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: { ...baseInput(), ...override } } }),
          'INVALID_INPUT',
          pattern
        );
      }
    });

    test('a bad token and a token from another campaign are the same NOT_FOUND', async () => {
      await expectGraphQLError(
        () => apiKeyClient.mutate({
          mutation: PUBLIC_CREATE_ORDER,
          variables: { input: { ...baseInput(), token: 'deadbeefdeadbeefdeadbeefdeadbeef' } },
        }),
        'NOT_FOUND',
        new RegExp(PUBLIC_ORDER_UNAVAILABLE)
      );
      // Cross-wiring: the race campaign's token submitted against the main
      // campaign's id. The campaign IS the anchor, so a foreign token cannot be
      // steered onto it.
      await expectGraphQLError(
        () => apiKeyClient.mutate({
          mutation: PUBLIC_CREATE_ORDER,
          variables: { input: { ...baseInput(), token: raceShareToken } },
        }),
        'NOT_FOUND',
        new RegExp(PUBLIC_ORDER_UNAVAILABLE)
      );
    });

    test('orders past the cap are rejected with no row written and the counter unchanged', async () => {
      await seedPublicOrderCount(profileId, capCampaignId, PUBLIC_ORDER_CAP - 1);
      const capInput = { ...baseInput(), campaignId: bareId(capCampaignId), token: capShareToken };

      const last = await apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: capInput } });
      expect(last.data.publicCreateOrder.orderId).toBeTruthy();
      expect(await readPublicOrderCount(profileId, capCampaignId)).toBe(PUBLIC_ORDER_CAP);

      await expectGraphQLError(
        () => apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: capInput } }),
        'PUBLIC_ORDER_LIMIT_EXCEEDED',
        /reached its public order limit/i
      );
      expect(await readPublicOrderCount(profileId, capCampaignId)).toBe(PUBLIC_ORDER_CAP);

      const orders = await ownerClient.query({
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId: capCampaignId },
        fetchPolicy: 'network-only',
      });
      expect(orders.data.listOrdersByCampaign.orders).toHaveLength(1);
    });

    test('a concurrent pair at 499 admits exactly one order (the cap lives in the condition)', async () => {
      await seedPublicOrderCount(profileId, raceCampaignId, PUBLIC_ORDER_CAP - 1);
      const raceInput = { ...baseInput(), campaignId: bareId(raceCampaignId), token: raceShareToken };

      const settled = await Promise.allSettled([
        apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: raceInput } }),
        apiKeyClient.mutate({ mutation: PUBLIC_CREATE_ORDER, variables: { input: raceInput } }),
      ]);
      const succeeded = settled.filter((outcome) => outcome.status === 'fulfilled');
      expect(succeeded, 'exactly one of the pair must be admitted').toHaveLength(1);
      expect(await readPublicOrderCount(profileId, raceCampaignId)).toBe(PUBLIC_ORDER_CAP);

      const orders = await ownerClient.query({
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId: raceCampaignId },
        fetchPolicy: 'network-only',
      });
      expect(orders.data.listOrdersByCampaign.orders, 'the loser must write no order row').toHaveLength(1);
    });
  });

  // -------------------------------------------------------------------------
  // Receipt (API key)
  // -------------------------------------------------------------------------

  describe('publicGetOrderReceipt', () => {
    test('the receipt link from the create returns the buyer view', async () => {
      const { data } = await apiKeyClient.query({
        query: PUBLIC_GET_RECEIPT,
        variables: { campaignId: bareId(campaignId), orderSuffix: publicOrderId.split('#')[2], receiptToken: publicReceiptToken },
        fetchPolicy: 'network-only',
      });
      const receipt = data.publicGetOrderReceipt;
      expect(receipt.orderId).toBe(publicOrderId);
      expect(receipt.sellerName).toBe(profileName);
      expect(receipt.status).toBe('NEW');
      expect(receipt.buyerFirstName).toBe('Ivy');
      expect(receipt.lineItems).toHaveLength(1);
      expect(receipt.totalAmount).toBeCloseTo(productPrice * 2, 2);
      // The buyer already supplied their own contact details; the view must not
      // echo them, and it must never echo the receipt token.
      const raw = JSON.stringify(receipt);
      expect(raw).not.toContain(publicReceiptToken);
      expect(receipt).not.toHaveProperty('customerEmail');
      expect(receipt).not.toHaveProperty('customerPhone');
    });

    test('a wrong receipt token is NOT_FOUND', async () => {
      await expectGraphQLError(
        () => apiKeyClient.query({
          query: PUBLIC_GET_RECEIPT,
          variables: { campaignId: bareId(campaignId), orderSuffix: publicOrderId.split('#')[2], receiptToken: 'deadbeefdeadbeefdeadbeefdeadbeef' },
        }),
        'NOT_FOUND'
      );
    });
  });

  // -------------------------------------------------------------------------
  // Order status lifecycle (Cognito)
  // -------------------------------------------------------------------------

  describe('updateOrder status', () => {
    test('the owner marks a public order CONFIRMED and the buyer receipt follows', async () => {
      const { data } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: { orderId: publicOrderId, status: 'CONFIRMED' } },
      });
      expect(data.updateOrder.status).toBe('CONFIRMED');

      const { data: buyerView } = await apiKeyClient.query({
        query: PUBLIC_GET_RECEIPT,
        variables: { campaignId: bareId(campaignId), orderSuffix: publicOrderId.split('#')[2], receiptToken: publicReceiptToken },
        fetchPolicy: 'network-only',
      });
      expect(buyerView.publicGetOrderReceipt.status).toBe('CONFIRMED');
    });

    test('status cannot be set again once CONFIRMED (one-way in v1)', async () => {
      await expectGraphQLError(
        () => ownerClient.mutate({ mutation: UPDATE_ORDER, variables: { input: { orderId: publicOrderId, status: 'CONFIRMED' } } }),
        'INVALID_INPUT'
      );
    });

    test('status cannot be set on an authenticated order', async () => {
      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId,
            campaignId,
            customerName: 'No Status Buyer',
            customerPhone: '5551234567',
            orderDate: new Date().toISOString(),
            paymentMethod: plainMethod,
            lineItems: [{ productId, quantity: 1 }],
          },
        },
      });
      const authenticatedOrderId = data.createOrder.orderId;
      try {
        await expectGraphQLError(
          () => ownerClient.mutate({ mutation: UPDATE_ORDER, variables: { input: { orderId: authenticatedOrderId, status: 'CONFIRMED' } } }),
          'INVALID_INPUT'
        );
      } finally {
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: authenticatedOrderId } });
      }
    });

    test('status cannot be cleared and the public attributes are not settable', async () => {
      await expectGraphQLError(
        () => ownerClient.mutate({ mutation: UPDATE_ORDER, variables: { input: { orderId: publicOrderId, status: null } } }),
        'INVALID_INPUT'
      );

      const row = await readOrderRow(campaignId, publicOrderId);
      expect(row.orderSource).toEqual({ S: 'PUBLIC' });
      expect(row.receiptToken).toBeTruthy();
    });
  });
});
