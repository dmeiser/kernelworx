/**
 * GraphQL queries and mutations for the app
 */

import { gql } from "@apollo/client";

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

export const SEASON_FRAGMENT = gql`
  fragment SeasonFields on Season {
    seasonId
    profileId
    seasonName
    seasonYear
    startDate
    endDate
    catalogId
    unitType
    unitNumber
    city
    state
    prefillCode
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
    seasonId
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
    ownerAccountId
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

export const LIST_SEASONS_BY_PROFILE = gql`
  ${SEASON_FRAGMENT}
  query ListSeasonsByProfile($profileId: ID!) {
    listSeasonsByProfile(profileId: $profileId) {
      ...SeasonFields
    }
  }
`;

export const GET_SEASON = gql`
  ${SEASON_FRAGMENT}
  query GetSeason($seasonId: ID!) {
    getSeason(seasonId: $seasonId) {
      ...SeasonFields
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

export const LIST_ORDERS_BY_SEASON = gql`
  ${ORDER_FRAGMENT}
  query ListOrdersBySeason($seasonId: ID!) {
    listOrdersBySeason(seasonId: $seasonId) {
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

export const LIST_PUBLIC_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query ListPublicCatalogs {
    listPublicCatalogs {
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
    updateSellerProfile(
      input: { profileId: $profileId, sellerName: $sellerName }
    ) {
      ...SellerProfileFields
    }
  }
`;

export const DELETE_SELLER_PROFILE = gql`
  mutation DeleteSellerProfile($profileId: ID!) {
    deleteSellerProfile(profileId: $profileId)
  }
`;

export const CREATE_SEASON = gql`
  ${SEASON_FRAGMENT}
  mutation CreateSeason($input: CreateSeasonInput!) {
    createSeason(input: $input) {
      ...SeasonFields
    }
  }
`;

export const UPDATE_SEASON = gql`
  ${SEASON_FRAGMENT}
  mutation UpdateSeason($input: UpdateSeasonInput!) {
    updateSeason(input: $input) {
      ...SeasonFields
    }
  }
`;

export const DELETE_SEASON = gql`
  mutation DeleteSeason($seasonId: ID!) {
    deleteSeason(seasonId: $seasonId)
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

export const REQUEST_SEASON_REPORT = gql`
  mutation RequestSeasonReport($input: RequestSeasonReportInput!) {
    requestSeasonReport(input: $input) {
      reportId
      seasonId
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
    $seasonName: String!
    $seasonYear: Int!
    $catalogId: ID!
  ) {
    getUnitReport(
      unitType: $unitType
      unitNumber: $unitNumber
      seasonName: $seasonName
      seasonYear: $seasonYear
      catalogId: $catalogId
    ) {
      unitType
      unitNumber
      seasonName
      seasonYear
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
  query ListUnitCatalogs(
    $unitType: String!
    $unitNumber: Int!
    $seasonName: String!
    $seasonYear: Int!
  ) {
    listUnitCatalogs(
      unitType: $unitType
      unitNumber: $unitNumber
      seasonName: $seasonName
      seasonYear: $seasonYear
    ) {
      ...CatalogFields
    }
  }
`;

// ============================================================================
// Campaign Prefill Fragment
// ============================================================================

export const CAMPAIGN_PREFILL_FRAGMENT = gql`
  fragment CampaignPrefillFields on CampaignPrefill {
    prefillCode
    catalogId
    catalog {
      catalogId
      catalogName
    }
    seasonName
    seasonYear
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
// Campaign Prefill Queries
// ============================================================================

export const GET_CAMPAIGN_PREFILL = gql`
  ${CAMPAIGN_PREFILL_FRAGMENT}
  query GetCampaignPrefill($prefillCode: String!) {
    getCampaignPrefill(prefillCode: $prefillCode) {
      ...CampaignPrefillFields
    }
  }
`;

export const LIST_MY_CAMPAIGN_PREFILLS = gql`
  ${CAMPAIGN_PREFILL_FRAGMENT}
  query ListMyCampaignPrefills {
    listMyCampaignPrefills {
      ...CampaignPrefillFields
    }
  }
`;

export const FIND_CAMPAIGN_PREFILLS = gql`
  ${CAMPAIGN_PREFILL_FRAGMENT}
  query FindCampaignPrefills(
    $unitType: String!
    $unitNumber: Int!
    $city: String!
    $state: String!
    $seasonName: String!
    $seasonYear: Int!
  ) {
    findCampaignPrefills(
      unitType: $unitType
      unitNumber: $unitNumber
      city: $city
      state: $state
      seasonName: $seasonName
      seasonYear: $seasonYear
    ) {
      ...CampaignPrefillFields
    }
  }
`;

// ============================================================================
// Unit Season Catalogs Query (replacement for listUnitCatalogs)
// ============================================================================

export const LIST_UNIT_SEASON_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query ListUnitSeasonCatalogs(
    $unitType: String!
    $unitNumber: Int!
    $city: String!
    $state: String!
    $seasonName: String!
    $seasonYear: Int!
  ) {
    listUnitSeasonCatalogs(
      unitType: $unitType
      unitNumber: $unitNumber
      city: $city
      state: $state
      seasonName: $seasonName
      seasonYear: $seasonYear
    ) {
      ...CatalogFields
    }
  }
`;

// ============================================================================
// Campaign Prefill Mutations
// ============================================================================

export const CREATE_CAMPAIGN_PREFILL = gql`
  ${CAMPAIGN_PREFILL_FRAGMENT}
  mutation CreateCampaignPrefill($input: CreateCampaignPrefillInput!) {
    createCampaignPrefill(input: $input) {
      ...CampaignPrefillFields
    }
  }
`;

export const UPDATE_CAMPAIGN_PREFILL = gql`
  ${CAMPAIGN_PREFILL_FRAGMENT}
  mutation UpdateCampaignPrefill($input: UpdateCampaignPrefillInput!) {
    updateCampaignPrefill(input: $input) {
      ...CampaignPrefillFields
    }
  }
`;

export const DELETE_CAMPAIGN_PREFILL = gql`
  mutation DeleteCampaignPrefill($prefillCode: String!) {
    deleteCampaignPrefill(prefillCode: $prefillCode)
  }
`;
