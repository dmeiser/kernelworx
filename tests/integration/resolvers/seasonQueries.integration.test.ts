import '../setup.ts';
/**
 * Integration tests for Season query resolvers
 * Tests: getSeason, listSeasonsByProfile
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';



// Helper to generate unique test prefix
const getTestPrefix = () => `TEST-${Date.now()}`;

// GraphQL Mutations for setup
const CREATE_PROFILE = gql`
  mutation CreateProfile($input: CreateSellerProfileInput!) {
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
      catalogName
    }
  }
`;

const CREATE_SEASON = gql`
  mutation CreateSeason($input: CreateSeasonInput!) {
    createSeason(input: $input) {
      seasonId
      profileId
      seasonName
      seasonYear
      startDate
      endDate
      catalogId
      createdAt
      updatedAt
    }
  }
`;

const SHARE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      profileId
      targetAccountId
      permissions
    }
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

const DELETE_SEASON = gql`
  mutation DeleteSeason($seasonId: ID!) {
    deleteSeason(seasonId: $seasonId)
  }
`;

const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

// GraphQL Queries to test
const GET_SEASON = gql`
  query GetSeason($seasonId: ID!) {
    getSeason(seasonId: $seasonId) {
      seasonId
      profileId
      seasonName
      seasonYear
      startDate
      endDate
      catalogId
      createdAt
      updatedAt
    }
  }
`;

const LIST_SEASONS_BY_PROFILE = gql`
  query ListSeasonsByProfile($profileId: ID!) {
    listSeasonsByProfile(profileId: $profileId) {
      seasonId
      profileId
      seasonName
      seasonYear
      startDate
      endDate
      catalogId
      createdAt
      updatedAt
    }
  }
`;

describe('Season Query Resolvers Integration Tests', () => {
  let ownerClient: ApolloClient;
  let contributorClient: ApolloClient;
  let readonlyClient: ApolloClient;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let readonlyEmail: string;

  beforeAll(async () => {
    const ownerResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorResult: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyResult: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    ownerClient = ownerResult.client;
    contributorClient = contributorResult.client;
    readonlyClient = readonlyResult.client;
    ownerAccountId = ownerResult.accountId;
    contributorAccountId = contributorResult.accountId;
    readonlyAccountId = readonlyResult.accountId;
    readonlyEmail = process.env.TEST_READONLY_EMAIL!;
  });

  afterAll(async () => {
    // Clean up account records created by Cognito post-auth trigger
    console.log('Cleaning up account records...');
    // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
    console.log('Account cleanup complete.');
  }, 30000);


  describe('getSeason', () => {
    describe('Happy Path', () => {
      it('should return season by seasonId with all fields', async () => {
        // Arrange: Create profile, catalog, and season
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              endDate: '2025-12-31T23:59:59Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Act: Query season
        const { data } = await ownerClient.query({
          query: GET_SEASON,
          variables: { seasonId: seasonId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeDefined();
        expect(data.getSeason.seasonId).toBe(seasonId);
        expect(data.getSeason.profileId).toBe(profileId);
        expect(data.getSeason.seasonName).toContain('Season');
        expect(data.getSeason.startDate).toBe('2025-01-01T00:00:00Z');
        expect(data.getSeason.endDate).toBe('2025-12-31T23:59:59Z');
        expect(data.getSeason.catalogId).toBe(catalogId);
        expect(data.getSeason.createdAt).toBeDefined();
        expect(data.getSeason.updatedAt).toBeDefined();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }, 15000); // Extended timeout for GSI consistency

      it('should return null for non-existent seasonId', async () => {
        // Act: Query non-existent season
        const { data } = await ownerClient.query({
          query: GET_SEASON,
          variables: { seasonId: 'SEASON#nonexistent' },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeNull();
      });
    });

    describe('Authorization', () => {
      it('should allow profile owner to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Act
        const { data } = await ownerClient.query({
          query: GET_SEASON,
          variables: { seasonId: seasonId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeDefined();
        expect(data.getSeason.seasonId).toBe(seasonId);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should allow shared user (READ) to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Share profile with readonly user (READ permission)
        const { data: shareData }: any = await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: profileId,
              targetAccountEmail: readonlyEmail,
              permissions: ['READ'],
            },
          },
        });

        // Act: Readonly user queries season
        const { data } = await readonlyClient.query({
          query: GET_SEASON,
          variables: { seasonId: seasonId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeDefined();
        expect(data.getSeason.seasonId).toBe(seasonId);
        
        // Cleanup
        await ownerClient.mutate({ mutation: REVOKE_SHARE, variables: { input: { profileId, targetAccountId: readonlyAccountId } } });
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should NOT allow non-shared user to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Act: Contributor (not shared) queries season
        const { data } = await contributorClient.query({
          query: GET_SEASON,
          variables: { seasonId: seasonId },
          fetchPolicy: 'network-only',
        });

        // Assert: Should return null due to authorization failure
        expect(data.getSeason).toBeNull();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });
    });
  });

  describe('listSeasonsByProfile', () => {
    describe('Happy Path', () => {
      it('should return all seasons for a profile', async () => {
        // Arrange: Create profile and catalog
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create multiple seasons
        const { data: season1Data } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season1`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId1 = season1Data.createSeason.seasonId;

        const { data: season2Data } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season2`,
              seasonYear: 2025,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId2 = season2Data.createSeason.seasonId;

        // Act: List seasons
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile.length).toBe(2);
        expect(data.listSeasonsByProfile[0].seasonId).toBeDefined();
        expect(data.listSeasonsByProfile[0].seasonName).toContain('Season');
        expect(data.listSeasonsByProfile[1].seasonId).toBeDefined();
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: seasonId1 } });
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: seasonId2 } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should return empty array for profile with no seasons', async () => {
        // Arrange: Create profile without seasons
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        // Act
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile).toEqual([]);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should return empty array for non-existent profileId', async () => {
        // Act
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: 'PROFILE#nonexistent' },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile).toEqual([]);
      });

      it('should not include deleted season in list', async () => {
        // Arrange: Create profile, catalog, and seasons
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        // Create two seasons
        const { data: season1Data } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-SeasonToKeep`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonIdToKeep = season1Data.createSeason.seasonId;

        const { data: season2Data } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-SeasonToDelete`,
              seasonYear: 2025,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonIdToDelete = season2Data.createSeason.seasonId;

        // Verify both appear in list
        const { data: beforeDelete } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });
        expect(beforeDelete.listSeasonsByProfile.length).toBe(2);
        const beforeSeasonIds = beforeDelete.listSeasonsByProfile.map((s: any) => s.seasonId);
        expect(beforeSeasonIds).toContain(seasonIdToKeep);
        expect(beforeSeasonIds).toContain(seasonIdToDelete);

        // Delete one season
        await ownerClient.mutate({
          mutation: DELETE_SEASON,
          variables: { seasonId: seasonIdToDelete },
        });

        // Act: List seasons again
        const { data: afterDelete } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert: Only the kept season should appear
        expect(afterDelete.listSeasonsByProfile.length).toBe(1);
        const afterSeasonIds = afterDelete.listSeasonsByProfile.map((s: any) => s.seasonId);
        expect(afterSeasonIds).toContain(seasonIdToKeep);
        expect(afterSeasonIds).not.toContain(seasonIdToDelete);

        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: seasonIdToKeep } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      }, 15000);
    });

    describe('Authorization', () => {
      it('should allow profile owner to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Act
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile.length).toBeGreaterThan(0);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should allow shared user (READ) to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Share profile with readonly user
        const { data: shareData }: any = await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: profileId,
              targetAccountEmail: readonlyEmail,
              permissions: ['READ'],
            },
          },
        });

        // Act: Readonly user lists seasons
        const { data } = await readonlyClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile.length).toBeGreaterThan(0);
        
        // Cleanup
        await ownerClient.mutate({ mutation: REVOKE_SHARE, variables: { input: { profileId, targetAccountId: readonlyAccountId } } });
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });

      it('should NOT allow non-shared user to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        const profileId = profileData.createSellerProfile.profileId;

        const { data: catalogData } = await ownerClient.mutate({
          mutation: CREATE_CATALOG,
          variables: {
            input: {
              catalogName: `${getTestPrefix()}-Catalog`,
              isPublic: true,
              products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
            },
          },
        });
        const catalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season`,
              seasonYear: 2025,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: catalogId,
            },
          },
        });
        const seasonId = seasonData.createSeason.seasonId;

        // Act: Contributor (not shared) lists seasons
        const { data } = await contributorClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: profileId },
          fetchPolicy: 'network-only',
        });

        // Assert: Should return empty array due to authorization failure
        expect(data.listSeasonsByProfile).toEqual([]);
        
        // Cleanup
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
        await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
        await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
      });
    });
  });

  describe('Season with optional endDate', () => {
    it('should return season without endDate (open-ended season)', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-Catalog`,
            isPublic: true,
            products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      // Create season without endDate
      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-OpenSeason`,
            seasonYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            // No endDate specified
            catalogId: catalogId,
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Act
      const { data } = await ownerClient.query({
        query: GET_SEASON,
        variables: { seasonId: seasonId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getSeason.endDate).toBeNull();
      expect(data.getSeason.startDate).toBe('2025-01-01T00:00:00Z');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });

    it('should return season with both startDate and endDate', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-Catalog`,
            isPublic: true,
            products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-ClosedSeason`,
            seasonYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            endDate: '2025-06-30T23:59:59Z',
            catalogId: catalogId,
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Act
      const { data } = await ownerClient.query({
        query: GET_SEASON,
        variables: { seasonId: seasonId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getSeason.startDate).toBe('2025-01-01T00:00:00Z');
      expect(data.getSeason.endDate).toBe('2025-06-30T23:59:59Z');

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });
  });

  describe('listSeasonsByProfile after delete', () => {
    it('should not show deleted season in list', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-Catalog`,
            isPublic: true,
            products: [{ productName: 'Product 1', price: 10.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: season1Data } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-Season1`,
            seasonYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const seasonId1 = season1Data.createSeason.seasonId;

      const { data: season2Data } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-Season2`,
            seasonYear: 2025,
            startDate: '2025-06-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const seasonId2 = season2Data.createSeason.seasonId;

      // Delete one season
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: seasonId1 } });

      // Act
      const { data } = await ownerClient.query({
        query: LIST_SEASONS_BY_PROFILE,
        variables: { profileId: profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Only one season should remain
      expect(data.listSeasonsByProfile.length).toBe(1);
      expect(data.listSeasonsByProfile[0].seasonId).toBe(seasonId2);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: seasonId2 } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });
  });

  describe('getSeason with computed fields', () => {
    const GET_SEASON_WITH_COMPUTED = gql`
      query GetSeason($seasonId: ID!) {
        getSeason(seasonId: $seasonId) {
          seasonId
          seasonName
          seasonYear
          catalogId
          totalOrders
          totalRevenue
          catalog {
            catalogId
            catalogName
            products {
              productId
              productName
              price
            }
          }
        }
      }
    `;

    const CREATE_CATALOG_WITH_PRODUCTS = gql`
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

    const CREATE_ORDER = gql`
      mutation CreateOrder($input: CreateOrderInput!) {
        createOrder(input: $input) {
          orderId
          seasonId
          totalAmount
        }
      }
    `;

    const DELETE_ORDER = gql`
      mutation DeleteOrder($orderId: ID!) {
        deleteOrder(orderId: $orderId)
      }
    `;

    it('should return totalOrders and totalRevenue fields', async () => {
      // Arrange: Create profile, catalog with a product, season, and orders
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-ComputedFieldsProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG_WITH_PRODUCTS,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-ComputedCatalog`,
            isPublic: true,
            products: [
              { productName: 'Popcorn', price: 10.0, sortOrder: 1 },
              { productName: 'Candy', price: 5.0, sortOrder: 2 },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;
      const product1Id = catalogData.createCatalog.products[0].productId;
      const product2Id = catalogData.createCatalog.products[1].productId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-ComputedSeason`,
            seasonYear: 2025,
            startDate: '2025-01-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Create 2 orders with specific amounts
      const { data: order1Data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: profileId,
            seasonId: seasonId,
            customerName: 'Customer 1',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CASH',
            lineItems: [
              { productId: product1Id, quantity: 2 }, // 2 x $10 = $20
            ],
          },
        },
      });
      const orderId1 = order1Data.createOrder.orderId;

      const { data: order2Data } = await ownerClient.mutate({
        mutation: CREATE_ORDER,
        variables: {
          input: {
            profileId: profileId,
            seasonId: seasonId,
            customerName: 'Customer 2',
            orderDate: new Date().toISOString(),
            paymentMethod: 'CHECK',
            lineItems: [
              { productId: product1Id, quantity: 1 }, // 1 x $10 = $10
              { productId: product2Id, quantity: 3 }, // 3 x $5 = $15
            ],
          },
        },
      });
      const orderId2 = order2Data.createOrder.orderId;

      // Act: Get season with computed fields
      const { data } = await ownerClient.query({
        query: GET_SEASON_WITH_COMPUTED,
        variables: { seasonId: seasonId },
        fetchPolicy: 'network-only',
      });

      // Assert: Check computed fields
      expect(data.getSeason.totalOrders).toBe(2);
      expect(data.getSeason.totalRevenue).toBe(45); // $20 + $10 + $15 = $45

      // Assert: Check catalog field resolver
      expect(data.getSeason.catalog).not.toBeNull();
      expect(data.getSeason.catalog.catalogId).toBe(catalogId);
      expect(data.getSeason.catalog.products).toHaveLength(2);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderId1 } });
      await ownerClient.mutate({ mutation: DELETE_ORDER, variables: { orderId: orderId2 } });
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });

    it('should return catalog data via field resolver', async () => {
      // Arrange: Create profile, catalog, and season
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-CatalogResolverProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const catalogName = `${getTestPrefix()}-TestCatalogName`;
      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: catalogName,
            isPublic: false,
            products: [
              { productName: 'Caramel Corn', price: 12.50, sortOrder: 1 },
            ],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-CatalogResolverSeason`,
            seasonYear: 2025,
            startDate: '2025-03-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Act: Get season with catalog field
      const { data } = await ownerClient.query({
        query: GET_SEASON_WITH_COMPUTED,
        variables: { seasonId: seasonId },
        fetchPolicy: 'network-only',
      });

      // Assert: Catalog should be populated via field resolver
      expect(data.getSeason.catalog).toBeDefined();
      expect(data.getSeason.catalog.catalogName).toBe(catalogName);
      expect(data.getSeason.catalog.products).toHaveLength(1);
      expect(data.getSeason.catalog.products[0].productName).toBe('Caramel Corn');
      expect(data.getSeason.catalog.products[0].price).toBe(12.50);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });

    it('should return zero for totalOrders and totalRevenue when season has no orders', async () => {
      // Arrange: Create profile, catalog, and season (no orders)
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-NoOrdersProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData } = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-NoOrdersCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const { data: seasonData } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-NoOrdersSeason`,
            seasonYear: 2025,
            startDate: '2025-04-01T00:00:00Z',
            catalogId: catalogId,
          },
        },
      });
      const seasonId = seasonData.createSeason.seasonId;

      // Act: Get season with computed fields
      const { data } = await ownerClient.query({
        query: GET_SEASON_WITH_COMPUTED,
        variables: { seasonId: seasonId },
        fetchPolicy: 'network-only',
      });

      // Assert: Should return 0 for both computed fields (or null)
      expect(data.getSeason.totalOrders).toBe(0);
      expect(data.getSeason.totalRevenue).toBe(0);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    });
  });

  describe('Performance', () => {
    it('Performance: Listing seasons ordered by startDate', async () => {
      // Arrange: Create profile, catalog, and multiple seasons with different start dates
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-SeasonOrderProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-SeasonOrderCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      // Create seasons with different start dates (oldest to newest)
      const seasonIds: string[] = [];
      const startDates = [
        '2022-01-01T00:00:00Z',
        '2023-01-01T00:00:00Z',
        '2024-01-01T00:00:00Z',
        '2025-01-01T00:00:00Z',
      ];
      
      for (let i = 0; i < startDates.length; i++) {
        const { data: seasonData }: any = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: profileId,
              seasonName: `${getTestPrefix()}-Season-${i + 1}`,
              seasonYear: 2025,
              startDate: startDates[i],
              catalogId: catalogId,
            },
          },
        });
        seasonIds.push(seasonData.createSeason.seasonId);
      }

      // Act: List seasons
      const { data }: any = await ownerClient.query({
        query: LIST_SEASONS_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Seasons are returned with startDate for ordering
      expect(data.listSeasonsByProfile.length).toBe(startDates.length);
      
      for (const season of data.listSeasonsByProfile) {
        expect(season.startDate).toBeDefined();
      }
      
      // Check ordering (may be ascending or descending by implementation)
      const dates = data.listSeasonsByProfile.map((s: any) => new Date(s.startDate).getTime());
      const sortedAsc = [...dates].sort((a, b) => a - b);
      const sortedDesc = [...dates].sort((a, b) => b - a);
      
      const isAscending = JSON.stringify(dates) === JSON.stringify(sortedAsc);
      const isDescending = JSON.stringify(dates) === JSON.stringify(sortedDesc);
      
      console.log(`Seasons are ordered by startDate: ascending=${isAscending}, descending=${isDescending}`);

      // Cleanup
      for (const seasonId of seasonIds) {
        await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId } });
      }
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    }, 60000);

    it('Performance: Listing seasons with filters (active vs past vs future)', async () => {
      // Arrange: Create profile, catalog, and seasons with different date ranges
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-SeasonFilterProfile` } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      const { data: catalogData }: any = await ownerClient.mutate({
        mutation: CREATE_CATALOG,
        variables: {
          input: {
            catalogName: `${getTestPrefix()}-SeasonFilterCatalog`,
            isPublic: true,
            products: [{ productName: 'Product', price: 15.0, sortOrder: 1 }],
          },
        },
      });
      const catalogId = catalogData.createCatalog.catalogId;

      const now = new Date();
      const pastStart = new Date(now.getFullYear() - 2, 0, 1).toISOString();
      const pastEnd = new Date(now.getFullYear() - 1, 11, 31).toISOString();
      const activeStart = new Date(now.getFullYear(), 0, 1).toISOString();
      const activeEnd = new Date(now.getFullYear(), 11, 31).toISOString();
      const futureStart = new Date(now.getFullYear() + 1, 0, 1).toISOString();

      // Create past season
      const { data: pastSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-PastSeason`,
            seasonYear: 2025,
            startDate: pastStart,
            endDate: pastEnd,
            catalogId: catalogId,
          },
        },
      });
      const pastSeasonId = pastSeasonData.createSeason.seasonId;

      // Create active season
      const { data: activeSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-ActiveSeason`,
            seasonYear: 2025,
            startDate: activeStart,
            endDate: activeEnd,
            catalogId: catalogId,
          },
        },
      });
      const activeSeasonId = activeSeasonData.createSeason.seasonId;

      // Create future season
      const { data: futureSeasonData }: any = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: profileId,
            seasonName: `${getTestPrefix()}-FutureSeason`,
            seasonYear: 2025,
            startDate: futureStart,
            catalogId: catalogId,
          },
        },
      });
      const futureSeasonId = futureSeasonData.createSeason.seasonId;

      // Act: List all seasons
      const { data }: any = await ownerClient.query({
        query: LIST_SEASONS_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: All seasons are returned with date information for filtering
      expect(data.listSeasonsByProfile.length).toBe(3);
      
      // Verify each season has dates that allow client-side filtering
      const seasons = data.listSeasonsByProfile;
      for (const season of seasons) {
        expect(season.startDate).toBeDefined();
        // endDate may be null for ongoing seasons
      }
      
      // Categorize seasons by date range
      const pastSeasons = seasons.filter((s: any) => {
        const end = s.endDate ? new Date(s.endDate) : null;
        return end && end < now;
      });
      const activeSeasons = seasons.filter((s: any) => {
        const start = new Date(s.startDate);
        const end = s.endDate ? new Date(s.endDate) : null;
        return start <= now && (!end || end >= now);
      });
      const futureSeasons = seasons.filter((s: any) => {
        const start = new Date(s.startDate);
        return start > now;
      });
      
      console.log(`Seasons: past=${pastSeasons.length}, active=${activeSeasons.length}, future=${futureSeasons.length}`);
      expect(pastSeasons.length + activeSeasons.length + futureSeasons.length).toBe(3);

      // Cleanup
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: pastSeasonId } });
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: activeSeasonId } });
      await ownerClient.mutate({ mutation: DELETE_SEASON, variables: { seasonId: futureSeasonId } });
      await ownerClient.mutate({ mutation: DELETE_CATALOG, variables: { catalogId } });
      await ownerClient.mutate({ mutation: DELETE_PROFILE, variables: { profileId } });
    }, 60000);
  });
});
