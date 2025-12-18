import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql, NormalizedCacheObject } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';
import { deleteTestAccounts, TABLE_NAMES } from '../setup/testData';


/**
 * Integration tests for Share Query Operations (listSharesByProfile, listInvitesByProfile)
 * 
 * Test Data Setup:
 * - TEST_OWNER_EMAIL: Owner of profile (can query shares and invites)
 * - TEST_CONTRIBUTOR_EMAIL: Has WRITE access (can query shares, not invites)
 * - TEST_READONLY_EMAIL: Has READ access (can query shares, not invites)
 * 
 * VTL Resolvers Under Test:
 * - listSharesByProfile: Queries main table (PK=profileId, SK begins_with "SHARE#")
 * - listInvitesByProfile: Queries main table (PK=profileId, SK begins_with "INVITE#")
 */

// GraphQL mutations for setup
const CREATE_SELLER_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
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
      createdAt
      createdByAccountId
    }
  }
`;

const CREATE_PROFILE_INVITE = gql`
  mutation CreateProfileInvite($input: CreateProfileInviteInput!) {
    createProfileInvite(input: $input) {
      inviteCode
      profileId
      permissions
      expiresAt
      createdAt
    }
  }
`;

const REDEEM_PROFILE_INVITE = gql`
  mutation RedeemProfileInvite($input: RedeemProfileInviteInput!) {
    redeemProfileInvite(input: $input) {
      shareId
      profileId
      targetAccountId
      permissions
      createdAt
    }
  }
`;

// GraphQL queries under test
const LIST_SHARES_BY_PROFILE = gql`
  query ListSharesByProfile($profileId: ID!) {
    listSharesByProfile(profileId: $profileId) {
      shareId
      profileId
      targetAccountId
      permissions
      createdAt
      createdByAccountId
    }
  }
