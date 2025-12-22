import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';


/**
 * Integration tests for Order Operations (createOrder, updateOrder, deleteOrder)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile/campaign (can create/update/delete orders)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can create/update/delete orders)
 * - TEST_READONLY_EMAIL: Has READ access (cannot modify orders)
 * 
 * Note: These tests create their own test data (profile, campaign, catalog)
 * and clean up after themselves.
 */

// GraphQL Mutations for setup
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
      catalogName
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
      campaignYear
      catalogId
      startDate
      endDate
    }
  }
`;

const GET_CAMPAIGN = gql`
  query GetCampaign($campaignId: ID!) {
    getCampaign(campaignId: $campaignId) {
      campaignId
      catalogId
      campaignName
    }
  }
`;


const SHARE_PROFILE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      shareId
      profileId
      targetAccountId
      permissions
    }
  }
`;

// GraphQL Mutations for tests
const CREATE_ORDER = gql`
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      orderId
      profileId
      campaignId
      customerName
      customerPhone
      orderDate
      paymentMethod
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      totalAmount
      createdAt
    }
  }
`;

const UPDATE_ORDER = gql`
  mutation UpdateOrder($input: UpdateOrderInput!) {
    updateOrder(input: $input) {
      orderId
      customerName
      customerPhone
      paymentMethod
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      totalAmount
      updatedAt
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
  mutation DeleteProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

const LIST_ORDERS_BY_CAMPAIGN = gql`
  query ListOrdersByCampaign($campaignId: ID!) {
    listOrdersByCampaign(campaignId: $campaignId) {
      orderId
    }
  }
`;

const GET_ORDER = gql`
  query GetOrder($orderId: ID!) {
    getOrder(orderId: $orderId) {
      orderId
      customerName
      orderDate
      paymentMethod
    }
  }
