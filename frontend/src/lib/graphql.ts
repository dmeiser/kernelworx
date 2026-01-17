/**
 * GraphQL queries and mutations for the app
 */

import { gql } from '@apollo/client';

// ============================================================================
// Fragments
// ============================================================================

export const SELLER_PROFILE_FRAGMENT = gql`
  fragment SellerProfileFields on SellerProfile {
    profileId
    ownerAccountId
    sellerName
    createdAt
    updatedAt
    isOwner
    permissions
  }
`;

export const CAMPAIGN_FRAGMENT = gql`
  fragment CampaignFields on Campaign {
    campaignId
    profileId
    campaignName
    campaignYear
    startDate
    endDate
    catalogId
    unitType
    unitNumber
    city
    state
    sharedCampaignCode
    createdAt
    updatedAt
    totalOrders
    totalRevenue
  }
`;

export const ORDER_FRAGMENT = gql`
  fragment OrderFields on Order {
    orderId
    profileId
    campaignId
    customerName
    customerPhone
    customerAddress {
      street
      city
      state
      zipCode
    }
    orderDate
    paymentMethod
    lineItems {
      productId
      productName
      quantity
      pricePerUnit
      subtotal
    }
    totalAmount
    notes
    createdAt
    updatedAt
  }
`;

export const CATALOG_FRAGMENT = gql`
  fragment CatalogFields on Catalog {
    catalogId
    catalogName
    catalogType
    isPublic
    products {
      productId
      productName
      description
      price
      sortOrder
    }
    createdAt
    updatedAt
  }
`;

// ============================================================================
// Queries
// ============================================================================

export const GET_MY_ACCOUNT = gql`
  query GetMyAccount {
    getMyAccount {
      accountId
      email
      givenName
      familyName
      city
      state
      unitType
      unitNumber
      preferences
      createdAt
      updatedAt
    }
  }
`;

export const UPDATE_MY_ACCOUNT = gql`
  mutation UpdateMyAccount($input: UpdateMyAccountInput!) {
    updateMyAccount(input: $input) {
      accountId
      email
      givenName
      familyName
      city
      state
      unitType
      unitNumber
      createdAt
      updatedAt
    }
  }
`;

export const UPDATE_MY_PREFERENCES = gql`
  mutation UpdateMyPreferences($preferences: AWSJSON!) {
    updateMyPreferences(preferences: $preferences) {
      accountId
      preferences
    }
  }
`;

export const LIST_MY_PROFILES = gql`
  ${SELLER_PROFILE_FRAGMENT}
  query ListMyProfiles {
    listMyProfiles {
      ...SellerProfileFields
    }
  }
`;

export const LIST_MY_SHARES = gql`
  query ListMyShares {
    listMyShares {
      profileId
      ownerAccountId
      sellerName
      unitType
      unitNumber
      createdAt
      updatedAt
      isOwner
      permissions
    }
  }
`;

export const GET_PROFILE = gql`
  ${SELLER_PROFILE_FRAGMENT}
  query GetProfile($profileId: ID!) {
    getProfile(profileId: $profileId) {
      ...SellerProfileFields
    }
  }
`;

export const LIST_CAMPAIGNS_BY_PROFILE = gql`
  ${CAMPAIGN_FRAGMENT}
  query ListCampaignsByProfile($profileId: ID!) {
    listCampaignsByProfile(profileId: $profileId) {
      ...CampaignFields
    }
  }
`;

export const GET_CAMPAIGN = gql`
  ${CAMPAIGN_FRAGMENT}
  query GetCampaign($campaignId: ID!) {
    getCampaign(campaignId: $campaignId) {
      ...CampaignFields
      catalog {
        catalogId
        catalogName
        products {
          productId
          productName
          description
          price
          sortOrder
        }
      }
    }
  }
`;

export const LIST_ORDERS_BY_CAMPAIGN = gql`
  ${ORDER_FRAGMENT}
  query ListOrdersByCampaign($campaignId: ID!) {
    listOrdersByCampaign(campaignId: $campaignId) {
      ...OrderFields
    }
  }
`;

export const GET_ORDER = gql`
  ${ORDER_FRAGMENT}
  query GetOrder($orderId: ID!) {
    getOrder(orderId: $orderId) {
      ...OrderFields
    }
  }
`;

