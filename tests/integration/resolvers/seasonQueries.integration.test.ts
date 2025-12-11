import '../setup.ts';
/**
 * Integration tests for Season query resolvers
 * Tests: getSeason, listSeasonsByProfile
 */

import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { cleanupTestData } from '../setup/testData';

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

// GraphQL Queries to test
const GET_SEASON = gql`
  query GetSeason($seasonId: ID!) {
    getSeason(seasonId: $seasonId) {
      seasonId
      profileId
      seasonName
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
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let readonlyEmail: string;

  let testProfileId: string;
  let testCatalogId: string;
  let testSeasonId: string;

  beforeAll(async () => {
    const ownerResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorResult: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyResult: AuthenticatedClientResult = await createAuthenticatedClient('readonly');

    ownerClient = ownerResult.client;
    contributorClient = contributorResult.client;
    readonlyClient = readonlyResult.client;
    contributorAccountId = contributorResult.accountId;
    readonlyAccountId = readonlyResult.accountId;
    readonlyEmail = process.env.TEST_READONLY_EMAIL!;
  });

  afterEach(async () => {
    if (testProfileId) {
      await cleanupTestData({ profileId: testProfileId, seasonId: testSeasonId });
      testProfileId = '';
      testCatalogId = '';
      testSeasonId = '';
    }
  });

  describe('getSeason', () => {
    describe('Happy Path', () => {
      it('should return season by seasonId with all fields', async () => {
        // Arrange: Create profile, catalog, and season
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              endDate: '2025-12-31T23:59:59Z',
              catalogId: testCatalogId,
            },
          },
        });
        testSeasonId = seasonData.createSeason.seasonId;

        // Wait for GSI7 eventual consistency (Bug #21 - known issue)
        // GSI indexes can take 5-7 seconds to become consistent
        await new Promise(resolve => setTimeout(resolve, 7000));

        // Act: Query season
        const { data } = await ownerClient.query({
          query: GET_SEASON,
          variables: { seasonId: testSeasonId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeDefined();
        expect(data.getSeason.seasonId).toBe(testSeasonId);
        expect(data.getSeason.profileId).toBe(testProfileId);
        expect(data.getSeason.seasonName).toContain('Season');
        expect(data.getSeason.startDate).toBe('2025-01-01T00:00:00Z');
        expect(data.getSeason.endDate).toBe('2025-12-31T23:59:59Z');
        expect(data.getSeason.catalogId).toBe(testCatalogId);
        expect(data.getSeason.createdAt).toBeDefined();
        expect(data.getSeason.updatedAt).toBeDefined();
      });

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
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });
        testSeasonId = seasonData.createSeason.seasonId;

        // Act
        const { data } = await ownerClient.query({
          query: GET_SEASON,
          variables: { seasonId: testSeasonId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeDefined();
        expect(data.getSeason.seasonId).toBe(testSeasonId);
      });

      it('should allow shared user (READ) to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });
        testSeasonId = seasonData.createSeason.seasonId;

        // Share profile with readonly user (READ permission)
        await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: testProfileId,
              targetAccountEmail: readonlyEmail,
              permissions: ['READ'],
            },
          },
        });

        // Act: Readonly user queries season
        const { data } = await readonlyClient.query({
          query: GET_SEASON,
          variables: { seasonId: testSeasonId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.getSeason).toBeDefined();
        expect(data.getSeason.seasonId).toBe(testSeasonId);
      });

      it('should NOT allow non-shared user to get season', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        const { data: seasonData } = await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });
        testSeasonId = seasonData.createSeason.seasonId;

        // Act: Contributor (not shared) queries season
        const { data } = await contributorClient.query({
          query: GET_SEASON,
          variables: { seasonId: testSeasonId },
          fetchPolicy: 'network-only',
        });

        // Assert: Should return null due to authorization failure
        expect(data.getSeason).toBeNull();
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
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        // Create multiple seasons
        await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season1`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });

        await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season2`,
              startDate: '2025-06-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });

        // Act: List seasons
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile.length).toBe(2);
        expect(data.listSeasonsByProfile[0].seasonId).toBeDefined();
        expect(data.listSeasonsByProfile[0].seasonName).toContain('Season');
        expect(data.listSeasonsByProfile[1].seasonId).toBeDefined();
      });

      it('should return empty array for profile with no seasons', async () => {
        // Arrange: Create profile without seasons
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

        // Act
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile).toEqual([]);
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
    });

    describe('Authorization', () => {
      it('should allow profile owner to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });

        // Act
        const { data } = await ownerClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile.length).toBeGreaterThan(0);
      });

      it('should allow shared user (READ) to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });

        // Share profile with readonly user
        await ownerClient.mutate({
          mutation: SHARE_DIRECT,
          variables: {
            input: {
              profileId: testProfileId,
              targetAccountEmail: readonlyEmail,
              permissions: ['READ'],
            },
          },
        });

        // Act: Readonly user lists seasons
        const { data } = await readonlyClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        });

        // Assert
        expect(data.listSeasonsByProfile).toBeDefined();
        expect(data.listSeasonsByProfile.length).toBeGreaterThan(0);
      });

      it('should NOT allow non-shared user to list seasons', async () => {
        // Arrange
        const { data: profileData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
        });
        testProfileId = profileData.createSellerProfile.profileId;

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
        testCatalogId = catalogData.createCatalog.catalogId;

        await ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        });

        // Act: Contributor (not shared) lists seasons
        const { data } = await contributorClient.query({
          query: LIST_SEASONS_BY_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        });

        // Assert: Should return empty array due to authorization failure
        expect(data.listSeasonsByProfile).toEqual([]);
      });
    });
  });
});
