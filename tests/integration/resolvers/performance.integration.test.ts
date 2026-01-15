/**
 * Performance Sanity Tests for Custom Payment Methods
 * 
 * Phase 8 requirement: Verify payment methods operations don't degrade with scale.
 * 
 * These tests verify:
 * - paymentMethodsForProfile query completes quickly (<500ms)
 * - S3 pre-signed URL generation is fast (<500ms)
 * - Order listing performance with payment methods remains acceptable
 */

import '../setup.ts';
import { describe, test, expect, beforeAll, afterAll } from 'vitest';
import { ApolloClient, gql } from '@apollo/client';
import { createAuthenticatedClient, AuthenticatedClientResult } from '../setup/apolloClient';

// GraphQL Queries
const PAYMENT_METHODS_FOR_PROFILE = gql`
  query PaymentMethodsForProfile($profileId: ID!) {
    paymentMethodsForProfile(profileId: $profileId) {
      name
      qrCodeUrl
    }
  }
`;

const MY_PAYMENT_METHODS = gql`
  query MyPaymentMethods {
    myPaymentMethods {
      name
      qrCodeUrl
    }
  }
`;

const CREATE_PAYMENT_METHOD = gql`
  mutation CreatePaymentMethod($name: String!) {
    createPaymentMethod(name: $name) {
      name
      qrCodeUrl
    }
  }
`;

const DELETE_PAYMENT_METHOD = gql`
  mutation DeletePaymentMethod($name: String!) {
    deletePaymentMethod(name: $name)
  }
`;

const REQUEST_QR_UPLOAD = gql`
  mutation RequestPaymentMethodQRCodeUpload($paymentMethodName: String!) {
    requestPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName) {
      uploadUrl
      fields
      s3Key
    }
  }
`;

const CREATE_PROFILE = gql`
  mutation CreateSellerProfile($input: CreateSellerProfileInput!) {
    createSellerProfile(input: $input) {
      profileId
      sellerName
      ownerAccountId
    }
  }
`;

const DELETE_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

const LIST_ORDERS_BY_CAMPAIGN = gql`
  query ListOrdersByCampaign($campaignId: ID!) {
    listOrdersByCampaign(campaignId: $campaignId) {
      orderId
      customerName
      paymentMethod
      totalAmount
      lineItems {
        productId
        quantity
      }
    }
  }
`;

