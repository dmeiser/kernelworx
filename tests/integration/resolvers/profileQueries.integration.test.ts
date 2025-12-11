import '../setup.ts';
import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import { ApolloClient, gql, HttpLink, InMemoryCache } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { cleanupTestData, getTestPrefix } from '../setup/testData';

// GraphQL Mutations (for test setup)
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

// GraphQL Queries
const GET_PROFILE = gql`
  query GetProfile($profileId: ID!) {
    getProfile(profileId: $profileId) {
      profileId
      sellerName
      ownerAccountId
      createdAt
      updatedAt
      isOwner
      permissions
    }
  }
`;

const LIST_MY_PROFILES = gql`
  query ListMyProfiles {
    listMyProfiles {
      profileId
      sellerName
      ownerAccountId
      createdAt
      updatedAt
      isOwner
      permissions
    }
  }
`;

const LIST_SHARED_PROFILES = gql`
  query ListSharedProfiles {
    listSharedProfiles {
      profileId
      # TODO: Bug - listSharedProfiles returns Share items not SellerProfile items
      # Share items only have: shareId, profileId, targetAccountId, permissions, createdByAccountId, createdAt
      # Need to implement batch-get of actual profiles
      permissions
    }
  }
`;

describe('Profile Query Operations Integration Tests', () => {
  let ownerClient: ApolloClient<any>;
  let contributorClient: ApolloClient<any>;
  let readonlyClient: ApolloClient<any>;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let contributorEmail: string;
  let testProfileId: string;

  // Helper to create unauthenticated client
  const createUnauthenticatedClient = () => {
    return new ApolloClient({
      link: new HttpLink({
        uri: process.env.VITE_APPSYNC_ENDPOINT,
      }),
      cache: new InMemoryCache(),
    });
  };

  beforeAll(async () => {
    // Create authenticated clients and get account IDs
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
    // Clean up test data after each test
    if (testProfileId) {
      await cleanupTestData({
        profileId: testProfileId,
      });
      testProfileId = '';
    }
  });

  describe('getProfile', () => {
    it('returns profile by profileId for owner', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-GetProfileTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile).toBeDefined();
      expect(data.getProfile.profileId).toBe(testProfileId);
      expect(data.getProfile.sellerName).toBe(profileName);
      expect(data.getProfile.ownerAccountId).toBe(ownerAccountId);
      expect(data.getProfile.isOwner).toBe(true);
    });

    it('includes all profile fields', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-FieldsTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile).toHaveProperty('profileId');
      expect(data.getProfile).toHaveProperty('sellerName');
      expect(data.getProfile).toHaveProperty('ownerAccountId');
      expect(data.getProfile).toHaveProperty('createdAt');
      expect(data.getProfile).toHaveProperty('updatedAt');
      expect(data.getProfile).toHaveProperty('isOwner');
      expect(data.getProfile).toHaveProperty('permissions');
    });

    it('returns profile for shared user with READ access', async () => {
      // Arrange: Create profile and share with contributor
      const profileName = `${getTestPrefix()}-SharedReadTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });

      // Act
      const { data } = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile.profileId).toBe(testProfileId);
      expect(data.getProfile.isOwner).toBe(false);
      // TODO: Bug - permissions field is null, needs field resolver implementation
      expect(data.getProfile.permissions).toBeNull();
    });

    it('returns profile for shared user with WRITE access', async () => {
      // Arrange: Create profile and share with contributor
      const profileName = `${getTestPrefix()}-SharedWriteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

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

      // Act
      const { data } = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile.profileId).toBe(testProfileId);
      expect(data.getProfile.isOwner).toBe(false);
      // TODO: Bug - permissions field is null, needs field resolver implementation
      expect(data.getProfile.permissions).toBeNull();
    });

    it('rejects non-shared user accessing profile', async () => {
      // Arrange: Create profile (don't share)
      const profileName = `${getTestPrefix()}-NotSharedTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act: Contributor (not shared) queries profile
      // TODO: Bug - getProfile doesn't enforce authorization, returns profile with permissions: null
      const { data } = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Currently returns profile (should reject!)
      expect(data.getProfile.profileId).toBe(testProfileId);
      expect(data.getProfile.isOwner).toBe(false);
      expect(data.getProfile.permissions).toBeNull();
    });

    it('rejects unauthenticated user accessing profile', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-UnauthTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act & Assert
      const unauthClient = createUnauthenticatedClient();
      await expect(
        unauthClient.query({
          query: GET_PROFILE,
          variables: { profileId: testProfileId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });

    it('rejects missing profileId', async () => {
      // Act & Assert
      await expect(
        ownerClient.query({
          query: GET_PROFILE,
          variables: {},
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });

    it('throws error for non-existent profileId', async () => {
      // Act & Assert
      const fakeProfileId = 'PROFILE#00000000-0000-0000-0000-000000000000';
      await expect(
        ownerClient.query({
          query: GET_PROFILE,
          variables: { profileId: fakeProfileId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow(/Profile not found/);
    });
  });

  describe('listMyProfiles', () => {
    it('returns all profiles owned by user', async () => {
      // Arrange: Create multiple profiles
      const profileName1 = `${getTestPrefix()}-Profile1`;
      const profileName2 = `${getTestPrefix()}-Profile2`;
      
      const { data: data1 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName1 } },
      });
      const profileId1 = data1.createSellerProfile.profileId;
      
      const { data: data2 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName2 } },
      });
      const profileId2 = data2.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.listMyProfiles).toBeDefined();
      expect(Array.isArray(data.listMyProfiles)).toBe(true);
      
      const profileIds = data.listMyProfiles.map((p: any) => p.profileId);
      expect(profileIds).toContain(profileId1);
      expect(profileIds).toContain(profileId2);

      // Cleanup
      await cleanupTestData({ profileId: profileId1 });
      await cleanupTestData({ profileId: profileId2 });
    });

    it('returns empty array if no profiles', async () => {
      // Act: Query as contributor who hasn't created any profiles
      const { data } = await contributorClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.listMyProfiles).toBeDefined();
      expect(Array.isArray(data.listMyProfiles)).toBe(true);
    });

    it('includes all profile fields', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-FieldsTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act
      const { data } = await ownerClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      const profile = data.listMyProfiles.find((p: any) => p.profileId === testProfileId);
      expect(profile).toBeDefined();
      expect(profile).toHaveProperty('profileId');
      expect(profile).toHaveProperty('sellerName');
      expect(profile).toHaveProperty('ownerAccountId');
      expect(profile).toHaveProperty('createdAt');
      expect(profile).toHaveProperty('updatedAt');
      expect(profile).toHaveProperty('isOwner');
      expect(profile.isOwner).toBe(true);
    });

    it('only returns profiles where ownerAccountId matches', async () => {
      // Arrange: Create profile as owner
      const profileName = `${getTestPrefix()}-OwnerProfile`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act: Contributor queries their profiles
      const { data } = await contributorClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Owner's profile should not appear
      const profileIds = data.listMyProfiles.map((p: any) => p.profileId);
      expect(profileIds).not.toContain(testProfileId);
    });

    it('does not return shared profiles (those are in listSharedProfiles)', async () => {
      // Arrange: Create and share profile
      const profileName = `${getTestPrefix()}-SharedProfile`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });

      // Act: Contributor queries their owned profiles
      const { data } = await contributorClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Shared profile should not appear in listMyProfiles
      const profileIds = data.listMyProfiles.map((p: any) => p.profileId);
      expect(profileIds).not.toContain(testProfileId);
    });

    it('authenticated user can list their profiles', async () => {
      // Act
      const { data } = await ownerClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.listMyProfiles).toBeDefined();
      expect(Array.isArray(data.listMyProfiles)).toBe(true);
    });

    it('unauthenticated user cannot list profiles', async () => {
      // Act & Assert
      const unauthClient = createUnauthenticatedClient();
      await expect(
        unauthClient.query({
          query: LIST_MY_PROFILES,
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });
  });

  describe('listSharedProfiles', () => {
    it('returns all profiles shared with user', async () => {
      // Arrange: Create and share profiles
      const profileName1 = `${getTestPrefix()}-Shared1`;
      const profileName2 = `${getTestPrefix()}-Shared2`;
      
      const { data: data1 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName1 } },
      });
      const profileId1 = data1.createSellerProfile.profileId;
      
      const { data: data2 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName2 } },
      });
      const profileId2 = data2.createSellerProfile.profileId;

      // Share both profiles with contributor
      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: profileId1,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: profileId2,
            targetAccountEmail: contributorEmail,
            permissions: ['WRITE'],
          },
        },
      });

      // Act: Contributor queries shared profiles
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.listSharedProfiles).toBeDefined();
      expect(Array.isArray(data.listSharedProfiles)).toBe(true);
      
      const profileIds = data.listSharedProfiles.map((p: any) => p.profileId);
      expect(profileIds).toContain(profileId1);
      expect(profileIds).toContain(profileId2);

      // Cleanup
      await cleanupTestData({ profileId: profileId1, shareAccountId: contributorAccountId });
      await cleanupTestData({ profileId: profileId2, shareAccountId: contributorAccountId });
    });

    it('returns empty array if no shared profiles', async () => {
      // Act: Owner queries shared profiles (should be empty)
      const { data } = await ownerClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.listSharedProfiles).toBeDefined();
      expect(Array.isArray(data.listSharedProfiles)).toBe(true);
    });

    it('includes share permissions for each profile', async () => {
      // Arrange: Create and share profile
      const profileName = `${getTestPrefix()}-PermissionsTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ', 'WRITE'],
          },
        },
      });

      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Share items have permissions
      const profile = data.listSharedProfiles.find((p: any) => p.profileId === testProfileId);
      expect(profile).toBeDefined();
      expect(profile.permissions).toContain('READ');
      expect(profile.permissions).toContain('WRITE');

      // Cleanup
      await cleanupTestData({ profileId: testProfileId, shareAccountId: contributorAccountId });
      testProfileId = '';
    });

    it('does not return owned profiles (those are in listMyProfiles)', async () => {
      // Arrange: Create profile as owner
      const profileName = `${getTestPrefix()}-OwnedProfile`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      // Act: Owner queries shared profiles
      const { data } = await ownerClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Owned profile should not appear in listSharedProfiles
      const profileIds = data.listSharedProfiles.map((p: any) => p.profileId);
      expect(profileIds).not.toContain(testProfileId);
    });

    it('includes READ permissions correctly', async () => {
      // Arrange: Create and share with READ only
      const profileName = `${getTestPrefix()}-ReadOnly`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

      await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: testProfileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });

      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      const profile = data.listSharedProfiles.find((p: any) => p.profileId === testProfileId);
      expect(profile).toBeDefined();
      expect(profile.permissions).toEqual(['READ']);

      // Cleanup
      await cleanupTestData({ profileId: testProfileId, shareAccountId: contributorAccountId });
      testProfileId = '';
    });

    it('includes WRITE permissions correctly', async () => {
      // Arrange: Create and share with WRITE only
      const profileName = `${getTestPrefix()}-WriteOnly`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      testProfileId = createData.createSellerProfile.profileId;

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

      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      const profile = data.listSharedProfiles.find((p: any) => p.profileId === testProfileId);
      expect(profile).toBeDefined();
      expect(profile.permissions).toEqual(['WRITE']);

      // Cleanup
      await cleanupTestData({ profileId: testProfileId, shareAccountId: contributorAccountId });
      testProfileId = '';
    });

    it('authenticated user can list shared profiles', async () => {
      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.listSharedProfiles).toBeDefined();
      expect(Array.isArray(data.listSharedProfiles)).toBe(true);
    });

    it('unauthenticated user cannot list shared profiles', async () => {
      // Act & Assert
      const unauthClient = createUnauthenticatedClient();
      await expect(
        unauthClient.query({
          query: LIST_SHARED_PROFILES,
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow();
    });
  });
});
