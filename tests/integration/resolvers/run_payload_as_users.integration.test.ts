import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

// GraphQL Mutations for setup
const CREATE_SELLER_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
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
      }
    }
  }
`;

const CREATE_CAMPAIGN = gql`
  mutation CreateCampaign($input: CreateCampaignInput!) {
    createCampaign(input: $input) {
      campaignId
      catalogId
    }
  }
`;

const SHARE_PROFILE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      targetAccountId
    }
  }
`;

const CREATE_ORDER = gql`
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      orderId
      campaignId
      customerName
    }
  }
`;

const DELETE_ORDER = gql`
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

const DELETE_CAMPAIGN = gql`
  mutation DeleteCampaign($campaignId: ID!) {
    deleteCampaign(campaignId: $campaignId)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

describe('Multi-User Order Creation Tests', () => {
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;

  let testProfileId: string;
  let testCampaignId: string;
  let testCatalogId: string;
  let testProductId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let createdOrderIds: string[] = [];

  beforeAll(async () => {
    // Authenticate all test users
    const ownerAuth = await createAuthenticatedClient('owner');
    const contributorAuth = await createAuthenticatedClient('contributor');
    const readonlyAuth = await createAuthenticatedClient('readonly');

    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;

    console.log('Creating test data for multi-user order test...');

    // 1. Create profile (as owner)
    const { data: profileData } = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: { input: { sellerName: 'Multi-User Test Seller' } },
    });
    testProfileId = profileData.createSellerProfile.profileId;

    // 2. Create catalog with a product
    const { data: catalogData } = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: 'Multi-User Test Catalog',
          isPublic: false,
          products: [{ productName: 'Test Product', price: 15.00, sortOrder: 1 }],
        },
      },
    });
    testCatalogId = catalogData.createCatalog.catalogId;
    testProductId = catalogData.createCatalog.products[0].productId;

    // 3. Create campaign
    const { data: campaignData } = await ownerClient.mutate({
      mutation: CREATE_CAMPAIGN,
      variables: {
        input: {
          profileId: testProfileId,
          campaignName: 'Multi-User Test Campaign',
          campaignYear: 2026,
          startDate: new Date('2026-01-01').toISOString(),
          endDate: new Date('2026-12-31').toISOString(),
          catalogId: testCatalogId,
        },
      },
    });
    testCampaignId = campaignData.createCampaign.campaignId;

    // 4. Share profile with contributor (WRITE permission)
    const { data: share1 } = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
          permissions: ['READ', 'WRITE'],
        },
      },
    });
    contributorAccountId = share1.shareProfileDirect.targetAccountId;

    // 5. Share profile with readonly (READ permission only)
    const { data: share2 } = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
          permissions: ['READ'],
        },
      },
    });
    readonlyAccountId = share2.shareProfileDirect.targetAccountId;

    console.log(`Test data created: Profile=${testProfileId}, Campaign=${testCampaignId}, Product=${testProductId}`);
  }, 30000);

  afterAll(async () => {
    console.log('Cleaning up multi-user test data...');

    // Delete created orders
    for (const orderId of createdOrderIds) {
      try {
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      } catch (e) {
        console.log(`Error deleting order ${orderId}:`, e);
      }
    }

    // Revoke shares
    try {
      await ownerClient.mutate({
        mutation: REVOKE_SHARE,
        variables: { input: { profileId: testProfileId, targetAccountId: contributorAccountId } },
      });
      await ownerClient.mutate({
        mutation: REVOKE_SHARE,
        variables: { input: { profileId: testProfileId, targetAccountId: readonlyAccountId } },
      });
    } catch (e) {
      console.log('Error revoking shares:', e);
    }

    // Delete campaign, catalog, profile
    try {
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: testCampaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: testCatalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: testProfileId } });
    } catch (e) {
      console.log('Error deleting test resources:', e);
    }

    console.log('Multi-user test data cleanup complete.');
  });

  test('owner can create order', async () => {
    const payload = {
      profileId: testProfileId,
      campaignId: testCampaignId,
      customerName: 'Owner Test Customer',
      orderDate: new Date().toISOString(),
      paymentMethod: 'CASH',
      lineItems: [{ productId: testProductId, quantity: 2 }],
    };

    const { data } = await ownerClient.mutate({
      mutation: CREATE_ORDER,
      variables: { input: payload },
    });

    expect(data.createOrder).toBeDefined();
    expect(data.createOrder.orderId).toBeDefined();
    expect(data.createOrder.customerName).toBe('Owner Test Customer');
    createdOrderIds.push(data.createOrder.orderId);
  });

  test('contributor with WRITE permission can create order', async () => {
    const payload = {
      profileId: testProfileId,
      campaignId: testCampaignId,
      customerName: 'Contributor Test Customer',
      orderDate: new Date().toISOString(),
      paymentMethod: 'CASH',
      lineItems: [{ productId: testProductId, quantity: 1 }],
    };

    const { data } = await contributorClient.mutate({
      mutation: CREATE_ORDER,
      variables: { input: payload },
    });

    expect(data.createOrder).toBeDefined();
    expect(data.createOrder.orderId).toBeDefined();
    expect(data.createOrder.customerName).toBe('Contributor Test Customer');
    createdOrderIds.push(data.createOrder.orderId);
  });

  test('readonly with READ permission cannot create order', async () => {
    const payload = {
      profileId: testProfileId,
      campaignId: testCampaignId,
      customerName: 'Readonly Test Customer',
      orderDate: new Date().toISOString(),
      paymentMethod: 'CASH',
      lineItems: [{ productId: testProductId, quantity: 1 }],
    };

    await expect(
      readonlyClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: payload },
      })
    ).rejects.toThrow(/Forbidden|permission/i);
  });
});