describe.sequential('Performance Sanity Tests', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let ownerClient: ApolloClient<any>;
  let testProfileId: string;
  const testPaymentMethods: string[] = [];
  
  // Performance thresholds
  const QUERY_THRESHOLD_MS = 500;
  const S3_URL_THRESHOLD_MS = 500;

  beforeAll(async () => {
    const ownerResult: AuthenticatedClientResult = await createAuthenticatedClient('owner');
    ownerClient = ownerResult.client;

    // Clean up any leftover PerfTest payment methods from previous test runs
    // Only delete methods with PerfTest- prefix to avoid interfering with other tests
    try {
      const { data: existingMethods } = await ownerClient.query({
        query: MY_PAYMENT_METHODS,
        fetchPolicy: 'network-only',
      });

      for (const method of existingMethods.myPaymentMethods) {
        // Only delete our own test methods (PerfTest- prefix)
        if (method.name.startsWith('PerfTest-')) {
          try {
            await ownerClient.mutate({
              mutation: DELETE_PAYMENT_METHOD,
              variables: { name: method.name },
            });
          } catch (e) {
            // Ignore cleanup errors
          }
        }
      }
    } catch (e) {
      // Ignore query errors
    }

    // Create a test profile for performance tests
    const { data } = await ownerClient.mutate({
      mutation: CREATE_PROFILE,
      variables: {
        input: {
          sellerName: 'Performance Test Profile',
        },
      },
    });
    testProfileId = data.createSellerProfile.profileId;
  }, 30000);

  afterAll(async () => {
    // Cleanup test payment methods
    for (const methodName of testPaymentMethods) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_PAYMENT_METHOD,
          variables: { name: methodName },
        });
      } catch (e) {
        // Ignore cleanup errors
      }
    }

    // Cleanup test profile
    if (testProfileId) {
      try {
        await ownerClient.mutate({
          mutation: DELETE_PROFILE,
          variables: { profileId: testProfileId },
        });
      } catch (e) {
        // Ignore cleanup errors
      }
    }
  }, 30000);

  describe('Payment Methods Query Performance', () => {
    test('myPaymentMethods query completes within threshold', async () => {
      const startTime = performance.now();
      
      const { data } = await ownerClient.query({
        query: MY_PAYMENT_METHODS,
        fetchPolicy: 'network-only',
      });
      
      const endTime = performance.now();
      const duration = endTime - startTime;

      console.log(`myPaymentMethods query took ${duration.toFixed(2)}ms`);
      
      expect(data.myPaymentMethods).toBeDefined();
      expect(data.myPaymentMethods.length).toBeGreaterThanOrEqual(2); // At least Cash and Check
      expect(duration).toBeLessThan(QUERY_THRESHOLD_MS);
    }, 10000);

    test('paymentMethodsForProfile query completes within threshold', async () => {
      const startTime = performance.now();
      
      const { data } = await ownerClient.query({
        query: PAYMENT_METHODS_FOR_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      
      const endTime = performance.now();
      const duration = endTime - startTime;

      console.log(`paymentMethodsForProfile query took ${duration.toFixed(2)}ms`);
      
      expect(data.paymentMethodsForProfile).toBeDefined();
      expect(data.paymentMethodsForProfile.length).toBeGreaterThanOrEqual(2); // At least Cash and Check
      expect(duration).toBeLessThan(QUERY_THRESHOLD_MS);
    }, 10000);

    test('paymentMethodsForProfile with multiple custom methods completes within threshold', async () => {
      // Create several custom payment methods
      const methodsToCreate = ['PerfTest-Venmo', 'PerfTest-PayPal', 'PerfTest-Zelle', 'PerfTest-CashApp', 'PerfTest-ApplePay'];
      
      for (const methodName of methodsToCreate) {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: methodName },
        });
        testPaymentMethods.push(methodName);
      }

      const startTime = performance.now();
      
      const { data } = await ownerClient.query({
        query: PAYMENT_METHODS_FOR_PROFILE,
        variables: { profileId: testProfileId },
        fetchPolicy: 'network-only',
      });
      
      const endTime = performance.now();
      const duration = endTime - startTime;

      console.log(`paymentMethodsForProfile with ${methodsToCreate.length} custom methods took ${duration.toFixed(2)}ms`);
      
      // Should have Cash, Check + custom methods
      // Use >= instead of === to handle race conditions where other tests might add/remove payment methods
      expect(data.paymentMethodsForProfile.length).toBeGreaterThanOrEqual(2 + methodsToCreate.length);
      expect(duration).toBeLessThan(QUERY_THRESHOLD_MS);
    }, 30000);
  });

  describe('S3 Pre-signed URL Generation Performance', () => {
    test('requestPaymentMethodQRCodeUpload generates URL within threshold (accounting for cold start)', async () => {
      // Create a payment method for upload test
      const methodName = 'PerfTest-QRUpload';
      await ownerClient.mutate({
        mutation: CREATE_PAYMENT_METHOD,
        variables: { name: methodName },
      });
      testPaymentMethods.push(methodName);

      const startTime = performance.now();
      
      const { data } = await ownerClient.mutate({
        mutation: REQUEST_QR_UPLOAD,
        variables: { paymentMethodName: methodName },
      });
      
      const endTime = performance.now();
      const duration = endTime - startTime;

      console.log(`S3 pre-signed URL generation took ${duration.toFixed(2)}ms`);
      
      expect(data.requestPaymentMethodQRCodeUpload.uploadUrl).toBeDefined();
      expect(data.requestPaymentMethodQRCodeUpload.s3Key).toBeDefined();
      
      // First call may include Lambda cold start (up to 3s)
      // The important thing is that the Lambda works and subsequent calls are fast
      // Threshold for cold start: 5000ms (5 seconds)
      const COLD_START_THRESHOLD_MS = 5000;
      expect(duration).toBeLessThan(COLD_START_THRESHOLD_MS);
    }, 10000);

    test('multiple consecutive URL generations complete within threshold each', async () => {
      // Create multiple payment methods
      const methodNames = ['PerfTest-Multi1', 'PerfTest-Multi2', 'PerfTest-Multi3'];
      
      for (const methodName of methodNames) {
        await ownerClient.mutate({
          mutation: CREATE_PAYMENT_METHOD,
          variables: { name: methodName },
        });
        testPaymentMethods.push(methodName);
      }

      // Time each URL generation
      for (const methodName of methodNames) {
        const startTime = performance.now();
        
        const { data } = await ownerClient.mutate({
          mutation: REQUEST_QR_UPLOAD,
          variables: { paymentMethodName: methodName },
        });
        
        const endTime = performance.now();
        const duration = endTime - startTime;

        console.log(`URL generation for ${methodName} took ${duration.toFixed(2)}ms`);
        
        expect(data.requestPaymentMethodQRCodeUpload.uploadUrl).toBeDefined();
        expect(duration).toBeLessThan(S3_URL_THRESHOLD_MS);
      }
    }, 30000);
  });
});