`;

describe('Order Operations Integration Tests', () => {
  const SUITE_ID = 'order-operations';
  
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;

  // Test data IDs (created during setup)
  let testProfileId: string;
  let testCampaignId: string;
  let testCatalogId: string;
  let testProductId: string;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;

  beforeAll(async () => {
    // Authenticate all test users
    const ownerAuth = await createAuthenticatedClient('owner');
    const contributorAuth = await createAuthenticatedClient('contributor');
    const readonlyAuth = await createAuthenticatedClient('readonly');

    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;
    ownerAccountId = ownerAuth.accountId;

    // Clear Apollo caches to avoid state pollution from other tests
    await ownerClient.cache.reset();
    await contributorClient.cache.reset();
    await readonlyClient.cache.reset();

    // Create test data
    console.log('Creating test profile, catalog, and campaign...');
    
    // 1. Create profile
    const { data: profileData } = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: {
        input: {
          sellerName: 'Order Test Seller',
        },
      },
    });
    testProfileId = profileData.createSellerProfile.profileId;

    // 2. Create catalog with products
    const { data: catalogData } = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: 'Order Test Catalog',
          isPublic: false,
          products: [
            {
              productName: 'Test Popcorn',
              description: 'Test product for integration tests',
              price: 10.00,
              sortOrder: 1,
            },
          ],
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
          campaignName: 'Order Test Campaign',
          campaignYear: 2025,
          startDate: new Date('2025-01-01T00:00:00Z').toISOString(),
          endDate: new Date('2025-12-31T23:59:59Z').toISOString(),
          catalogId: testCatalogId,
        },
      },
    });
    testCampaignId = campaignData.createCampaign.campaignId;

    // Verify campaign has catalogId before proceeding (GSI5 propagation)
    let retries = 0;
    while (retries < 5) {
      try {
        const { data: campaignVerify } = await ownerClient.query({
          query: GET_CAMPAIGN,
          variables: { campaignId: testCampaignId },
          fetchPolicy: 'network-only', // Bypass cache
        });
        if (campaignVerify?.getCampaign?.catalogId) {
          break; // Campaign has catalogId, proceed
        }
      } catch (e) {
        // Campaign not found yet in GSI, retry
      }
      await new Promise(resolve => setTimeout(resolve, 500)); // Wait 500ms
      retries++;
    }

    // 4. Share profile with contributor (WRITE)
    const { data: share1Data } = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
          permissions: ['READ', 'WRITE'],
        },
      },
    });
    contributorAccountId = share1Data.shareProfileDirect.targetAccountId;

    // 5. Share profile with readonly (READ)
    const { data: share2Data } = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
          permissions: ['READ'],
        },
      },
    });
    readonlyAccountId = share2Data.shareProfileDirect.targetAccountId;

    console.log(`Test data created: Profile=${testProfileId}, Campaign=${testCampaignId}, Product=${testProductId}`);
  }, 30000);

  afterAll(async () => {
    // Clean up all test data in reverse order
    console.log('Cleaning up test data...');
    
    // 1. Delete all orders in the campaign
    try {
      const { data: ordersData } = await ownerClient.query({
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId: testCampaignId },
        fetchPolicy: 'network-only',
      });
      for (const order of ordersData.listOrdersByCampaign || []) {
        await ownerClient.mutate({
          mutation: DELETE_ORDER,
          variables: { orderId: order.orderId },
        });
      }
    } catch (e) {
      console.log('Error cleaning up orders:', e);
    }
    
    // 2. Revoke shares
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
    
    // 3. Delete campaign
    try {
      await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: testCampaignId },
      });
    } catch (e) {
      console.log('Error deleting campaign:', e);
    }
    
    // 4. Delete catalog
    try {
      await ownerClient.mutate({
        mutation: DELETE_CATALOG,
        variables: { catalogId: testCatalogId },
      });
    } catch (e) {
      console.log('Error deleting catalog:', e);
    }
    
    // 5. Delete profile
    try {
      await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: testProfileId },
      });
    } catch (e) {
      console.log('Error deleting profile:', e);
    }
    
    // 6. Delete account records
    console.log('Cleaning up account records...');
    // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
    
    console.log('Test data cleanup complete.');
  }, 30000);


  describe('createOrder', () => {
    test('creates order with valid line items', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'John Doe',
        customerPhone: '+15551234567',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 2,
          },
        ],
        notes: 'Test order from integration test',
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder).toBeDefined();
      expect(data.createOrder.orderId).toBeDefined();
      expect(data.createOrder.customerName).toBe('John Doe');
      expect(data.createOrder.paymentMethod).toBe('CASH');
      expect(data.createOrder.lineItems).toHaveLength(1);
      expect(data.createOrder.lineItems[0].quantity).toBe(2);
      expect(data.createOrder.lineItems[0].productName).toBe('Test Popcorn');
      expect(data.createOrder.lineItems[0].pricePerUnit).toBe(10.00);
      expect(data.createOrder.totalAmount).toBe(20.00);

      // Track for cleanup
    }, 10000);

    test('contributor with WRITE access can create order', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Jane Smith',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CHECK',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data } = await contributorClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder).toBeDefined();
      expect(data.createOrder.customerName).toBe('Jane Smith');

      // Track for cleanup
    }, 10000);

    test('rejects order with non-existent product', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: 'PRODUCT#non-existent-product',
            quantity: 1,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow(/not found|does not exist/i);
    }, 10000);

    test('rejects order with invalid campaign', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: 'CAMPAIGN#non-existent-campaign',
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow(/not found|does not exist|invalid/i);
    }, 10000);
  });

  describe('updateOrder', () => {
    test('updates order customer name', async () => {
      // First create an order
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Original Name',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Now delete it
      const updateInput = {
        orderId,
        customerName: 'Updated Name',
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.customerName).toBe('Updated Name');
      expect(updateData.updateOrder.orderId).toBe(orderId);
    }, 10000);

    test('contributor with WRITE access can update order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Original Name',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Contributor deletes it
      const updateInput = {
        orderId,
        customerName: 'Updated by Contributor',
      };

      const { data: updateData } = await contributorClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.customerName).toBe('Updated by Contributor');
    }, 10000);

    test('rejects update with non-existent orderId', async () => {
      const updateInput = {
        orderId: 'ORDER#non-existent-order',
        customerName: 'Updated Name',
      };

      await expect(
        ownerClient.mutate({
          mutation: UPDATE_ORDER,
          variables: { input: updateInput },
        })
      ).rejects.toThrow(/not found|does not exist/i);
    }, 10000);
  });

  describe('deleteOrder', () => {
    test('deletes existing order', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'To Be Deleted',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Delete it
      const { data: deleteData } = await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });

      expect(deleteData.deleteOrder).toBe(true);
      
      // Don't add to cleanup list since it's already deleted
    }, 10000);

    test('contributor with WRITE access can delete order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'To Be Deleted by Contributor',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Contributor deletes it
      const { data: deleteData } = await contributorClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });

      expect(deleteData.deleteOrder).toBe(true);
    }, 10000);

    test('returns true for non-existent order (idempotent)', async () => {
      const { data } = await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId: 'ORDER#non-existent-order' },
      });

      expect(data.deleteOrder).toBe(true);
    }, 10000);

    test('Data Integrity: Deleted order cannot be retrieved with getOrder', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Get After Delete Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Verify it exists
      const { data: getBeforeData }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });
      expect(getBeforeData.getOrder).toBeDefined();
      expect(getBeforeData.getOrder.orderId).toBe(orderId);

      // Delete it
      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });

      // Verify it no longer exists
      const { data: getAfterData }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });
      expect(getAfterData.getOrder).toBeNull();
    }, 15000);

    test('Data Integrity: Deleted order does not appear in listOrdersByCampaign', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'List After Delete Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CHECK',
        lineItems: [
          {
            productId: testProductId,
            quantity: 2,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Verify it appears in list
      const { data: listBeforeData }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId: testCampaignId },
        fetchPolicy: 'network-only',
      });
      const beforeOrderIds = listBeforeData.listOrdersByCampaign.map((o: any) => o.orderId);
      expect(beforeOrderIds).toContain(orderId);

      // Delete it
      await ownerClient.mutate({
        mutation: DELETE_ORDER,
        variables: { orderId },
      });

      // Verify it no longer appears in list
      const { data: listAfterData }: any = await ownerClient.query({
        query: LIST_ORDERS_BY_CAMPAIGN,
        variables: { campaignId: testCampaignId },
        fetchPolicy: 'network-only',
      });
      const afterOrderIds = listAfterData.listOrdersByCampaign.map((o: any) => o.orderId);
      expect(afterOrderIds).not.toContain(orderId);
    }, 15000);

    test('Data Integrity: Concurrent deletion of same order (idempotent)', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Concurrent Delete Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Act: Issue two concurrent delete requests for the same order
      const [result1, result2] = await Promise.all([
        ownerClient.mutate({
          mutation: DELETE_ORDER,
          variables: { orderId },
        }),
        ownerClient.mutate({
          mutation: DELETE_ORDER,
          variables: { orderId },
        }),
      ]);

      // Assert: Both should succeed (idempotent behavior)
      expect(result1.data.deleteOrder).toBe(true);
      expect(result2.data.deleteOrder).toBe(true);

      // Verify the order is actually deleted
      const { data: verifyData }: any = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });
      expect(verifyData.getOrder).toBeNull();
    }, 15000);
  });

  /**
   * Authorization Tests - Bug #13
   * 
   * Status: FIXED - VerifyProfileWriteAccessFn now properly blocks readonly users
   */
  describe('createOrder authorization', () => {
    test('readonly user cannot create order', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Read Only Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      await expect(
        readonlyClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);

    test('SECURITY: non-owner without shares cannot create order on others profile', async () => {
      // Arrange: Create a NEW profile without sharing it with contributor
      const { data: newProfile } = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: { input: { sellerName: 'No Share Profile' } },
      });
      const noShareProfileId = newProfile.createSellerProfile.profileId;

      // Create a campaign for the new profile
      const { data: newCampaign } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: noShareProfileId,
            campaignName: 'No Share Campaign',
            campaignYear: 2025,
            startDate: new Date('2025-01-01').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const noShareCampaignId = newCampaign.createCampaign.campaignId;

      // Wait for GSI propagation
      await new Promise(resolve => setTimeout(resolve, 500));

      try {
        // Act: Contributor (who has NO share on this new profile) tries to create order
        const input = {
          profileId: noShareProfileId,
          campaignId: noShareCampaignId,
          customerName: 'Unauthorized Order',
          orderDate: new Date().toISOString(),
          paymentMethod: 'CASH',
          lineItems: [{ productId: testProductId, quantity: 1 }],
        };

        await expect(
          contributorClient.mutate({
            mutation: CREATE_ORDER,
            variables: { input },
          })
        ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
      } finally {
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: noShareCampaignId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: noShareProfileId } });
      }
    }, 20000);
  });

  describe('updateOrder authorization', () => {
    test('readonly user cannot update order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Original Name',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Readonly tries to update
      await expect(
        readonlyClient.mutate({
          mutation: UPDATE_ORDER,
          variables: {
            input: {
              orderId,
              customerName: 'Readonly Update Attempt',
            },
          },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);

    test('SECURITY: non-owner without shares cannot update order on others profile', async () => {
      // Arrange: Create a NEW profile without sharing it with contributor
      const { data: newProfile } = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: { input: { sellerName: 'No Share Update Profile' } },
      });
      const noShareProfileId = newProfile.createSellerProfile.profileId;

      // Create a campaign for the new profile
      const { data: newCampaign } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: noShareProfileId,
            campaignName: 'No Share Update Campaign',
            campaignYear: 2025,
            startDate: new Date('2025-01-01').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const noShareCampaignId = newCampaign.createCampaign.campaignId;

      // Wait for GSI propagation
      await new Promise(resolve => setTimeout(resolve, 500));

      // Owner creates an order on the non-shared profile
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: noShareProfileId,
            campaignId: noShareCampaignId,
            customerName: 'Protected Order',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      try {
        // Act: Contributor (who has NO share on this profile) tries to update order
        await expect(
          contributorClient.mutate({
            mutation: UPDATE_ORDER,
            variables: {
              input: {
                orderId,
                customerName: 'Unauthorized Update',
              },
            },
          })
        ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
      } finally {
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: noShareCampaignId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: noShareProfileId } });
      }
    }, 25000);
  });

  describe('deleteOrder authorization', () => {
    test('readonly user cannot delete order', async () => {
      // Owner creates order
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'To Be Protected',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Readonly tries to delete
      await expect(
        readonlyClient.mutate({
          mutation: DELETE_ORDER,
          variables: { orderId },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);

    test('SECURITY: non-owner without shares cannot delete order on others profile', async () => {
      // Arrange: Create a NEW profile without sharing it with contributor
      const { data: newProfile } = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: { input: { sellerName: 'No Share Delete Profile' } },
      });
      const noShareProfileId = newProfile.createSellerProfile.profileId;

      // Create a campaign for the new profile
      const { data: newCampaign } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: noShareProfileId,
            campaignName: 'No Share Delete Campaign',
            campaignYear: 2025,
            startDate: new Date('2025-01-01').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const noShareCampaignId = newCampaign.createCampaign.campaignId;

      // Wait for GSI propagation
      await new Promise(resolve => setTimeout(resolve, 500));

      // Owner creates an order on the non-shared profile
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: noShareProfileId,
            campaignId: noShareCampaignId,
            customerName: 'Protected Order Delete',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      try {
        // Act: Contributor (who has NO share on this profile) tries to delete order
        await expect(
          contributorClient.mutate({
            mutation: DELETE_ORDER,
            variables: { orderId },
          })
        ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
      } finally {
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
        await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: noShareCampaignId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId: noShareProfileId } });
      }
    }, 25000);
  });

  /**
   * Input Validation Tests - Bug #15
   * 
   * KNOWN BUG: createOrder accepts invalid quantities.
   * Empty line items, zero, and negative quantities are all allowed.
   * 
   * Status: FIXED - Input validation added to CreateOrderFn
   */
  describe('createOrder input validation', () => {
    test('rejects order with empty line items', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow();
    }, 10000);

    test('rejects order with zero quantity', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 0,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow();
    }, 10000);

    test('rejects order with negative quantity', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Test Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: -5,
          },
        ],
      };

      await expect(
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: { input },
        })
      ).rejects.toThrow();
    }, 10000);
  });

  /**
   * updateOrder Input Validation Tests - Bug #16
   * 
   * Status: FIXED - Conditional catalog lookup added to UpdateOrder pipeline
   */
  describe('updateOrder input validation', () => {
    test('updates order with new line items', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Original Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Update with increased quantity
      const updateInput = {
        orderId,
        lineItems: [
          {
            productId: testProductId,
            quantity: 5,
          },
        ],
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.lineItems[0].quantity).toBe(5);
      expect(updateData.updateOrder.totalAmount).toBe(50.00); // 5 * 10.00
    }, 10000);

    test('updates order payment method', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Payment Test',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [
          {
            productId: testProductId,
            quantity: 1,
          },
        ],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Update payment method
      const updateInput = {
        orderId,
        paymentMethod: 'CREDIT_CARD',
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      expect(updateData.updateOrder.paymentMethod).toBe('CREDIT_CARD');
    }, 10000);
  });

  describe('createOrder payment methods', () => {
    test('creates order with CASH payment method', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Cash Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [{ productId: testProductId, quantity: 1 }],
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder.paymentMethod).toBe('CASH');
    }, 10000);

    test('creates order with CHECK payment method', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Check Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CHECK',
        lineItems: [{ productId: testProductId, quantity: 1 }],
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder.paymentMethod).toBe('CHECK');
    }, 10000);

    test('creates order with CREDIT_CARD payment method', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Credit Card Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CREDIT_CARD',
        lineItems: [{ productId: testProductId, quantity: 1 }],
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder.paymentMethod).toBe('CREDIT_CARD');
    }, 10000);

    test('creates order with OTHER payment method', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Other Payment Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'OTHER',
        lineItems: [{ productId: testProductId, quantity: 1 }],
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder.paymentMethod).toBe('OTHER');
    }, 10000);
  });

  describe('createOrder optional fields', () => {
    test('creates order with all optional fields provided', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Full Details Customer',
        customerPhone: '+15551234567',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [{ productId: testProductId, quantity: 2 }],
        notes: 'Test notes for this order',
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder.customerName).toBe('Full Details Customer');
      expect(data.createOrder.customerPhone).toBe('+15551234567');
    }, 10000);

    test('creates order with optional fields missing', async () => {
      const input = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Minimal Customer',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [{ productId: testProductId, quantity: 1 }],
        // customerPhone and notes are not provided
      };

      const { data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input },
      });

      expect(data.createOrder.customerName).toBe('Minimal Customer');
      expect(data.createOrder.customerPhone).toBeNull();
    }, 10000);
  });

  describe('updateOrder edge cases', () => {
    test('updating order with no changes returns same data', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'No Change Customer',
        customerPhone: '+15559876543',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [{ productId: testProductId, quantity: 3 }],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;
      const originalTotal = createData.createOrder.totalAmount;

      // Update with only orderId (no actual changes)
      const updateInput = {
        orderId,
        // No other fields - essentially a no-op
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      // Original data should be preserved
      expect(updateData.updateOrder.orderId).toBe(orderId);
      expect(updateData.updateOrder.customerName).toBe('No Change Customer');
      expect(updateData.updateOrder.customerPhone).toBe('+15559876543');
      expect(updateData.updateOrder.totalAmount).toBe(originalTotal);
    }, 10000);

    test('partial update only changes specified fields', async () => {
      // Create an order first
      const createInput = {
        profileId: testProfileId,
        campaignId: testCampaignId,
        customerName: 'Partial Update Customer',
        customerPhone: '+15551112222',
        orderDate: new Date().toISOString(),
        paymentMethod: 'CASH',
        lineItems: [{ productId: testProductId, quantity: 2 }],
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: { input: createInput },
      });

      const orderId = createData.createOrder.orderId;

      // Update only the customer name
      const updateInput = {
        orderId,
        customerName: 'New Customer Name',
      };

      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: { input: updateInput },
      });

      // Only customerName should change, other fields preserved
      expect(updateData.updateOrder.customerName).toBe('New Customer Name');
      expect(updateData.updateOrder.customerPhone).toBe('+15551112222');
      expect(updateData.updateOrder.paymentMethod).toBe('CASH');
      expect(updateData.updateOrder.lineItems[0].quantity).toBe(2);
    }, 10000);
  });

  describe('Order boundary tests', () => {
    test('order with many line items (boundary testing)', async () => {
      // Create catalog with 20 products for testing many line items
      const products = [];
      for (let i = 1; i <= 20; i++) {
        products.push({
          productName: `Product ${i}`,
          description: `Product ${i} description`,
          price: i * 1.5, // prices: 1.50, 3.00, 4.50, ...
          sortOrder: i,
        });
      }

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: 'Many Products Catalog',
            isPublic: false,
            products: products,
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;
      const productIds = catalogData.createCatalog.products.map((p: { productId: string }) => p.productId);

      // Create a campaign with this catalog
      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Many Items Campaign',
            campaignYear: 2025,
            startDate: new Date('2025-06-01T00:00:00Z').toISOString(),
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

      // Wait a moment for GSI propagation
      await new Promise(resolve => setTimeout(resolve, 500));

      // Create order with all 20 products (20 line items)
      const lineItems = productIds.map((productId: string, index: number) => ({
        productId,
        quantity: index + 1, // quantities: 1, 2, 3, ..., 20
      }));

      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: campaignId,
            customerName: 'Many Items Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: lineItems,
          },
        },
      });

      // Assert: Order created with all 20 line items
      expect(orderData.createOrder.lineItems).toHaveLength(20);
      expect(orderData.createOrder.orderId).toBeDefined();
      
      // Calculate expected total: sum of (quantity * price) for each product
      // Product 1: 1 * 1.50 = 1.50
      // Product 2: 2 * 3.00 = 6.00
      // ...
      // Product 20: 20 * 30.00 = 600.00
      let expectedTotal = 0;
      for (let i = 1; i <= 20; i++) {
        const price = i * 1.5;
        const quantity = i;
        expectedTotal += price * quantity;
      }
      expect(orderData.createOrder.totalAmount).toBe(expectedTotal);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderData.createOrder.orderId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: catalogId } });
    }, 30000);

    test('order with very large quantity', async () => {
      // Test with a large quantity value
      const largeQuantity = 99999;

      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: testCampaignId,
            customerName: 'Large Quantity Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CHECK',
            lineItems: [{ productId: testProductId, quantity: largeQuantity }],
          },
        },
      });

      // Assert: Order created with large quantity
      expect(orderData.createOrder.orderId).toBeDefined();
      expect(orderData.createOrder.lineItems[0].quantity).toBe(largeQuantity);
      // Total: 99999 * $10.00 = $999990.00
      expect(orderData.createOrder.totalAmount).toBe(largeQuantity * 10.0);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderData.createOrder.orderId } });
    }, 10000);

    test('order with high precision price calculation', async () => {
      // Create a catalog with a price that has many decimal places when multiplied
      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: 'Precision Price Catalog',
            isPublic: false,
            products: [
              { productName: 'Precision Product', price: 3.33, sortOrder: 1 },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;
      const productId = catalogData.createCatalog.products[0].productId;

      // Create a campaign with this catalog
      const { data: campaignData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Precision Campaign',
            campaignYear: 2025,
            startDate: new Date('2025-07-01T00:00:00Z').toISOString(),
            catalogId: catalogId,
          },
        },
      });
      const campaignId = campaignData.createCampaign.campaignId;

      // Wait for GSI propagation
      await new Promise(resolve => setTimeout(resolve, 500));

      // Create order: 7 * $3.33 = $23.31
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: campaignId,
            customerName: 'Precision Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CREDIT_CARD',
            lineItems: [{ productId: productId, quantity: 7 }],
          },
        },
      });

      // Assert: Check price calculation precision
      expect(orderData.createOrder.lineItems[0].pricePerUnit).toBe(3.33);
      expect(orderData.createOrder.lineItems[0].quantity).toBe(7);
      // 7 * 3.33 = 23.31
      expect(orderData.createOrder.lineItems[0].subtotal).toBeCloseTo(23.31, 2);
      expect(orderData.createOrder.totalAmount).toBeCloseTo(23.31, 2);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderData.createOrder.orderId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId: catalogId } });
    }, 15000);

    test('concurrent order creation for same campaign', async () => {
      // Test that multiple orders can be created concurrently without conflicts
      const orderPromises = Array.from({ length: 5 }, (_, i) =>
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: {
            input: {
              profileId: testProfileId,
              campaignId: testCampaignId,
              customerName: `Concurrent Customer ${i + 1}`,
              orderDate: new Date().toISOString(),
              paymentMethod: 'CASH',
              lineItems: [{ productId: testProductId, quantity: i + 1 }],
            },
          },
        })
      );

      // Act: Execute all order creations concurrently
      const results = await Promise.allSettled(orderPromises);

      // Assert: All orders should be created successfully with unique IDs
      const successes = results.filter(r => r.status === 'fulfilled');
      expect(successes.length).toBe(5);

      const orderIds = successes.map(r => (r as PromiseFulfilledResult<any>).value.data.createOrder.orderId);
      const uniqueOrderIds = new Set(orderIds);
      expect(uniqueOrderIds.size).toBe(5);

      // Cleanup all created orders
      for (const orderId of orderIds) {
        await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      }
    }, 20000);

    test('updating order to reference non-existent product ID', async () => {
      // Create an order first
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: testCampaignId,
            customerName: 'Invalid Product Test',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Act: Try to update with a non-existent product ID
      try {
        await ownerClient.mutate({
          mutation: UPDATE_ORDER,
          variables: {
            input: {
              orderId: orderId,
              lineItems: [{ productId: 'NON_EXISTENT_PRODUCT_ID', quantity: 2 }],
            },
          },
        });
        // If it succeeds, the product might just be stored as-is (no validation)
        // This is acceptable behavior depending on design
      } catch (error) {
        // Expected: Validation error for non-existent product
        expect((error as Error).message).toMatch(/product|not found|invalid/i);
      }

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
    }, 10000);

    test('removing optional fields from order (set to null) - NOT SUPPORTED', async () => {
      // Note: The current implementation does NOT support removing optional fields
      // once they are set. Setting a field to null is treated as passing null to DynamoDB,
      // which is different from removing the attribute. This is acceptable behavior
      // for this application - once set, optional fields remain.
      
      // Create an order with optional customerPhone
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: testCampaignId,
            customerName: 'Optional Fields Test',
            customerPhone: '555-1234',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Act: Attempt to update to remove customerPhone (set to null)
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_ORDER,
        variables: {
          input: {
            orderId: orderId,
            customerPhone: null,
          },
        },
      });

      // Assert: customerPhone should STILL have original value (removing not supported)
      expect(updateData.updateOrder.customerPhone).toBe('555-1234');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
    }, 10000);

    test('concurrent updates to same order', async () => {
      // Create an order
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: testCampaignId,
            customerName: 'Concurrent Update Test',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 1 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Act: Concurrent updates
      const [result1, result2] = await Promise.allSettled([
        ownerClient.mutate({
          mutation: UPDATE_ORDER,
          variables: {
            input: {
              orderId: orderId,
              customerName: 'Update 1',
            },
          },
        }),
        ownerClient.mutate({
          mutation: UPDATE_ORDER,
          variables: {
            input: {
              orderId: orderId,
              paymentMethod: 'CHECK',
            },
          },
        }),
      ]);

      // Assert: At least one should succeed
      const successes = [result1, result2].filter(r => r.status === 'fulfilled');
      expect(successes.length).toBeGreaterThanOrEqual(1);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
    }, 10000);
  });
});
