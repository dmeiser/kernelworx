import '../setup.ts';
import { test, expect } from 'vitest';
import { gql } from '@apollo/client';
import { createAuthenticatedClient } from '../setup/apolloClient';

// This test reproduces the 'Catalog not found' error observed in the UI
// It targets a specific campaign/profile/product reported by the user.
// SKIPPED: This test is for debugging a specific issue and requires specific test data.

test.skip('reproduce Catalog not found for known campaign', async () => {
  const { client } = await createAuthenticatedClient('owner');

  const CREATE_ORDER = gql`
    mutation CreateOrder($input: CreateOrderInput!) {
      createOrder(input: $input) {
        orderId
        campaignId
      }
    }
  `;

  const input = {
    profileId: 'PROFILE#dd69b3bd-5978-419e-9e55-f7c85817e020',
    campaignId: 'CAMPAIGN#6fdf925c-f700-4134-8199-419c19ea1fe8',
    customerName: 'Repro Test',
    orderDate: new Date().toISOString(),
    paymentMethod: 'CASH',
    lineItems: [
      { productId: 'PRODUCT#17bf118c-cca6-464c-92bc-80bfeb982b0a', quantity: 1 },
    ],
  };

  // First verify that the catalog can be read directly
  const GET_CATALOG = gql`
    query GetCatalog($catalogId: ID!) {
      getCatalog(catalogId: $catalogId) {
        catalogId
        catalogName
        products { productId productName price }
      }
    }
  `;

  const catalogId = 'CATALOG#1b79da85-675c-46e4-8a84-ac369de82162';
  try {
    const { data: catalogData } = await client.query({ query: GET_CATALOG, variables: { catalogId } });
    console.log('getCatalog result:', catalogData);
  } catch (catErr: unknown) {
    console.log('getCatalog error (unexpected):', catErr);
  }

  try {
    const { data, errors } = await client.mutate({ mutation: CREATE_ORDER, variables: { input } });
    console.log('createOrder response data:', data);
    if (errors) {
      console.log('createOrder response errors:', JSON.stringify(errors, null, 2));
    }
    // If we get data, that's a success - assert the order exists
    if (data && data.createOrder && data.createOrder.orderId) {
      console.log('Order created successfully (unexpected for repro):', data.createOrder.orderId);
    }
  } catch (err: unknown) {
    console.log('createOrder threw error (expected for repro):', err);
    // Try again with explicit catalogId in input to test whether that bypasses pipeline lookup
    const inputWithCatalog = { ...input, catalogId: 'CATALOG#1b79da85-675c-46e4-8a84-ac369de82162' };
    try {
      const { data: data2, errors: errors2 } = await client.mutate({ mutation: CREATE_ORDER, variables: { input: inputWithCatalog } });
      console.log('createOrder with explicit catalog response data:', data2);
      if (errors2) console.log('errors:', JSON.stringify(errors2, null, 2));
      if (data2 && data2.createOrder && data2.createOrder.orderId) {
        console.log('Order created successfully when catalogId provided:', data2.createOrder.orderId);
      }
    } catch (err2: unknown) {
      console.log('createOrder with explicit catalog still failed:', err2);
    }

    // Surface the original error so the test fails visibly
    throw err;
  }
}, 20000);
