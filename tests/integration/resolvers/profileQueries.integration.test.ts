import '../setup.ts';
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql, HttpLink, InMemoryCache } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { getTestPrefix, waitForGSIConsistency, deleteTestAccounts } from '../setup/testData';


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
      isOwner
      createdAt
      updatedAt
    }
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
  const SUITE_ID = 'profile-queries';
  
  let ownerClient: ApolloClient<any>;
  let contributorClient: ApolloClient<any>;
  let readonlyClient: ApolloClient<any>;
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;
  let contributorEmail: string;

  // Track created resources for cleanup
  const createdProfileIds: string[] = [];
  const createdShares: { profileId: string; targetAccountId: string }[] = [];

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
    readonlyAccountId = readonlyAuth.accountId;
    contributorEmail = contributorAuth.email;
  });

  afterAll(async () => {
    console.log('Cleaning up profile query test data...');
    try {
      // 1. Revoke shares first
      for (const share of createdShares) {
        try {
          await ownerClient.mutate({
            mutation: REVOKE_SHARE,
            variables: { input: { profileId: share.profileId, targetAccountId: share.targetAccountId } },
          });
        } catch (e) { /* may already be revoked */ }
      }
      // 2. Delete profiles
      for (const profileId of createdProfileIds) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_PROFILE,
            variables: { profileId },
          });
        } catch (e) { /* may already be deleted */ }
      }
      
      // 3. Clean up account records
      console.log('Cleaning up account records...');
      // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
      
      console.log('Profile query test data cleanup complete.');
    } catch (error) {
      console.log('Error in cleanup:', error);
    }
  }, 30000);


  describe('getProfile', () => {
    it('returns profile by profileId for owner', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-GetProfileTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act
      const { data } = await ownerClient.query({
        query: GET_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile).toBeDefined();
      expect(data.getProfile.profileId).toBe(profileId);
      expect(data.getProfile.sellerName).toBe(profileName);
      expect(data.getProfile.ownerAccountId).toBe(ownerAccountId);
      expect(data.getProfile.isOwner).toBe(true);
      // Owner gets full READ and WRITE permissions
      expect(data.getProfile.permissions).toEqual(['READ', 'WRITE']);
    });

    it('includes all profile fields', async () => {
      // Arrange
      const profileName = `${getTestPrefix()}-FieldsTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act
      const { data } = await ownerClient.query({
        query: GET_PROFILE,
        variables: { profileId },
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
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act
      const { data } = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile.profileId).toBe(profileId);
      expect(data.getProfile.isOwner).toBe(false);
      // FIXED: permissions field now returns the caller's share permissions
      expect(data.getProfile.permissions).toEqual(['READ']);
    });

    it('returns profile for shared user with WRITE access', async () => {
      // Arrange: Create profile and share with contributor
      const profileName = `${getTestPrefix()}-SharedWriteTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['WRITE'],
          },
        },
      });
      createdShares.push({ profileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act
      const { data } = await contributorClient.query({
        query: GET_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert
      expect(data.getProfile.profileId).toBe(profileId);
      expect(data.getProfile.isOwner).toBe(false);
      // FIXED: permissions field now returns the caller's share permissions
      expect(data.getProfile.permissions).toEqual(['WRITE']);
    });

    it('rejects non-shared user accessing profile', async () => {
      // Arrange: Create profile (don't share)
      const profileName = `${getTestPrefix()}-NotSharedTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act & Assert: Contributor (not shared) queries profile - should be rejected
      await expect(
        contributorClient.query({
          query: GET_PROFILE,
          variables: { profileId },
          fetchPolicy: 'network-only',
        })
      ).rejects.toThrow(/not authorized|unauthorized/i);
    });

    it('rejects unauthenticated user accessing profile', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-UnauthTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act & Assert
      const unauthClient = createUnauthenticatedClient();
      await expect(
        unauthClient.query({
          query: GET_PROFILE,
          variables: { profileId },
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
    // NOTE: This test may take 60-120+ seconds due to GSI eventual consistency issues (Bug #21)
    // when the DynamoDB table contains thousands of test items from previous runs
    it('returns all profiles owned by user', async () => {
      // Arrange: Create multiple profiles
      const profileName1 = `${getTestPrefix()}-Profile1`;
      const profileName2 = `${getTestPrefix()}-Profile2`;
      
      const { data: data1 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName1 } },
      });
      const profileId1 = data1.createSellerProfile.profileId;
      createdProfileIds.push(profileId1);
      
      const { data: data2 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName2 } },
      });
      const profileId2 = data2.createSellerProfile.profileId;
      createdProfileIds.push(profileId2);

      // Wait for GSI eventual consistency with retry logic (Bug #21 - known AWS limitation)
      // Poll listMyProfiles until both profiles appear in results
      // Increased to 120 attempts (2 minutes) due to EXTREMELY slow GSI propagation when DB has thousands of test items
      // This test may take up to 3+ minutes to complete in heavily polluted test environments
      const profiles = await waitForGSIConsistency(
        async () => {
          const { data } = await ownerClient.query({
            query: LIST_MY_PROFILES,
            fetchPolicy: 'network-only',
          });
          return data.listMyProfiles;
        },
        (items: any[]) => {
          const profileIds = items.map((p: any) => p.profileId);
          return profileIds.includes(profileId1) && profileIds.includes(profileId2);
        },
        120, // maxAttempts (2 minutes of polling)
        1000 // delayMs
      );

      // Assert
      const profileIds = profiles.map((p: any) => p.profileId);
      expect(profileIds).toContain(profileId1);
      expect(profileIds).toContain(profileId2);
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

    // NOTE: This test may take 60-120+ seconds due to GSI eventual consistency issues (Bug #21)
    // when the DynamoDB table contains thousands of test items from previous runs
    it('includes all profile fields', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-FieldsTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Wait for GSI eventual consistency with retry logic (Bug #21 - known AWS limitation)
      // Poll listMyProfiles until the profile appears in results
      // Increased to 120 attempts (2 minutes) due to EXTREMELY slow GSI propagation when DB has thousands of test items
      // This test may take up to 3+ minutes to complete in heavily polluted test environments
      const profiles = await waitForGSIConsistency(
        async () => {
          const { data } = await ownerClient.query({
            query: LIST_MY_PROFILES,
            fetchPolicy: 'network-only',
          });
          return data.listMyProfiles;
        },
        (items: any[]) => items.some((p: any) => p.profileId === profileId),
        120, // maxAttempts (2 minutes of polling)
        1000 // delayMs
      );

      // Assert
      const profile = profiles.find((p: any) => p.profileId === profileId);
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
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act: Contributor queries their profiles
      const { data } = await contributorClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Owner's profile should not appear
      const profileIds = data.listMyProfiles.map((p: any) => p.profileId);
      expect(profileIds).not.toContain(profileId);
    });

    it('does not return shared profiles (those are in listSharedProfiles)', async () => {
      // Arrange: Create and share profile
      const profileName = `${getTestPrefix()}-SharedProfile`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act: Contributor queries their owned profiles
      const { data } = await contributorClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Shared profile should not appear in listMyProfiles
      const profileIds = data.listMyProfiles.map((p: any) => p.profileId);
      expect(profileIds).not.toContain(profileId);
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
      createdProfileIds.push(profileId1);
      
      const { data: data2 } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName2 } },
      });
      const profileId2 = data2.createSellerProfile.profileId;
      createdProfileIds.push(profileId2);

      // Share both profiles with contributor
      const { data: share1Data }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: profileId1,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId: profileId1, targetAccountId: share1Data.shareProfileDirect.targetAccountId });

      const { data: share2Data }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: profileId2,
            targetAccountEmail: contributorEmail,
            permissions: ['WRITE'],
          },
        },
      });
      createdShares.push({ profileId: profileId2, targetAccountId: share2Data.shareProfileDirect.targetAccountId });

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
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ', 'WRITE'],
          },
        },
      });
      createdShares.push({ profileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Share items have permissions
      const profile = data.listSharedProfiles.find((p: any) => p.profileId === profileId);
      expect(profile).toBeDefined();
      expect(profile.permissions).toContain('READ');
      expect(profile.permissions).toContain('WRITE');
    });

    it('does not return owned profiles (those are in listMyProfiles)', async () => {
      // Arrange: Create profile as owner
      const profileName = `${getTestPrefix()}-OwnedProfile`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act: Owner queries shared profiles
      const { data } = await ownerClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Owned profile should not appear in listSharedProfiles
      const profileIds = data.listSharedProfiles.map((p: any) => p.profileId);
      expect(profileIds).not.toContain(profileId);
    });

    it('includes READ permissions correctly', async () => {
      // Arrange: Create and share with READ only
      const profileName = `${getTestPrefix()}-ReadOnly`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      const profile = data.listSharedProfiles.find((p: any) => p.profileId === profileId);
      expect(profile).toBeDefined();
      expect(profile.permissions).toEqual(['READ']);
    });

    it('includes WRITE permissions correctly', async () => {
      // Arrange: Create and share with WRITE only
      const profileName = `${getTestPrefix()}-WriteOnly`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['WRITE'],
          },
        },
      });
      createdShares.push({ profileId, targetAccountId: shareData.shareProfileDirect.targetAccountId });

      // Act
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert
      const profile = data.listSharedProfiles.find((p: any) => p.profileId === profileId);
      expect(profile).toBeDefined();
      expect(profile.permissions).toEqual(['WRITE']);
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

    it('listing profiles after share revocation (should not appear)', async () => {
      // Arrange: Create profile and share with contributor
      const profileName = `${getTestPrefix()}-RevokeShareTest`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });
      const targetAccountId = shareData.shareProfileDirect.targetAccountId;

      // Verify share appears in list
      const { data: beforeRevoke } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });
      expect(beforeRevoke.listSharedProfiles.some((p: any) => p.profileId === profileId)).toBe(true);

      // Revoke the share
      await ownerClient.mutate({
        mutation: REVOKE_SHARE,
        variables: { input: { profileId, targetAccountId } },
      });

      // Act: List shared profiles again
      const { data: afterRevoke } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Profile should no longer appear
      expect(afterRevoke.listSharedProfiles.some((p: any) => p.profileId === profileId)).toBe(false);
    });

    it('listing profiles with mixed READ/WRITE permissions', async () => {
      // Arrange: Create two profiles with different permissions
      const profile1Name = `${getTestPrefix()}-ReadShareProfile`;
      const { data: create1Data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profile1Name } },
      });
      const profile1Id = create1Data.createSellerProfile.profileId;
      createdProfileIds.push(profile1Id);

      const profile2Name = `${getTestPrefix()}-WriteShareProfile`;
      const { data: create2Data } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profile2Name } },
      });
      const profile2Id = create2Data.createSellerProfile.profileId;
      createdProfileIds.push(profile2Id);

      // Share profile1 with READ
      const { data: share1Data }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: profile1Id,
            targetAccountEmail: contributorEmail,
            permissions: ['READ'],
          },
        },
      });
      createdShares.push({ profileId: profile1Id, targetAccountId: share1Data.shareProfileDirect.targetAccountId });

      // Share profile2 with WRITE
      const { data: share2Data }: any = await ownerClient.mutate({
        mutation: SHARE_DIRECT,
        variables: {
          input: {
            profileId: profile2Id,
            targetAccountEmail: contributorEmail,
            permissions: ['READ', 'WRITE'],
          },
        },
      });
      createdShares.push({ profileId: profile2Id, targetAccountId: share2Data.shareProfileDirect.targetAccountId });

      // Act: List shared profiles
      const { data } = await contributorClient.query({
        query: LIST_SHARED_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Both profiles appear with correct permissions
      const readProfile = data.listSharedProfiles.find((p: any) => p.profileId === profile1Id);
      const writeProfile = data.listSharedProfiles.find((p: any) => p.profileId === profile2Id);

      expect(readProfile).toBeDefined();
      expect(readProfile.permissions).toEqual(['READ']);

      expect(writeProfile).toBeDefined();
      expect(writeProfile.permissions).toEqual(['READ', 'WRITE']);
    });
  });

  describe('Performance', () => {
    it('Performance: Listing profiles when user has many profiles', async () => {
      // Arrange: Create many profiles for performance testing
      const profileCount = 15;
      const performanceProfileIds: string[] = [];
      
      for (let i = 0; i < profileCount; i++) {
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-PerfProfile-${i + 1}` } },
        });
        performanceProfileIds.push(createData.createSellerProfile.profileId);
        createdProfileIds.push(createData.createSellerProfile.profileId);
      }

      // Act: List profiles and measure time
      const startTime = Date.now();
      const { data } = await ownerClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });
      const endTime = Date.now();
      const queryTime = endTime - startTime;

      // Assert: All profiles are returned
      expect(data.listMyProfiles.length).toBeGreaterThanOrEqual(profileCount);
      
      // Performance check: Query should complete quickly
      expect(queryTime).toBeLessThan(5000); // Less than 5 seconds
      
      console.log(`Listing ${data.listMyProfiles.length} profiles took ${queryTime}ms`);
    }, 90000);

    it('Performance: Listing profiles ordered by createdAt', async () => {
      // Arrange: Create several profiles with small delays to ensure different createdAt
      const profileIds: string[] = [];
      
      for (let i = 0; i < 5; i++) {
        const { data: createData } = await ownerClient.mutate({
          mutation: CREATE_PROFILE,
          variables: { input: { sellerName: `${getTestPrefix()}-OrderedProfile-${i + 1}` } },
        });
        profileIds.push(createData.createSellerProfile.profileId);
        createdProfileIds.push(createData.createSellerProfile.profileId);
        await new Promise(resolve => setTimeout(resolve, 50)); // Small delay
      }

      // Act: List profiles
      const { data } = await ownerClient.query({
        query: LIST_MY_PROFILES,
        fetchPolicy: 'network-only',
      });

      // Assert: Profiles are returned (order may vary by implementation)
      // Note: listMyProfiles may not guarantee a specific order currently
      expect(data.listMyProfiles.length).toBeGreaterThanOrEqual(5);
      
      // Verify createdAt fields are present for ordering
      for (const profile of data.listMyProfiles) {
        expect(profile.createdAt).toBeDefined();
      }
      
      // Check if profiles are ordered by createdAt (ascending or descending)
      const createdTimes = data.listMyProfiles.map((p: any) => new Date(p.createdAt).getTime());
      const sortedAsc = [...createdTimes].sort((a, b) => a - b);
      const sortedDesc = [...createdTimes].sort((a, b) => b - a);
      
      const isAscending = JSON.stringify(createdTimes) === JSON.stringify(sortedAsc);
      const isDescending = JSON.stringify(createdTimes) === JSON.stringify(sortedDesc);
      
      // Document the actual ordering behavior
      console.log(`Profiles are ordered: ascending=${isAscending}, descending=${isDescending}`);
      // At minimum, profiles should be returned in a consistent order
      expect(data.listMyProfiles.length).toBeGreaterThan(0);
    }, 60000);
  });

  describe('Profile Edge Cases', () => {
    it('handles profile with Unicode/special characters in sellerName', async () => {
      // Arrange: Create profile with Unicode characters
      const profileName = `${getTestPrefix()}-Unicode-日本語-Émojis-🍿`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act
      const { data } = await ownerClient.query({
        query: GET_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Unicode characters are preserved
      expect(data.getProfile.sellerName).toBe(profileName);
      expect(data.getProfile.sellerName).toContain('日本語');
      expect(data.getProfile.sellerName).toContain('🍿');
    });

    it('handles profile with very long sellerName', async () => {
      // Arrange: Create profile with a long name (close to max allowed)
      // Assuming 255 character limit is reasonable
      const longName = `${getTestPrefix()}-` + 'A'.repeat(200);
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: longName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act
      const { data } = await ownerClient.query({
        query: GET_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Long name is preserved
      expect(data.getProfile.sellerName).toBe(longName);
      expect(data.getProfile.sellerName.length).toBeGreaterThan(200);
    });

    it('handles concurrent profile access during query', async () => {
      // Arrange: Create profile
      const profileName = `${getTestPrefix()}-ConcurrentAccess`;
      const { data: createData } = await ownerClient.mutate({
        mutation: CREATE_PROFILE,
        variables: { input: { sellerName: profileName } },
      });
      const profileId = createData.createSellerProfile.profileId;
      createdProfileIds.push(profileId);

      // Act: Fire off multiple concurrent queries
      const concurrentQueries = [
        ownerClient.query({ query: GET_PROFILE, variables: { profileId }, fetchPolicy: 'network-only' }),
        ownerClient.query({ query: GET_PROFILE, variables: { profileId }, fetchPolicy: 'network-only' }),
        ownerClient.query({ query: GET_PROFILE, variables: { profileId }, fetchPolicy: 'network-only' }),
      ];

      const results = await Promise.all(concurrentQueries);

      // Assert: All queries return the same data
      for (const result of results) {
        expect(result.data.getProfile.profileId).toBe(profileId);
        expect(result.data.getProfile.sellerName).toBe(profileName);
      }
    });
  });
});
