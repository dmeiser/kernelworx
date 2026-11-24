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

export const SELLER_PROFILE_WITH_LATEST_CAMPAIGN_FRAGMENT = gql`
  fragment SellerProfileWithLatestCampaignFields on SellerProfile {
    profileId
    ownerAccountId
    sellerName
    createdAt
    updatedAt
    isOwner
    permissions
    latestCampaign {
      campaignId
      campaignName
      campaignYear
      isActive
    }
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
    isActive
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
    status
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

export const DELETE_MY_ACCOUNT = gql`
  mutation DeleteMyAccount {
    deleteMyAccount
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
  ${SELLER_PROFILE_WITH_LATEST_CAMPAIGN_FRAGMENT}
  query ListMyProfiles($limit: Int, $nextToken: String) {
    listMyProfiles(limit: $limit, nextToken: $nextToken) {
      profiles {
        ...SellerProfileWithLatestCampaignFields
      }
      nextToken
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
      latestCampaign {
        campaignId
        campaignName
        campaignYear
        isActive
      }
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
  query ListCampaignsByProfile($profileId: ID!, $limit: Int, $nextToken: String) {
    listCampaignsByProfile(profileId: $profileId, limit: $limit, nextToken: $nextToken) {
      campaigns {
        ...CampaignFields
      }
      nextToken
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
  query ListOrdersByCampaign($campaignId: ID!, $limit: Int, $nextToken: String) {
    listOrdersByCampaign(campaignId: $campaignId, limit: $limit, nextToken: $nextToken) {
      orders {
        ...OrderFields
      }
      nextToken
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

export const LIST_CATALOGS_IN_USE = gql`
  query ListCatalogsInUse {
    listCatalogsInUse
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

// Lightweight list fragment that keeps the nested catalog nullable so a stale
// or deleted catalog does not prevent the shared-campaign list from rendering.
export const SHARED_CAMPAIGN_LIST_FRAGMENT = gql`
  fragment SharedCampaignListFields on SharedCampaign {
    sharedCampaignCode
    catalogId
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
  ${SHARED_CAMPAIGN_LIST_FRAGMENT}
  query ListMySharedCampaigns {
    listMySharedCampaigns {
      ...SharedCampaignListFields
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

// ============================================================================
// Admin Operations (requires ADMIN Cognito group)
// ============================================================================

export const ADMIN_USER_FRAGMENT = gql`
  fragment AdminUserFields on AdminUser {
    accountId
    email
    displayName
    status
    enabled
    emailVerified
    isAdmin
    createdAt
    lastModifiedAt
  }
`;

export const ADMIN_LIST_USERS = gql`
  ${ADMIN_USER_FRAGMENT}
  query AdminListUsers($limit: Int, $nextToken: String) {
    adminListUsers(limit: $limit, nextToken: $nextToken) {
      users {
        ...AdminUserFields
      }
      nextToken
    }
  }
`;

export const ADMIN_SEARCH_USER = gql`
  ${ADMIN_USER_FRAGMENT}
  query AdminSearchUser($query: String!) {
    adminSearchUser(query: $query) {
      ...AdminUserFields
    }
  }
`;

export const ADMIN_GET_USER_PROFILES = gql`
  ${SELLER_PROFILE_FRAGMENT}
  query AdminGetUserProfiles($accountId: ID!) {
    adminGetUserProfiles(accountId: $accountId) {
      ...SellerProfileFields
    }
  }
`;

export const ADMIN_GET_USER_CATALOGS = gql`
  ${CATALOG_FRAGMENT}
  query AdminGetUserCatalogs($accountId: ID!) {
    adminGetUserCatalogs(accountId: $accountId) {
      ...CatalogFields
    }
  }
`;

export const ADMIN_GET_USER_CAMPAIGNS = gql`
  query AdminGetUserCampaigns($accountId: ID!) {
    adminGetUserCampaigns(accountId: $accountId) {
      campaignId
      profileId
      campaignName
      campaignYear
      catalogId
      startDate
      endDate
      sharedCampaignCode
      createdAt
      updatedAt
    }
  }
`;

export const ADMIN_GET_USER_SHARED_CAMPAIGNS = gql`
  query AdminGetUserSharedCampaigns($accountId: ID!) {
    adminGetUserSharedCampaigns(accountId: $accountId) {
      sharedCampaignCode
      catalogId
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
      createdAt
    }
  }
`;

export const ADMIN_GET_PROFILE_SHARES = gql`
  query AdminGetProfileShares($profileId: ID!) {
    adminGetProfileShares(profileId: $profileId) {
      shareId
      profileId
      targetAccountId
      targetAccount {
        accountId
        email
        givenName
        familyName
      }
      permissions
      createdAt
    }
  }
`;

export const ADMIN_RESET_USER_PASSWORD = gql`
  mutation AdminResetUserPassword($email: AWSEmail!) {
    adminResetUserPassword(email: $email)
  }
`;

export const ADMIN_PURGE_USER_ACCOUNT = gql`
  mutation AdminPurgeUserAccount($accountId: ID!, $profileIds: [ID!]!) {
    adminPurgeUserAccount(accountId: $accountId, profileIds: $profileIds)
  }
`;

export const ADMIN_DELETE_USER_ORDERS = gql`
  mutation AdminDeleteUserOrders($accountId: ID!) {
    adminDeleteUserOrders(accountId: $accountId)
  }
`;

export const ADMIN_DELETE_USER_CAMPAIGNS = gql`
  mutation AdminDeleteUserCampaigns($accountId: ID!) {
    adminDeleteUserCampaigns(accountId: $accountId)
  }
`;

export const ADMIN_DELETE_USER_SHARES = gql`
  mutation AdminDeleteUserShares($accountId: ID!) {
    adminDeleteUserShares(accountId: $accountId)
  }
`;

export const ADMIN_DELETE_USER_PROFILES = gql`
  mutation AdminDeleteUserProfiles($accountId: ID!) {
    adminDeleteUserProfiles(accountId: $accountId)
  }
`;

export const ADMIN_DELETE_SHARE = gql`
  mutation AdminDeleteShare($profileId: ID!, $targetAccountId: ID!) {
    adminDeleteShare(profileId: $profileId, targetAccountId: $targetAccountId)
  }
`;

export const ADMIN_UPDATE_CAMPAIGN_SHARED_CODE = gql`
  mutation AdminUpdateCampaignSharedCode($campaignId: ID!, $sharedCampaignCode: String) {
    adminUpdateCampaignSharedCode(campaignId: $campaignId, sharedCampaignCode: $sharedCampaignCode) {
      campaignId
      sharedCampaignCode
    }
  }
`;

export const CREATE_MANAGED_CATALOG = gql`
  ${CATALOG_FRAGMENT}
  mutation CreateManagedCatalog($input: CreateCatalogInput!) {
    createManagedCatalog(input: $input) {
      ...CatalogFields
    }
  }
`;

export const GET_CAMPAIGN_PUBLIC_ORDER_SETTINGS = gql`
  query GetCampaignPublicOrderSettings($campaignId: ID!) {
    getCampaignPublicOrderSettings(campaignId: $campaignId) {
      enabled
      shareToken
      allowedPaymentMethods
      acknowledgedAt
      ackVersion
      publicOrderCount
      campaignId
      campaignName
      campaignState
    }
  }
`;

export const UPDATE_CAMPAIGN_PUBLIC_ORDER_SETTINGS = gql`
  mutation UpdateCampaignPublicOrderSettings($input: UpdateCampaignPublicOrderSettingsInput!) {
    updateCampaignPublicOrderSettings(input: $input) {
      enabled
      shareToken
      allowedPaymentMethods
      acknowledgedAt
      ackVersion
      publicOrderCount
      campaignId
      campaignName
      campaignState
    }
  }
`;

// ============================================================================
// Units and Unit Campaigns (Show & Sell Stage 1)
//
// One section for the whole Stage 1 surface, so the SDL contract (§ Unit,
// UnitCampaign, UnitCampaignMembership, PageInput, VersionedInput,
// IdempotencyInput) is readable in one place. Reads select only the fields a
// screen renders — a projection written out field by field is what keeps a
// later SDL addition from silently widening what the browser holds.
// ============================================================================

export const UNIT_FRAGMENT = gql`
  fragment UnitFields on Unit {
    unitId
    unitType
    unitNumber
    city
    state
    displayName
    timezone
    splitDefault
    councilNeedBasis
    adminCount
    version
    createdAt
    updatedAt
    createdByAccountId
  }
`;

export const UNIT_ACCESS_GRANT_FRAGMENT = gql`
  fragment UnitAccessGrantFields on UnitAccessGrant {
    unitId
    accountId
    role
    email
    name
    createdByAccountId
    createdAt
  }
`;

export const UNIT_INVITE_FRAGMENT = gql`
  fragment UnitInviteFields on UnitInvite {
    inviteCode
    unitId
    createdByAccountId
    createdAt
    expiresAt
  }
`;

export const UNIT_CAMPAIGN_FRAGMENT = gql`
  fragment UnitCampaignFields on UnitCampaignAdmin {
    unitCampaignId
    unitId
    campaignName
    campaignYear
    catalogId
    joinCode
    isActive
    version
    createdAt
    updatedAt
    createdByAccountId
    updatedByAccountId
  }
`;

export const UNIT_CAMPAIGN_MEMBERSHIP_FRAGMENT = gql`
  fragment UnitCampaignMembershipFields on UnitCampaignMembership {
    unitCampaignId
    unitId
    campaignId
    profileId
    scoutName
    campaignName
    scoutCampaignCatalogId
    status
    joinedByAccountId
    joinedAt
    removedByAccountId
    removedAt
    version
    guardVersion
  }
`;

export const MY_UNITS = gql`
  ${UNIT_FRAGMENT}
  query MyUnits($page: PageInput) {
    myUnits(page: $page) {
      items {
        ...UnitFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const GET_UNIT = gql`
  ${UNIT_FRAGMENT}
  query GetUnit($unitId: ID!) {
    unit(unitId: $unitId) {
      ...UnitFields
    }
  }
`;

export const LIST_UNIT_ADMINS = gql`
  ${UNIT_ACCESS_GRANT_FRAGMENT}
  query ListUnitAdmins($unitId: ID!, $page: PageInput) {
    unitAdmins(unitId: $unitId, page: $page) {
      items {
        ...UnitAccessGrantFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const LIST_UNIT_INVITES = gql`
  ${UNIT_INVITE_FRAGMENT}
  query ListUnitInvites($unitId: ID!, $page: PageInput) {
    unitInvites(unitId: $unitId, page: $page) {
      items {
        ...UnitInviteFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const LIST_UNIT_CAMPAIGNS = gql`
  ${UNIT_CAMPAIGN_FRAGMENT}
  query ListUnitCampaigns($unitId: ID!, $isActive: Boolean, $page: PageInput) {
    unitCampaigns(unitId: $unitId, isActive: $isActive, page: $page) {
      items {
        ...UnitCampaignFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const GET_UNIT_CAMPAIGN = gql`
  ${UNIT_CAMPAIGN_FRAGMENT}
  query GetUnitCampaign($unitCampaignId: ID!) {
    unitCampaign(unitCampaignId: $unitCampaignId) {
      ...UnitCampaignFields
    }
  }
`;

export const GET_UNIT_CAMPAIGN_CATALOG = gql`
  query GetUnitCampaignCatalog($unitCampaignId: ID!) {
    unitCampaignCatalog(unitCampaignId: $unitCampaignId) {
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
`;

export const LIST_UNIT_CAMPAIGN_ROSTER = gql`
  ${UNIT_CAMPAIGN_MEMBERSHIP_FRAGMENT}
  query ListUnitCampaignRoster($unitCampaignId: ID!, $status: MembershipStatus, $page: PageInput) {
    unitCampaignRoster(unitCampaignId: $unitCampaignId, status: $status, page: $page) {
      items {
        ...UnitCampaignMembershipFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

// The participant-safe projection: this is all a bare join code buys, and the
// 1.7.5 guard suite fails a build that widens it.
export const GET_UNIT_CAMPAIGN_JOIN_INFO = gql`
  query GetUnitCampaignJoinInfo($joinCode: String!) {
    unitCampaignJoinInfo(joinCode: $joinCode) {
      unitDisplayName
      campaignName
      campaignYear
      catalogName
      isActive
    }
  }
`;

export const CREATE_UNIT = gql`
  ${UNIT_FRAGMENT}
  ${UNIT_ACCESS_GRANT_FRAGMENT}
  mutation CreateUnit($input: CreateUnitInput!) {
    createUnit(input: $input) {
      unit {
        ...UnitFields
      }
      grant {
        ...UnitAccessGrantFields
      }
    }
  }
`;

export const UPDATE_UNIT = gql`
  ${UNIT_FRAGMENT}
  mutation UpdateUnit($input: UpdateUnitInput!) {
    updateUnit(input: $input) {
      ...UnitFields
    }
  }
`;

export const REVOKE_UNIT_ACCESS_GRANT = gql`
  ${UNIT_FRAGMENT}
  mutation RevokeUnitAccessGrant($input: RevokeUnitAccessGrantInput!) {
    revokeUnitAccessGrant(input: $input) {
      ...UnitFields
    }
  }
`;

export const CREATE_UNIT_INVITE = gql`
  ${UNIT_INVITE_FRAGMENT}
  mutation CreateUnitInvite($input: CreateUnitInviteInput!) {
    createUnitInvite(input: $input) {
      ...UnitInviteFields
    }
  }
`;

export const REDEEM_UNIT_INVITE = gql`
  ${UNIT_ACCESS_GRANT_FRAGMENT}
  mutation RedeemUnitInvite($input: RedeemUnitInviteInput!) {
    redeemUnitInvite(input: $input) {
      ...UnitAccessGrantFields
    }
  }
`;

export const REVOKE_UNIT_INVITE = gql`
  mutation RevokeUnitInvite($input: RevokeUnitInviteInput!) {
    revokeUnitInvite(input: $input)
  }
`;

/**
 * One Unit's payment methods (§4.1.1, §4.1.2).
 *
 * `version` is requested because every mutable row here is written conditionally: the
 * screen sends back the version it read, and a row that moved underneath it is refused
 * rather than overwritten. `createdAt` is asked for because the built-ins answer null,
 * which is how the screen tells a computed method from one the Unit created.
 */
export const UNIT_PAYMENT_METHOD_FRAGMENT = gql`
  fragment UnitPaymentMethodFields on UnitPaymentMethod {
    paymentMethodId
    unitId
    displayName
    isActive
    qrCodeS3Key
    createdAt
    version
  }
`;

export const LIST_UNIT_PAYMENT_METHODS = gql`
  ${UNIT_PAYMENT_METHOD_FRAGMENT}
  query ListUnitPaymentMethods($unitId: ID!, $includeInactive: Boolean) {
    unitPaymentMethods(unitId: $unitId, includeInactive: $includeInactive) {
      ...UnitPaymentMethodFields
    }
  }
`;

/**
 * The pre-signed GET for one method's QR image (§4.1.2). Read on demand rather than
 * listed with the methods: the URL is short-lived, so a list that carried it would
 * hold an expired link for as long as the screen stayed open.
 */
export const GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD = gql`
  query UnitPaymentMethodQrDownloadUrl($unitId: ID!, $paymentMethodId: ID!) {
    unitPaymentMethodQrDownloadUrl(unitId: $unitId, paymentMethodId: $paymentMethodId) {
      downloadUrl
      expiresAt
    }
  }
`;

export const CREATE_UNIT_PAYMENT_METHOD = gql`
  ${UNIT_PAYMENT_METHOD_FRAGMENT}
  mutation CreateUnitPaymentMethod($input: CreateUnitPaymentMethodInput!) {
    createUnitPaymentMethod(input: $input) {
      ...UnitPaymentMethodFields
    }
  }
`;

export const UPDATE_UNIT_PAYMENT_METHOD = gql`
  ${UNIT_PAYMENT_METHOD_FRAGMENT}
  mutation UpdateUnitPaymentMethod($input: UpdateUnitPaymentMethodInput!) {
    updateUnitPaymentMethod(input: $input) {
      ...UnitPaymentMethodFields
    }
  }
`;

export const DEACTIVATE_UNIT_PAYMENT_METHOD = gql`
  ${UNIT_PAYMENT_METHOD_FRAGMENT}
  mutation DeactivateUnitPaymentMethod($input: DeactivateUnitPaymentMethodInput!) {
    deactivateUnitPaymentMethod(input: $input) {
      ...UnitPaymentMethodFields
    }
  }
`;

export const REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD = gql`
  mutation RequestUnitPaymentMethodQrUpload($input: RequestUnitPaymentMethodQrUploadInput!) {
    requestUnitPaymentMethodQrUpload(input: $input) {
      uploadUrl
      fields
      s3Key
    }
  }
`;

export const CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD = gql`
  ${UNIT_PAYMENT_METHOD_FRAGMENT}
  mutation ConfirmUnitPaymentMethodQrUpload($input: ConfirmUnitPaymentMethodQrUploadInput!) {
    confirmUnitPaymentMethodQrUpload(input: $input) {
      ...UnitPaymentMethodFields
    }
  }
`;

export const DELETE_UNIT_PAYMENT_METHOD_QR_CODE = gql`
  ${UNIT_PAYMENT_METHOD_FRAGMENT}
  mutation DeleteUnitPaymentMethodQrCode($input: DeleteUnitPaymentMethodQrCodeInput!) {
    deleteUnitPaymentMethodQrCode(input: $input) {
      ...UnitPaymentMethodFields
    }
  }
`;

export const CREATE_UNIT_CAMPAIGN = gql`
  ${UNIT_CAMPAIGN_FRAGMENT}
  mutation CreateUnitCampaign($input: CreateUnitCampaignInput!) {
    createUnitCampaign(input: $input) {
      ...UnitCampaignFields
    }
  }
`;

export const UPDATE_UNIT_CAMPAIGN = gql`
  ${UNIT_CAMPAIGN_FRAGMENT}
  mutation UpdateUnitCampaign($input: UpdateUnitCampaignInput!) {
    updateUnitCampaign(input: $input) {
      ...UnitCampaignFields
    }
  }
`;

export const JOIN_UNIT_CAMPAIGN = gql`
  ${UNIT_CAMPAIGN_MEMBERSHIP_FRAGMENT}
  mutation JoinUnitCampaign($input: JoinUnitCampaignInput!) {
    joinUnitCampaign(input: $input) {
      ...UnitCampaignMembershipFields
    }
  }
`;

export const REMOVE_UNIT_CAMPAIGN_MEMBERSHIP = gql`
  ${UNIT_CAMPAIGN_MEMBERSHIP_FRAGMENT}
  mutation RemoveUnitCampaignMembership($input: RemoveUnitCampaignMembershipInput!) {
    removeUnitCampaignMembership(input: $input) {
      ...UnitCampaignMembershipFields
    }
  }
`;

// ============================================================================
// Show & Sell — Stage 2: inventory, Scout custody, individual Order fulfillment
// (§2.6). Same posture as Stage 1: a read selects only the fields a screen
// renders, so an SDL addition cannot silently widen what the browser holds.
//
// The derived quantities (sellable, assigned, unassigned, overage, With Scout,
// total unit-owned) are computed server-side and never typed in here: a screen
// that added them up itself would be able to disagree with the balance it is
// auditing (§7).
// ============================================================================

export const INVENTORY_POSITION_FRAGMENT = gql`
  fragment InventoryPositionFields on InventoryPosition {
    unitCampaignId
    productId
    kernelPhysicalQty
    soldInPossessionQty
    councilOnOrderQty
    version
    createdAt
    updatedAt
    sellableKernelQty
    assignedOpenQty
    unassignedKernelQty
    assignmentOverageQty
    withScoutQty
    totalUnitOwnedUndeliveredQty
  }
`;

export const INVENTORY_MOVEMENT_FRAGMENT = gql`
  fragment InventoryMovementFields on InventoryMovement {
    movementId
    unitCampaignId
    productId
    movementType
    kernelPhysicalDelta
    soldPossessionDelta
    withScoutDelta
    assignedDelta
    councilOnOrderDelta
    profileId
    showAndSellId
    orderId
    fulfillmentId
    reason
    actorAccountId
    occurredAt
    idempotencyKey
    inventoryVersion
  }
`;

export const SCOUT_CUSTODY_BALANCE_FRAGMENT = gql`
  fragment ScoutCustodyBalanceFields on ScoutCustodyBalance {
    unitCampaignId
    productId
    profileId
    campaignId
    withScoutQty
    version
    createdAt
    updatedAt
  }
`;

/**
 * The administrative fulfillment audit: actor account and inventory movement id
 * included. This projection is only ever fetched by the Unit-Admin
 * `orderFulfillments` query, never by the participant one (§10.2) — the split is
 * in the documents as well as the server, so a screen cannot ask for the audit
 * fields by accident.
 */
export const ORDER_FULFILLMENT_FRAGMENT = gql`
  fragment OrderFulfillmentFields on OrderFulfillment {
    fulfillmentId
    orderId
    campaignId
    profileId
    unitId
    unitCampaignId
    lineItemId
    productId
    recordType
    quantity
    source
    inventoryMovementId
    reversalOfFulfillmentId
    actorAccountId
    createdAt
  }
`;

/** The participant projection: no actor account, no movement id, no audit (§10.2). */
/**
 * One individual Order as the fulfillment screens read it: the Wave 3 additions
 * (origin scope, `fulfillmentVersion`, the stable line identity and its fulfilled
 * quantity) and nothing else. This is the Unit-scoped projection, not the legacy
 * `Order` type: an admin fulfilling stock has no use for the customer's phone,
 * address, payment method, or notes, and a read that carries none cannot disclose
 * them from this screen.
 */
export const UNIT_ORDER_FRAGMENT = gql`
  fragment UnitOrderFields on UnitOrder {
    orderId
    profileId
    campaignId
    unitId
    unitCampaignId
    customerName
    orderDate
    fulfillmentVersion
    lineItems {
      productId
      productName
      quantity
      lineItemId
      fulfilledQuantity
    }
  }
`;

export const GET_INVENTORY_POSITIONS = gql`
  ${INVENTORY_POSITION_FRAGMENT}
  query GetInventoryPositions($unitCampaignId: ID!, $productIds: [ID!], $page: PageInput) {
    inventoryPositions(unitCampaignId: $unitCampaignId, productIds: $productIds, page: $page) {
      items {
        ...InventoryPositionFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

/**
 * The movement audit with every filter the server offers. Filters are separate
 * variables rather than one input object because the screen turns them on and
 * off independently, and a filter the screen did not send must be absent from
 * the request rather than null-with-a-meaning.
 */
export const GET_INVENTORY_MOVEMENTS = gql`
  ${INVENTORY_MOVEMENT_FRAGMENT}
  query GetInventoryMovements(
    $unitCampaignId: ID!
    $productId: ID
    $movementType: InventoryMovementType
    $showAndSellId: ID
    $profileId: ID
    $dateRange: DateRangeFilter
    $page: PageInput
  ) {
    inventoryMovements(
      unitCampaignId: $unitCampaignId
      productId: $productId
      movementType: $movementType
      showAndSellId: $showAndSellId
      profileId: $profileId
      dateRange: $dateRange
      page: $page
    ) {
      items {
        ...InventoryMovementFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

/**
 * `totalWithScoutQty` is the aggregate the server computed across the whole
 * filtered set, not the sum of the page: the panel shows both, and a locally
 * summed aggregate would be a number that changes with page size.
 */
export const GET_SCOUT_CUSTODY_BALANCES = gql`
  ${SCOUT_CUSTODY_BALANCE_FRAGMENT}
  query GetScoutCustodyBalances($unitCampaignId: ID!, $profileId: ID, $productId: ID, $page: PageInput) {
    scoutCustodyBalances(unitCampaignId: $unitCampaignId, profileId: $profileId, productId: $productId, page: $page) {
      items {
        ...ScoutCustodyBalanceFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
      totalWithScoutQty
    }
  }
`;

export const GET_ORDER_FULFILLMENTS = gql`
  ${ORDER_FULFILLMENT_FRAGMENT}
  query GetOrderFulfillments($orderId: ID!, $page: PageInput) {
    orderFulfillments(orderId: $orderId, page: $page) {
      items {
        ...OrderFulfillmentFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

/**
 * The individual Orders one Scout Campaign holds for this Unit Campaign, in the
 * fulfillment projection.
 *
 * This is the Unit-Admin Order read (§2.6.3), not the legacy `listOrdersByCampaign`:
 * those pipelines authorize Profile ownership and READ shares only, so the admin who
 * owes the stock these Orders sold — and who therefore has to fulfill them — reads an
 * empty list through them. Here the read's authorization is the Order's immutable
 * Unit origin, which is the same scope the fulfillment writes demand.
 */
export const LIST_UNIT_SCOUT_CAMPAIGN_ORDERS = gql`
  ${UNIT_ORDER_FRAGMENT}
  query ListUnitScoutCampaignOrders($unitCampaignId: ID!, $campaignId: ID!, $page: PageInput) {
    unitScoutCampaignOrders(unitCampaignId: $unitCampaignId, campaignId: $campaignId, page: $page) {
      items {
        ...UnitOrderFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const RECORD_INVENTORY_RECEIPT = gql`
  ${INVENTORY_POSITION_FRAGMENT}
  mutation RecordInventoryReceipt($input: RecordInventoryReceiptInput!) {
    recordInventoryReceipt(input: $input) {
      ...InventoryPositionFields
    }
  }
`;

export const ADJUST_INVENTORY = gql`
  ${INVENTORY_POSITION_FRAGMENT}
  mutation AdjustInventory($input: AdjustInventoryInput!) {
    adjustInventory(input: $input) {
      ...InventoryPositionFields
    }
  }
`;

export const ADJUST_COUNCIL_ON_ORDER = gql`
  ${INVENTORY_POSITION_FRAGMENT}
  mutation AdjustCouncilOnOrder($input: AdjustCouncilOnOrderInput!) {
    adjustCouncilOnOrder(input: $input) {
      ...InventoryPositionFields
    }
  }
`;

export const ISSUE_STOCK_TO_SCOUT = gql`
  ${INVENTORY_POSITION_FRAGMENT}
  ${SCOUT_CUSTODY_BALANCE_FRAGMENT}
  mutation IssueStockToScout($input: IssueStockToScoutInput!) {
    issueStockToScout(input: $input) {
      inventoryPosition {
        ...InventoryPositionFields
      }
      custodyBalance {
        ...ScoutCustodyBalanceFields
      }
    }
  }
`;

/** One atomic batch: the server refuses the whole request when one product would over-return. */
export const RETURN_STOCK_FROM_SCOUT = gql`
  ${INVENTORY_POSITION_FRAGMENT}
  ${SCOUT_CUSTODY_BALANCE_FRAGMENT}
  mutation ReturnStockFromScout($input: ReturnStockFromScoutInput!) {
    returnStockFromScout(input: $input) {
      inventoryPositions {
        ...InventoryPositionFields
      }
      custodyBalances {
        ...ScoutCustodyBalanceFields
      }
    }
  }
`;

/**
 * A door-to-door sale: the existing `createOrder` mutation with
 * `fulfillmentMode: CONSUME_SCOUT_CUSTODY` and its required idempotency key
 * (§10.1). Insufficient custody is never an error, so this write succeeds and
 * reports what was consumed through the Order's own fulfillment records.
 */
/**
 * What a fulfillment write echoes back about the Order it changed (§2.4.3, §2.4.4): the
 * version the next write conditions on, and the line the write named. The screens do not
 * render this — a write is followed by the Order read, because the number the next write
 * carries has to be the one the write produced — so the selection is the smallest one that
 * shows the write landed on the line it named. It is a separate fragment from
 * `UnitOrderFields` because the §2.4 payloads answer with the existing `Order` type, and
 * this admin surface never reads the contact fields that type can carry.
 */
export const ORDER_WRITE_STATE_FRAGMENT = gql`
  fragment OrderWriteState on Order {
    orderId
    fulfillmentVersion
    lineItems {
      lineItemId
      productId
      quantity
      fulfilledQuantity
    }
  }
`;

export const RECORD_CUSTODY_SALE = gql`
  ${ORDER_WRITE_STATE_FRAGMENT}
  mutation RecordCustodySale($input: CreateOrderInput!) {
    createOrder(input: $input) {
      ...OrderWriteState
    }
  }
`;

export const FULFILL_INDIVIDUAL_ORDER_LINE = gql`
  ${ORDER_WRITE_STATE_FRAGMENT}
  ${INVENTORY_POSITION_FRAGMENT}
  ${ORDER_FULFILLMENT_FRAGMENT}
  mutation FulfillIndividualOrderLine($input: FulfillIndividualOrderLineInput!) {
    fulfillIndividualOrderLine(input: $input) {
      order {
        ...OrderWriteState
      }
      fulfillment {
        ...OrderFulfillmentFields
      }
      inventoryPosition {
        ...InventoryPositionFields
      }
    }
  }
`;

export const REVERSE_INDIVIDUAL_ORDER_FULFILLMENT = gql`
  ${ORDER_WRITE_STATE_FRAGMENT}
  ${INVENTORY_POSITION_FRAGMENT}
  ${ORDER_FULFILLMENT_FRAGMENT}
  mutation ReverseIndividualOrderFulfillment($input: ReverseIndividualOrderFulfillmentInput!) {
    reverseIndividualOrderFulfillment(input: $input) {
      order {
        ...OrderWriteState
      }
      reversal {
        ...OrderFulfillmentFields
      }
      inventoryPosition {
        ...InventoryPositionFields
      }
    }
  }
`;

// ============================================================================
// Show & Sell — Stage 3: events, allocations, slots, signups, work, and the
// participant surfaces (§3.5). The admin documents and the participant
// documents are separate on purpose: `ShowAndSellAdmin` carries allocations,
// stock quantities, audit actors, and the finalization pointers, and no
// participant screen may fetch it; the participant documents select only the
// `# participant-safe` types (SEC-04), which carry none of it.
// ============================================================================

/**
 * One event's reservation of one product, as the admin event board reads it.
 * `remainingQty` is the server's stored answer, never a browser subtraction.
 */
export const SHOW_AND_SELL_ALLOCATION_FRAGMENT = gql`
  fragment ShowAndSellAllocationFields on ShowAndSellAllocation {
    unitCampaignId
    productId
    showAndSellId
    startAt
    endAt
    status
    allocatedQty
    soldQty
    releasedQty
    remainingQty
    version
    createdAt
    updatedAt
  }
`;

/** One working slot: its interval, its capacity, and the counter signups maintain. */
export const SHOW_AND_SELL_SLOT_FRAGMENT = gql`
  fragment ShowAndSellSlotFields on ShowAndSellSlot {
    showAndSellId
    slotId
    label
    startAt
    endAt
    capacity
    activeSignupCount
    version
    createdAt
    updatedAt
  }
`;

/**
 * The administrative signup row: who placed it, who confirmed the work, and
 * when. This projection is admin-only — the participant screens fetch
 * `ParticipantSignup` (§3.5.3) and never this type.
 */
export const SHOW_AND_SELL_SIGNUP_FRAGMENT = gql`
  fragment ShowAndSellSignupFields on ShowAndSellSignup {
    showAndSellId
    slotId
    profileId
    unitCampaignId
    campaignId
    status
    actualMinutes
    signedUpByAccountId
    confirmedByAccountId
    confirmedAt
    version
    createdAt
    updatedAt
  }
`;

/**
 * A Show & Sell as its Unit Admin manages it. The times are selected for
 * display — they are immutable, and the screen shows them, it never edits
 * them; there is no update input that could carry them (SSE-07).
 */
export const SHOW_AND_SELL_ADMIN_FRAGMENT = gql`
  ${SHOW_AND_SELL_ALLOCATION_FRAGMENT}
  ${SHOW_AND_SELL_SLOT_FRAGMENT}
  fragment ShowAndSellAdminFields on ShowAndSellAdmin {
    showAndSellId
    unitId
    unitCampaignId
    locationName
    address
    startAt
    endAt
    status
    splitMethod
    weOweEnabled
    productIds
    allocations {
      ...ShowAndSellAllocationFields
    }
    slots {
      ...ShowAndSellSlotFields
    }
    version
    createdAt
    updatedAt
    createdByAccountId
    updatedByAccountId
    cancelledByAccountId
    cancelledAt
    cancellationReason
  }
`;

/** The pending work picture a confirmation batch returns: computed, never approved. */
export const SHOW_AND_SELL_WORK_PREVIEW_FRAGMENT = gql`
  fragment ShowAndSellWorkPreviewFields on ShowAndSellWorkPreview {
    eventVersion
    totalConfirmedMinutes
    confirmedWorkRows
    confirmedParticipants
    minimumFinalizationActions
  }
`;

// --- participant-safe surfaces (SEC-04) -------------------------------------
// These documents select only the participant types. The 1.7.5 guard suite fails
// a build that puts an administrative field on them; these documents are the
// browser-side half of the same line. `signupScoutForShowAndSellSlot` and
// `cancelShowAndSellSignup` answer `ParticipantSignup` even when a Unit Admin
// placed or released the place, because the write's own result is the caller's
// next concurrency token — the admin's audit read is `showAndSellSignups`.

/**
 * One signup as the Scout who holds it sees it: the slot, the interval, whether
 * it is still active, the confirmed minutes, and the version that cancellation
 * conditions on. No actor field is on this type.
 */
export const PARTICIPANT_SIGNUP_FRAGMENT = gql`
  fragment ParticipantSignupFields on ParticipantSignup {
    showAndSellId
    slotId
    startAt
    endAt
    status
    actualMinutes
    signupVersion
  }
`;

export const GET_SHOW_AND_SELL = gql`
  ${SHOW_AND_SELL_ADMIN_FRAGMENT}
  query GetShowAndSell($showAndSellId: ID!) {
    showAndSell(showAndSellId: $showAndSellId) {
      ...ShowAndSellAdminFields
    }
  }
`;

export const LIST_SHOW_AND_SELLS = gql`
  ${SHOW_AND_SELL_ADMIN_FRAGMENT}
  query ListShowAndSells(
    $unitCampaignId: ID!
    $status: ShowAndSellStatus
    $dateRange: DateRangeFilter
    $page: PageInput
  ) {
    showAndSells(unitCampaignId: $unitCampaignId, status: $status, dateRange: $dateRange, page: $page) {
      items {
        ...ShowAndSellAdminFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const CREATE_SHOW_AND_SELL = gql`
  ${SHOW_AND_SELL_ADMIN_FRAGMENT}
  mutation CreateShowAndSell($input: CreateShowAndSellInput!) {
    createShowAndSell(input: $input) {
      ...ShowAndSellAdminFields
    }
  }
`;

/**
 * The edit surface is exactly what `UpdateShowAndSellInput` allows: location,
 * address, split override, We Owe. The document carries no `startAt`/`endAt`
 * because rescheduling is not a feature; the cancel-and-recreate workflow is
 * what changes an event's time, and it is a different write on a new row.
 */
export const UPDATE_SHOW_AND_SELL = gql`
  ${SHOW_AND_SELL_ADMIN_FRAGMENT}
  mutation UpdateShowAndSell($input: UpdateShowAndSellInput!) {
    updateShowAndSell(input: $input) {
      ...ShowAndSellAdminFields
    }
  }
`;

export const CANCEL_SHOW_AND_SELL = gql`
  ${SHOW_AND_SELL_ADMIN_FRAGMENT}
  ${SHOW_AND_SELL_ALLOCATION_FRAGMENT}
  ${SHOW_AND_SELL_SIGNUP_FRAGMENT}
  mutation CancelShowAndSell($input: CancelShowAndSellInput!) {
    cancelShowAndSell(input: $input) {
      event {
        ...ShowAndSellAdminFields
      }
      releasedAllocations {
        ...ShowAndSellAllocationFields
      }
      cancelledSignups {
        ...ShowAndSellSignupFields
      }
    }
  }
`;

/** One product's stock target for one event: a target, not a delta. */
export const ASSIGN_SHOW_AND_SELL_INVENTORY = gql`
  ${SHOW_AND_SELL_ALLOCATION_FRAGMENT}
  ${INVENTORY_POSITION_FRAGMENT}
  mutation AssignShowAndSellInventory($input: AssignShowAndSellInventoryInput!) {
    assignShowAndSellInventory(input: $input) {
      allocations {
        ...ShowAndSellAllocationFields
      }
      inventoryPositions {
        ...InventoryPositionFields
      }
      warnings {
        code
        productId
        currentStockQty
        assignedQty
        overageQty
        message
      }
    }
  }
`;

/** Raw allocation facts for a campaign; totals are the browser's, over every page. */
export const LIST_EVENT_INVENTORY_ALLOCATIONS = gql`
  ${SHOW_AND_SELL_ALLOCATION_FRAGMENT}
  query ListEventInventoryAllocations(
    $unitCampaignId: ID!
    $productId: ID
    $showAndSellId: ID
    $status: AllocationStatus
    $page: PageInput
  ) {
    eventInventoryAllocations(
      unitCampaignId: $unitCampaignId
      productId: $productId
      showAndSellId: $showAndSellId
      status: $status
      page: $page
    ) {
      items {
        ...ShowAndSellAllocationFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const UPSERT_SHOW_AND_SELL_SLOT = gql`
  ${SHOW_AND_SELL_SLOT_FRAGMENT}
  mutation UpsertShowAndSellSlot($input: UpsertShowAndSellSlotInput!) {
    upsertShowAndSellSlot(input: $input) {
      ...ShowAndSellSlotFields
    }
  }
`;

export const DELETE_SHOW_AND_SELL_SLOT = gql`
  mutation DeleteShowAndSellSlot($input: DeleteShowAndSellSlotInput!) {
    deleteShowAndSellSlot(input: $input)
  }
`;

export const LIST_SHOW_AND_SELL_SIGNUPS = gql`
  ${SHOW_AND_SELL_SIGNUP_FRAGMENT}
  query ListShowAndSellSignups($showAndSellId: ID!, $status: SignupStatus, $page: PageInput) {
    showAndSellSignups(showAndSellId: $showAndSellId, status: $status, page: $page) {
      items {
        ...ShowAndSellSignupFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const SIGNUP_SCOUT_FOR_SHOW_AND_SELL_SLOT = gql`
  ${PARTICIPANT_SIGNUP_FRAGMENT}
  mutation SignupScoutForShowAndSellSlot($input: SignupShowAndSellSlotInput!) {
    signupScoutForShowAndSellSlot(input: $input) {
      ...ParticipantSignupFields
    }
  }
`;

export const CANCEL_SHOW_AND_SELL_SIGNUP = gql`
  ${PARTICIPANT_SIGNUP_FRAGMENT}
  mutation CancelShowAndSellSignup($input: CancelShowAndSellSignupInput!) {
    cancelShowAndSellSignup(input: $input) {
      ...ParticipantSignupFields
    }
  }
`;

export const CONFIRM_SHOW_AND_SELL_WORK = gql`
  ${SHOW_AND_SELL_SIGNUP_FRAGMENT}
  ${SHOW_AND_SELL_WORK_PREVIEW_FRAGMENT}
  mutation ConfirmShowAndSellWork($input: ConfirmShowAndSellWorkInput!) {
    confirmShowAndSellWork(input: $input) {
      work {
        ...ShowAndSellSignupFields
      }
      preview {
        ...ShowAndSellWorkPreviewFields
      }
    }
  }
`;

/**
 * One event as a Scout is offered it: where and when, the slots with the room
 * left in each, and this Scout's own signups. `openCapacity` and `timezone` come
 * from the server so the browser never subtracts a capacity it hopes for and
 * never has to guess the zone an interval is displayed in (SEC-04, SEC-05).
 */
export const SHOW_AND_SELL_OPPORTUNITY_FRAGMENT = gql`
  ${PARTICIPANT_SIGNUP_FRAGMENT}
  fragment ShowAndSellOpportunityFields on ShowAndSellOpportunity {
    showAndSellId
    locationName
    address
    startAt
    endAt
    status
    splitMethod
    weOweEnabled
    timezone
    eventVersion
    slots {
      slotId
      label
      startAt
      endAt
      capacity
      openCapacity
    }
    mySignups {
      ...ParticipantSignupFields
    }
  }
`;

/**
 * The Scout Campaigns one profile holds, with the Unit Campaign each is joined to.
 *
 * A signup names the pair the roster keys on — the Scout Campaign and the profile —
 * and the server refuses a pair that is not the roster row's own. This is the read
 * that lets a Scout page name the right half without any administrative surface:
 * `Campaign.unitCampaignId` is set atomically by `joinUnitCampaign`, so the join the
 * Unit Admin approved is what the write is addressed to. Removal does not clear it,
 * which is why the server, not this read, decides whether the place may still be
 * taken.
 */
export const LIST_SCOUT_CAMPAIGN_JOINS = gql`
  query ListScoutCampaignJoins($profileId: ID!, $limit: Int, $nextToken: String) {
    listCampaignsByProfile(profileId: $profileId, limit: $limit, nextToken: $nextToken) {
      campaigns {
        campaignId
        campaignName
        campaignYear
        isActive
        unitCampaignId
      }
      nextToken
    }
  }
`;

export const LIST_UNIT_CAMPAIGN_OPPORTUNITIES = gql`
  ${SHOW_AND_SELL_OPPORTUNITY_FRAGMENT}
  query ListUnitCampaignOpportunities($unitCampaignId: ID!, $includePast: Boolean, $page: PageInput) {
    unitCampaignOpportunities(unitCampaignId: $unitCampaignId, includePast: $includePast, page: $page) {
      items {
        ...ShowAndSellOpportunityFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const GET_SHOW_AND_SELL_OPPORTUNITY = gql`
  ${SHOW_AND_SELL_OPPORTUNITY_FRAGMENT}
  query GetShowAndSellOpportunity($showAndSellId: ID!, $profileId: ID!) {
    showAndSellOpportunity(showAndSellId: $showAndSellId, profileId: $profileId) {
      ...ShowAndSellOpportunityFields
    }
  }
`;

export const LIST_MY_SCOUT_COMMITMENTS = gql`
  fragment ParticipantCommitmentFields on ParticipantCommitment {
    showAndSellId
    slotId
    startAt
    endAt
    status
    signupVersion
  }
  query ListMyScoutCommitments($profileId: ID!, $unitId: ID, $includeCancelled: Boolean, $page: PageInput) {
    myScoutCommitments(profileId: $profileId, unitId: $unitId, includeCancelled: $includeCancelled, page: $page) {
      items {
        ...ParticipantCommitmentFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

/**
 * The authorized inputs an ICS needs — data only. No mutation or query here
 * generates a file: the browser assembles, serializes, and downloads it
 * itself, and the server holds no artifact to download (CAL-01, CAL-02).
 */
export const GET_SIGNUP_CALENDAR_DATA = gql`
  query GetSignupCalendarData($showAndSellId: ID!, $slotId: ID!, $profileId: ID!) {
    showAndSellSignupCalendarData(showAndSellId: $showAndSellId, slotId: $slotId, profileId: $profileId) {
      unitId
      unitDisplayName
      unitCampaignId
      unitCampaignName
      showAndSellId
      slotId
      profileId
      slotLabel
      locationName
      address
      timezone
      slotStartAt
      slotEndAt
    }
  }
`;

// ============================================================================
// Show & Sell — Stage 4.5: sale entry/correction and We Owe administration
// (checklist §4.5.1). The admin documents and the participant documents are
// separate on purpose: a sale carries buyer contact detail, and the We Owe list
// carries buyer names and no actor — both are Unit-Admin-only reads, never a
// participant projection.
// ============================================================================

/** One sale line as the admin sale screen reads it. */
export const SHOW_AND_SELL_SALE_LINE_FRAGMENT = gql`
  fragment ShowAndSellSaleLineFields on ShowAndSellSaleLine {
    lineItemId
    productId
    productNameSnapshot
    unitPriceCentsSnapshot
    immediateQty
    weOweQty
    subtotalCents
  }
`;

/** One pooled sale as the admin sale screen reads it. */
export const SHOW_AND_SELL_SALE_FRAGMENT = gql`
  ${SHOW_AND_SELL_SALE_LINE_FRAGMENT}
  fragment ShowAndSellSaleFields on ShowAndSellSale {
    saleId
    showAndSellId
    unitId
    unitCampaignId
    saleAt
    enteredByAccountId
    buyerName
    buyerPhone
    buyerEmail
    lineItems {
      ...ShowAndSellSaleLineFields
    }
    totalCents
    paymentMethodSnapshot {
      methodCode
      displayName
      otherDetails
    }
    revision
    status
    voidedByAccountId
    voidedAt
    createdAt
    updatedAt
    expectedCashCents
  }
`;

/** One obligation as the admin We Owe screen reads it. */
export const WE_OWE_OBLIGATION_FRAGMENT = gql`
  fragment WeOweObligationFields on WeOweObligation {
    weOweId
    unitCampaignId
    showAndSellId
    saleId
    lineItemId
    buyerName
    productId
    productNameSnapshot
    originalQty
    fulfilledQty
    cancelledQty
    reservedQty
    remainingQty
    uncoveredQty
    valueCentsSnapshot
    status
    closeReason
    version
    createdAt
    closedAt
  }
`;

/** One event's sales, raw and paginated (§4.5.2). */
export const LIST_SHOW_AND_SELL_SALES = gql`
  ${SHOW_AND_SELL_SALE_FRAGMENT}
  query ListShowAndSellSales($showAndSellId: ID!, $status: String, $page: PageInput) {
    showAndSellSales(showAndSellId: $showAndSellId, status: $status, page: $page) {
      items {
        ...ShowAndSellSaleFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

/** One campaign's obligations, raw and paginated (§4.4.4). */
export const LIST_WE_OWE_OBLIGATIONS = gql`
  ${WE_OWE_OBLIGATION_FRAGMENT}
  query ListWeOweObligations(
    $unitCampaignId: ID!
    $showAndSellId: ID
    $productId: ID
    $status: WeOweStatus
    $page: PageInput
  ) {
    weOweObligations(
      unitCampaignId: $unitCampaignId
      showAndSellId: $showAndSellId
      productId: $productId
      status: $status
      page: $page
    ) {
      items {
        ...WeOweObligationFields
      }
      pageInfo {
        endCursor
        hasNextPage
      }
    }
  }
`;

export const CREATE_SHOW_AND_SELL_SALE = gql`
  ${SHOW_AND_SELL_SALE_FRAGMENT}
  ${WE_OWE_OBLIGATION_FRAGMENT}
  mutation CreateShowAndSellSale($input: CreateShowAndSellSaleInput!) {
    createShowAndSellSale(input: $input) {
      sale {
        ...ShowAndSellSaleFields
      }
      eventVersion
      draftOnly
      warnings {
        productId
        currentStockQty
        assignedQty
        overageQty
        message
      }
      obligations {
        ...WeOweObligationFields
      }
    }
  }
`;

export const CORRECT_SHOW_AND_SELL_SALE = gql`
  ${SHOW_AND_SELL_SALE_FRAGMENT}
  ${WE_OWE_OBLIGATION_FRAGMENT}
  mutation CorrectShowAndSellSale($input: CorrectShowAndSellSaleInput!) {
    correctShowAndSellSale(input: $input) {
      sale {
        ...ShowAndSellSaleFields
      }
      priorRevision {
        saleId
        showAndSellId
        revision
        saleAt
        enteredByAccountId
        buyerName
        buyerPhone
        buyerEmail
        lineItems {
          ...ShowAndSellSaleLineFields
        }
        totalCents
        paymentMethodSnapshot {
          methodCode
          displayName
          otherDetails
        }
        status
        correctedByAccountId
        correctedAt
        reason
      }
      eventVersion
      draftOnly
      warnings {
        productId
        currentStockQty
        assignedQty
        overageQty
        message
      }
      obligations {
        ...WeOweObligationFields
      }
    }
  }
`;

export const VOID_SHOW_AND_SELL_SALE = gql`
  ${SHOW_AND_SELL_SALE_FRAGMENT}
  ${WE_OWE_OBLIGATION_FRAGMENT}
  mutation VoidShowAndSellSale($input: VoidShowAndSellSaleInput!) {
    voidShowAndSellSale(input: $input) {
      sale {
        ...ShowAndSellSaleFields
      }
      priorRevision {
        saleId
        showAndSellId
        revision
        saleAt
        enteredByAccountId
        buyerName
        buyerPhone
        buyerEmail
        lineItems {
          ...ShowAndSellSaleLineFields
        }
        totalCents
        paymentMethodSnapshot {
          methodCode
          displayName
          otherDetails
        }
        status
        correctedByAccountId
        correctedAt
        reason
      }
      eventVersion
      draftOnly
      warnings {
        productId
        currentStockQty
        assignedQty
        overageQty
        message
      }
      obligations {
        ...WeOweObligationFields
      }
    }
  }
`;

export const SET_WE_OWE_RESERVATION = gql`
  ${WE_OWE_OBLIGATION_FRAGMENT}
  mutation SetWeOweReservation($input: SetWeOweReservationInput!) {
    setWeOweReservation(input: $input) {
      obligation {
        ...WeOweObligationFields
      }
    }
  }
`;

export const FULFILL_WE_OWE = gql`
  ${WE_OWE_OBLIGATION_FRAGMENT}
  mutation FulfillWeOwe($input: FulfillWeOweInput!) {
    fulfillWeOwe(input: $input) {
      obligation {
        ...WeOweObligationFields
      }
      fulfillment {
        fulfillmentId
        weOweId
        quantity
        source
        createdAt
      }
    }
  }
`;
