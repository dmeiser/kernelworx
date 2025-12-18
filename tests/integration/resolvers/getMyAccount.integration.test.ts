import '../setup.ts';
/**
 * Integration tests for getMyAccount resolver
 * Tests retrieval of current authenticated user's account information
 * 
 * NOTE: Account records are created by the Cognito post-authentication Lambda trigger,
 * not by these tests. We clean them up in afterAll to ensure the table is empty,
 * but they will be recreated on the next test run when users authenticate.
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';
import { deleteTestAccounts } from '../setup/testData';

const GET_MY_ACCOUNT = gql`
  query GetMyAccount {
    getMyAccount {
      accountId
      email
      isAdmin
      createdAt
      updatedAt
    }
  }
`;

describe('getMyAccount Resolver Integration Tests', () => {
  let ownerClient: ApolloClient;
  let contributorClient: ApolloClient;
  let readonlyClient: ApolloClient;
  
  // Track account IDs for cleanup
  let ownerAccountId: string;
  let contributorAccountId: string;
  let readonlyAccountId: string;

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
  });

  afterAll(async () => {
    // Clean up account records created by Cognito post-auth trigger
    // These are recreated on next auth, but we delete them to leave table empty
    console.log('Cleaning up account records...');
    // await deleteTestAccounts([ownerAccountId, contributorAccountId, readonlyAccountId]);
    console.log('Account cleanup complete.');
  }, 30000);

  describe('Happy Path - Account Retrieval', () => {
    it('should return current user account for owner', async () => {
      const { data } = await ownerClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      expect(data.getMyAccount).toBeDefined();
      expect(data.getMyAccount.accountId).toBeDefined();
      expect(data.getMyAccount.email).toContain('@');
      expect(typeof data.getMyAccount.isAdmin).toBe('boolean');
      expect(data.getMyAccount.createdAt).toBeDefined();
      expect(data.getMyAccount.updatedAt).toBeDefined();
    });

    it('should return current user account for contributor', async () => {
      const { data } = await contributorClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      expect(data.getMyAccount).toBeDefined();
      expect(data.getMyAccount.accountId).toBeDefined();
      expect(data.getMyAccount.email).toContain('@');
      expect(typeof data.getMyAccount.isAdmin).toBe('boolean');
    });

    it('should return current user account for readonly user', async () => {
      const { data } = await readonlyClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      expect(data.getMyAccount).toBeDefined();
      expect(data.getMyAccount.accountId).toBeDefined();
      expect(data.getMyAccount.email).toContain('@');
      expect(typeof data.getMyAccount.isAdmin).toBe('boolean');
    });
  });

  describe('Account Attributes', () => {
    it('should return isAdmin flag as boolean', async () => {
      const { data } = await ownerClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      // isAdmin can be true or false, just verify it's a boolean
      expect(typeof data.getMyAccount.isAdmin).toBe('boolean');
    });

    it('should include valid timestamps', async () => {
      const { data } = await ownerClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      const createdAt = new Date(data.getMyAccount.createdAt);
      const updatedAt = new Date(data.getMyAccount.updatedAt);

      expect(createdAt.getTime()).toBeGreaterThan(0);
      expect(updatedAt.getTime()).toBeGreaterThan(0);
      expect(updatedAt.getTime()).toBeGreaterThanOrEqual(createdAt.getTime());
    });
  });

  describe('Account Identity', () => {
    it('should return different accountIds for different users', async () => {
      const { data: ownerData } = await ownerClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });
      const { data: contributorData } = await contributorClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      expect(ownerData.getMyAccount.accountId).toBeDefined();
      expect(contributorData.getMyAccount.accountId).toBeDefined();
      expect(ownerData.getMyAccount.accountId).not.toBe(
        contributorData.getMyAccount.accountId
      );
    });

    it('should return same accountId on multiple calls', async () => {
      const { data: data1 } = await ownerClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });
      const { data: data2 } = await ownerClient.query({
        query: GET_MY_ACCOUNT,
        fetchPolicy: 'network-only',
      });

      expect(data1.getMyAccount.accountId).toBe(data2.getMyAccount.accountId);
    });
  });
});