export const LIST_MANAGED_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query ListManagedCatalogs {
    listManagedCatalogs {
      ...CatalogFields
    }
  }
`;

export const LIST_MY_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query ListMyCatalogs {
    listMyCatalogs {
      ...CatalogFields
    }
  }
`;

export const GET_CATALOG = gql`
  ${CATALOG_FRAGMENT}
  query GetCatalog($catalogId: ID!) {
    getCatalog(catalogId: $catalogId) {
      ...CatalogFields
    }
  }
`;

export const LIST_INVITES_BY_PROFILE = gql`
  query ListInvitesByProfile($profileId: ID!) {
    listInvitesByProfile(profileId: $profileId) {
      inviteCode
      profileId
      permissions
      expiresAt
      createdAt
      createdByAccountId
    }
  }
`;

export const LIST_SHARES_BY_PROFILE = gql`
  query ListSharesByProfile($profileId: ID!) {
    listSharesByProfile(profileId: $profileId) {
      shareId
      profileId
      targetAccountId
      targetAccount {
        email
        givenName
        familyName
      }
      permissions
      createdAt
      createdByAccountId
    }
  }
`;

// ============================================================================
// Mutations
// ============================================================================

export const CREATE_SELLER_PROFILE = gql`
  ${SELLER_PROFILE_FRAGMENT}
  mutation CreateSellerProfile($sellerName: String!) {
    createSellerProfile(input: { sellerName: $sellerName }) {
      ...SellerProfileFields
    }
  }
`;

export const UPDATE_SELLER_PROFILE = gql`
  ${SELLER_PROFILE_FRAGMENT}
  mutation UpdateSellerProfile($profileId: ID!, $sellerName: String!) {
    updateSellerProfile(input: { profileId: $profileId, sellerName: $sellerName }) {
      ...SellerProfileFields
    }
  }
`;

export const DELETE_SELLER_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

export const CREATE_CAMPAIGN = gql`
  ${CAMPAIGN_FRAGMENT}
  mutation CreateCampaign($input: CreateCampaignInput!) {
    createCampaign(input: $input) {
      ...CampaignFields
    }
  }
`;

export const UPDATE_CAMPAIGN = gql`
  ${CAMPAIGN_FRAGMENT}
  mutation UpdateCampaign($input: UpdateCampaignInput!) {
    updateCampaign(input: $input) {
      ...CampaignFields
    }
  }
`;

export const DELETE_CAMPAIGN = gql`
  mutation DeleteCampaign($campaignId: ID!) {
    deleteCampaign(campaignId: $campaignId)
  }
`;

export const CREATE_ORDER = gql`
  ${ORDER_FRAGMENT}
  mutation CreateOrder($input: CreateOrderInput!) {
    createOrder(input: $input) {
      ...OrderFields
    }
  }
`;

export const UPDATE_ORDER = gql`
  ${ORDER_FRAGMENT}
  mutation UpdateOrder($input: UpdateOrderInput!) {
    updateOrder(input: $input) {
      ...OrderFields
    }
  }
`;

export const DELETE_ORDER = gql`
  mutation DeleteOrder($orderId: ID!) {
    deleteOrder(orderId: $orderId)
  }
`;

export const REQUEST_CAMPAIGN_REPORT = gql`
  mutation RequestCampaignReport($input: RequestCampaignReportInput!) {
    requestCampaignReport(input: $input) {
      reportId
      campaignId
      profileId
      reportUrl
      status
      createdAt
      expiresAt
    }
  }
`;

export const CREATE_PROFILE_INVITE = gql`
  mutation CreateProfileInvite($input: CreateProfileInviteInput!) {
    createProfileInvite(input: $input) {
      inviteCode
      profileId
      permissions
      expiresAt
      createdAt
      createdByAccountId
    }
  }
`;

export const REDEEM_PROFILE_INVITE = gql`
  mutation RedeemProfileInvite($input: RedeemProfileInviteInput!) {
    redeemProfileInvite(input: $input) {
      shareId
      profileId
      targetAccountId
      permissions
      createdAt
      createdByAccountId
    }
  }
`;

