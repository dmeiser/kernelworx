/**
 * GraphQL operations for the public order pages.
 *
 * These run on the API-key-only client (`lib/publicApollo.ts`), never on the
 * authenticated client: AppSync's auth directives are an exclusive allow-list,
 * so a request carrying a Cognito `Authorization` header is refused outright on
 * a field marked `@aws_api_key` only. Keeping the documents in their own module
 * makes it obvious which operations belong to that client.
 */

import { gql } from '@apollo/client';

/** The offer a buyer sees on /o/:profileId/:token. */
export const PUBLIC_GET_ORDER_OFFER = gql`
  query PublicGetOrderOffer($profileId: ID!, $token: String!) {
    publicGetOrderOffer(profileId: $profileId, token: $token) {
      sellerName
      campaignId
      campaignName
      products {
        productId
        productName
        price
        description
        sortOrder
      }
      paymentMethods {
        name
        qrCodeUrl
      }
    }
  }
`;

/** What publicCreateOrder returns to the success screen. */
export const PUBLIC_CREATE_ORDER = gql`
  mutation PublicCreateOrder($input: PublicCreateOrderInput!) {
    publicCreateOrder(input: $input) {
      orderId
      receiptUrl
      totalAmount
      buyerEmailProvided
      confirmationEmailSent
    }
  }
`;

/** The buyer receipt view on /r/:campaignId/:orderSuffix/:receiptToken. */
export const PUBLIC_GET_ORDER_RECEIPT = gql`
  query PublicGetOrderReceipt($campaignId: ID!, $orderSuffix: ID!, $receiptToken: String!) {
    publicGetOrderReceipt(campaignId: $campaignId, orderSuffix: $orderSuffix, receiptToken: $receiptToken) {
      sellerName
      orderId
      orderDate
      lineItems {
        productId
        productName
        quantity
        pricePerUnit
        subtotal
      }
      totalAmount
      paymentMethodName
      status
      buyerFirstName
      buyerLastName
    }
  }
`;
