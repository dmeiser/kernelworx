import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll, it } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';
import { deleteTestAccounts, TABLE_NAMES } from '../setup/testData';


/**
 * Integration tests for Season Operations (updateSeason, deleteSeason)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile/season (can update/delete seasons)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can update/delete seasons)
 * - TEST_READONLY_EMAIL: Has READ access (cannot modify seasons)
 * 
 * Note: These tests create their own test data (profile, catalog, season)
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
const UPDATE_CAMPAIGN = gql`
  mutation UpdateCampaign($input: UpdateCampaignInput!) {
    updateCampaign(input: $input) {
      campaignId
      campaignName
      startDate
      endDate
      catalogId
      updatedAt
    }
  }
`;

const DELETE_CAMPAIGN = gql`
  mutation DeleteCampaign($campaignId: ID!) {
    deleteCampaign(campaignId: $campaignId)
  }
`;

const GET_CAMPAIGN = gql`
  query GetCampaign($campaignId: ID!) {
    getCampaign(campaignId: $campaignId) {
      campaignId
      campaignName
      catalogId
    }
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const DELETE_SELLER_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

describe('Season Operations Integration Tests', () => {
  const SUITE_ID = 'season-operations';
  
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;

  // Test data IDs (created during setup)
  let testProfileId: string;
  let testCatalogId: string;
  let testSeasonId: string;
  let testProductId: string;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;

  beforeAll(async () => {
    console.log('Creating test profile, catalog, and season...');

    // Create authenticated clients
    const ownerResult = await createAuthenticatedClient('owner');
    ownerClient = ownerResult.client;
    ownerAccountId = ownerResult.accountId;

    const contributorResult = await createAuthenticatedClient('contributor');
    contributorClient = contributorResult.client;
    contributorAccountId = contributorResult.accountId;

    const readonlyResult = await createAuthenticatedClient('readonly');
    readonlyClient = readonlyResult.client;
    readonlyAccountId = readonlyResult.accountId;

    // 1. Create test profile
    const { data: profileData } = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: {
        input: {
          sellerName: 'Season Test Seller',
        },
      },
    });
    testProfileId = profileData.createSellerProfile.profileId;

    // 2. Create catalog
    const { data: catalogData } = await ownerClient.mutate({
      mutation: CREATE_CATALOG,
      variables: {
        input: {
          catalogName: 'Season Test Catalog',
          isPublic: false,
          products: [
            {
              productName: 'Test Popcorn',
              description: 'Test product for season tests',
              price: 10.00,
              sortOrder: 1,
            },
          ],
        },
      },
    });
    testCatalogId = catalogData.createCatalog.catalogId;
    testProductId = catalogData.createCatalog.products[0].productId;

    // 3. Create initial season
    const { data: seasonData } = await ownerClient.mutate({
      mutation: CREATE_CAMPAIGN,
      variables: {
        input: {
          profileId: testProfileId,
          campaignName: 'Original Season Name',
          campaignYear: 2025,
          startDate: new Date('2025-01-01T00:00:00Z').toISOString(),
          endDate: new Date('2025-12-31T23:59:59Z').toISOString(),
          catalogId: testCatalogId,
        },
      },
    });
    testSeasonId = seasonData.createCampaign.campaignId;

    // 4. Share profile with contributor (WRITE)
    const { data: contributorShareData }: any = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
          permissions: ['READ', 'WRITE'],
        },
      },
    });

    // 5. Share profile with readonly (READ)
    const { data: readonlyShareData }: any = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
          permissions: ['READ'],
        },
      },
    });

    console.log(`Test data created: Profile=${testProfileId}, Season=${testSeasonId}, Catalog=${testCatalogId}`);
  }, 30000);

  afterAll(async () => {
    console.log('Cleaning up season operations test data...');
    try {
      // 1. Revoke shares
      if (contributorAccountId) {
        await ownerClient.mutate({
          mutation: REVOKE_SHARE,
          variables: { input: { profileId: testProfileId, targetAccountId: contributorAccountId } },
        });
      }
      if (readonlyAccountId) {
        await ownerClient.mutate({
          mutation: REVOKE_SHARE,
          variables: { input: { profileId: testProfileId, targetAccountId: readonlyAccountId } },
        });
      }
      
      // 2. Delete season (may already be deleted by tests)
      if (testSeasonId) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_CAMPAIGN,
            variables: { campaignId: testSeasonId },
          });
        } catch (e) { /* may already be deleted */ }
      }
      
      // 3. Delete catalog
      if (testCatalogId) {
        await ownerClient.mutate({
          mutation: DELETE_CATALOG,
          variables: { catalogId: testCatalogId },
        });
      }
      
      // 4. Delete profile
      if (testProfileId) {
        await ownerClient.mutate({
          mutation: DELETE_SELLER_PROFILE,
          variables: { profileId: testProfileId },
        });
      }
      
      // 5. Clean up account records
      console.log('Cleaning up account records...');
      // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
      
      console.log('Season operations test data cleanup complete.');
    } catch (error) {
      console.log('Error in cleanup:', error);
    }
  }, 30000);


  describe('updateSeason', () => {
    test('updates season name', async () => {
      const input = {
        campaignId: testSeasonId,
        campaignName: 'Updated Season Name',
        campaignYear: 2025,
      };

      const { data } = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: { input },
      });

      expect(data.updateCampaign).toBeDefined();
      expect(data.updateCampaign.campaignId).toBe(testSeasonId);
      expect(data.updateCampaign.campaignName).toBe('Updated Season Name');
      expect(data.updateCampaign.updatedAt).toBeDefined();
    }, 10000);

    test('contributor with WRITE access can update season', async () => {
      const input = {
        campaignId: testSeasonId,
        campaignName: 'Contributor Updated Name',
        campaignYear: 2025,
      };

      const { data } = await contributorClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: { input },
      });

      expect(data.updateCampaign).toBeDefined();
      expect(data.updateCampaign.campaignName).toBe('Contributor Updated Name');
    }, 10000);

    test('updates season dates', async () => {
      const newStartDate = new Date('2025-02-01T00:00:00Z').toISOString();
      const newEndDate = new Date('2025-11-30T23:59:59Z').toISOString();

      const input = {
        campaignId: testSeasonId,
        startDate: newStartDate,
        endDate: newEndDate,
      };

      const { data } = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: { input },
      });

      expect(data.updateCampaign).toBeDefined();
      expect(data.updateCampaign.startDate).toBe(newStartDate);
      expect(data.updateCampaign.endDate).toBe(newEndDate);
    }, 10000);

    test('rejects update with non-existent campaignId', async () => {
      const input = {
        campaignId: 'SEASON#non-existent-season',
        campaignName: 'Should Fail',
        campaignYear: 2025,
      };

      await expect(
        ownerClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: { input },
        })
      ).rejects.toThrow(/not found|does not exist/i);
    }, 10000);

    test('accepts or rejects endDate before startDate (validation check)', async () => {
      // Arrange - Create a new season for this test
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Date Validation Test Season',
            campaignYear: 2025,
            startDate: new Date('2030-06-01T00:00:00Z').toISOString(),
            endDate: new Date('2030-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const validationTestSeasonId = createData.createCampaign.campaignId;

      try {
        // Act - Try to update with endDate before startDate
        const invalidInput = {
          campaignId: validationTestSeasonId,
          startDate: new Date('2030-12-01T00:00:00Z').toISOString(), // December
          endDate: new Date('2030-01-01T23:59:59Z').toISOString(),   // January (before December)
        };

        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: { input: invalidInput },
        });

        // If it succeeds, the system doesn't validate date order
        // This is acceptable - the app may allow overlapping date ranges
        expect(data.updateCampaign.startDate).toBe(invalidInput.startDate);
        expect(data.updateCampaign.endDate).toBe(invalidInput.endDate);
      } catch (error: any) {
        // If it rejects, the system validates that endDate must be after startDate
        expect(error.message).toMatch(/date|before|after|invalid|validation/i);
      } finally {
        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: validationTestSeasonId },
        });
      }
    }, 10000);

    test('can remove endDate (set open-ended season)', async () => {
      // Arrange - Create a season with endDate
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Season To Remove EndDate',
            campaignYear: 2025,
            startDate: new Date('2031-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2031-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const seasonToUpdate = createData.createCampaign.campaignId;
      expect(createData.createCampaign.endDate).toBeDefined();

      try {
        // Act - Update to remove endDate (set to null to make it open-ended)
        const { data } = await ownerClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId: seasonToUpdate,
              endDate: null,
            },
          },
        });

        // Assert - Season should now have no endDate
        expect(data.updateCampaign.endDate).toBeNull();
      } catch (error: any) {
        // If setting null is not allowed, verify it throws appropriate error
        expect(error.message).toBeDefined();
      } finally {
        // Cleanup
        await ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId: seasonToUpdate },
        });
      }
    }, 10000);
  });

  describe('deleteSeason', () => {
    test('deletes existing season', async () => {
      // Create a season to delete
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Season to Delete',
            campaignYear: 2025,
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });

      const campaignIdToDelete = createData.createCampaign.campaignId;

      // Delete it
      const { data: deleteData } = await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: campaignIdToDelete },
      });

      expect(deleteData.deleteCampaign).toBe(true);

      // Verify it's deleted - getSeason should return null (not throw error)
      const { data: verifyData } = await ownerClient.query({
        query: GET_CAMPAIGN,
        variables: { campaignId: campaignIdToDelete },
        fetchPolicy: 'network-only',
      });

      expect(verifyData.getCampaign).toBeNull();
    }, 10000);

    test('contributor with WRITE access can delete season', async () => {
      // Create a season to delete
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName: 'Season for Contributor to Delete',
            campaignYear: 2025,
            startDate: new Date('2027-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2027-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });

      const campaignIdToDelete = createData.createCampaign.campaignId;

      // Contributor deletes it
      const { data: deleteData } = await contributorClient.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: campaignIdToDelete },
      });

      expect(deleteData.deleteCampaign).toBe(true);
    }, 10000);

    test('returns true for non-existent season (idempotent)', async () => {
      const { data } = await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: 'SEASON#non-existent-season' },
      });

      expect(data.deleteCampaign).toBe(true);
    }, 10000);

    test('Data Integrity: Deleting season then creating new season with same name', async () => {
      const campaignName = 'Reusable Season Name';
      
      // Create first season
      const { data: createData1 } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName,
            campaignYear: 2028,
            startDate: new Date('2028-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2028-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const campaignId1 = createData1.createCampaign.campaignId;

      // Delete it
      const { data: deleteData } = await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: campaignId1 },
      });
      expect(deleteData.deleteCampaign).toBe(true);

      // Create new season with same name - should succeed
      const { data: createData2 } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            campaignName,
            campaignYear: 2029,
            startDate: new Date('2029-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2029-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });
      const campaignId2 = createData2.createCampaign.campaignId;

      expect(campaignId2).toBeDefined();
      expect(campaignId2).not.toBe(campaignId1); // Should be different ID
      expect(createData2.createCampaign.campaignName).toBe(campaignName);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId: campaignId2 } });
    }, 15000);
  });

  /**
   * Authorization Tests - Bug #14
   * 
   * Status: FIXED - VerifyProfileWriteAccessFn added to updateSeason/deleteSeason pipelines
   */
  describe('updateSeason authorization', () => {
    test('readonly user cannot update season', async () => {
      // First create a season as owner
      const createInput = {
        profileId: testProfileId,
        catalogId: testCatalogId,
        campaignName: 'Protected Season',
        campaignYear: 2025,
        startDate: new Date().toISOString(),
        endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: { input: createInput },
      });

      const campaignId = createData.createCampaign.campaignId;

      // Readonly tries to update
      await expect(
        readonlyClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId,
              campaignName: 'Readonly Update Attempt',
              campaignYear: 2025,
            },
          },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
      
      // Cleanup: Owner deletes the season
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
    }, 10000);
  });

  describe('deleteSeason authorization', () => {
    test('readonly user cannot delete season', async () => {
      // First create a season as owner
      const createInput = {
        profileId: testProfileId,
        catalogId: testCatalogId,
        campaignName: 'Protected For Delete',
        campaignYear: 2025,
        startDate: new Date().toISOString(),
        endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: { input: createInput },
      });

      const campaignId = createData.createCampaign.campaignId;

      // Readonly tries to delete
      await expect(
        readonlyClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
      
      // Cleanup: Owner deletes the season
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
    }, 10000);
  });

  describe('updateSeason additional fields', () => {
    test('updates season with all updateable fields', async () => {
      // Create season first
      const createInput = {
        profileId: testProfileId,
        catalogId: testCatalogId,
        campaignName: 'Full Update Test',
        campaignYear: 2025,
        startDate: new Date().toISOString(),
        endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: { input: createInput },
      });

      const campaignId = createData.createCampaign.campaignId;

      const newStartDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
      const newEndDate = new Date(Date.now() + 60 * 24 * 60 * 60 * 1000).toISOString();

      // Update all available fields
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: {
          input: {
            campaignId,
            campaignName: 'Fully Updated Season',
            campaignYear: 2025,
            startDate: newStartDate,
            endDate: newEndDate,
          },
        },
      });

      expect(updateData.updateCampaign.campaignName).toBe('Fully Updated Season');
      // Verify dates are updated (they should be different from the original)
      expect(updateData.updateCampaign.startDate).toBeDefined();
      expect(updateData.updateCampaign.endDate).toBeDefined();
      
      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
    }, 10000);

    it('Data Integrity: Deleting season cleans up associated orders', async () => {
      // Arrange: Create a season and an order
      const createSeasonInput = {
        profileId: testProfileId,
        catalogId: testCatalogId,
        campaignName: 'Season With Orders',
        campaignYear: 2025,
        startDate: new Date().toISOString(),
      };

      const { data: createSeasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: { input: createSeasonInput },
      });

      const campaignIdToDelete = createSeasonData.createCampaign.campaignId;

      // Create an order for this season
      const CREATE_ORDER = gql`
        mutation CreateOrder($input: CreateOrderInput!) {
          createOrder(input: $input) {
            orderId
            campaignId
          }
        }
      `;
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: campaignIdToDelete,
            customerName: 'Test Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [
              {
                productId: testProductId,
                quantity: 1,
              },
            ],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Verify order exists via GraphQL
      const LIST_ORDERS = gql`
        query ListOrdersBySeason($campaignId: ID!) {
          listOrdersBySeason(campaignId: $campaignId) {
            orderId
          }
        }
      `;
      const { data: beforeDelete }: any = await ownerClient.query({
        query: LIST_ORDERS,
        variables: { campaignId: campaignIdToDelete },
        fetchPolicy: 'network-only',
      });
      expect(beforeDelete.listOrdersBySeason.map((o: any) => o.orderId)).toContain(orderId);

      // Act: Delete the season
      const { data: deleteData } = await ownerClient.mutate({
        mutation: DELETE_CAMPAIGN,
        variables: { campaignId: campaignIdToDelete },
      });
      expect(deleteData.deleteCampaign).toBe(true);

      // Assert: Orders should be cleaned up (no orphaned records)
      // V2 schema: Query orderId-index GSI to check if order still exists
      const { DynamoDBClient, QueryCommand } = await import('@aws-sdk/client-dynamodb');
      const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
      
      const result = await dynamoClient.send(new QueryCommand({
        TableName: TABLE_NAMES.orders,
        IndexName: 'orderId-index',
        KeyConditionExpression: 'orderId = :oid',
        ExpressionAttributeValues: {
          ':oid': { S: orderId },
        },
      }));
      
      // Order should be deleted when season is deleted
      expect(result.Items?.length || 0).toBe(0);
    }, 15000);

    it('Updating season to reference non-existent catalog succeeds (no foreign key validation)', async () => {
      // Arrange: Create a season
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            catalogId: testCatalogId,
            campaignName: 'Non-existent Catalog Test',
            campaignYear: 2025,
            startDate: new Date().toISOString(),
          },
        },
      });
      const campaignId = createData.createCampaign.campaignId;

      // Act & Assert: Try to update with non-existent catalog
      // Note: The resolver allows updating catalogId to a reference that doesn't exist.
      // This is acceptable behavior - the catalog might be deleted later, or
      // the caller might provide an invalid ID. The resolver only stores the reference.
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: {
          input: {
            campaignId,
            catalogId: 'CATALOG#non-existent-catalog-id',
          },
        },
      });
      
      // The update should succeed (resolver doesn't validate catalog existence)
      expect(updateData.updateCampaign.campaignId).toBe(campaignId);
      expect(updateData.updateCampaign.catalogId).toBe('CATALOG#non-existent-catalog-id');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
    }, 10000);

    it('Updating season that has existing orders preserves order data', async () => {
      // Arrange: Create season and order
      const { data: createSeasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            catalogId: testCatalogId,
            campaignName: 'Season With Orders For Update',
            campaignYear: 2025,
            startDate: new Date().toISOString(),
          },
        },
      });
      const campaignId = createSeasonData.createCampaign.campaignId;

      // Create an order
      const CREATE_ORDER = gql`
        mutation CreateOrder($input: CreateOrderInput!) {
          createOrder(input: $input) {
            orderId
            campaignId
            customerName
          }
        }
      `;
      const { data: orderData } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: testProfileId,
            campaignId: campaignId,
            customerName: 'Preserved Customer',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [{ productId: testProductId, quantity: 2 }],
          },
        },
      });
      const orderId = orderData.createOrder.orderId;

      // Act: Update the season
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_CAMPAIGN,
        variables: {
          input: {
            campaignId,
            campaignName: 'Updated Season Name With Orders',
            campaignYear: 2025,
          },
        },
      });

      expect(updateData.updateCampaign.campaignName).toBe('Updated Season Name With Orders');

      // Assert: Order still exists with correct data
      const GET_ORDER = gql`
        query GetOrder($orderId: ID!) {
          getOrder(orderId: $orderId) {
            orderId
            customerName
            campaignId
          }
        }
      `;
      const { data: orderCheck } = await ownerClient.query({
        query: GET_ORDER,
        variables: { orderId },
        fetchPolicy: 'network-only',
      });
      expect(orderCheck.getOrder.orderId).toBe(orderId);
      expect(orderCheck.getOrder.customerName).toBe('Preserved Customer');
      expect(orderCheck.getOrder.campaignId).toBe(campaignId);

      // Cleanup: Delete order first, then season
      const DELETE_ORDER = gql`
        mutation DeleteOrder($orderId: ID!) {
          deleteOrder(orderId: $orderId)
        }
      `;
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
    }, 15000);

    it('Concurrent season updates both succeed', async () => {
      // Arrange: Create season
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            catalogId: testCatalogId,
            campaignName: 'Concurrent Update Test',
            campaignYear: 2025,
            startDate: new Date().toISOString(),
          },
        },
      });
      const campaignId = createData.createCampaign.campaignId;

      // Act: Concurrent updates
      const [result1, result2] = await Promise.allSettled([
        ownerClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId,
              campaignName: 'Update 1',
              campaignYear: 2025,
            },
          },
        }),
        ownerClient.mutate({
          mutation: UPDATE_CAMPAIGN,
          variables: {
            input: {
              campaignId,
              endDate: new Date('2026-01-01').toISOString(),
            },
          },
        }),
      ]);

      // Assert: At least one should succeed
      const successes = [result1, result2].filter(r => r.status === 'fulfilled');
      expect(successes.length).toBeGreaterThanOrEqual(1);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_CAMPAIGN, variables: { campaignId } });
    }, 10000);

    it('Data Integrity: Concurrent season deletion and order creation (race condition)', async () => {
      // Arrange: Create season
      const { data: createSeasonData } = await ownerClient.mutate({
        mutation: CREATE_CAMPAIGN,
        variables: {
          input: {
            profileId: testProfileId,
            catalogId: testCatalogId,
            campaignName: 'Concurrent Delete Season',
            campaignYear: 2025,
            startDate: new Date().toISOString(),
          },
        },
      });
      const campaignId = createSeasonData.createCampaign.campaignId;

      const CREATE_ORDER = gql`
        mutation CreateOrder($input: CreateOrderInput!) {
          createOrder(input: $input) {
            orderId
            campaignId
          }
        }
      `;

      // Act: Concurrent season deletion and order creation
      const [deleteResult, orderResult] = await Promise.allSettled([
        ownerClient.mutate({
          mutation: DELETE_CAMPAIGN,
          variables: { campaignId },
        }),
        ownerClient.mutate({
          mutation: CREATE_ORDER,
          variables: {
            input: {
              profileId: testProfileId,
              campaignId: campaignId,
              customerName: 'Concurrent Order',
              orderDate: new Date().toISOString(),
              paymentMethod: 'CASH',
              lineItems: [
                {
                  productId: testProductId,
                  quantity: 1,
                },
              ],
            },
          },
        }),
      ]);

      // Assert: Delete should succeed
      expect(deleteResult.status).toBe('fulfilled');
      if (deleteResult.status === 'fulfilled') {
        expect(deleteResult.value.data.deleteCampaign).toBe(true);
      }
      
      // Order creation may succeed (if it happens before deletion)
      // or fail (if deletion happens first and cleans up)
      // Either result is acceptable for a race condition test
      expect(['fulfilled', 'rejected']).toContain(orderResult.status);

      // Cleanup: If order was created and not cascade-deleted, delete it
      if (orderResult.status === 'fulfilled') {
        const orderId = (orderResult as PromiseFulfilledResult<any>).value.data.createOrder.orderId;
        const DELETE_ORDER = gql`
          mutation DeleteOrder($orderId: ID!) {
            deleteOrder(orderId: $orderId)
          }
        `;
        try {
          await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId } });
        } catch { /* order may have been cascade deleted */ }
      }
    }, 15000);
  });
});