export const SHARE_PROFILE_DIRECT = gql`
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

export const REVOKE_SHARE = gql`
  mutation RevokeShare($input: RevokeShareInput!) {
    revokeShare(input: $input)
  }
`;

export const TRANSFER_PROFILE_OWNERSHIP = gql`
  ${SELLER_PROFILE_FRAGMENT}
  mutation TransferProfileOwnership($input: TransferProfileOwnershipInput!) {
    transferProfileOwnership(input: $input) {
      ...SellerProfileFields
    }
  }
`;

export const CREATE_CATALOG = gql`
  ${CATALOG_FRAGMENT}
  mutation CreateCatalog($input: CreateCatalogInput!) {
    createCatalog(input: $input) {
      ...CatalogFields
    }
  }
`;

export const UPDATE_CATALOG = gql`
  ${CATALOG_FRAGMENT}
  mutation UpdateCatalog($catalogId: ID!, $input: CreateCatalogInput!) {
    updateCatalog(catalogId: $catalogId, input: $input) {
      ...CatalogFields
    }
  }
`;

export const DELETE_CATALOG = gql`
  mutation DeleteCatalog($catalogId: ID!) {
    deleteCatalog(catalogId: $catalogId)
  }
`;

export const DELETE_PROFILE_INVITE = gql`
  mutation DeleteProfileInvite($profileId: ID!, $inviteCode: ID!) {
    deleteProfileInvite(profileId: $profileId, inviteCode: $inviteCode)
  }
`;

export const GET_UNIT_REPORT = gql`
  query GetUnitReport(
    $unitType: String!
    $unitNumber: Int!
    $city: String
    $state: String
    $campaignName: String!
    $campaignYear: Int!
    $catalogId: ID!
  ) {
    getUnitReport(
      unitType: $unitType
      unitNumber: $unitNumber
      city: $city
      state: $state
      campaignName: $campaignName
      campaignYear: $campaignYear
      catalogId: $catalogId
    ) {
      unitType
      unitNumber
      campaignName
      campaignYear
      totalSales
      totalOrders
      sellers {
        profileId
        sellerName
        totalSales
        orderCount
        orders {
          orderId
          customerName
          orderDate
          totalAmount
          lineItems {
            productId
            productName
            quantity
            pricePerUnit
            subtotal
          }
        }
      }
    }
  }
`;

export const LIST_UNIT_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query ListUnitCatalogs($unitType: String!, $unitNumber: Int!, $campaignName: String!, $campaignYear: Int!) {
    listUnitCatalogs(
      unitType: $unitType
      unitNumber: $unitNumber
      campaignName: $campaignName
      campaignYear: $campaignYear
    ) {
      ...CatalogFields
    }
  }
`;

// ============================================================================
// Campaign shared campaign Fragment
// ============================================================================

export const SHARED_CAMPAIGN_FRAGMENT = gql`
  fragment SharedCampaignFields on SharedCampaign {
    sharedCampaignCode
    catalogId
    catalog {
      catalogId
      catalogName
    }
    campaignName
    campaignYear
    startDate
    endDate
    unitType
    unitNumber
    city
    state
    createdBy
    createdByName
    creatorMessage
    description
    isActive
    createdAt
  }
`;

// ============================================================================
// Campaign shared campaign Queries
// ============================================================================

export const GET_SHARED_CAMPAIGN = gql`
  ${SHARED_CAMPAIGN_FRAGMENT}
  query GetSharedCampaign($sharedCampaignCode: String!) {
    getSharedCampaign(sharedCampaignCode: $sharedCampaignCode) {
      ...SharedCampaignFields
    }
  }
`;

export const LIST_MY_SHARED_CAMPAIGNS = gql`
  ${SHARED_CAMPAIGN_FRAGMENT}
  query ListMySharedCampaigns {
    listMySharedCampaigns {
      ...SharedCampaignFields
    }
  }
`;

export const FIND_SHARED_CAMPAIGNS = gql`
  ${SHARED_CAMPAIGN_FRAGMENT}
  query FindSharedCampaigns(
    $unitType: String!
    $unitNumber: Int!
    $city: String!
    $state: String!
    $campaignName: String!
    $campaignYear: Int!
  ) {
    findSharedCampaigns(
      unitType: $unitType
      unitNumber: $unitNumber
      city: $city
      state: $state
      campaignName: $campaignName
      campaignYear: $campaignYear
    ) {
      ...SharedCampaignFields
    }
  }
`;

