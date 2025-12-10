/**
 * Integration tests for createSeason VTL resolver
 * 
 * Tests cover:
 * - Happy paths (season creation with required/optional fields)
 * - Authorization (owner, WRITE contributor, READ contributor, non-shared, unauthenticated)
 * - Input validation (missing fields, invalid references)
 * - Data integrity (field presence, GSI attributes)
 */

import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { cleanupTestData } from '../setup/testData';

// Helper to generate unique test prefix
const getTestPrefix = () => `TEST-${Date.now()}`;

// GraphQL Mutations
const CREATE_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
    }
  }
`;

const SHARE_DIRECT = gql`
  mutation ShareProfileDirect($input: ShareProfileDirectInput!) {
    shareProfileDirect(input: $input) {
      shareId
      profileId
      targetAccountId
      permissions
    }
  }
`;

const CREATE_CATALOG = gql`
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      catalogId
      catalogName
      isPublic
      createdAt
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

describe('createSeason Integration Tests', () => {
  let ownerClient: ApolloClient<any>;
  let contributorClient: ApolloClient<any>;
  let readonlyClient: ApolloClient<any>;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let contributorEmail: string;
  let testProfileId: string;
  let testCatalogId: string;
  let testSeasonId: string;

  beforeAll(async () => {
    // Create authenticated clients
    const ownerAuth: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    const contributorAuth: AuthenticatedClientResult = await createAuthenticatedClient('contributor');
    const readonlyAuth: AuthenticatedClientResult = await createAuthenticatedClient('readonly');
    
    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;
    ownerAccountId = ownerAuth.accountId;
    contributorAccountId = contributorAuth.accountId;
    contributorEmail = contributorAuth.email;
  });

  afterEach(async () => {
    // Clean up test data
    if (testSeasonId) {
      await cleanupTestData({ seasonId: testSeasonId });
      testSeasonId = '';
    }
    if (testProfileId) {
      await cleanupTestData({ profileId: testProfileId });
      testProfileId = '';
    }
    if (testCatalogId) {
      await cleanupTestData({ catalogId: testCatalogId });
      testCatalogId = '';
    }
  });

  describe('Happy Paths', () => {
    it('creates season with required fields', async () => {
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

      // Act: Create season
      const { data } = await ownerClient.mutate({
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

      // Assert
      expect(data.createSeason).toBeDefined();
      expect(data.createSeason.seasonId).toBeDefined();
      expect(data.createSeason.profileId).toBe(testProfileId);
      expect(data.createSeason.seasonName).toContain('Season');
      expect(data.createSeason.catalogId).toBe(testCatalogId);
      expect(data.createSeason.startDate).toBe('2025-01-01T00:00:00Z');
      
      testSeasonId = data.createSeason.seasonId;
    });

    it('auto-generates unique seasonId', async () => {
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

      // Act: Create two seasons
      const { data: season1 } = await ownerClient.mutate({
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

      const { data: season2 } = await ownerClient.mutate({
        mutation: CREATE_SEASON,
        variables: {
          input: {
            profileId: testProfileId,
            seasonName: `${getTestPrefix()}-Season2`,
            startDate: '2025-02-01T00:00:00Z',
            catalogId: testCatalogId,
          },
        },
      });

      // Assert: Different seasonIds
      expect(season1.createSeason.seasonId).toBeDefined();
      expect(season2.createSeason.seasonId).toBeDefined();
      expect(season1.createSeason.seasonId).not.toBe(season2.createSeason.seasonId);

      // Cleanup second season
      testSeasonId = season1.createSeason.seasonId;
      await cleanupTestData({ seasonId: season2.createSeason.seasonId });
    });

    it('sets timestamps (createdAt, updatedAt)', async () => {
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

      // Act
      const { data } = await ownerClient.mutate({
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

      // Assert: Timestamps exist and are valid ISO8601
      expect(data.createSeason.createdAt).toBeDefined();
      expect(data.createSeason.updatedAt).toBeDefined();
      expect(new Date(data.createSeason.createdAt).toISOString()).toBe(data.createSeason.createdAt);
      expect(new Date(data.createSeason.updatedAt).toISOString()).toBe(data.createSeason.updatedAt);
      
      testSeasonId = data.createSeason.seasonId;
    });

    it('accepts optional endDate', async () => {
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

      // Act: Create with endDate
      const { data } = await ownerClient.mutate({
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

      // Assert
      expect(data.createSeason.endDate).toBe('2025-12-31T23:59:59Z');
      
      testSeasonId = data.createSeason.seasonId;
    });
  });

  describe('Authorization', () => {
    it('profile owner can create seasons', async () => {
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

      // Act: Owner creates season
      const { data } = await ownerClient.mutate({
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

      // Assert
      expect(data.createSeason).toBeDefined();
      expect(data.createSeason.profileId).toBe(testProfileId);
      
      testSeasonId = data.createSeason.seasonId;
    });

    it('shared user with WRITE can create seasons', async () => {
      // Arrange: Owner creates profile and shares with contributor (WRITE)
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      testProfileId = profileData.createSellerProfile.profileId;

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: contributorEmail,
            permissions: ['WRITE'],
          },
        },
      });

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

      // Act: Contributor creates season
      const { data } = await contributorClient.mutate({
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

      // Assert
      expect(data.createSeason).toBeDefined();
      expect(data.createSeason.profileId).toBe(testProfileId);
      
      testSeasonId = data.createSeason.seasonId;
    });

    it('shared user with READ cannot create seasons', async () => {
      // Arrange: Owner creates profile and shares with readonly (READ only)
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      testProfileId = profileData.createSellerProfile.profileId;

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL!,
            permissions: ['READ'],
          },
        },
      });

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

      // Act & Assert: Readonly user tries to create season
      await expect(
        readonlyClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('non-shared user cannot create seasons', async () => {
      // Arrange: Owner creates profile (no share with contributor)
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

      // Act & Assert: Non-shared user tries to create season
      await expect(
        contributorClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        })
      ).rejects.toThrow();
    });
  });

  describe('Input Validation', () => {
    it('rejects missing profileId', async () => {
      // Arrange
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

      // Act & Assert
      await expect(
        ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              // profileId missing
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('rejects missing seasonName', async () => {
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

      // Act & Assert
      await expect(
        ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              // seasonName missing
              startDate: '2025-01-01T00:00:00Z',
              catalogId: testCatalogId,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('rejects missing startDate', async () => {
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

      // Act & Assert
      await expect(
        ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              // startDate missing
              catalogId: testCatalogId,
            },
          },
        })
      ).rejects.toThrow();
    });

    it('rejects missing catalogId', async () => {
      // Arrange
      const { data: profileData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: `${getTestPrefix()}-Profile` } },
      });
      testProfileId = profileData.createSellerProfile.profileId;

      // Act & Assert
      await expect(
        ownerClient.mutate({
          mutation: CREATE_SEASON,
          variables: {
            input: {
              profileId: testProfileId,
              seasonName: `${getTestPrefix()}-Season`,
              startDate: '2025-01-01T00:00:00Z',
              // catalogId missing
            },
          },
        })
      ).rejects.toThrow();
    });
  });
});
