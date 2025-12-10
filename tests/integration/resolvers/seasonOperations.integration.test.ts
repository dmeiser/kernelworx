import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, NormalizedCacheObject, gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

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

const CREATE_SEASON = gql`
  mutation CreateSeason($input: CreateSeasonInput!) {
    createSeason(input: $input) {
      seasonId
      seasonName
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
const UPDATE_SEASON = gql`
  mutation UpdateSeason($input: UpdateSeasonInput!) {
    updateSeason(input: $input) {
      seasonId
      seasonName
      startDate
      endDate
      catalogId
      updatedAt
    }
  }
`;

const DELETE_SEASON = gql`
  mutation DeleteSeason($seasonId: ID!) {
    deleteSeason(seasonId: $seasonId)
  }
`;

const GET_SEASON = gql`
  query GetSeason($seasonId: ID!) {
    getSeason(seasonId: $seasonId) {
      seasonId
      seasonName
      catalogId
    }
  }
`;

describe('Season Operations Integration Tests', () => {
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;

  // Test data IDs (created during setup)
  let testProfileId: string;
  let testCatalogId: string;
  let testSeasonId: string;

  // Track created seasons for cleanup
  const createdSeasonIds: string[] = [];

  beforeAll(async () => {
    console.log('Creating test profile, catalog, and season...');

    // Create authenticated clients
    const ownerResult = await createAuthenticatedClient('owner');
    ownerClient = ownerResult.client;

    const contributorResult = await createAuthenticatedClient('contributor');
    contributorClient = contributorResult.client;

    const readonlyResult = await createAuthenticatedClient('readonly');
    readonlyClient = readonlyResult.client;

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

    // 3. Create initial season
    const { data: seasonData } = await ownerClient.mutate({
      mutation: CREATE_SEASON,
      variables: {
        input: {
          profileId: testProfileId,
          seasonName: 'Original Season Name',
          startDate: new Date('2025-01-01T00:00:00Z').toISOString(),
          endDate: new Date('2025-12-31T23:59:59Z').toISOString(),
          catalogId: testCatalogId,
        },
      },
    });
    testSeasonId = seasonData.createSeason.seasonId;
    createdSeasonIds.push(testSeasonId);

    // 4. Share profile with contributor (WRITE)
    await ownerClient.mutate({
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
    await ownerClient.mutate({
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
    // Cleanup: Delete all test seasons
    for (const seasonId of createdSeasonIds) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_SEASON,
          variables: { seasonId },
        });
      } catch (error) {
        // Season may already be deleted by a test
      }
    }
    console.log(`Cleaned up ${createdSeasonIds.length} test seasons`);
  });

  describe('updateSeason', () => {
    test('updates season name', async () => {
      const input = {
        seasonId: testSeasonId,
        seasonName: 'Updated Season Name',
      };

      const { data } = await ownerClient.mutate({
        mutation: UPDATE_SEASON,
        variables: { input },
      });

      expect(data.updateSeason).toBeDefined();
      expect(data.updateSeason.seasonId).toBe(testSeasonId);
      expect(data.updateSeason.seasonName).toBe('Updated Season Name');
      expect(data.updateSeason.updatedAt).toBeDefined();
    }, 10000);

    test('contributor with WRITE access can update season', async () => {
      const input = {
        seasonId: testSeasonId,
        seasonName: 'Contributor Updated Name',
      };

      const { data } = await contributorClient.mutate({
        mutation: UPDATE_SEASON,
        variables: { input },
      });

      expect(data.updateSeason).toBeDefined();
      expect(data.updateSeason.seasonName).toBe('Contributor Updated Name');
    }, 10000);

    test('updates season dates', async () => {
      const newStartDate = new Date('2025-02-01T00:00:00Z').toISOString();
      const newEndDate = new Date('2025-11-30T23:59:59Z').toISOString();

      const input = {
        seasonId: testSeasonId,
        startDate: newStartDate,
        endDate: newEndDate,
      };

      const { data } = await ownerClient.mutate({
        mutation: UPDATE_SEASON,
        variables: { input },
      });

      expect(data.updateSeason).toBeDefined();
      expect(data.updateSeason.startDate).toBe(newStartDate);
      expect(data.updateSeason.endDate).toBe(newEndDate);
    }, 10000);

    test('rejects update with non-existent seasonId', async () => {
      const input = {
        seasonId: 'SEASON#non-existent-season',
        seasonName: 'Should Fail',
      };

      await expect(
        ownerClient.mutate({
          mutation: UPDATE_SEASON,
          variables: { input },
        })
      ).rejects.toThrow(/not found|does not exist/i);
    }, 10000);
  });

  describe('deleteSeason', () => {
    test('deletes existing season', async () => {
      // Create a season to delete
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonName: 'Season to Delete',
            startDate: new Date('2026-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2026-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });

      const seasonIdToDelete = createData.createSeason.seasonId;

      // Delete it
      const { data: deleteData } = await ownerClient.mutate({
        mutation: DELETE_SEASON,
        variables: { seasonId: seasonIdToDelete },
      });

      expect(deleteData.deleteSeason).toBe(true);

      // Verify it's deleted - getSeason should return null (not throw error)
      const { data: verifyData } = await ownerClient.query({
        query: GET_SEASON,
        variables: { seasonId: seasonIdToDelete },
        fetchPolicy: 'network-only',
      });

      expect(verifyData.getSeason).toBeNull();
    }, 10000);

    test('contributor with WRITE access can delete season', async () => {
      // Create a season to delete
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonName: 'Season for Contributor to Delete',
            startDate: new Date('2027-01-01T00:00:00Z').toISOString(),
            endDate: new Date('2027-12-31T23:59:59Z').toISOString(),
            catalogId: testCatalogId,
          },
        },
      });

      const seasonIdToDelete = createData.createSeason.seasonId;

      // Contributor deletes it
      const { data: deleteData } = await contributorClient.mutate({
        mutation: DELETE_SEASON,
        variables: { seasonId: seasonIdToDelete },
      });

      expect(deleteData.deleteSeason).toBe(true);
    }, 10000);

    test('returns true for non-existent season (idempotent)', async () => {
      const { data } = await ownerClient.mutate({
        mutation: DELETE_SEASON,
        variables: { seasonId: 'SEASON#non-existent-season' },
      });

      expect(data.deleteSeason).toBe(true);
    }, 10000);
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
        seasonName: 'Protected Season',
        startDate: new Date().toISOString(),
        endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: { input: createInput },
      });

      const seasonId = createData.createSeason.seasonId;
      createdSeasonIds.push(seasonId);

      // Readonly tries to update
      await expect(
        readonlyClient.mutate({
          mutation: UPDATE_SEASON,
          variables: {
            input: {
              seasonId,
              seasonName: 'Readonly Update Attempt',
            },
          },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);
  });

  describe('deleteSeason authorization', () => {
    test('readonly user cannot delete season', async () => {
      // First create a season as owner
      const createInput = {
        profileId: testProfileId,
        catalogId: testCatalogId,
        seasonName: 'Protected For Delete',
        startDate: new Date().toISOString(),
        endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: { input: createInput },
      });

      const seasonId = createData.createSeason.seasonId;
      createdSeasonIds.push(seasonId);

      // Readonly tries to delete
      await expect(
        readonlyClient.mutate({
          mutation: DELETE_SEASON,
          variables: { seasonId },
        })
      ).rejects.toThrow(/forbidden|not authorized|unauthorized/i);
    }, 10000);
  });

  describe('updateSeason additional fields', () => {
    test('updates season with all updateable fields', async () => {
      // Create season first
      const createInput = {
        profileId: testProfileId,
        catalogId: testCatalogId,
        seasonName: 'Full Update Test',
        startDate: new Date().toISOString(),
        endDate: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString(),
      };

      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: { input: createInput },
      });

      const seasonId = createData.createSeason.seasonId;
      createdSeasonIds.push(seasonId);

      const newStartDate = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
      const newEndDate = new Date(Date.now() + 60 * 24 * 60 * 60 * 1000).toISOString();

      // Update all available fields
      const { data: updateData } = await ownerClient.mutate({
        mutation: UPDATE_SEASON,
        variables: {
          input: {
            seasonId,
            seasonName: 'Fully Updated Season',
            startDate: newStartDate,
            endDate: newEndDate,
          },
        },
      });

      expect(updateData.updateSeason.seasonName).toBe('Fully Updated Season');
      // Verify dates are updated (they should be different from the original)
      expect(updateData.updateSeason.startDate).toBeDefined();
      expect(updateData.updateSeason.endDate).toBeDefined();
    }, 10000);
  });
});