// ============================================================================
// Unit Campaign Catalogs Query (replacement for listUnitCatalogs)
// ============================================================================

export const LIST_UNIT_CAMPAIGN_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query ListUnitCampaignCatalogs(
    $unitType: String!
    $unitNumber: Int!
    $city: String!
    $state: String!
    $campaignName: String!
    $campaignYear: Int!
  ) {
    listUnitCampaignCatalogs(
      unitType: $unitType
      unitNumber: $unitNumber
      city: $city
      state: $state
      campaignName: $campaignName
      campaignYear: $campaignYear
    ) {
      ...CatalogFields
    }
  }
`;

// ============================================================================
// Campaign shared campaign Mutations
// ============================================================================

export const CREATE_SHARED_CAMPAIGN = gql`
  ${SHARED_CAMPAIGN_FRAGMENT}
  mutation CreateSharedCampaign($input: CreateSharedCampaignInput!) {
    createSharedCampaign(input: $input) {
      ...SharedCampaignFields
    }
  }
`;

export const UPDATE_SHARED_CAMPAIGN = gql`
  ${SHARED_CAMPAIGN_FRAGMENT}
  mutation UpdateSharedCampaign($input: UpdateSharedCampaignInput!) {
    updateSharedCampaign(input: $input) {
      ...SharedCampaignFields
    }
  }
`;

export const DELETE_SHARED_CAMPAIGN = gql`
  mutation DeleteSharedCampaign($sharedCampaignCode: String!) {
    deleteSharedCampaign(sharedCampaignCode: $sharedCampaignCode)
  }
`;

// ============================================================================
// Payment Methods
// ============================================================================

export const PAYMENT_METHOD_FRAGMENT = gql`
  fragment PaymentMethodFields on PaymentMethod {
    name
    qrCodeUrl
  }
`;

export const GET_MY_PAYMENT_METHODS = gql`
  ${PAYMENT_METHOD_FRAGMENT}
  query GetMyPaymentMethods {
    myPaymentMethods {
      ...PaymentMethodFields
    }
  }
`;

export const GET_PAYMENT_METHODS_FOR_PROFILE = gql`
  ${PAYMENT_METHOD_FRAGMENT}
  query GetPaymentMethodsForProfile($profileId: ID!) {
    paymentMethodsForProfile(profileId: $profileId) {
      ...PaymentMethodFields
    }
  }
`;

export const CREATE_PAYMENT_METHOD = gql`
  ${PAYMENT_METHOD_FRAGMENT}
  mutation CreatePaymentMethod($name: String!) {
    createPaymentMethod(name: $name) {
      ...PaymentMethodFields
    }
  }
`;

export const UPDATE_PAYMENT_METHOD = gql`
  ${PAYMENT_METHOD_FRAGMENT}
  mutation UpdatePaymentMethod($currentName: String!, $newName: String!) {
    updatePaymentMethod(currentName: $currentName, newName: $newName) {
      ...PaymentMethodFields
    }
  }
`;

export const DELETE_PAYMENT_METHOD = gql`
  mutation DeletePaymentMethod($name: String!) {
    deletePaymentMethod(name: $name)
  }
`;

export const REQUEST_PAYMENT_METHOD_QR_UPLOAD = gql`
  mutation RequestPaymentMethodQRUpload($paymentMethodName: String!) {
    requestPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName) {
      uploadUrl
      fields
      s3Key
    }
  }
`;

export const CONFIRM_PAYMENT_METHOD_QR_UPLOAD = gql`
  ${PAYMENT_METHOD_FRAGMENT}
  mutation ConfirmPaymentMethodQRUpload($paymentMethodName: String!, $s3Key: String!) {
    confirmPaymentMethodQRCodeUpload(paymentMethodName: $paymentMethodName, s3Key: $s3Key) {
      ...PaymentMethodFields
    }
  }
`;

export const DELETE_PAYMENT_METHOD_QR_CODE = gql`
  mutation DeletePaymentMethodQRCode($paymentMethodName: String!) {
    deletePaymentMethodQRCode(paymentMethodName: $paymentMethodName)
  }
`;