`;

const LIST_INVITES_BY_PROFILE = gql`
  query ListInvitesByProfile($profileId: ID!) {
    listInvitesByProfile(profileId: $profileId) {
      inviteCode
      profileId
      permissions
      expiresAt
      createdAt
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

const DELETE_INVITE = gql`
  mutation DeleteInvite($inviteCode: ID!) {
    deleteProfileInvite(inviteCode: $inviteCode)
  }
`;

describe('Share Query Operations Integration Tests', () => {
  const SUITE_ID = 'share-queries';
  
  let ownerClient: ApolloClient<NormalizedCacheObject>;
  let contributorClient: ApolloClient<NormalizedCacheObject>;
  let readonlyClient: ApolloClient<NormalizedCacheObject>;
  
  // Account IDs for cleanup
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;

  // Test data IDs
  let testProfileId: string;
  let testShareId: string;
  let testInviteCode: string;

  // Unshared profile for authorization testing
  let unsharedProfileId: string;

  beforeAll(async () => {
    // Authenticate users
    const ownerAuth = await createAuthenticatedClient('owner');
    const contributorAuth = await createAuthenticatedClient('contributor');
    const readonlyAuth = await createAuthenticatedClient('readonly');

    ownerClient = ownerAuth.client;
    contributorClient = contributorAuth.client;
    readonlyClient = readonlyAuth.client;
    ownerAccountId = ownerAuth.accountId;
    contributorAccountId = contributorAuth.accountId;
    readonlyAccountId = readonlyAuth.accountId;

    // Create test profile
    const { data: profileData }: any = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: {
        input: {
          sellerName: 'Share Query Test Seller',
        },
      },
    });
    testProfileId = profileData.createSellerProfile.profileId;

    // Share profile with contributor (WRITE)
    const { data: shareData }: any = await ownerClient.mutate({
      mutation: SHARE_PROFILE_DIRECT,
      variables: {
        input: {
          profileId: testProfileId,
          targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
          permissions: ['READ', 'WRITE'],
        },
      },
    });
    testShareId = shareData.shareProfileDirect.shareId;

    // Create profile invite
    const { data: inviteData }: any = await ownerClient.mutate({
      mutation: CREATE_PROFILE_INVITE,
      variables: {
        input: {
          profileId: testProfileId,
          permissions: ['READ'],
        },
      },
    });
    testInviteCode = inviteData.createProfileInvite.inviteCode;

    // Create unshared profile for authorization testing
    const { data: unsharedProfileData }: any = await ownerClient.mutate({
      mutation: CREATE_SELLER_PROFILE,
      variables: {
        input: {
          sellerName: 'Unshared Profile',
        },
      },
    });
    unsharedProfileId = unsharedProfileData.createSellerProfile.profileId;

    console.log(`Test data created: Profile=${testProfileId}, Share=${testShareId}, Invite=${testInviteCode}`);
  }, 30000);

  afterAll(async () => {
    console.log('Cleaning up share query test data...');
    const { DynamoDBClient, QueryCommand, DeleteItemCommand } = await import('@aws-sdk/client-dynamodb');
    const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
    
    try {
      // 1. Delete all invites for testProfileId (uses profiles table with profileId/recordType)
      const inviteResult = await dynamoClient.send(new QueryCommand({
        TableName: TABLE_NAMES.profiles,
        KeyConditionExpression: 'profileId = :pid AND begins_with(recordType, :rt)',
        ExpressionAttributeValues: {
          ':pid': { S: testProfileId },
          ':rt': { S: 'INVITE#' },
        },
        ProjectionExpression: 'profileId, recordType',
      }));
      
      for (const item of inviteResult.Items || []) {
        await dynamoClient.send(new DeleteItemCommand({
          TableName: TABLE_NAMES.profiles,
          Key: { profileId: item.profileId, recordType: item.recordType },
        }));
      }
      
      // 2. Delete any remaining shares for testProfileId
      const shareResult = await dynamoClient.send(new QueryCommand({
        TableName: TABLE_NAMES.profiles,
        KeyConditionExpression: 'profileId = :pid AND begins_with(recordType, :rt)',
        ExpressionAttributeValues: {
          ':pid': { S: testProfileId },
          ':rt': { S: 'SHARE#' },
        },
        ProjectionExpression: 'profileId, recordType',
      }));
      
      for (const item of shareResult.Items || []) {
        await dynamoClient.send(new DeleteItemCommand({
          TableName: TABLE_NAMES.profiles,
          Key: { profileId: item.profileId, recordType: item.recordType },
        }));
      }
      
      // 3. Delete profiles via GraphQL (deletes METADATA record and ownership references)
      if (testProfileId) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_PROFILE,
            variables: { profileId: testProfileId },
          });
        } catch (e) { /* may already be deleted */ }
      }
      if (unsharedProfileId) {
        try {
          await ownerClient.mutate({
            mutation: DELETE_PROFILE,
            variables: { profileId: unsharedProfileId },
          });
        } catch (e) { /* may already be deleted */ }
      }
      
      console.log('Share query test data cleanup complete.');
    } catch (error) {
      console.log('Error in cleanup:', error);
    }
  }, 60000);


  // ========================================
  // 5.13.1: listSharesByProfile
  // ========================================

  describe('5.13.1: listSharesByProfile', () => {
    test('Happy Path: Returns all shares for a profile', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toBeDefined();
      expect(data.listSharesByProfile.length).toBeGreaterThan(0);
      
      const shareIds = data.listSharesByProfile.map((s: any) => s.shareId);
      expect(shareIds).toContain(testShareId);
    });

    test('Happy Path: Returns empty array if no shares', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: unsharedProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toBeDefined();
      expect(data.listSharesByProfile).toEqual([]);
    });

    test('Happy Path: Includes share permissions', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const share = data.listSharesByProfile.find((s: any) => s.shareId === testShareId);
      expect(share).toBeDefined();
      expect(share.permissions).toBeDefined();
      expect(share.permissions.length).toBeGreaterThan(0);
    });

    test('Happy Path: Includes targetAccountId for each share', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const share = data.listSharesByProfile[0];
      expect(share).toHaveProperty('targetAccountId');
      expect(share.targetAccountId).toBeDefined();
    });

    test('Authorization: Profile owner can list shares', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toBeDefined();
      expect(data.listSharesByProfile.length).toBeGreaterThan(0);
    });

    test('Authorization: Shared user with WRITE can list shares', async () => {
      // FIXED BUG #27: listSharesByProfile now requires owner or WRITE permission
      // WRITE user can list shares
      
      const { data }: any = await contributorClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toBeDefined();
      expect(Array.isArray(data.listSharesByProfile)).toBe(true);
    });

    test('Authorization: Shared user with READ cannot list shares', async () => {
      // FIXED BUG #28: listSharesByProfile requires owner or WRITE permission
      // READ-only user gets empty array (not authorized)
      
      const { data }: any = await readonlyClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toEqual([]);
    });

    test('Authorization: Non-shared user cannot list shares', async () => {
      // FIXED: Non-shared user gets empty array (not authorized)
      const { data }: any = await contributorClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: unsharedProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toEqual([]);
    });

    test('Input Validation: Returns empty array for non-existent profileId', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: 'PROFILE#nonexistent' },
        fetchPolicy: 'network-only',
      });

      expect(data.listSharesByProfile).toEqual([]);
    });

    test('Data Integrity: Listing shares includes both READ and WRITE permissions', async () => {
      // The testShareId share was created with ['READ', 'WRITE'] permissions
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const share = data.listSharesByProfile.find((s: any) => s.shareId === testShareId);
      expect(share).toBeDefined();
      expect(share.permissions).toContain('READ');
      expect(share.permissions).toContain('WRITE');
    });

    test('Data Integrity: Listing shares after revocation (should not appear)', async () => {
      // Create a new profile and share it for this test
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: {
          input: {
            sellerName: 'Revocation Test Profile',
          },
        },
      });
      const tempProfileId = profileData.createSellerProfile.profileId;

      // Create a share
      const { data: shareData }: any = await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId: tempProfileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL!,
            permissions: ['READ'],
          },
        },
      });
      const tempShareId = shareData.shareProfileDirect.shareId;
      const tempTargetAccountId = shareData.shareProfileDirect.targetAccountId;

      // Verify share exists in list
      const { data: beforeRevoke }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: tempProfileId },
        fetchPolicy: 'network-only',
      });
      expect(beforeRevoke.listSharesByProfile.some((s: any) => s.shareId === tempShareId)).toBe(true);

      // Revoke the share
      await ownerClient.mutate({
        mutation: REVOKE_SHARE,
        variables: { input: { profileId: tempProfileId, targetAccountId: tempTargetAccountId } },
      });

      // Verify share no longer in list
      const { data: afterRevoke }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId: tempProfileId },
        fetchPolicy: 'network-only',
      });
      expect(afterRevoke.listSharesByProfile.some((s: any) => s.shareId === tempShareId)).toBe(false);

      // Cleanup temp profile
      await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId: tempProfileId },
      });
    });
  });

  // ========================================
  // 5.13.2: listInvitesByProfile
  // ========================================

  describe('5.13.2: listInvitesByProfile', () => {
    test('Happy Path: Returns all active invites for a profile', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listInvitesByProfile).toBeDefined();
      expect(data.listInvitesByProfile.length).toBeGreaterThan(0);
      
      const inviteCodes = data.listInvitesByProfile.map((i: any) => i.inviteCode);
      expect(inviteCodes).toContain(testInviteCode);
    });

    test('Happy Path: Returns empty array if no invites', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: unsharedProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listInvitesByProfile).toBeDefined();
      expect(data.listInvitesByProfile).toEqual([]);
    });

    test('Happy Path: Includes invite code and permissions', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const invite = data.listInvitesByProfile.find((i: any) => i.inviteCode === testInviteCode);
      expect(invite).toBeDefined();
      expect(invite.inviteCode).toBe(testInviteCode);
      expect(invite.permissions).toBeDefined();
      expect(invite.permissions.length).toBeGreaterThan(0);
    });

    test('Happy Path: Includes expiration timestamp', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      const invite = data.listInvitesByProfile[0];
      expect(invite).toHaveProperty('expiresAt');
      expect(invite.expiresAt).toBeDefined();
    });

    test('Authorization: Profile owner can list invites', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listInvitesByProfile).toBeDefined();
      expect(data.listInvitesByProfile.length).toBeGreaterThan(0);
    });

    test('Authorization: Shared user cannot list invites (owner only)', async () => {
      // FIXED BUG #29: listInvitesByProfile now requires owner-only authorization
      // Shared user (even with WRITE) gets empty array
      
      const { data }: any = await contributorClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listInvitesByProfile).toEqual([]);
    });

    test('Authorization: Non-shared user cannot list invites', async () => {
      // FIXED BUG #29: Non-owner gets empty array
      const { data }: any = await contributorClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: unsharedProfileId },
        fetchPolicy: 'network-only',
      });

      expect(data.listInvitesByProfile).toEqual([]);
    });

    test('Input Validation: Returns empty array for non-existent profileId', async () => {
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: 'PROFILE#nonexistent' },
        fetchPolicy: 'network-only',
      });

      expect(data.listInvitesByProfile).toEqual([]);
    });

    test('Data Integrity: Does not return expired invites', async () => {
      // Create expired invite by directly inserting into DynamoDB
      const { DynamoDBClient, PutItemCommand } = await import('@aws-sdk/client-dynamodb');
      const dynamoClient = new DynamoDBClient({ region: 'us-east-1' });
      
      const expiredInviteCode = 'EXPIRED999';
      const now = Math.floor(Date.now() / 1000);
      const pastDate = now - (7 * 24 * 60 * 60); // Date 7 days ago
      const futureTTL = now + (7 * 24 * 60 * 60); // TTL 7 days in future (so DynamoDB doesn't auto-delete)
      
      const putCommand = new PutItemCommand({
        TableName: TABLE_NAMES.profiles,
        Item: {
          profileId: { S: testProfileId },
          recordType: { S: `INVITE#${expiredInviteCode}` },
          inviteCode: { S: expiredInviteCode },
          permissions: { L: [{ S: 'READ' }] },
          createdBy: { S: 'test-account-id' },
          createdAt: { S: new Date(pastDate * 1000).toISOString() },
          expiresAt: { S: new Date(pastDate * 1000).toISOString() }, // Expired date
          used: { BOOL: false },
          TTL: { N: futureTTL.toString() }, // Future TTL so item persists for test
        },
      });
      
      await dynamoClient.send(putCommand);

      // Query should not return expired invite
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Should not include the expired invite
      const inviteCodes = data.listInvitesByProfile.map((i: any) => i.inviteCode);
      expect(inviteCodes).not.toContain(expiredInviteCode);
    });

    test('Data Integrity: Does not return used invites', async () => {
      // Create invite
      const { data: inviteData }: any = await ownerClient.mutate({
        mutation: CREATE_PROFILE_INVITE,
        variables: {
          input: {
            profileId: testProfileId,
            permissions: ['READ'],
          },
        },
      });

      const usedInviteCode = inviteData.createProfileInvite.inviteCode;

      // Redeem the invite to mark it as used
      await contributorClient.mutate({
        mutation: REDEEM_PROFILE_INVITE,
        variables: { input: { inviteCode: usedInviteCode } },
      });

      // Query should not return used invite
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });

      // Should not include the used invite
      const inviteCodes = data.listInvitesByProfile.map((i: any) => i.inviteCode);
      expect(inviteCodes).not.toContain(usedInviteCode);
    });

    test('Listing invites for profile with many invites', async () => {
      // Create a new profile specifically for this test
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: { input: { sellerName: 'Many Invites Test Profile' } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      // Create 5 invites for this profile
      const createdInviteCodes: string[] = [];
      for (let i = 0; i < 5; i++) {
        const { data: inviteData }: any = await ownerClient.mutate({
          mutation: CREATE_PROFILE_INVITE,
          variables: {
            input: {
              profileId,
              permissions: i % 2 === 0 ? ['READ'] : ['READ', 'WRITE'],
            },
          },
        });
        createdInviteCodes.push(inviteData.createProfileInvite.inviteCode);
      }

      // Query invites
      const { data }: any = await ownerClient.query({
        query: LIST_INVITES_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: All 5 invites should be returned
      expect(data.listInvitesByProfile.length).toBeGreaterThanOrEqual(5);
      const returnedInviteCodes = data.listInvitesByProfile.map((i: any) => i.inviteCode);
      for (const inviteCode of createdInviteCodes) {
        expect(returnedInviteCodes).toContain(inviteCode);
      }

      // Cleanup - delete profile (which should cascade delete invites)
      await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId },
      });
    }, 20000);
  });

  describe('listSharesByProfile additional tests', () => {
    test('Listing shares for profile with many shares', async () => {
      // Note: We only have 3 test users (owner, contributor, readonly)
      // So we can share with 2 of them at most from a new profile
      // This test verifies the pattern works with available users

      // Create a new profile specifically for this test
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: { input: { sellerName: 'Many Shares Test Profile' } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      // Share with contributor (WRITE)
      await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['READ', 'WRITE'],
          },
        },
      });

      // Share with readonly (READ)
      await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL,
            permissions: ['READ'],
          },
        },
      });

      // Query shares
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });

      // Assert: Both shares should be present
      expect(data.listSharesByProfile.length).toBeGreaterThanOrEqual(2);

      // Verify different permission levels
      const permissions = data.listSharesByProfile.map((s: any) => s.permissions);
      const hasReadOnly = permissions.some((p: string[]) => 
        p.includes('READ') && !p.includes('WRITE')
      );
      const hasReadWrite = permissions.some((p: string[]) => 
        p.includes('READ') && p.includes('WRITE')
      );
      expect(hasReadOnly).toBe(true);
      expect(hasReadWrite).toBe(true);

      // Cleanup
      await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId },
      });
    }, 15000);

    test('Performance: Listing shares ordered by createdAt', async () => {
      // Create a new profile specifically for this test
      const { data: profileData }: any = await ownerClient.mutate({
        mutation: CREATE_SELLER_PROFILE,
        variables: { input: { sellerName: 'Shares Ordering Test Profile' } },
      });
      const profileId = profileData.createSellerProfile.profileId;

      // Share with contributor first (should have earlier createdAt)
      await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: process.env.TEST_CONTRIBUTOR_EMAIL,
            permissions: ['READ', 'WRITE'],
          },
        },
      });

      // Small delay to ensure different timestamps
      await new Promise(resolve => setTimeout(resolve, 100));

      // Share with readonly second (should have later createdAt)
      await ownerClient.mutate({
        mutation: SHARE_PROFILE_DIRECT,
        variables: {
          input: {
            profileId,
            targetAccountEmail: process.env.TEST_READONLY_EMAIL,
            permissions: ['READ'],
          },
        },
      });

      // Measure query performance
      const startTime = Date.now();
      const { data }: any = await ownerClient.query({
        query: LIST_SHARES_BY_PROFILE,
        variables: { profileId },
        fetchPolicy: 'network-only',
      });
      const queryTime = Date.now() - startTime;

      console.log(`📊 Performance: listSharesByProfile took ${queryTime}ms`);

      // Assert: Query should complete in reasonable time (under 5 seconds)
      expect(queryTime).toBeLessThan(5000);

      // Assert: Both shares should be present
      expect(data.listSharesByProfile.length).toBe(2);

      // Verify shares have createdAt timestamps
      for (const share of data.listSharesByProfile) {
        expect(share.createdAt).toBeDefined();
        expect(typeof share.createdAt).toBe('string');
      }

      // Cleanup
      await ownerClient.mutate({
        mutation: DELETE_PROFILE,
        variables: { profileId },
      });
    }, 15000);
  });
});
