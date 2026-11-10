export type Maybe<T> = T | null | undefined;
export type InputMaybe<T> = T | null | undefined;
export type Exact<T extends { [key: string]: unknown }> = { [K in keyof T]: T[K] };
export type MakeOptional<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]?: Maybe<T[SubKey]> };
export type MakeMaybe<T, K extends keyof T> = Omit<T, K> & { [SubKey in K]: Maybe<T[SubKey]> };
export type MakeEmpty<T extends { [key: string]: unknown }, K extends keyof T> = { [_ in K]?: never };
export type Incremental<T> = T | { [P in keyof T]?: P extends ' $fragmentName' | '__typename' ? T[P] : never };
/** All built-in and custom scalars, mapped to their actual values */
export type Scalars = {
  ID: { input: string; output: string };
  String: { input: string; output: string };
  Boolean: { input: boolean; output: boolean };
  Int: { input: number; output: number };
  Float: { input: number; output: number };
  /** A calendar date without a time component in ISO-8601 format (for example 2025-01-15). Used for campaign start and end windows. */
  AWSDate: { input: string; output: string };
  /** A timestamp with timezone in ISO-8601 format (for example 2025-01-15T12:30:00Z). Used for created/updated times and order/campaign event dates. */
  AWSDateTime: { input: string; output: string };
  /** An RFC-5322 email address. */
  AWSEmail: { input: string; output: string };
  /** An arbitrary JSON value (object, array, or scalar). Used for the Account preferences blob and S3 upload form fields. */
  AWSJSON: { input: Record<string, unknown>; output: Record<string, unknown> };
  /** A phone number. */
  AWSPhone: { input: string; output: string };
  /** An RFC-3986 URL. */
  AWSURL: { input: string; output: string };
};

/**
 * An authenticated user's account, stored in the Accounts table.
 *
 * `getMyAccount` creates the row automatically on first read if it does not yet exist. `preferences` is an opaque JSON blob managed with `updateMyPreferences`.
 */
export type GqlAccount = {
  __typename?: 'Account';
  /** The account's unique ID (the Cognito user sub, with the ACCOUNT# prefix). */
  accountId: Scalars['ID']['output'];
  /** City, used for unit identification when a scout unit is specified. */
  city?: Maybe<Scalars['String']['output']>;
  /** When the account was first created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The account's Cognito email address. */
  email: Scalars['AWSEmail']['output'];
  /** The account's last name. */
  familyName?: Maybe<Scalars['String']['output']>;
  /** The account's first name. */
  givenName?: Maybe<Scalars['String']['output']>;
  /** A free-form JSON blob of user preferences, managed via updateMyPreferences. */
  preferences?: Maybe<Scalars['AWSJSON']['output']>;
  /** State (postal code), used for unit identification when a scout unit is specified. */
  state?: Maybe<Scalars['String']['output']>;
  /** The scout unit number (a positive integer), set together with unitType. */
  unitNumber?: Maybe<Scalars['Int']['output']>;
  /** The scout unit type (for example Pack, Troop, Crew, Ship, Post). */
  unitType?: Maybe<Scalars['String']['output']>;
  /** When the account was last modified. */
  updatedAt: Scalars['AWSDateTime']['output'];
};

/** A physical mailing address. */
export type GqlAddress = {
  __typename?: 'Address';
  /** City. */
  city?: Maybe<Scalars['String']['output']>;
  /** State. */
  state?: Maybe<Scalars['String']['output']>;
  /** Street address. */
  street?: Maybe<Scalars['String']['output']>;
  /** ZIP/postal code. */
  zipCode?: Maybe<Scalars['String']['output']>;
};

/** Input for a physical mailing address. */
export type GqlAddressInput = {
  /** City. */
  city?: InputMaybe<Scalars['String']['input']>;
  /** State. */
  state?: InputMaybe<Scalars['String']['input']>;
  /** Street address. */
  street?: InputMaybe<Scalars['String']['input']>;
  /** ZIP/postal code. */
  zipCode?: InputMaybe<Scalars['String']['input']>;
};

/** An admin view of a Cognito user, merging Cognito identity data with the stored Account record. Admin-only. */
export type GqlAdminUser = {
  __typename?: 'AdminUser';
  /** The user's Cognito sub (account ID). */
  accountId: Scalars['ID']['output'];
  /** When the Cognito user was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** Display name built from the stored Account's givenName and familyName, if present. */
  displayName?: Maybe<Scalars['String']['output']>;
  /** The user's Cognito email address. */
  email: Scalars['AWSEmail']['output'];
  /** Whether the user's email is verified in Cognito. */
  emailVerified: Scalars['Boolean']['output'];
  /** Whether the Cognito user is enabled. */
  enabled: Scalars['Boolean']['output'];
  /** Whether the user belongs to the ADMIN Cognito group. */
  isAdmin: Scalars['Boolean']['output'];
  /** When the Cognito user was last modified, if known. */
  lastModifiedAt?: Maybe<Scalars['AWSDateTime']['output']>;
  /** Cognito user status (for example CONFIRMED, UNCONFIRMED, or FORCE_CHANGE_PASSWORD). */
  status: Scalars['String']['output'];
};

/** A page of AdminUser results from adminListUsers, with a token for fetching the next page. */
export type GqlAdminUserConnection = {
  __typename?: 'AdminUserConnection';
  /** Token to pass to adminListUsers to fetch the next page, or null if there are no more results. */
  nextToken?: Maybe<Scalars['String']['output']>;
  /** The users on this page. */
  users: Array<GqlAdminUser>;
};

export type GqlAllocationStatus = 'ACTIVE' | 'RELEASED';

export type GqlAllocationTargetInput = {
  productId: Scalars['ID']['input'];
  quantity: Scalars['Int']['input'];
};

/** A fundraising campaign owned by a seller profile, tied to a catalog for a season. */
export type GqlCampaign = {
  __typename?: 'Campaign';
  /** The campaign's unique ID (with the CAMPAIGN# prefix). */
  campaignId: Scalars['ID']['output'];
  /** The campaign's display name (for example "Fall" or "Spring"). */
  campaignName: Scalars['String']['output'];
  /** The campaign's year (for example 2024). */
  campaignYear: Scalars['Int']['output'];
  /** The catalog this campaign sells from. Returns the stored catalog (including soft-deleted ones), or null if the catalog is missing. */
  catalog?: Maybe<GqlCatalog>;
  /** The ID of the catalog this campaign sells from. */
  catalogId: Scalars['ID']['output'];
  /** The city, used (with unitType, unitNumber, and state) to identify the unit. */
  city?: Maybe<Scalars['String']['output']>;
  /** When the campaign was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The campaign's end date, if set. */
  endDate?: Maybe<Scalars['AWSDateTime']['output']>;
  /** Whether the campaign is active. New campaigns are active by default; deactivating hides it from latest-campaign and shared lookups. */
  isActive: Scalars['Boolean']['output'];
  /** The ID of the profile that owns this campaign. */
  profileId: Scalars['ID']['output'];
  /** Set when this campaign was created from a shared campaign; holds the shared campaign's code. */
  sharedCampaignCode?: Maybe<Scalars['String']['output']>;
  /** The campaign's start date, if set. */
  startDate?: Maybe<Scalars['AWSDateTime']['output']>;
  /** The state, used (with unitType, unitNumber, and city) to identify the unit. */
  state?: Maybe<Scalars['String']['output']>;
  /** The number of orders placed in this campaign. */
  totalOrders?: Maybe<Scalars['Int']['output']>;
  /** The sum of totalAmount across this campaign's orders. */
  totalRevenue?: Maybe<Scalars['Float']['output']>;
  /** The Unit Campaign this campaign is joined to, or null for an independent campaign. Set atomically by joinUnitCampaign; removal does not clear it (history retention). */
  unitCampaignId?: Maybe<Scalars['ID']['output']>;
  /** The Unit this campaign is joined to, or null for an independent campaign. Set atomically by joinUnitCampaign; removal does not clear it (history retention). */
  unitId?: Maybe<Scalars['ID']['output']>;
  /** The scout unit number; set together with city and state when unitType is provided. */
  unitNumber?: Maybe<Scalars['Int']['output']>;
  /** The scout unit type, if the campaign is scoped to a unit. */
  unitType?: Maybe<Scalars['String']['output']>;
  /** When the campaign was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
};

/** A page of Campaign results from listCampaignsByProfile, with a token for fetching the next page. */
export type GqlCampaignConnection = {
  __typename?: 'CampaignConnection';
  /** The campaigns on this page. */
  campaigns: Array<GqlCampaign>;
  /** Token to pass to listCampaignsByProfile to fetch the next page, or null if there are no more results. */
  nextToken?: Maybe<Scalars['String']['output']>;
};

/** A generated report for a campaign (Excel or CSV), stored in S3 with a time-limited pre-signed download URL. */
export type GqlCampaignReport = {
  __typename?: 'CampaignReport';
  /** The ID of the campaign the report covers. */
  campaignId: Scalars['ID']['output'];
  /** When the report was requested and generated. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** When the pre-signed download URL expires. */
  expiresAt?: Maybe<Scalars['AWSDateTime']['output']>;
  /** The ID of the profile that owns the campaign. */
  profileId: Scalars['ID']['output'];
  /** The report's unique ID (with the REPORT# prefix). */
  reportId: Scalars['ID']['output'];
  /** A pre-signed S3 URL to download the report (valid for a few hours). */
  reportUrl?: Maybe<Scalars['AWSURL']['output']>;
  /** The report's generation status (COMPLETED once it has been generated and uploaded). */
  status: Scalars['String']['output'];
};

/** The state of a campaign's public order surface. */
export type GqlCampaignState =
  /** Public orders are disabled or the campaign is inactive. */
  | 'INACTIVE'
  /** Public orders are enabled and the campaign is active. */
  | 'OK';

/**
 * A catalog of products that campaigns sell from.
 *
 * `getCatalog` returns a catalog by ID only when it is public, admin-managed, or owned by the caller. `listManagedCatalogs` returns only public ADMIN_MANAGED catalogs and `listMyCatalogs` returns the caller's own catalogs; both exclude soft-deleted catalogs, which remain retrievable by ID by an authorized caller.
 */
export type GqlCatalog = {
  __typename?: 'Catalog';
  /** The catalog's unique ID (with the CATALOG# prefix). */
  catalogId: Scalars['ID']['output'];
  /** The catalog's display name. */
  catalogName: Scalars['String']['output'];
  /** Whether the catalog is admin-managed (global) or user-created. */
  catalogType: GqlCatalogType;
  /** When the catalog was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** Soft-delete flag. Set by deleteCatalog instead of removing the row; soft-deleted catalogs are hidden from list queries. */
  isDeleted?: Maybe<Scalars['Boolean']['output']>;
  /** Whether the catalog is public. Public admin-managed catalogs appear in listManagedCatalogs. */
  isPublic: Scalars['Boolean']['output'];
  /** The products in this catalog. */
  products: Array<GqlProduct>;
  /** When the catalog was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
};

/** How a catalog is provisioned. */
export type GqlCatalogType =
  /** A global catalog created by an admin (via createManagedCatalog) that is available to every user. */
  | 'ADMIN_MANAGED'
  /** A catalog created by a regular user for use in their own campaigns. */
  | 'USER_CREATED';

export type GqlCommitmentStatus = 'ACTIVE' | 'CANCELLED';

/** Primary presentation basis for a unit's needs report. */
export type GqlCouncilNeedBasis =
  /** Present after applying assignments. */
  | 'AFTER_ASSIGNMENTS'
  /** Present on physical stock held in the kernel. */
  | 'PHYSICAL_STOCK';

/**
 * Input for createCampaign. Creates a new active campaign on a profile.
 *
 * Either provide `catalogId` directly, or provide `sharedCampaignCode` to copy the name, year, catalog, and unit details from an existing shared campaign.
 */
export type GqlCreateCampaignInput = {
  /** The campaign's display name (for example "Fall" or "Spring"). Required unless a shared campaign supplies it. */
  campaignName?: InputMaybe<Scalars['String']['input']>;
  /** The campaign's year (for example 2024). Required unless a shared campaign supplies it. */
  campaignYear?: InputMaybe<Scalars['Int']['input']>;
  /** The ID of the catalog the campaign sells from. Required unless a shared campaign supplies it. */
  catalogId?: InputMaybe<Scalars['ID']['input']>;
  /** The city, with unitType, unitNumber, and state, to identify the unit. */
  city?: InputMaybe<Scalars['String']['input']>;
  /** The campaign's end date. */
  endDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  /** The ID of the profile to create the campaign on (the caller must have WRITE access). */
  profileId: Scalars['ID']['input'];
  /** Used with sharedCampaignCode: also share the new campaign back to the shared campaign's creator. */
  shareWithCreator?: InputMaybe<Scalars['Boolean']['input']>;
  /** Create this campaign from the shared campaign with this code; name, year, catalog, and unit details are copied from it. */
  sharedCampaignCode?: InputMaybe<Scalars['String']['input']>;
  /** The campaign's start date. */
  startDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  /** The state, with unitType, unitNumber, and city, to identify the unit. */
  state?: InputMaybe<Scalars['String']['input']>;
  /** The scout unit number (a positive integer), with city and state. */
  unitNumber?: InputMaybe<Scalars['Int']['input']>;
  /** The scout unit type, to scope the campaign to a unit. */
  unitType?: InputMaybe<Scalars['String']['input']>;
};

/** Input for createCatalog and createManagedCatalog. Defines a catalog and its products. */
export type GqlCreateCatalogInput = {
  /** The catalog's display name. */
  catalogName: Scalars['String']['input'];
  /** Whether the catalog is public. */
  isPublic: Scalars['Boolean']['input'];
  /** The products to include in the catalog. */
  products: Array<GqlProductInput>;
};

/** Input for createOrder. Places a new order in a campaign. */
export type GqlCreateOrderInput = {
  /** The ID of the campaign the order belongs to. */
  campaignId: Scalars['ID']['input'];
  /** The customer's address. */
  customerAddress?: InputMaybe<GqlAddressInput>;
  /** The customer's name. */
  customerName: Scalars['String']['input'];
  /** The customer's phone number. */
  customerPhone?: InputMaybe<Scalars['String']['input']>;
  /** The products and quantities to order; prices are looked up from the campaign's catalog. */
  lineItems: Array<GqlLineItemInput>;
  /** Free-text notes about the order. */
  notes?: InputMaybe<Scalars['String']['input']>;
  /** When the order was placed. */
  orderDate: Scalars['AWSDateTime']['input'];
  /** The name of the payment method used for this order. */
  paymentMethod: Scalars['String']['input'];
  /** The ID of the profile the order belongs to (the caller must have WRITE access). */
  profileId: Scalars['ID']['input'];
};

/** Input for createProfileInvite. Creates a redeemable invite to join a profile (owner only). */
export type GqlCreateProfileInviteInput = {
  /** How many days until the invite expires; defaults to 14 if omitted. Must be an integer between 1 and 14. */
  expiresInDays?: InputMaybe<Scalars['Int']['input']>;
  /** The permissions the invite grants once redeemed (READ and/or WRITE). */
  permissions: Array<GqlPermissionType>;
  /** The ID of the profile to invite to (the caller must own it). */
  profileId: Scalars['ID']['input'];
};

/** Input for createSellerProfile. */
export type GqlCreateSellerProfileInput = {
  /** The seller's display name (required, up to 100 characters). */
  sellerName: Scalars['String']['input'];
};

/** Input for createSharedCampaign. Publishes a campaign so other units can find and clone it. */
export type GqlCreateSharedCampaignInput = {
  /** The campaign's display name (for example "Fall" or "Spring"). */
  campaignName: Scalars['String']['input'];
  /** The campaign's year (for example 2024). */
  campaignYear: Scalars['Int']['input'];
  /** The ID of the catalog the shared campaign sells from. */
  catalogId: Scalars['ID']['input'];
  /** The city, part of the unit's identity. */
  city: Scalars['String']['input'];
  /** A message from the creator to whoever uses the shared campaign. */
  creatorMessage?: InputMaybe<Scalars['String']['input']>;
  /** A description of the campaign. */
  description?: InputMaybe<Scalars['String']['input']>;
  /** The campaign's end date. */
  endDate?: InputMaybe<Scalars['AWSDate']['input']>;
  /** The campaign's start date. */
  startDate?: InputMaybe<Scalars['AWSDate']['input']>;
  /** The state, part of the unit's identity. */
  state: Scalars['String']['input'];
  /** The scout unit number. */
  unitNumber: Scalars['Int']['input'];
  /** The scout unit type. */
  unitType: Scalars['String']['input'];
};

/** Input for createUnitCampaign. The catalog must exist and be usable by the campaign. */
export type GqlCreateUnitCampaignInput = {
  /** The sales-season name. */
  campaignName: Scalars['String']['input'];
  /** The sales year. */
  campaignYear: Scalars['Int']['input'];
  /** The existing catalog used by this campaign. */
  catalogId: Scalars['ID']['input'];
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The parent Unit. */
  unitId: Scalars['ID']['input'];
};

/** Input for createUnit. The caller becomes the initial Unit Admin; an exact metadata match requires duplicateConfirmed. */
export type GqlCreateUnitInput = {
  /** Geographic discriminator: the city. */
  city: Scalars['String']['input'];
  /** Primary presentation basis for the unit's needs report. */
  councilNeedBasis?: InputMaybe<GqlCouncilNeedBasis>;
  /** Optional display name; generated from the metadata when omitted. */
  displayName?: InputMaybe<Scalars['String']['input']>;
  /** Set true to confirm an exact unitType/unitNumber/city/state duplicate. */
  duplicateConfirmed?: InputMaybe<Scalars['Boolean']['input']>;
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** Unit-wide default split method for new events. */
  splitDefault?: InputMaybe<GqlSplitMethod>;
  /** Geographic discriminator: the state. */
  state: Scalars['String']['input'];
  /** Timezone for display and calendar generation. */
  timezone: Scalars['String']['input'];
  /** The scout unit number. */
  unitNumber: Scalars['Int']['input'];
  /** The scout unit type, for example Pack or Troop. */
  unitType: Scalars['String']['input'];
};

/** Input for createUnitInvite. Generates a 16-character, 14-day, single-use invite. */
export type GqlCreateUnitInviteInput = {
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The Unit to generate an invite for. */
  unitId: Scalars['ID']['input'];
};

/** The result of createUnit: the new Unit and the creator's initial admin grant. */
export type GqlCreateUnitPayload = {
  __typename?: 'CreateUnitPayload';
  /** The creator's initial Unit Admin grant. */
  grant: GqlUnitAccessGrant;
  /** The newly created Unit. */
  unit: GqlUnit;
};

export type GqlEventInventoryAllocation = {
  __typename?: 'EventInventoryAllocation';
  allocatedQty: Scalars['Int']['output'];
  allocationId: Scalars['ID']['output'];
  intervalEnd?: Maybe<Scalars['String']['output']>;
  intervalStart?: Maybe<Scalars['String']['output']>;
  productId: Scalars['ID']['output'];
  releasedQty: Scalars['Int']['output'];
  remainingQty: Scalars['Int']['output'];
  showAndSellId: Scalars['ID']['output'];
  soldQty: Scalars['Int']['output'];
  status: GqlAllocationStatus;
  unitCampaignId: Scalars['ID']['output'];
  version: Scalars['Int']['output'];
};

export type GqlEventInventoryAllocationConnection = {
  __typename?: 'EventInventoryAllocationConnection';
  items: Array<GqlEventInventoryAllocation>;
  pageInfo: GqlPageInfo;
};

/** Idempotency for a mutation: a client key scoped to the caller, operation, and resource. */
export type GqlIdempotencyInput = {
  /** Client-supplied idempotency key (1-128 trimmed characters). */
  idempotencyKey: Scalars['String']['input'];
};

/** Input for joinUnitCampaign. The caller must have Owner or WRITE on the campaign's Scout. */
export type GqlJoinUnitCampaignInput = {
  /** The caller's Scout Campaign (must match the roster identity). */
  campaignId: Scalars['ID']['input'];
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The campaign join code. */
  joinCode: Scalars['String']['input'];
};

/** A single product line within an order. */
export type GqlLineItem = {
  __typename?: 'LineItem';
  /** The product's unit price captured from the catalog at order time. */
  pricePerUnit: Scalars['Float']['output'];
  /** The ID of the product. */
  productId: Scalars['ID']['output'];
  /** The product's display name. */
  productName: Scalars['String']['output'];
  /** The quantity ordered. */
  quantity: Scalars['Int']['output'];
  /** quantity times pricePerUnit. */
  subtotal: Scalars['Float']['output'];
};

/** Input for a product line within an order; the price is looked up from the catalog. */
export type GqlLineItemInput = {
  /** The ID of the product to order. */
  productId: Scalars['ID']['input'];
  /** The quantity to order (at least 1). */
  quantity: Scalars['Int']['input'];
};

/** Membership status on a Unit Campaign roster. */
export type GqlMembershipStatus =
  /** Active roster member; may sign up for events. */
  | 'ACTIVE'
  /** Removed from the roster; blocks new signups, preserves history. */
  | 'REMOVED';

/** The root mutation object for the KernelWorx API. */
export type GqlMutation = {
  __typename?: 'Mutation';
  /** Delete a specific share, revoking that account's access to a profile (admin only). Returns true on success. */
  adminDeleteShare: Scalars['Boolean']['output'];
  /** Delete all campaigns across all profiles owned by the given account (admin only). Returns the number of campaigns deleted. */
  adminDeleteUserCampaigns: Scalars['Int']['output'];
  /** Delete all orders across all campaigns of all profiles owned by the given account (admin only). Returns the number of orders deleted. */
  adminDeleteUserOrders: Scalars['Int']['output'];
  /** Delete all profiles owned by the given account (admin only). Returns the number of profiles deleted. */
  adminDeleteUserProfiles: Scalars['Int']['output'];
  /** Delete all shares across all profiles owned by the given account (admin only). Returns the number of shares deleted. */
  adminDeleteUserShares: Scalars['Int']['output'];
  /** Delete the account record and the Cognito user for an account whose per-entity data the caller has already deleted (admin only). The caller cannot purge their own account. Catalogs are never deleted. Returns true on success. */
  adminPurgeUserAccount: Scalars['Boolean']['output'];
  /** Send a password-reset email to a user by email (admin only). Returns true once the reset is initiated. */
  adminResetUserPassword: Scalars['Boolean']['output'];
  /** Set or clear a campaign's sharedCampaignCode, associating it with a shared campaign (admin only). Returns the updated campaign. */
  adminUpdateCampaignSharedCode: GqlCampaign;
  assignShowAndSellInventory: Array<GqlEventInventoryAllocation>;
  cancelShowAndSell: GqlShowAndSellAdmin;
  /** Confirm a QR code upload for a payment method after the S3 upload completes. Returns the updated payment method. */
  confirmPaymentMethodQRCodeUpload: GqlPaymentMethod;
  /** Create a new active campaign on a profile the caller has write access to. Returns the created campaign. */
  createCampaign: GqlCampaign;
  /** Create a catalog owned by the caller. Returns the created catalog. */
  createCatalog: GqlCatalog;
  /** Create an admin-managed global catalog available to all users (admin only). Returns the created catalog. */
  createManagedCatalog: GqlCatalog;
  /** Place a new order in a campaign on a profile the caller has write access to. Returns the created order. */
  createOrder: GqlOrder;
  /** Create a new payment method for the caller. The name must be unique and not a reserved name (Cash or Check). Returns the created payment method. */
  createPaymentMethod: GqlPaymentMethod;
  /** Create a redeemable invite to join a profile the caller owns. Returns the created invite. */
  createProfileInvite: GqlProfileInvite;
  /** Create a new seller profile owned by the caller. Returns the created profile. */
  createSellerProfile: GqlSellerProfile;
  /** Create a shared campaign so other units can find and clone it. Returns the created shared campaign. */
  createSharedCampaign: GqlSharedCampaign;
  createShowAndSell: GqlShowAndSellAdmin;
  /** Create a unit; the caller becomes its initial Unit Admin. Returns the Unit and the creator grant. */
  createUnit: GqlCreateUnitPayload;
  /** Create a Unit Campaign. Unit Admin for the parent Unit. */
  createUnitCampaign: GqlUnitCampaignAdmin;
  /** Generate a 16-character, 14-day, single-use unit admin invite. Unit Admin for that Unit. */
  createUnitInvite: GqlUnitInvite;
  /** Delete a campaign and all of its orders, on a profile the caller has write access to. Returns true on success. */
  deleteCampaign: Scalars['Boolean']['output'];
  /** Soft-delete a catalog the caller owns (it is hidden from list queries but kept for reference). Returns true on success. */
  deleteCatalog: Scalars['Boolean']['output'];
  /** Delete the caller's account and all associated data (profiles, campaigns, orders, shares, and invites; catalogs are preserved) and remove the user from Cognito. Returns true on success. */
  deleteMyAccount: Scalars['Boolean']['output'];
  /** Delete an order on a profile the caller has write access to. Returns true on success. */
  deleteOrder: Scalars['Boolean']['output'];
  /** Delete one of the caller's payment methods and its stored QR code. Returns true on success. */
  deletePaymentMethod: Scalars['Boolean']['output'];
  /** Delete the stored QR code for a payment method. Returns true on success. */
  deletePaymentMethodQRCode: Scalars['Boolean']['output'];
  /** Delete (revoke) an invite on a profile the caller owns. Returns true on success. */
  deleteProfileInvite: Scalars['Boolean']['output'];
  /** Delete a seller profile the caller owns, along with all of its campaigns, orders, shares, and invites. Returns true on success. */
  deleteSellerProfile: Scalars['Boolean']['output'];
  /** Delete a shared campaign the caller created. Returns true on success. */
  deleteSharedCampaign: Scalars['Boolean']['output'];
  deleteShowAndSellSlot: Scalars['Boolean']['output'];
  /** Join a Unit Campaign with a join code. Any authenticated account with Owner or WRITE on the Scout. */
  joinUnitCampaign: GqlUnitCampaignMembership;
  /** Place a public order on a campaign whose share token is in the request. Returns the buyer's receipt. A never-enabled campaign, a disabled campaign, and a bad token all return NOT_FOUND so probing cannot distinguish them; a campaign at its order cap returns PUBLIC_ORDER_LIMIT_EXCEEDED. */
  publicCreateOrder: GqlPublicOrderReceipt;
  /** Redeem an invite code to grant the caller access to a profile. Returns the created share. */
  redeemProfileInvite: GqlShare;
  /** Redeem a single-use, unexpired invite to become a Unit Admin. Any authenticated account. */
  redeemUnitInvite: GqlUnitAccessGrant;
  /** Remove a Scout from a Unit Campaign roster (sets REMOVED). Unit Admin for the parent Unit. */
  removeUnitCampaignMembership: GqlUnitCampaignMembership;
  /** Get pre-signed S3 credentials to upload a QR code for one of the caller's payment methods. */
  requestPaymentMethodQRCodeUpload: GqlS3UploadInfo;
  /** Remove a share's access to a profile the caller owns. Returns true on success. */
  revokeShare: Scalars['Boolean']['output'];
  /** Revoke a Unit Admin grant; the last grant returns CONFLICT. Unit Admin for that Unit. */
  revokeUnitAccessGrant: GqlUnit;
  /** Revoke an unused unit invite. Unit Admin for that Unit. */
  revokeUnitInvite: Scalars['Boolean']['output'];
  /** Share a profile the caller owns directly with another account by email. Returns the created share. */
  shareProfileDirect: GqlShare;
  /** Transfer a profile's ownership to an account that already has a share (the caller must be the owner or an admin). Returns the updated profile. */
  transferProfileOwnership: GqlSellerProfile;
  /** Update a campaign on a profile the caller has write access to. Only provided fields change. Returns the updated campaign. */
  updateCampaign: GqlCampaign;
  /** Enable, configure, or disable one campaign's public order surface. Owner only (share collaborators are FORBIDDEN). Enabling requires the campaign to be active, its catalog to exist and not be soft-deleted, and a non-empty method list, and re-requires the acknowledgements when the stored version is behind. Disabling keeps the share token so the URL stays stable; rotateToken mints a replacement. */
  updateCampaignPublicOrderSettings: GqlPublicOrderSettings;
  /** Update a catalog the caller owns, replacing its name, visibility, and products. Returns the updated catalog. */
  updateCatalog: GqlCatalog;
  /** Update profile fields on the caller's own account. At least one field must be provided. Returns the updated account. */
  updateMyAccount: GqlAccount;
  /** Replace the caller's account preferences blob. Returns the updated account. */
  updateMyPreferences: GqlAccount;
  /** Update an order on a profile the caller has write access to. Only provided fields change. Returns the updated order. */
  updateOrder: GqlOrder;
  /** Rename one of the caller's payment methods. Returns the updated payment method. */
  updatePaymentMethod: GqlPaymentMethod;
  /** Update a seller profile the caller owns. Returns the updated profile. */
  updateSellerProfile: GqlSellerProfile;
  /** Update a shared campaign the caller created. Only provided fields change. Returns the updated shared campaign. */
  updateSharedCampaign: GqlSharedCampaign;
  updateShowAndSell: GqlShowAndSellAdmin;
  /** Update a unit's metadata and settings. Unit Admin for that Unit. */
  updateUnit: GqlUnit;
  /** Update a Unit Campaign's name, year, and active state. Unit Admin for the parent Unit. */
  updateUnitCampaign: GqlUnitCampaignAdmin;
  upsertShowAndSellSlot: GqlShowAndSellSlot;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminDeleteShareArgs = {
  profileId: Scalars['ID']['input'];
  targetAccountId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminDeleteUserCampaignsArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminDeleteUserOrdersArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminDeleteUserProfilesArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminDeleteUserSharesArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminPurgeUserAccountArgs = {
  accountId: Scalars['ID']['input'];
  profileIds: Array<Scalars['ID']['input']>;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminResetUserPasswordArgs = {
  email: Scalars['AWSEmail']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AdminUpdateCampaignSharedCodeArgs = {
  campaignId: Scalars['ID']['input'];
  sharedCampaignCode?: InputMaybe<Scalars['String']['input']>;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_AssignShowAndSellInventoryArgs = {
  expectedVersion: Scalars['Int']['input'];
  idempotencyKey: Scalars['String']['input'];
  items?: InputMaybe<Array<GqlAllocationTargetInput>>;
  showAndSellId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CancelShowAndSellArgs = {
  expectedVersion: Scalars['Int']['input'];
  idempotencyKey: Scalars['String']['input'];
  reason: Scalars['String']['input'];
  showAndSellId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_ConfirmPaymentMethodQrCodeUploadArgs = {
  paymentMethodName: Scalars['String']['input'];
  s3Key: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateCampaignArgs = {
  input: GqlCreateCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateCatalogArgs = {
  input: GqlCreateCatalogInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateManagedCatalogArgs = {
  input: GqlCreateCatalogInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateOrderArgs = {
  input: GqlCreateOrderInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreatePaymentMethodArgs = {
  name: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateProfileInviteArgs = {
  input: GqlCreateProfileInviteInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateSellerProfileArgs = {
  input: GqlCreateSellerProfileInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateSharedCampaignArgs = {
  input: GqlCreateSharedCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateShowAndSellArgs = {
  address?: InputMaybe<Scalars['String']['input']>;
  endAt: Scalars['String']['input'];
  idempotencyKey: Scalars['String']['input'];
  locationName: Scalars['String']['input'];
  splitMethod?: InputMaybe<Scalars['String']['input']>;
  startAt: Scalars['String']['input'];
  unitCampaignId: Scalars['ID']['input'];
  weOweEnabled?: InputMaybe<Scalars['Boolean']['input']>;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateUnitArgs = {
  input: GqlCreateUnitInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateUnitCampaignArgs = {
  input: GqlCreateUnitCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_CreateUnitInviteArgs = {
  input: GqlCreateUnitInviteInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteCampaignArgs = {
  campaignId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteCatalogArgs = {
  catalogId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteOrderArgs = {
  orderId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeletePaymentMethodArgs = {
  name: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeletePaymentMethodQrCodeArgs = {
  paymentMethodName: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteProfileInviteArgs = {
  inviteCode: Scalars['ID']['input'];
  profileId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteSellerProfileArgs = {
  profileId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteSharedCampaignArgs = {
  sharedCampaignCode: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_DeleteShowAndSellSlotArgs = {
  expectedVersion: Scalars['Int']['input'];
  idempotencyKey: Scalars['String']['input'];
  showAndSellId: Scalars['ID']['input'];
  slotId: Scalars['ID']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_JoinUnitCampaignArgs = {
  input: GqlJoinUnitCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_PublicCreateOrderArgs = {
  input: GqlPublicCreateOrderInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RedeemProfileInviteArgs = {
  input: GqlRedeemProfileInviteInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RedeemUnitInviteArgs = {
  input: GqlRedeemUnitInviteInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RemoveUnitCampaignMembershipArgs = {
  input: GqlRemoveUnitCampaignMembershipInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RequestPaymentMethodQrCodeUploadArgs = {
  paymentMethodName: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RevokeShareArgs = {
  input: GqlRevokeShareInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RevokeUnitAccessGrantArgs = {
  input: GqlRevokeUnitAccessGrantInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_RevokeUnitInviteArgs = {
  input: GqlRevokeUnitInviteInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_ShareProfileDirectArgs = {
  input: GqlShareProfileDirectInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_TransferProfileOwnershipArgs = {
  input: GqlTransferProfileOwnershipInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateCampaignArgs = {
  input: GqlUpdateCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateCampaignPublicOrderSettingsArgs = {
  input: GqlUpdateCampaignPublicOrderSettingsInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateCatalogArgs = {
  catalogId: Scalars['ID']['input'];
  input: GqlCreateCatalogInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateMyAccountArgs = {
  input: GqlUpdateMyAccountInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateMyPreferencesArgs = {
  preferences: Scalars['AWSJSON']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateOrderArgs = {
  input: GqlUpdateOrderInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdatePaymentMethodArgs = {
  currentName: Scalars['String']['input'];
  newName: Scalars['String']['input'];
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateSellerProfileArgs = {
  input: GqlUpdateSellerProfileInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateSharedCampaignArgs = {
  input: GqlUpdateSharedCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateShowAndSellArgs = {
  address?: InputMaybe<Scalars['String']['input']>;
  expectedVersion: Scalars['Int']['input'];
  idempotencyKey: Scalars['String']['input'];
  locationName?: InputMaybe<Scalars['String']['input']>;
  showAndSellId: Scalars['ID']['input'];
  splitMethod?: InputMaybe<Scalars['String']['input']>;
  weOweEnabled?: InputMaybe<Scalars['Boolean']['input']>;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateUnitArgs = {
  input: GqlUpdateUnitInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpdateUnitCampaignArgs = {
  input: GqlUpdateUnitCampaignInput;
};

/** The root mutation object for the KernelWorx API. */
export type GqlMutation_UpsertShowAndSellSlotArgs = {
  capacity: Scalars['Int']['input'];
  endAt: Scalars['String']['input'];
  expectedEventVersion: Scalars['Int']['input'];
  expectedSlotVersion?: InputMaybe<Scalars['Int']['input']>;
  idempotencyKey: Scalars['String']['input'];
  label?: InputMaybe<Scalars['String']['input']>;
  showAndSellId: Scalars['ID']['input'];
  slotId?: InputMaybe<Scalars['ID']['input']>;
  startAt: Scalars['String']['input'];
};

/** A customer order placed in a campaign. */
export type GqlOrder = {
  __typename?: 'Order';
  /** The ID of the campaign the order belongs to. */
  campaignId: Scalars['ID']['output'];
  /** When the order was confirmed by the seller (for CONFIRMED orders). */
  confirmedAt?: Maybe<Scalars['AWSDateTime']['output']>;
  /** The account ID of the user who confirmed the order (for CONFIRMED orders). */
  confirmedBy?: Maybe<Scalars['ID']['output']>;
  /** When the order was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The customer's address, if provided. */
  customerAddress?: Maybe<GqlAddress>;
  /** The customer's name. */
  customerName: Scalars['String']['output'];
  /** The customer's phone number, if provided. */
  customerPhone?: Maybe<Scalars['String']['output']>;
  /** The ordered products and quantities, with prices captured from the catalog at order time. */
  lineItems: Array<GqlLineItem>;
  /** Free-text notes about the order. */
  notes?: Maybe<Scalars['String']['output']>;
  /** When the order was placed. */
  orderDate: Scalars['AWSDateTime']['output'];
  /** The order's unique ID (with the ORDER# prefix). */
  orderId: Scalars['ID']['output'];
  /** The name of the payment method used for this order. */
  paymentMethod: Scalars['String']['output'];
  /** The ID of the profile the order belongs to. */
  profileId: Scalars['ID']['output'];
  /** The order's payment-verification state. Absent on pre-feature rows; the public path always writes NEW. */
  status?: Maybe<GqlOrderStatus>;
  /** The order's total amount (the sum of the line-item subtotals). */
  totalAmount: Scalars['Float']['output'];
  /** The Unit Campaign the campaign was joined to when this order was created; null for an independent campaign. Captured immutably at order creation (API-FIX-05). */
  unitCampaignId?: Maybe<Scalars['ID']['output']>;
  /** The Unit the campaign was joined to when this order was created; null for an independent campaign. Captured immutably at order creation (API-FIX-05). */
  unitId?: Maybe<Scalars['ID']['output']>;
  /** When the order was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
};

/** A page of Order results from listOrdersByCampaign, with a token for fetching the next page. */
export type GqlOrderConnection = {
  __typename?: 'OrderConnection';
  /** Token to pass to listOrdersByCampaign to fetch the next page, or null if there are no more results. */
  nextToken?: Maybe<Scalars['String']['output']>;
  /** The orders on this page. */
  orders: Array<GqlOrder>;
};

/** The payment-verification state of an order. Authenticated orders leave this absent; the public path always writes NEW. */
export type GqlOrderStatus =
  /** The seller confirmed the buyer paid. */
  | 'CONFIRMED'
  /** Created, awaiting the seller's off-platform payment verification. */
  | 'NEW';

/** Server-issued cursor state for one page of a Show & Sell connection. */
export type GqlPageInfo = {
  __typename?: 'PageInfo';
  /** Opaque cursor to pass back as `page.cursor` to fetch the next page, or null when no results remain. */
  endCursor?: Maybe<Scalars['String']['output']>;
  /** True while more results remain after this page. */
  hasNextPage: Scalars['Boolean']['output'];
};

/** Pagination parameters for a list resolver: a limit (default 50, max 100) and an opaque cursor. */
export type GqlPageInput = {
  /** Opaque cursor from a previous page; omit to start from the first page. */
  cursor?: InputMaybe<Scalars['String']['input']>;
  /** Maximum number of items to return in the page (1-100). Defaults to 50. */
  limit?: InputMaybe<Scalars['Int']['input']>;
};

/**
 * A named payment method a seller can assign to orders.
 *
 * In addition to the caller's stored methods, two built-in methods, "Cash" and "Check", are always returned by the payment-method queries. `qrCodeUrl` is a short-lived pre-signed S3 GET URL when a QR code has been uploaded for the method, or null otherwise.
 */
export type GqlPaymentMethod = {
  __typename?: 'PaymentMethod';
  /** The display name of the payment method. */
  name: Scalars['String']['output'];
  /** A pre-signed S3 GET URL for the method's uploaded QR code, or null when no QR code is stored or the caller may not view it. */
  qrCodeUrl?: Maybe<Scalars['String']['output']>;
};

/** The level of access a seller profile is granted to another account through a share. WRITE implies READ: a WRITE holder can view and modify, a READ holder can only view. */
export type GqlPermissionType =
  /** View the profile and its campaigns, orders, and generated reports. */
  | 'READ'
  /** View and modify the profile's campaigns and orders (place and update orders). */
  | 'WRITE';

/** A product in a catalog, with a price and an ordering position within the catalog. */
export type GqlProduct = {
  __typename?: 'Product';
  /** A free-text description of the product. */
  description?: Maybe<Scalars['String']['output']>;
  /** The product's unit price. */
  price: Scalars['Float']['output'];
  /** The product's unique ID. */
  productId: Scalars['ID']['output'];
  /** The product's display name. */
  productName: Scalars['String']['output'];
  /** The display order of the product within the catalog. */
  sortOrder: Scalars['Int']['output'];
};

/** Input for a product within a catalog. */
export type GqlProductInput = {
  /** A free-text description of the product. */
  description?: InputMaybe<Scalars['String']['input']>;
  /** The product's unit price. */
  price: Scalars['Float']['input'];
  /** The product's display name. */
  productName: Scalars['String']['input'];
  /** The display order of the product within the catalog. */
  sortOrder: Scalars['Int']['input'];
};

/** An invitation for another account to join a seller profile, redeemable by its invite code. */
export type GqlProfileInvite = {
  __typename?: 'ProfileInvite';
  /** When the invite was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The ID of the account that created the invite. */
  createdByAccountId: Scalars['ID']['output'];
  /** When the invite expires; it can no longer be redeemed after this time. */
  expiresAt: Scalars['AWSDateTime']['output'];
  /** The invite's code, the credential the recipient redeems to gain access. */
  inviteCode: Scalars['ID']['output'];
  /** The permissions the invite grants once redeemed. */
  permissions: Array<GqlPermissionType>;
  /** The ID of the profile the invite grants access to. */
  profileId: Scalars['ID']['output'];
};

/** Input for publicCreateOrder, submitted anonymously from the public order page. Input types carry no auth directive: AppSync field-level authorization does not govern inputs. */
export type GqlPublicCreateOrderInput = {
  acknowledgementsAccepted: Scalars['Boolean']['input'];
  address?: InputMaybe<GqlAddressInput>;
  campaignId: Scalars['ID']['input'];
  email?: InputMaybe<Scalars['AWSEmail']['input']>;
  firstName: Scalars['String']['input'];
  lastName: Scalars['String']['input'];
  lineItems: Array<GqlLineItemInput>;
  notes?: InputMaybe<Scalars['String']['input']>;
  paymentMethod: Scalars['String']['input'];
  phone?: InputMaybe<Scalars['String']['input']>;
  token: Scalars['String']['input'];
};

/** A line item on the buyer's receipt: the product and price captured at order time. */
export type GqlPublicLineItem = {
  __typename?: 'PublicLineItem';
  /** The product's unit price captured from the catalog at order time. */
  pricePerUnit: Scalars['Float']['output'];
  /** The ID of the product. */
  productId: Scalars['ID']['output'];
  /** The product's display name as captured at order time. */
  productName: Scalars['String']['output'];
  /** The quantity ordered. */
  quantity: Scalars['Int']['output'];
  /** quantity times pricePerUnit. */
  subtotal: Scalars['Float']['output'];
};

/** What the public order page shows a buyer. Served to an API-key caller; the share token in the page URL is the authorization. */
export type GqlPublicOrderOffer = {
  __typename?: 'PublicOrderOffer';
  /** The campaign's ID in bare (unprefixed) form. Echo it back on publicCreateOrder. */
  campaignId: Scalars['ID']['output'];
  /** The campaign's display name. */
  campaignName: Scalars['String']['output'];
  /** True when the campaign has reached its public order cap (500). */
  isSoldOut?: Maybe<Scalars['Boolean']['output']>;
  /** The allowlisted payment methods that still exist on the account, each with a short-lived pre-signed QR image URL when a QR was uploaded. */
  paymentMethods: Array<GqlPublicPaymentMethod>;
  /** The campaign's catalog's products in catalog order (v1: the full active catalog, unpaginated). */
  products: Array<GqlPublicProduct>;
  /** Remaining order slots before the campaign reaches its public order cap (500). Null if the campaign has no cap. */
  remainingOrders?: Maybe<Scalars['Int']['output']>;
  /** The seller profile's display name. */
  sellerName: Scalars['String']['output'];
};

/** The receipt returned when publicCreateOrder succeeds. */
export type GqlPublicOrderReceipt = {
  __typename?: 'PublicOrderReceipt';
  /** Whether the buyer supplied an email address. */
  buyerEmailProvided: Scalars['Boolean']['output'];
  /** Whether the confirmation email was sent. false also honestly covers \"not configured\" and \"send failed\"; email failure never fails the order. */
  confirmationEmailSent: Scalars['Boolean']['output'];
  /** The order's full ID (ORDER#...#... form), for display and support. */
  orderId: Scalars['ID']['output'];
  /** The buyer's receipt link as a site-relative path (/r/<campaignId>/<orderSuffix>/<receiptToken>): a resolver has no site origin, so the success screen resolves it against its own origin. The emailed copy is composed absolutely in the email slice. */
  receiptUrl?: Maybe<Scalars['String']['output']>;
  /** The order's total amount. */
  totalAmount: Scalars['Float']['output'];
};

/** The buyer's receipt for a public order, served to the receipt link's API-key caller. The receipt token in the URL is the authorization. */
export type GqlPublicOrderReceiptLookup = {
  __typename?: 'PublicOrderReceiptLookup';
  /** The buyer's first name as submitted. */
  buyerFirstName: Scalars['String']['output'];
  /** The buyer's last name as submitted. */
  buyerLastName: Scalars['String']['output'];
  /** The ordered products and quantities. */
  lineItems: Array<GqlPublicLineItem>;
  /** When the order was placed. */
  orderDate: Scalars['AWSDateTime']['output'];
  /** The order's full ID (ORDER#...#... form). */
  orderId: Scalars['ID']['output'];
  /** The name of the payment method the buyer selected. */
  paymentMethodName: Scalars['String']['output'];
  /** The seller profile's display name. */
  sellerName: Scalars['String']['output'];
  /** The order's payment-verification state (NEW until the seller confirms payment). */
  status: GqlOrderStatus;
  /** The order's total amount. */
  totalAmount: Scalars['Float']['output'];
};

/** Owner-facing settings for one campaign's public order surface. Owner-only on read and write. */
export type GqlPublicOrderSettings = {
  __typename?: 'PublicOrderSettings';
  ackVersion?: Maybe<Scalars['Int']['output']>;
  acknowledgedAt?: Maybe<Scalars['AWSDateTime']['output']>;
  allowedPaymentMethods: Array<Scalars['String']['output']>;
  campaignId: Scalars['ID']['output'];
  campaignName: Scalars['String']['output'];
  campaignState: GqlCampaignState;
  enabled: Scalars['Boolean']['output'];
  publicOrderCount?: Maybe<Scalars['Int']['output']>;
  shareToken?: Maybe<Scalars['String']['output']>;
};

/** A payment method a buyer may select on the public order page. */
export type GqlPublicPaymentMethod = {
  __typename?: 'PublicPaymentMethod';
  /** The method's display name. */
  name: Scalars['String']['output'];
  /** Pre-signed S3 GET URL for the seller's uploaded QR image (valid for 15 minutes), or null when the method has no QR. */
  qrCodeUrl?: Maybe<Scalars['String']['output']>;
};

/** A catalog product as the public order page sees it. Mirrors Product's field names verbatim: Product itself carries @aws_cognito_user_pools and cannot be returned to an API-key caller. */
export type GqlPublicProduct = {
  __typename?: 'PublicProduct';
  /** The product's description. */
  description?: Maybe<Scalars['String']['output']>;
  /** The product's unit price. */
  price: Scalars['Float']['output'];
  /** The product's ID within its catalog. */
  productId: Scalars['ID']['output'];
  /** The product's display name. */
  productName: Scalars['String']['output'];
  /** The product's position in the catalog; the offer is ordered by it. */
  sortOrder?: Maybe<Scalars['Int']['output']>;
};

/** The root query object for the KernelWorx API. */
export type GqlQuery = {
  __typename?: 'Query';
  /** List all shares (access grants) on a profile (admin only). */
  adminGetProfileShares: Array<GqlShare>;
  /** List all campaigns owned by the given account (admin only). */
  adminGetUserCampaigns: Array<GqlCampaign>;
  /** List all catalogs owned by the given account (admin only). */
  adminGetUserCatalogs: Array<GqlCatalog>;
  /** List all seller profiles owned by the given account (admin only). */
  adminGetUserProfiles: Array<GqlSellerProfile>;
  /** List all shared campaigns created by the given account (admin only). */
  adminGetUserSharedCampaigns: Array<GqlSharedCampaign>;
  /** List all Cognito users, merged with their stored Account data, with pagination (admin only). */
  adminListUsers: GqlAdminUserConnection;
  /** Search users by email, name, or accountId (admin only). */
  adminSearchUser: Array<GqlAdminUser>;
  eventInventoryAllocations: GqlEventInventoryAllocationConnection;
  /** Find active shared campaigns that exactly match the given unit and season (unitType, unitNumber, city, state, campaignName, and campaignYear). Inactive shared campaigns are excluded. */
  findSharedCampaigns: Array<GqlSharedCampaign>;
  /** Fetch a single campaign by ID. Returns the campaign if the caller has read access to its profile, otherwise null. */
  getCampaign?: Maybe<GqlCampaign>;
  /** Owner-facing settings for one campaign's public order surface. Owner-only on read and write. */
  getCampaignPublicOrderSettings?: Maybe<GqlPublicOrderSettings>;
  /** Fetch a single catalog by ID. Returns the catalog only when it is public, admin-managed (ADMIN_MANAGED), or owned by the caller; returns null otherwise. */
  getCatalog?: Maybe<GqlCatalog>;
  /** The authenticated caller's account. The row is created automatically on first read if it does not yet exist. */
  getMyAccount: GqlAccount;
  /** Fetch a single order by ID. Returns the order if the caller has read access to its profile, otherwise null. */
  getOrder?: Maybe<GqlOrder>;
  /** Fetch a single seller profile by ID. Returns the profile if the caller owns it or has read access via a share, otherwise null. */
  getProfile?: Maybe<GqlSellerProfile>;
  /** Fetch a single shared campaign by its bearer code. Returns null when the code is unknown or the shared campaign is inactive. */
  getSharedCampaign?: Maybe<GqlSharedCampaign>;
  /** Generate a unit-level sales report for a unit and season, covering only the sellers (profiles) the caller can read. catalogId is required so the report reflects a single catalog. */
  getUnitReport?: Maybe<GqlUnitReport>;
  /** List the campaigns on a profile, with pagination. The caller must have read access to the profile. */
  listCampaignsByProfile: GqlCampaignConnection;
  /** Return the IDs of every catalog used by a campaign the caller owns or has access to via a share. */
  listCatalogsInUse: Array<Scalars['ID']['output']>;
  /** List the pending invites on a profile. Owner only: a caller whose write access comes from a share is not authorized to list invites and receives an empty list. */
  listInvitesByProfile: Array<GqlProfileInvite>;
  /** List the public, admin-managed catalogs available to all users (soft-deleted catalogs excluded). */
  listManagedCatalogs: Array<GqlCatalog>;
  /** List the catalogs the caller has created (soft-deleted catalogs excluded). */
  listMyCatalogs: Array<GqlCatalog>;
  /** List the seller profiles the caller owns, with pagination. */
  listMyProfiles: GqlSellerProfileConnection;
  /** List the active shared campaigns the caller has created, most recent first. */
  listMySharedCampaigns: Array<GqlSharedCampaign>;
  /** List seller profiles that have been shared to the caller, each annotated with the caller's permissions. */
  listMyShares: Array<GqlSharedProfile>;
  /** List the orders in a campaign, with pagination. The caller must have read access to the campaign's profile. */
  listOrdersByCampaign: GqlOrderConnection;
  /** List the shares (access grants) on a profile. The caller must have write access to the profile. */
  listSharesByProfile: Array<GqlShare>;
  /** The payment methods available to the caller: the caller's stored custom methods plus the built-in "Cash" and "Check" methods, sorted by name. */
  myPaymentMethods: Array<GqlPaymentMethod>;
  /** The Units on which the caller holds a Unit Admin grant. No cross-Unit data. */
  myUnits: GqlUnitConnection;
  /** The payment methods stored for a profile's owner. The caller must have access to the profile; READ-only callers see the method names but not their QR codes (qrCodeUrl is null). */
  paymentMethodsForProfile: Array<GqlPaymentMethod>;
  /** Fetch the public order page's offer: seller, campaign, catalog products, and allowed payment methods. A campaign that never enabled public orders, is disabled, or carries a token mismatch all return the same NOT_FOUND, so probing cannot distinguish them. */
  publicGetOrderOffer: GqlPublicOrderOffer;
  /** Fetch the buyer's receipt for a public order. Served to an API-key caller; the receipt token in the URL is the authorization. An unknown campaign/suffix, an absent or mismatched token, and a token that does not match the order all return the same NOT_FOUND. */
  publicGetOrderReceipt: GqlPublicOrderReceiptLookup;
  showAndSell?: Maybe<GqlShowAndSellAdmin>;
  showAndSellOpportunity?: Maybe<GqlShowAndSellOpportunity>;
  showAndSells: GqlShowAndSellAdminConnection;
  /** The unit's settings and admin count. Unit Admin for that Unit. */
  unit?: Maybe<GqlUnit>;
  /** The unit's admin grants; account email/name limited to administration needs. Unit Admin. */
  unitAdmins: GqlUnitAccessGrantConnection;
  /** The campaign's join code and settings. Unit Admin for the parent Unit. */
  unitCampaign?: Maybe<GqlUnitCampaignAdmin>;
  /** The campaign's catalog and product inputs for browser sales sheets. Unit Admin for the parent Unit. */
  unitCampaignCatalog?: Maybe<GqlUnitCampaignCatalog>;
  /** The member-safe preview of a campaign from its join code; any authenticated account. No inventory, roster, or grant data. */
  unitCampaignJoinInfo?: Maybe<GqlUnitCampaignJoinPreview>;
  unitCampaignOpportunities: GqlShowAndSellOpportunityConnection;
  /** A Unit Campaign's roster, including removed history. Unit Admin for the parent Unit. */
  unitCampaignRoster: GqlUnitCampaignMembershipConnection;
  /** A Unit's campaigns. Unit Admin for the parent Unit. */
  unitCampaigns: GqlUnitCampaignConnection;
  /** The unit's active, unused invites; the code is returned only for them. Unit Admin. */
  unitInvites: GqlUnitInviteConnection;
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminGetProfileSharesArgs = {
  profileId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminGetUserCampaignsArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminGetUserCatalogsArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminGetUserProfilesArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminGetUserSharedCampaignsArgs = {
  accountId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminListUsersArgs = {
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_AdminSearchUserArgs = {
  query: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_EventInventoryAllocationsArgs = {
  page?: InputMaybe<GqlPageInput>;
  productId?: InputMaybe<Scalars['ID']['input']>;
  showAndSellId?: InputMaybe<Scalars['ID']['input']>;
  status?: InputMaybe<GqlAllocationStatus>;
  unitCampaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_FindSharedCampaignsArgs = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  city: Scalars['String']['input'];
  state: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetCampaignArgs = {
  campaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetCampaignPublicOrderSettingsArgs = {
  campaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetCatalogArgs = {
  catalogId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetOrderArgs = {
  orderId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetProfileArgs = {
  profileId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetSharedCampaignArgs = {
  sharedCampaignCode: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_GetUnitReportArgs = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  catalogId: Scalars['ID']['input'];
  city?: InputMaybe<Scalars['String']['input']>;
  state?: InputMaybe<Scalars['String']['input']>;
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ListCampaignsByProfileArgs = {
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
  profileId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ListInvitesByProfileArgs = {
  profileId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ListMyProfilesArgs = {
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ListOrdersByCampaignArgs = {
  campaignId: Scalars['ID']['input'];
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ListSharesByProfileArgs = {
  profileId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_MyUnitsArgs = {
  page?: InputMaybe<GqlPageInput>;
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_PaymentMethodsForProfileArgs = {
  profileId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_PublicGetOrderOfferArgs = {
  campaignId: Scalars['ID']['input'];
  token: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_PublicGetOrderReceiptArgs = {
  campaignId: Scalars['ID']['input'];
  orderSuffix: Scalars['String']['input'];
  receiptToken: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ShowAndSellArgs = {
  showAndSellId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ShowAndSellOpportunityArgs = {
  profileId: Scalars['ID']['input'];
  showAndSellId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_ShowAndSellsArgs = {
  page?: InputMaybe<GqlPageInput>;
  status?: InputMaybe<GqlShowAndSellStatus>;
  unitCampaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitArgs = {
  unitId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitAdminsArgs = {
  page?: InputMaybe<GqlPageInput>;
  unitId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitCampaignArgs = {
  unitCampaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitCampaignCatalogArgs = {
  unitCampaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitCampaignJoinInfoArgs = {
  joinCode: Scalars['String']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitCampaignOpportunitiesArgs = {
  includePast?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<GqlPageInput>;
  unitCampaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitCampaignRosterArgs = {
  page?: InputMaybe<GqlPageInput>;
  status?: InputMaybe<GqlMembershipStatus>;
  unitCampaignId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitCampaignsArgs = {
  isActive?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<GqlPageInput>;
  unitId: Scalars['ID']['input'];
};

/** The root query object for the KernelWorx API. */
export type GqlQuery_UnitInvitesArgs = {
  page?: InputMaybe<GqlPageInput>;
  unitId: Scalars['ID']['input'];
};

/** Input for redeemProfileInvite. Redeems an invite code to gain access to a profile. */
export type GqlRedeemProfileInviteInput = {
  /** The invite code to redeem. */
  inviteCode: Scalars['ID']['input'];
};

/** Input for redeemUnitInvite. Redeems a single-use, unexpired invite to grant Unit Admin. */
export type GqlRedeemUnitInviteInput = {
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The invite code to redeem. */
  inviteCode: Scalars['String']['input'];
};

/** Input for removeUnitCampaignMembership. Sets the roster status to REMOVED; blocks new signups only. */
export type GqlRemoveUnitCampaignMembershipInput = {
  /** The Scout Campaign to remove from the roster. */
  campaignId: Scalars['ID']['input'];
  /** The ScoutCampaignMembershipGuard version the caller last read (optimistic concurrency). */
  expectedGuardVersion: Scalars['Int']['input'];
  /** The membership version the caller last read (optimistic concurrency). */
  expectedMembershipVersion: Scalars['Int']['input'];
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The Unit Campaign the membership is on. */
  unitCampaignId: Scalars['ID']['input'];
};

/** Input for revokeShare. Removes a share's access to a profile (owner only). */
export type GqlRevokeShareInput = {
  /** The ID of the profile the share is on. */
  profileId: Scalars['ID']['input'];
  /** The ID of the account whose access should be revoked. */
  targetAccountId: Scalars['ID']['input'];
};

/** Input for revokeUnitAccessGrant. Revokes a Unit Admin grant; the last grant returns CONFLICT. */
export type GqlRevokeUnitAccessGrantInput = {
  /** The account whose grant is revoked. */
  accountId: Scalars['ID']['input'];
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The Unit the grant is on. */
  unitId: Scalars['ID']['input'];
  /** The Unit version the caller last read (optimistic concurrency). */
  version: GqlVersionedInput;
};

/** Input for revokeUnitInvite. Revokes an unused invite. */
export type GqlRevokeUnitInviteInput = {
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** The invite code to revoke. */
  inviteCode: Scalars['String']['input'];
  /** The Unit the invite belongs to. */
  unitId: Scalars['ID']['input'];
};

/** Credentials for uploading a file directly to S3 via a pre-signed POST request. */
export type GqlS3UploadInfo = {
  __typename?: 'S3UploadInfo';
  /** The form fields to include in the POST body (for example key, policy, and signature). */
  fields: Scalars['AWSJSON']['output'];
  /** The S3 object key where the file will be stored; pass this back to confirmPaymentMethodQRCodeUpload. */
  s3Key: Scalars['String']['output'];
  /** The pre-signed S3 URL to POST the file to. */
  uploadUrl: Scalars['String']['output'];
};

export type GqlScoutCommitment = {
  __typename?: 'ScoutCommitment';
  commitmentId: Scalars['ID']['output'];
  profileId: Scalars['ID']['output'];
  showAndSellId: Scalars['ID']['output'];
  status: GqlCommitmentStatus;
  version: Scalars['Int']['output'];
};

export type GqlScoutCommitmentGuard = {
  __typename?: 'ScoutCommitmentGuard';
  guardId: Scalars['ID']['output'];
  profileId: Scalars['ID']['output'];
  showAndSellId: Scalars['ID']['output'];
  version: Scalars['Int']['output'];
};

/** A seller (scout unit) profile that owns campaigns. Returned for the caller's own profiles and for profiles shared to them. */
export type GqlSellerProfile = {
  __typename?: 'SellerProfile';
  /** When the profile was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** True if the requesting account is the profile's owner. */
  isOwner: Scalars['Boolean']['output'];
  /** The profile's most recent active campaign (by creation time), or null if it has no active campaigns. */
  latestCampaign?: Maybe<GqlCampaign>;
  /** The ID of the account that owns this profile (with the ACCOUNT# prefix). */
  ownerAccountId: Scalars['ID']['output'];
  /** The caller's permissions on this profile: [READ, WRITE] for the owner, the granted share permissions for a shared profile, or null if the caller has no share. */
  permissions?: Maybe<Array<GqlPermissionType>>;
  /** The profile's unique ID (with the PROFILE# prefix). */
  profileId: Scalars['ID']['output'];
  /** The seller's display name. */
  sellerName: Scalars['String']['output'];
  /** The scout unit number, set together with unitType. */
  unitNumber?: Maybe<Scalars['Int']['output']>;
  /** The scout unit type, if the profile is scoped to a unit. */
  unitType?: Maybe<Scalars['String']['output']>;
  /** When the profile was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
};

/** A page of the caller's own seller profiles from listMyProfiles, with a token for fetching the next page. */
export type GqlSellerProfileConnection = {
  __typename?: 'SellerProfileConnection';
  /** Token to pass to listMyProfiles to fetch the next page, or null if there are no more results. */
  nextToken?: Maybe<Scalars['String']['output']>;
  /** The seller profiles owned by the caller on this page. */
  profiles: Array<GqlSellerProfile>;
};

/** A grant of access to a seller profile, letting another account (the target) view and/or modify it. */
export type GqlShare = {
  __typename?: 'Share';
  /** When the share was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The ID of the account that created the share. */
  createdByAccountId: Scalars['ID']['output'];
  /** The permissions this share grants (READ and/or WRITE). */
  permissions: Array<GqlPermissionType>;
  /** The ID of the profile this share grants access to. */
  profileId: Scalars['ID']['output'];
  /** The share's unique ID (with the SHARE# prefix). */
  shareId: Scalars['ID']['output'];
  /** The account that was granted access; null if that account no longer exists. */
  targetAccount?: Maybe<GqlAccount>;
  /** The ID of the account that was granted access (the share's target). */
  targetAccountId: Scalars['ID']['output'];
};

/** A lightweight share reference. Deprecated: use the SharedProfile returned by listMyShares instead. */
export type GqlShareInfo = {
  __typename?: 'ShareInfo';
  /** The permissions the share grants. */
  permissions: Array<GqlPermissionType>;
  /** The ID of the profile the share is for. */
  profileId: Scalars['ID']['output'];
};

/** Input for shareProfileDirect. Shares a profile directly with another account by email (owner only). */
export type GqlShareProfileDirectInput = {
  /** The permissions to grant (READ and/or WRITE). */
  permissions: Array<GqlPermissionType>;
  /** The ID of the profile to share (the caller must own it). */
  profileId: Scalars['ID']['input'];
  /** The email address of the account to grant access to; the account must already exist in Cognito. */
  targetAccountEmail: Scalars['AWSEmail']['input'];
};

/**
 * A campaign shared by its creator so other scouts and units can clone it into their own campaigns.
 *
 * Looked up by its bearer `sharedCampaignCode` (getSharedCampaign) or by an exact unit-and-season match (findSharedCampaigns). Inactive shared campaigns resolve to null and are filtered out of lists.
 */
export type GqlSharedCampaign = {
  __typename?: 'SharedCampaign';
  /** The campaign's display name (for example "Fall" or "Spring"). */
  campaignName: Scalars['String']['output'];
  /** The campaign's year (for example 2024). */
  campaignYear: Scalars['Int']['output'];
  /** The catalog this shared campaign sells from; null if the catalog is soft-deleted or missing. */
  catalog?: Maybe<GqlCatalog>;
  /** The ID of the catalog this shared campaign sells from. */
  catalogId: Scalars['ID']['output'];
  /** The city, part of the unit's identity. */
  city: Scalars['String']['output'];
  /** When the shared campaign was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The ID of the account that created this shared campaign. */
  createdBy: Scalars['ID']['output'];
  /** The display name of the creator. */
  createdByName: Scalars['String']['output'];
  /** A message from the creator to whoever uses the shared campaign. */
  creatorMessage?: Maybe<Scalars['String']['output']>;
  /** A description of the campaign. */
  description?: Maybe<Scalars['String']['output']>;
  /** The campaign's end date, if set. */
  endDate?: Maybe<Scalars['AWSDate']['output']>;
  /** Whether the shared campaign is active. Inactive shared campaigns are not returned by lookups or lists. */
  isActive: Scalars['Boolean']['output'];
  /** The shared campaign's code, the credential used to look up and redeem it. */
  sharedCampaignCode: Scalars['String']['output'];
  /** The campaign's start date, if set. */
  startDate?: Maybe<Scalars['AWSDate']['output']>;
  /** The state, part of the unit's identity. */
  state: Scalars['String']['output'];
  /** The scout unit number. */
  unitNumber: Scalars['Int']['output'];
  /** The scout unit type. */
  unitType: Scalars['String']['output'];
};

/** A seller profile shared to the caller, combining the profile's data with the share's permissions. Returned by listMyShares. */
export type GqlSharedProfile = {
  __typename?: 'SharedProfile';
  /** When the profile was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** True if the caller is the profile's owner (false for a profile merely shared to them). */
  isOwner: Scalars['Boolean']['output'];
  /** The profile's most recent active campaign, or null if it has none. */
  latestCampaign?: Maybe<GqlCampaign>;
  /** The ID of the account that owns the profile. */
  ownerAccountId: Scalars['ID']['output'];
  /** The permissions the caller holds on this profile via the share. */
  permissions: Array<GqlPermissionType>;
  /** The profile's unique ID. */
  profileId: Scalars['ID']['output'];
  /** The seller's display name. */
  sellerName: Scalars['String']['output'];
  /** The scout unit number, set together with unitType. */
  unitNumber?: Maybe<Scalars['Int']['output']>;
  /** The scout unit type, if the profile is scoped to a unit. */
  unitType?: Maybe<Scalars['String']['output']>;
  /** When the profile was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlShowAndSellAdmin = {
  __typename?: 'ShowAndSellAdmin';
  address?: Maybe<Scalars['String']['output']>;
  createdAt: Scalars['String']['output'];
  endAt: Scalars['String']['output'];
  locationName: Scalars['String']['output'];
  productIds?: Maybe<Array<Scalars['ID']['output']>>;
  showAndSellId: Scalars['ID']['output'];
  splitMethod: Scalars['String']['output'];
  startAt: Scalars['String']['output'];
  status: GqlShowAndSellStatus;
  unitCampaignId: Scalars['ID']['output'];
  updatedAt: Scalars['String']['output'];
  version: Scalars['Int']['output'];
  weOweEnabled: Scalars['Boolean']['output'];
};

export type GqlShowAndSellAdminConnection = {
  __typename?: 'ShowAndSellAdminConnection';
  items: Array<GqlShowAndSellAdmin>;
  pageInfo: GqlPageInfo;
};

export type GqlShowAndSellOpportunity = {
  __typename?: 'ShowAndSellOpportunity';
  endAt: Scalars['String']['output'];
  locationName: Scalars['String']['output'];
  mySignups?: Maybe<Array<GqlShowAndSellSignup>>;
  showAndSellId: Scalars['ID']['output'];
  slots?: Maybe<Array<GqlShowAndSellSlot>>;
  startAt: Scalars['String']['output'];
};

export type GqlShowAndSellOpportunityConnection = {
  __typename?: 'ShowAndSellOpportunityConnection';
  items: Array<GqlShowAndSellOpportunity>;
  pageInfo: GqlPageInfo;
};

export type GqlShowAndSellSignup = {
  __typename?: 'ShowAndSellSignup';
  profileId: Scalars['ID']['output'];
  showAndSellId: Scalars['ID']['output'];
  slotId: Scalars['ID']['output'];
  status: Scalars['String']['output'];
  version: Scalars['Int']['output'];
};

export type GqlShowAndSellSlot = {
  __typename?: 'ShowAndSellSlot';
  activeSignupCount: Scalars['Int']['output'];
  capacity: Scalars['Int']['output'];
  endAt: Scalars['String']['output'];
  label?: Maybe<Scalars['String']['output']>;
  showAndSellId: Scalars['ID']['output'];
  slotId: Scalars['ID']['output'];
  startAt: Scalars['String']['output'];
  version: Scalars['Int']['output'];
};

export type GqlShowAndSellSlotConnection = {
  __typename?: 'ShowAndSellSlotConnection';
  items: Array<GqlShowAndSellSlot>;
  pageInfo: GqlPageInfo;
};

export type GqlShowAndSellStatus = 'ACTIVE' | 'CANCELLED' | 'ENDED' | 'FINALIZED' | 'REOPENED' | 'SCHEDULED';

/** How event earnings are split between participants. */
export type GqlSplitMethod =
  /** Split equally among eligible participants. */
  | 'EQUAL'
  /** Split in proportion to confirmed work minutes. */
  | 'TIME_WORKED';

/** Input for transferProfileOwnership. Transfers a profile's ownership to an account that already has a share. */
export type GqlTransferProfileOwnershipInput = {
  /** The ID of the account to become the new owner; it must already hold a share on the profile. */
  newOwnerAccountId: Scalars['ID']['input'];
  /** The ID of the profile to transfer (the caller must be the owner or an admin). */
  profileId: Scalars['ID']['input'];
};

/** A scout unit: a type/number/city/state identity plus its settings and authoritative admin count. */
export type GqlUnit = {
  __typename?: 'Unit';
  /** Authoritative count of access grants; always at least 1. */
  adminCount: Scalars['Int']['output'];
  /** Geographic discriminator: the city. */
  city: Scalars['String']['output'];
  /** Primary presentation basis for the unit's needs report. */
  councilNeedBasis: GqlCouncilNeedBasis;
  /** When the unit was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The account that created the unit and is its initial Unit Admin. */
  createdByAccountId: Scalars['ID']['output'];
  /** Display name; generated from the metadata when the caller omits it. */
  displayName?: Maybe<Scalars['String']['output']>;
  /** Normalized unitType#unitNumber#city#state key used for duplicate lookup only; never grants access. */
  metadataKey?: Maybe<Scalars['String']['output']>;
  /** Unit-wide default split method for new events. */
  splitDefault: GqlSplitMethod;
  /** Geographic discriminator: the state. */
  state: Scalars['String']['output'];
  /** Timezone for display and calendar generation. */
  timezone: Scalars['String']['output'];
  /** The unit's stable ID; never derived from metadata. */
  unitId: Scalars['ID']['output'];
  /** The scout unit number (a display value; not globally unique). */
  unitNumber: Scalars['Int']['output'];
  /** The scout unit type, for example Pack or Troop. */
  unitType: Scalars['String']['output'];
  /** When the unit was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
  /** Optimistic-concurrency version protecting grant and settings mutations. */
  version: Scalars['Int']['output'];
};

/** A Unit administrator's access grant to a Unit, with the account's identity limited to what administration needs. */
export type GqlUnitAccessGrant = {
  __typename?: 'UnitAccessGrant';
  /** The granted account's ID. */
  accountId: Scalars['ID']['output'];
  /** When the grant started; no automatic expiry. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The Unit Admin (or creator) who created the grant. */
  createdByAccountId: Scalars['ID']['output'];
  /** The granted account's email, limited to administration needs. */
  email?: Maybe<Scalars['String']['output']>;
  /** The granted account's display name, limited to administration needs. */
  name?: Maybe<Scalars['String']['output']>;
  /** The stored role; only UNIT_ADMIN exists. */
  role: GqlUnitRole;
  /** The Unit this grant is on. */
  unitId: Scalars['ID']['output'];
};

/** A page of unit admin grants. */
export type GqlUnitAccessGrantConnection = {
  __typename?: 'UnitAccessGrantConnection';
  /** The grants on this page. */
  items: Array<GqlUnitAccessGrant>;
  /** Cursor state for the next page. */
  pageInfo: GqlPageInfo;
};

/** The administrative view of a Unit Campaign, including its reusable join code and settings. */
export type GqlUnitCampaignAdmin = {
  __typename?: 'UnitCampaignAdmin';
  /** The sales-season name. */
  campaignName: Scalars['String']['output'];
  /** The sales year. */
  campaignYear: Scalars['Int']['output'];
  /** The existing catalog used by this campaign (immutable after creation). */
  catalogId: Scalars['ID']['output'];
  /** When the campaign was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The Unit Admin who created the campaign. */
  createdByAccountId: Scalars['ID']['output'];
  /** Deactivation has no inventory or obligation side effects. */
  isActive: Scalars['Boolean']['output'];
  /** The reusable campaign-join credential. */
  joinCode: Scalars['String']['output'];
  /** The Unit Campaign's stable ID. */
  unitCampaignId: Scalars['ID']['output'];
  /** The parent Unit. */
  unitId: Scalars['ID']['output'];
  /** When the campaign was last updated. */
  updatedAt: Scalars['AWSDateTime']['output'];
  /** The Unit Admin who last updated the campaign. */
  updatedByAccountId: Scalars['ID']['output'];
  /** Optimistic-concurrency version for metadata and deactivation updates. */
  version: Scalars['Int']['output'];
};

/** The Unit Campaign's catalog and product inputs for browser sales sheets (including events with no sales). */
export type GqlUnitCampaignCatalog = {
  __typename?: 'UnitCampaignCatalog';
  /** The catalog's ID. */
  catalogId: Scalars['ID']['output'];
  /** The catalog's display name. */
  catalogName: Scalars['String']['output'];
  /** The catalog's products, in display order. */
  products: Array<GqlProduct>;
};

/** A page of a Unit's campaigns. */
export type GqlUnitCampaignConnection = {
  __typename?: 'UnitCampaignConnection';
  /** The campaigns on this page. */
  items: Array<GqlUnitCampaignAdmin>;
  /** Cursor state for the next page. */
  pageInfo: GqlPageInfo;
};

/** The member-safe preview of a Unit Campaign, exposed to any authenticated account via the join code. Carries no join code, IDs, catalog ID, or settings. */
export type GqlUnitCampaignJoinPreview = {
  __typename?: 'UnitCampaignJoinPreview';
  /** The sales-season name. */
  campaignName: Scalars['String']['output'];
  /** The sales year. */
  campaignYear: Scalars['Int']['output'];
  /** The campaign catalog's display name. */
  catalogName: Scalars['String']['output'];
  /** Whether the campaign is currently active. */
  isActive: Scalars['Boolean']['output'];
  /** The parent unit's display name. */
  unitDisplayName: Scalars['String']['output'];
};

/** A roster link between a Unit Campaign and a Scout (Campaign/Profile). */
export type GqlUnitCampaignMembership = {
  __typename?: 'UnitCampaignMembership';
  /** The existing Scout Campaign (immutable). */
  campaignId: Scalars['ID']['output'];
  /** When the Scout joined. */
  joinedAt: Scalars['AWSDateTime']['output'];
  /** The account that redeemed the join code. */
  joinedByAccountId: Scalars['ID']['output'];
  /** The Scout's profile identity. */
  profileId: Scalars['ID']['output'];
  /** When the Scout was removed, or null when not removed. */
  removedAt?: Maybe<Scalars['AWSDateTime']['output']>;
  /** The Unit Admin who removed the Scout, or null when not removed. */
  removedByAccountId?: Maybe<Scalars['ID']['output']>;
  /** ACTIVE allows new signups; REMOVED blocks them. */
  status: GqlMembershipStatus;
  /** The joined Unit Campaign. */
  unitCampaignId: Scalars['ID']['output'];
  /** Denormalized tenancy check: the parent Unit. */
  unitId: Scalars['ID']['output'];
  /** Optimistic-concurrency version for membership mutations and rejoin. */
  version: Scalars['Int']['output'];
};

/** A page of a Unit Campaign's roster (includes removed history). */
export type GqlUnitCampaignMembershipConnection = {
  __typename?: 'UnitCampaignMembershipConnection';
  /** The memberships on this page. */
  items: Array<GqlUnitCampaignMembership>;
  /** Cursor state for the next page. */
  pageInfo: GqlPageInfo;
};

/** A page of units. */
export type GqlUnitConnection = {
  __typename?: 'UnitConnection';
  /** The units on this page. */
  items: Array<GqlUnit>;
  /** Cursor state for the next page. */
  pageInfo: GqlPageInfo;
};

/** A single-use, 14-day credential a Unit Admin generates to add another Unit Admin. */
export type GqlUnitInvite = {
  __typename?: 'UnitInvite';
  /** When the invite was created. */
  createdAt: Scalars['AWSDateTime']['output'];
  /** The Unit Admin who generated the invite. */
  createdByAccountId: Scalars['ID']['output'];
  /** When the invite expires (at most 14 days from creation). */
  expiresAt: Scalars['AWSDateTime']['output'];
  /** The 16-character bearer code; returned only for active, unused invites. */
  inviteCode: Scalars['String']['output'];
  /** The Unit this invite joins. */
  unitId: Scalars['ID']['output'];
};

/** A page of unit invites (only active, unused invites are returned). */
export type GqlUnitInviteConnection = {
  __typename?: 'UnitInviteConnection';
  /** The invites on this page. */
  items: Array<GqlUnitInvite>;
  /** Cursor state for the next page. */
  pageInfo: GqlPageInfo;
};

/** An individual order within a unit report. */
export type GqlUnitOrderDetail = {
  __typename?: 'UnitOrderDetail';
  /** The buyer's email address, present only on orders that carry one (public order-page orders); null on authenticated and pre-feature orders. Unit reports carry it so the enable-time disclosure about buyer contact details appearing in reports and exports is true of the report itself. */
  customerEmail?: Maybe<Scalars['String']['output']>;
  /** The order's customer name. */
  customerName: Scalars['String']['output'];
  /** The order's product lines. */
  lineItems: Array<GqlLineItem>;
  /** When the order was placed. */
  orderDate: Scalars['AWSDateTime']['output'];
  /** The order's unique ID. */
  orderId: Scalars['ID']['output'];
  /** The order's total amount. */
  totalAmount: Scalars['Float']['output'];
};

/** A unit-level sales report aggregating sellers (profiles) and their orders for a unit and season. */
export type GqlUnitReport = {
  __typename?: 'UnitReport';
  /** The campaign name the report covers (for example "Fall" or "Spring"). */
  campaignName: Scalars['String']['output'];
  /** The campaign year the report covers. */
  campaignYear: Scalars['Int']['output'];
  /** One summary per seller (profile) in the unit, limited to profiles the caller can read. */
  sellers: Array<GqlUnitSellerSummary>;
  /** Total orders across all sellers in the report. */
  totalOrders: Scalars['Int']['output'];
  /** Total sales across all sellers in the report. */
  totalSales: Scalars['Float']['output'];
  /** The scout unit number the report covers. */
  unitNumber: Scalars['Int']['output'];
  /** The scout unit type the report covers. */
  unitType: Scalars['String']['output'];
};

/** The stored role on a Unit access grant. Only one role exists; 'Unit Kernel' is a display synonym, not a stored value. */
export type GqlUnitRole =
  /** Full Unit administrator. */
  'UNIT_ADMIN';

/** A per-seller (profile) summary within a unit report. */
export type GqlUnitSellerSummary = {
  __typename?: 'UnitSellerSummary';
  /** The number of orders the seller has in the report. */
  orderCount: Scalars['Int']['output'];
  /** The seller's individual orders in the report. */
  orders: Array<GqlUnitOrderDetail>;
  /** The seller's profile ID. */
  profileId: Scalars['ID']['output'];
  /** The seller's display name. */
  sellerName: Scalars['String']['output'];
  /** The seller's total sales in the report. */
  totalSales: Scalars['Float']['output'];
};

/** Input for updateCampaign. Only the provided fields are changed. An explicit null is rejected with INVALID_INPUT for campaignName, campaignYear, isActive, and catalogId, which the Campaign type declares non-null. */
export type GqlUpdateCampaignInput = {
  /** The ID of the campaign to update. */
  campaignId: Scalars['ID']['input'];
  /** New display name for the campaign. */
  campaignName?: InputMaybe<Scalars['String']['input']>;
  /** New year for the campaign. */
  campaignYear?: InputMaybe<Scalars['Int']['input']>;
  /** New catalog ID. */
  catalogId?: InputMaybe<Scalars['ID']['input']>;
  /** New city. */
  city?: InputMaybe<Scalars['String']['input']>;
  /** New end date. */
  endDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  /** Set to true or false to activate or deactivate the campaign. */
  isActive?: InputMaybe<Scalars['Boolean']['input']>;
  /** New start date. */
  startDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  /** New state. */
  state?: InputMaybe<Scalars['String']['input']>;
  /** New scout unit number. */
  unitNumber?: InputMaybe<Scalars['Int']['input']>;
  /** New scout unit type. */
  unitType?: InputMaybe<Scalars['String']['input']>;
};

/** Input for updateCampaignPublicOrderSettings. Owner-only; the campaign is identified by its canonical (CAMPAIGN# prefixed) ID. */
export type GqlUpdateCampaignPublicOrderSettingsInput = {
  /** Must be true when enabling and the stored acknowledgement version is behind the current one. */
  acknowledgementsAccepted?: InputMaybe<Scalars['Boolean']['input']>;
  /** Payment method names buyers may select. Omit to keep the stored value; an explicit null is rejected. */
  allowedPaymentMethods?: InputMaybe<Array<Scalars['String']['input']>>;
  /** Canonical ID of the campaign whose public-order settings are being written. */
  campaignId: Scalars['ID']['input'];
  /** Whether public orders should be enabled for this campaign. */
  enabled: Scalars['Boolean']['input'];
  /** Mint a replacement share token (the only revocation path). Allowed while disabled. */
  rotateToken?: InputMaybe<Scalars['Boolean']['input']>;
};

/** Input for updateMyAccount. Updates profile fields on the caller's own account; at least one field must be provided. */
export type GqlUpdateMyAccountInput = {
  /** New city. */
  city?: InputMaybe<Scalars['String']['input']>;
  /** New last name. */
  familyName?: InputMaybe<Scalars['String']['input']>;
  /** New first name. */
  givenName?: InputMaybe<Scalars['String']['input']>;
  /** New state. */
  state?: InputMaybe<Scalars['String']['input']>;
  /** New scout unit number (a positive integer). */
  unitNumber?: InputMaybe<Scalars['Int']['input']>;
  /** New scout unit type. */
  unitType?: InputMaybe<Scalars['String']['input']>;
};

/** Input for updateOrder. Only the provided fields are changed; providing lineItems replaces all existing line items. */
export type GqlUpdateOrderInput = {
  /** New customer address. */
  customerAddress?: InputMaybe<GqlAddressInput>;
  /** New customer name. */
  customerName?: InputMaybe<Scalars['String']['input']>;
  /** New customer phone number. */
  customerPhone?: InputMaybe<Scalars['String']['input']>;
  /** New line items; replaces the existing ones and recomputes the total. */
  lineItems?: InputMaybe<Array<GqlLineItemInput>>;
  /** New notes. */
  notes?: InputMaybe<Scalars['String']['input']>;
  /** New order date. */
  orderDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  /** The ID of the order to update. */
  orderId: Scalars['ID']['input'];
  /** New payment method name. Omit to keep the current value; an explicit null is rejected with INVALID_INPUT. */
  paymentMethod?: InputMaybe<Scalars['String']['input']>;
  /** Seller-side payment confirmation. Only `CONFIRMED` is accepted in v1, only on an order placed through the public order page (the public create path stamps the row's `orderSource` attribute), and only by the profile owner or a WRITE-share collaborator. The transition is one-way: an order already `CONFIRMED` rejects it, and there is no path back. Omit the field to leave the status untouched - an explicit null is rejected with INVALID_INPUT. */
  status?: InputMaybe<GqlOrderStatus>;
};

/** Input for updateSellerProfile. */
export type GqlUpdateSellerProfileInput = {
  /** The ID of the profile to update. */
  profileId: Scalars['ID']['input'];
  /** The seller's new display name (required, up to 100 characters; trimmed before storage). */
  sellerName: Scalars['String']['input'];
};

/** Input for updateSharedCampaign. Only the provided fields are changed. */
export type GqlUpdateSharedCampaignInput = {
  /** New creator message. */
  creatorMessage?: InputMaybe<Scalars['String']['input']>;
  /** New description. */
  description?: InputMaybe<Scalars['String']['input']>;
  /** Set to true or false to activate or deactivate the shared campaign. */
  isActive?: InputMaybe<Scalars['Boolean']['input']>;
  /** The shared campaign's code. */
  sharedCampaignCode: Scalars['String']['input'];
};

/** Input for updateUnitCampaign. Only name/year/isActive change; catalogId is immutable. */
export type GqlUpdateUnitCampaignInput = {
  /** The sales-season name. */
  campaignName?: InputMaybe<Scalars['String']['input']>;
  /** The sales year. */
  campaignYear?: InputMaybe<Scalars['Int']['input']>;
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** Activate or deactivate the campaign. */
  isActive?: InputMaybe<Scalars['Boolean']['input']>;
  /** The Unit Campaign to update. */
  unitCampaignId: Scalars['ID']['input'];
  /** The version the caller last read (optimistic concurrency). */
  version: GqlVersionedInput;
};

/** Input for updateUnit. Only metadata/settings fields may change; unitId and adminCount are not editable. */
export type GqlUpdateUnitInput = {
  /** Geographic discriminator: the city. */
  city?: InputMaybe<Scalars['String']['input']>;
  /** Primary presentation basis for the unit's needs report. */
  councilNeedBasis?: InputMaybe<GqlCouncilNeedBasis>;
  /** Display name. */
  displayName?: InputMaybe<Scalars['String']['input']>;
  /** Set true to confirm an exact unitType/unitNumber/city/state duplicate. */
  duplicateConfirmed?: InputMaybe<Scalars['Boolean']['input']>;
  /** Idempotency for the mutation. */
  idempotency: GqlIdempotencyInput;
  /** Unit-wide default split method for new events. */
  splitDefault?: InputMaybe<GqlSplitMethod>;
  /** Geographic discriminator: the state. */
  state?: InputMaybe<Scalars['String']['input']>;
  /** Timezone for display and calendar generation. */
  timezone?: InputMaybe<Scalars['String']['input']>;
  /** The Unit to update. */
  unitId: Scalars['ID']['input'];
  /** The scout unit number. */
  unitNumber?: InputMaybe<Scalars['Int']['input']>;
  /** The scout unit type. */
  unitType?: InputMaybe<Scalars['String']['input']>;
  /** The version the caller last read (optimistic concurrency). */
  version: GqlVersionedInput;
};

/** Optimistic-concurrency version carried by a version-changing operation. */
export type GqlVersionedInput = {
  /** The version the caller last read; a mismatch returns CONFLICT. */
  expectedVersion: Scalars['Int']['input'];
};

export type GqlSellerProfileFieldsFragment = {
  __typename?: 'SellerProfile';
  profileId: string;
  ownerAccountId: string;
  sellerName: string;
  createdAt: string;
  updatedAt: string;
  isOwner: boolean;
  permissions?: Array<GqlPermissionType> | null | undefined;
};

export type GqlSellerProfileWithLatestCampaignFieldsFragment = {
  __typename?: 'SellerProfile';
  profileId: string;
  ownerAccountId: string;
  sellerName: string;
  createdAt: string;
  updatedAt: string;
  isOwner: boolean;
  permissions?: Array<GqlPermissionType> | null | undefined;
  latestCampaign?:
    | { __typename?: 'Campaign'; campaignId: string; campaignName: string; campaignYear: number; isActive: boolean }
    | null
    | undefined;
};

export type GqlCampaignFieldsFragment = {
  __typename?: 'Campaign';
  campaignId: string;
  profileId: string;
  campaignName: string;
  campaignYear: number;
  startDate?: string | null | undefined;
  endDate?: string | null | undefined;
  catalogId: string;
  unitType?: string | null | undefined;
  unitNumber?: number | null | undefined;
  city?: string | null | undefined;
  state?: string | null | undefined;
  sharedCampaignCode?: string | null | undefined;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  totalOrders?: number | null | undefined;
  totalRevenue?: number | null | undefined;
};

export type GqlOrderFieldsFragment = {
  __typename?: 'Order';
  orderId: string;
  profileId: string;
  campaignId: string;
  customerName: string;
  customerPhone?: string | null | undefined;
  orderDate: string;
  paymentMethod: string;
  totalAmount: number;
  notes?: string | null | undefined;
  createdAt: string;
  updatedAt: string;
  status?: GqlOrderStatus | null | undefined;
  customerAddress?:
    | {
        __typename?: 'Address';
        street?: string | null | undefined;
        city?: string | null | undefined;
        state?: string | null | undefined;
        zipCode?: string | null | undefined;
      }
    | null
    | undefined;
  lineItems: Array<{
    __typename?: 'LineItem';
    productId: string;
    productName: string;
    quantity: number;
    pricePerUnit: number;
    subtotal: number;
  }>;
};

export type GqlCatalogFieldsFragment = {
  __typename?: 'Catalog';
  catalogId: string;
  catalogName: string;
  catalogType: GqlCatalogType;
  isPublic: boolean;
  createdAt: string;
  updatedAt: string;
  products: Array<{
    __typename?: 'Product';
    productId: string;
    productName: string;
    description?: string | null | undefined;
    price: number;
    sortOrder: number;
  }>;
};

export type GqlGetMyAccountQueryVariables = Exact<{ [key: string]: never }>;

export type GqlGetMyAccountQuery = {
  __typename?: 'Query';
  getMyAccount: {
    __typename?: 'Account';
    accountId: string;
    email: string;
    givenName?: string | null | undefined;
    familyName?: string | null | undefined;
    city?: string | null | undefined;
    state?: string | null | undefined;
    unitType?: string | null | undefined;
    unitNumber?: number | null | undefined;
    preferences?: Record<string, unknown> | null | undefined;
    createdAt: string;
    updatedAt: string;
  };
};

export type GqlUpdateMyAccountMutationVariables = Exact<{
  input: GqlUpdateMyAccountInput;
}>;

export type GqlUpdateMyAccountMutation = {
  __typename?: 'Mutation';
  updateMyAccount: {
    __typename?: 'Account';
    accountId: string;
    email: string;
    givenName?: string | null | undefined;
    familyName?: string | null | undefined;
    city?: string | null | undefined;
    state?: string | null | undefined;
    unitType?: string | null | undefined;
    unitNumber?: number | null | undefined;
    createdAt: string;
    updatedAt: string;
  };
};

export type GqlDeleteMyAccountMutationVariables = Exact<{ [key: string]: never }>;

export type GqlDeleteMyAccountMutation = { __typename?: 'Mutation'; deleteMyAccount: boolean };

export type GqlUpdateMyPreferencesMutationVariables = Exact<{
  preferences: Scalars['AWSJSON']['input'];
}>;

export type GqlUpdateMyPreferencesMutation = {
  __typename?: 'Mutation';
  updateMyPreferences: {
    __typename?: 'Account';
    accountId: string;
    preferences?: Record<string, unknown> | null | undefined;
  };
};

export type GqlListMyProfilesQueryVariables = Exact<{
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
}>;

export type GqlListMyProfilesQuery = {
  __typename?: 'Query';
  listMyProfiles: {
    __typename?: 'SellerProfileConnection';
    nextToken?: string | null | undefined;
    profiles: Array<{
      __typename?: 'SellerProfile';
      profileId: string;
      ownerAccountId: string;
      sellerName: string;
      createdAt: string;
      updatedAt: string;
      isOwner: boolean;
      permissions?: Array<GqlPermissionType> | null | undefined;
      latestCampaign?:
        | { __typename?: 'Campaign'; campaignId: string; campaignName: string; campaignYear: number; isActive: boolean }
        | null
        | undefined;
    }>;
  };
};

export type GqlListMySharesQueryVariables = Exact<{ [key: string]: never }>;

export type GqlListMySharesQuery = {
  __typename?: 'Query';
  listMyShares: Array<{
    __typename?: 'SharedProfile';
    profileId: string;
    ownerAccountId: string;
    sellerName: string;
    unitType?: string | null | undefined;
    unitNumber?: number | null | undefined;
    createdAt: string;
    updatedAt: string;
    isOwner: boolean;
    permissions: Array<GqlPermissionType>;
    latestCampaign?:
      | { __typename?: 'Campaign'; campaignId: string; campaignName: string; campaignYear: number; isActive: boolean }
      | null
      | undefined;
  }>;
};

export type GqlGetProfileQueryVariables = Exact<{
  profileId: Scalars['ID']['input'];
}>;

export type GqlGetProfileQuery = {
  __typename?: 'Query';
  getProfile?:
    | {
        __typename?: 'SellerProfile';
        profileId: string;
        ownerAccountId: string;
        sellerName: string;
        createdAt: string;
        updatedAt: string;
        isOwner: boolean;
        permissions?: Array<GqlPermissionType> | null | undefined;
      }
    | null
    | undefined;
};

export type GqlListCampaignsByProfileQueryVariables = Exact<{
  profileId: Scalars['ID']['input'];
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
}>;

export type GqlListCampaignsByProfileQuery = {
  __typename?: 'Query';
  listCampaignsByProfile: {
    __typename?: 'CampaignConnection';
    nextToken?: string | null | undefined;
    campaigns: Array<{
      __typename?: 'Campaign';
      campaignId: string;
      profileId: string;
      campaignName: string;
      campaignYear: number;
      startDate?: string | null | undefined;
      endDate?: string | null | undefined;
      catalogId: string;
      unitType?: string | null | undefined;
      unitNumber?: number | null | undefined;
      city?: string | null | undefined;
      state?: string | null | undefined;
      sharedCampaignCode?: string | null | undefined;
      isActive: boolean;
      createdAt: string;
      updatedAt: string;
      totalOrders?: number | null | undefined;
      totalRevenue?: number | null | undefined;
    }>;
  };
};

export type GqlGetCampaignQueryVariables = Exact<{
  campaignId: Scalars['ID']['input'];
}>;

export type GqlGetCampaignQuery = {
  __typename?: 'Query';
  getCampaign?:
    | {
        __typename?: 'Campaign';
        campaignId: string;
        profileId: string;
        campaignName: string;
        campaignYear: number;
        startDate?: string | null | undefined;
        endDate?: string | null | undefined;
        catalogId: string;
        unitType?: string | null | undefined;
        unitNumber?: number | null | undefined;
        city?: string | null | undefined;
        state?: string | null | undefined;
        sharedCampaignCode?: string | null | undefined;
        isActive: boolean;
        createdAt: string;
        updatedAt: string;
        totalOrders?: number | null | undefined;
        totalRevenue?: number | null | undefined;
        catalog?:
          | {
              __typename?: 'Catalog';
              catalogId: string;
              catalogName: string;
              products: Array<{
                __typename?: 'Product';
                productId: string;
                productName: string;
                description?: string | null | undefined;
                price: number;
                sortOrder: number;
              }>;
            }
          | null
          | undefined;
      }
    | null
    | undefined;
};

export type GqlListOrdersByCampaignQueryVariables = Exact<{
  campaignId: Scalars['ID']['input'];
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
}>;

export type GqlListOrdersByCampaignQuery = {
  __typename?: 'Query';
  listOrdersByCampaign: {
    __typename?: 'OrderConnection';
    nextToken?: string | null | undefined;
    orders: Array<{
      __typename?: 'Order';
      orderId: string;
      profileId: string;
      campaignId: string;
      customerName: string;
      customerPhone?: string | null | undefined;
      orderDate: string;
      paymentMethod: string;
      totalAmount: number;
      notes?: string | null | undefined;
      createdAt: string;
      updatedAt: string;
      status?: GqlOrderStatus | null | undefined;
      customerAddress?:
        | {
            __typename?: 'Address';
            street?: string | null | undefined;
            city?: string | null | undefined;
            state?: string | null | undefined;
            zipCode?: string | null | undefined;
          }
        | null
        | undefined;
      lineItems: Array<{
        __typename?: 'LineItem';
        productId: string;
        productName: string;
        quantity: number;
        pricePerUnit: number;
        subtotal: number;
      }>;
    }>;
  };
};

export type GqlGetOrderQueryVariables = Exact<{
  orderId: Scalars['ID']['input'];
}>;

export type GqlGetOrderQuery = {
  __typename?: 'Query';
  getOrder?:
    | {
        __typename?: 'Order';
        orderId: string;
        profileId: string;
        campaignId: string;
        customerName: string;
        customerPhone?: string | null | undefined;
        orderDate: string;
        paymentMethod: string;
        totalAmount: number;
        notes?: string | null | undefined;
        createdAt: string;
        updatedAt: string;
        status?: GqlOrderStatus | null | undefined;
        customerAddress?:
          | {
              __typename?: 'Address';
              street?: string | null | undefined;
              city?: string | null | undefined;
              state?: string | null | undefined;
              zipCode?: string | null | undefined;
            }
          | null
          | undefined;
        lineItems: Array<{
          __typename?: 'LineItem';
          productId: string;
          productName: string;
          quantity: number;
          pricePerUnit: number;
          subtotal: number;
        }>;
      }
    | null
    | undefined;
};

export type GqlListManagedCatalogsQueryVariables = Exact<{ [key: string]: never }>;

export type GqlListManagedCatalogsQuery = {
  __typename?: 'Query';
  listManagedCatalogs: Array<{
    __typename?: 'Catalog';
    catalogId: string;
    catalogName: string;
    catalogType: GqlCatalogType;
    isPublic: boolean;
    createdAt: string;
    updatedAt: string;
    products: Array<{
      __typename?: 'Product';
      productId: string;
      productName: string;
      description?: string | null | undefined;
      price: number;
      sortOrder: number;
    }>;
  }>;
};

export type GqlListMyCatalogsQueryVariables = Exact<{ [key: string]: never }>;

export type GqlListMyCatalogsQuery = {
  __typename?: 'Query';
  listMyCatalogs: Array<{
    __typename?: 'Catalog';
    catalogId: string;
    catalogName: string;
    catalogType: GqlCatalogType;
    isPublic: boolean;
    createdAt: string;
    updatedAt: string;
    products: Array<{
      __typename?: 'Product';
      productId: string;
      productName: string;
      description?: string | null | undefined;
      price: number;
      sortOrder: number;
    }>;
  }>;
};

export type GqlListCatalogsInUseQueryVariables = Exact<{ [key: string]: never }>;

export type GqlListCatalogsInUseQuery = { __typename?: 'Query'; listCatalogsInUse: Array<string> };

export type GqlGetCatalogQueryVariables = Exact<{
  catalogId: Scalars['ID']['input'];
}>;

export type GqlGetCatalogQuery = {
  __typename?: 'Query';
  getCatalog?:
    | {
        __typename?: 'Catalog';
        catalogId: string;
        catalogName: string;
        catalogType: GqlCatalogType;
        isPublic: boolean;
        createdAt: string;
        updatedAt: string;
        products: Array<{
          __typename?: 'Product';
          productId: string;
          productName: string;
          description?: string | null | undefined;
          price: number;
          sortOrder: number;
        }>;
      }
    | null
    | undefined;
};

export type GqlListInvitesByProfileQueryVariables = Exact<{
  profileId: Scalars['ID']['input'];
}>;

export type GqlListInvitesByProfileQuery = {
  __typename?: 'Query';
  listInvitesByProfile: Array<{
    __typename?: 'ProfileInvite';
    inviteCode: string;
    profileId: string;
    permissions: Array<GqlPermissionType>;
    expiresAt: string;
    createdAt: string;
    createdByAccountId: string;
  }>;
};

export type GqlListSharesByProfileQueryVariables = Exact<{
  profileId: Scalars['ID']['input'];
}>;

export type GqlListSharesByProfileQuery = {
  __typename?: 'Query';
  listSharesByProfile: Array<{
    __typename?: 'Share';
    shareId: string;
    profileId: string;
    targetAccountId: string;
    permissions: Array<GqlPermissionType>;
    createdAt: string;
    createdByAccountId: string;
    targetAccount?:
      | {
          __typename?: 'Account';
          email: string;
          givenName?: string | null | undefined;
          familyName?: string | null | undefined;
        }
      | null
      | undefined;
  }>;
};

export type GqlCreateSellerProfileMutationVariables = Exact<{
  sellerName: Scalars['String']['input'];
}>;

export type GqlCreateSellerProfileMutation = {
  __typename?: 'Mutation';
  createSellerProfile: {
    __typename?: 'SellerProfile';
    profileId: string;
    ownerAccountId: string;
    sellerName: string;
    createdAt: string;
    updatedAt: string;
    isOwner: boolean;
    permissions?: Array<GqlPermissionType> | null | undefined;
  };
};

export type GqlUpdateSellerProfileMutationVariables = Exact<{
  profileId: Scalars['ID']['input'];
  sellerName: Scalars['String']['input'];
}>;

export type GqlUpdateSellerProfileMutation = {
  __typename?: 'Mutation';
  updateSellerProfile: {
    __typename?: 'SellerProfile';
    profileId: string;
    ownerAccountId: string;
    sellerName: string;
    createdAt: string;
    updatedAt: string;
    isOwner: boolean;
    permissions?: Array<GqlPermissionType> | null | undefined;
  };
};

export type GqlDeleteSellerProfileMutationVariables = Exact<{
  profileId: Scalars['ID']['input'];
}>;

export type GqlDeleteSellerProfileMutation = { __typename?: 'Mutation'; deleteSellerProfile: boolean };

export type GqlCreateCampaignMutationVariables = Exact<{
  input: GqlCreateCampaignInput;
}>;

export type GqlCreateCampaignMutation = {
  __typename?: 'Mutation';
  createCampaign: {
    __typename?: 'Campaign';
    campaignId: string;
    profileId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    catalogId: string;
    unitType?: string | null | undefined;
    unitNumber?: number | null | undefined;
    city?: string | null | undefined;
    state?: string | null | undefined;
    sharedCampaignCode?: string | null | undefined;
    isActive: boolean;
    createdAt: string;
    updatedAt: string;
    totalOrders?: number | null | undefined;
    totalRevenue?: number | null | undefined;
  };
};

export type GqlUpdateCampaignMutationVariables = Exact<{
  input: GqlUpdateCampaignInput;
}>;

export type GqlUpdateCampaignMutation = {
  __typename?: 'Mutation';
  updateCampaign: {
    __typename?: 'Campaign';
    campaignId: string;
    profileId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    catalogId: string;
    unitType?: string | null | undefined;
    unitNumber?: number | null | undefined;
    city?: string | null | undefined;
    state?: string | null | undefined;
    sharedCampaignCode?: string | null | undefined;
    isActive: boolean;
    createdAt: string;
    updatedAt: string;
    totalOrders?: number | null | undefined;
    totalRevenue?: number | null | undefined;
  };
};

export type GqlDeleteCampaignMutationVariables = Exact<{
  campaignId: Scalars['ID']['input'];
}>;

export type GqlDeleteCampaignMutation = { __typename?: 'Mutation'; deleteCampaign: boolean };

export type GqlCreateOrderMutationVariables = Exact<{
  input: GqlCreateOrderInput;
}>;

export type GqlCreateOrderMutation = {
  __typename?: 'Mutation';
  createOrder: {
    __typename?: 'Order';
    orderId: string;
    profileId: string;
    campaignId: string;
    customerName: string;
    customerPhone?: string | null | undefined;
    orderDate: string;
    paymentMethod: string;
    totalAmount: number;
    notes?: string | null | undefined;
    createdAt: string;
    updatedAt: string;
    status?: GqlOrderStatus | null | undefined;
    customerAddress?:
      | {
          __typename?: 'Address';
          street?: string | null | undefined;
          city?: string | null | undefined;
          state?: string | null | undefined;
          zipCode?: string | null | undefined;
        }
      | null
      | undefined;
    lineItems: Array<{
      __typename?: 'LineItem';
      productId: string;
      productName: string;
      quantity: number;
      pricePerUnit: number;
      subtotal: number;
    }>;
  };
};

export type GqlUpdateOrderMutationVariables = Exact<{
  input: GqlUpdateOrderInput;
}>;

export type GqlUpdateOrderMutation = {
  __typename?: 'Mutation';
  updateOrder: {
    __typename?: 'Order';
    orderId: string;
    profileId: string;
    campaignId: string;
    customerName: string;
    customerPhone?: string | null | undefined;
    orderDate: string;
    paymentMethod: string;
    totalAmount: number;
    notes?: string | null | undefined;
    createdAt: string;
    updatedAt: string;
    status?: GqlOrderStatus | null | undefined;
    customerAddress?:
      | {
          __typename?: 'Address';
          street?: string | null | undefined;
          city?: string | null | undefined;
          state?: string | null | undefined;
          zipCode?: string | null | undefined;
        }
      | null
      | undefined;
    lineItems: Array<{
      __typename?: 'LineItem';
      productId: string;
      productName: string;
      quantity: number;
      pricePerUnit: number;
      subtotal: number;
    }>;
  };
};

export type GqlDeleteOrderMutationVariables = Exact<{
  orderId: Scalars['ID']['input'];
}>;

export type GqlDeleteOrderMutation = { __typename?: 'Mutation'; deleteOrder: boolean };

export type GqlCreateProfileInviteMutationVariables = Exact<{
  input: GqlCreateProfileInviteInput;
}>;

export type GqlCreateProfileInviteMutation = {
  __typename?: 'Mutation';
  createProfileInvite: {
    __typename?: 'ProfileInvite';
    inviteCode: string;
    profileId: string;
    permissions: Array<GqlPermissionType>;
    expiresAt: string;
    createdAt: string;
    createdByAccountId: string;
  };
};

export type GqlRedeemProfileInviteMutationVariables = Exact<{
  input: GqlRedeemProfileInviteInput;
}>;

export type GqlRedeemProfileInviteMutation = {
  __typename?: 'Mutation';
  redeemProfileInvite: {
    __typename?: 'Share';
    shareId: string;
    profileId: string;
    targetAccountId: string;
    permissions: Array<GqlPermissionType>;
    createdAt: string;
    createdByAccountId: string;
  };
};

export type GqlRevokeShareMutationVariables = Exact<{
  input: GqlRevokeShareInput;
}>;

export type GqlRevokeShareMutation = { __typename?: 'Mutation'; revokeShare: boolean };

export type GqlTransferProfileOwnershipMutationVariables = Exact<{
  input: GqlTransferProfileOwnershipInput;
}>;

export type GqlTransferProfileOwnershipMutation = {
  __typename?: 'Mutation';
  transferProfileOwnership: {
    __typename?: 'SellerProfile';
    profileId: string;
    ownerAccountId: string;
    sellerName: string;
    createdAt: string;
    updatedAt: string;
    isOwner: boolean;
    permissions?: Array<GqlPermissionType> | null | undefined;
  };
};

export type GqlCreateCatalogMutationVariables = Exact<{
  input: GqlCreateCatalogInput;
}>;

export type GqlCreateCatalogMutation = {
  __typename?: 'Mutation';
  createCatalog: {
    __typename?: 'Catalog';
    catalogId: string;
    catalogName: string;
    catalogType: GqlCatalogType;
    isPublic: boolean;
    createdAt: string;
    updatedAt: string;
    products: Array<{
      __typename?: 'Product';
      productId: string;
      productName: string;
      description?: string | null | undefined;
      price: number;
      sortOrder: number;
    }>;
  };
};

export type GqlUpdateCatalogMutationVariables = Exact<{
  catalogId: Scalars['ID']['input'];
  input: GqlCreateCatalogInput;
}>;

export type GqlUpdateCatalogMutation = {
  __typename?: 'Mutation';
  updateCatalog: {
    __typename?: 'Catalog';
    catalogId: string;
    catalogName: string;
    catalogType: GqlCatalogType;
    isPublic: boolean;
    createdAt: string;
    updatedAt: string;
    products: Array<{
      __typename?: 'Product';
      productId: string;
      productName: string;
      description?: string | null | undefined;
      price: number;
      sortOrder: number;
    }>;
  };
};

export type GqlDeleteCatalogMutationVariables = Exact<{
  catalogId: Scalars['ID']['input'];
}>;

export type GqlDeleteCatalogMutation = { __typename?: 'Mutation'; deleteCatalog: boolean };

export type GqlDeleteProfileInviteMutationVariables = Exact<{
  profileId: Scalars['ID']['input'];
  inviteCode: Scalars['ID']['input'];
}>;

export type GqlDeleteProfileInviteMutation = { __typename?: 'Mutation'; deleteProfileInvite: boolean };

export type GqlGetUnitReportQueryVariables = Exact<{
  unitType: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  city?: InputMaybe<Scalars['String']['input']>;
  state?: InputMaybe<Scalars['String']['input']>;
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  catalogId: Scalars['ID']['input'];
}>;

export type GqlGetUnitReportQuery = {
  __typename?: 'Query';
  getUnitReport?:
    | {
        __typename?: 'UnitReport';
        unitType: string;
        unitNumber: number;
        campaignName: string;
        campaignYear: number;
        totalSales: number;
        totalOrders: number;
        sellers: Array<{
          __typename?: 'UnitSellerSummary';
          profileId: string;
          sellerName: string;
          totalSales: number;
          orderCount: number;
          orders: Array<{
            __typename?: 'UnitOrderDetail';
            orderId: string;
            customerName: string;
            orderDate: string;
            totalAmount: number;
            lineItems: Array<{
              __typename?: 'LineItem';
              productId: string;
              productName: string;
              quantity: number;
              pricePerUnit: number;
              subtotal: number;
            }>;
          }>;
        }>;
      }
    | null
    | undefined;
};

export type GqlSharedCampaignFieldsFragment = {
  __typename?: 'SharedCampaign';
  sharedCampaignCode: string;
  catalogId: string;
  campaignName: string;
  campaignYear: number;
  startDate?: string | null | undefined;
  endDate?: string | null | undefined;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage?: string | null | undefined;
  description?: string | null | undefined;
  isActive: boolean;
  createdAt: string;
  catalog?: { __typename?: 'Catalog'; catalogId: string; catalogName: string } | null | undefined;
};

export type GqlSharedCampaignListFieldsFragment = {
  __typename?: 'SharedCampaign';
  sharedCampaignCode: string;
  catalogId: string;
  campaignName: string;
  campaignYear: number;
  startDate?: string | null | undefined;
  endDate?: string | null | undefined;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage?: string | null | undefined;
  description?: string | null | undefined;
  isActive: boolean;
  createdAt: string;
};

export type GqlGetSharedCampaignQueryVariables = Exact<{
  sharedCampaignCode: Scalars['String']['input'];
}>;

export type GqlGetSharedCampaignQuery = {
  __typename?: 'Query';
  getSharedCampaign?:
    | {
        __typename?: 'SharedCampaign';
        sharedCampaignCode: string;
        catalogId: string;
        campaignName: string;
        campaignYear: number;
        startDate?: string | null | undefined;
        endDate?: string | null | undefined;
        unitType: string;
        unitNumber: number;
        city: string;
        state: string;
        createdBy: string;
        createdByName: string;
        creatorMessage?: string | null | undefined;
        description?: string | null | undefined;
        isActive: boolean;
        createdAt: string;
        catalog?: { __typename?: 'Catalog'; catalogId: string; catalogName: string } | null | undefined;
      }
    | null
    | undefined;
};

export type GqlListMySharedCampaignsQueryVariables = Exact<{ [key: string]: never }>;

export type GqlListMySharedCampaignsQuery = {
  __typename?: 'Query';
  listMySharedCampaigns: Array<{
    __typename?: 'SharedCampaign';
    sharedCampaignCode: string;
    catalogId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    createdBy: string;
    createdByName: string;
    creatorMessage?: string | null | undefined;
    description?: string | null | undefined;
    isActive: boolean;
    createdAt: string;
  }>;
};

export type GqlFindSharedCampaignsQueryVariables = Exact<{
  unitType: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  city: Scalars['String']['input'];
  state: Scalars['String']['input'];
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
}>;

export type GqlFindSharedCampaignsQuery = {
  __typename?: 'Query';
  findSharedCampaigns: Array<{
    __typename?: 'SharedCampaign';
    sharedCampaignCode: string;
    catalogId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    createdBy: string;
    createdByName: string;
    creatorMessage?: string | null | undefined;
    description?: string | null | undefined;
    isActive: boolean;
    createdAt: string;
    catalog?: { __typename?: 'Catalog'; catalogId: string; catalogName: string } | null | undefined;
  }>;
};

export type GqlCreateSharedCampaignMutationVariables = Exact<{
  input: GqlCreateSharedCampaignInput;
}>;

export type GqlCreateSharedCampaignMutation = {
  __typename?: 'Mutation';
  createSharedCampaign: {
    __typename?: 'SharedCampaign';
    sharedCampaignCode: string;
    catalogId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    createdBy: string;
    createdByName: string;
    creatorMessage?: string | null | undefined;
    description?: string | null | undefined;
    isActive: boolean;
    createdAt: string;
    catalog?: { __typename?: 'Catalog'; catalogId: string; catalogName: string } | null | undefined;
  };
};

export type GqlUpdateSharedCampaignMutationVariables = Exact<{
  input: GqlUpdateSharedCampaignInput;
}>;

export type GqlUpdateSharedCampaignMutation = {
  __typename?: 'Mutation';
  updateSharedCampaign: {
    __typename?: 'SharedCampaign';
    sharedCampaignCode: string;
    catalogId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    createdBy: string;
    createdByName: string;
    creatorMessage?: string | null | undefined;
    description?: string | null | undefined;
    isActive: boolean;
    createdAt: string;
    catalog?: { __typename?: 'Catalog'; catalogId: string; catalogName: string } | null | undefined;
  };
};

export type GqlDeleteSharedCampaignMutationVariables = Exact<{
  sharedCampaignCode: Scalars['String']['input'];
}>;

export type GqlDeleteSharedCampaignMutation = { __typename?: 'Mutation'; deleteSharedCampaign: boolean };

export type GqlPaymentMethodFieldsFragment = {
  __typename?: 'PaymentMethod';
  name: string;
  qrCodeUrl?: string | null | undefined;
};

export type GqlGetMyPaymentMethodsQueryVariables = Exact<{ [key: string]: never }>;

export type GqlGetMyPaymentMethodsQuery = {
  __typename?: 'Query';
  myPaymentMethods: Array<{ __typename?: 'PaymentMethod'; name: string; qrCodeUrl?: string | null | undefined }>;
};

export type GqlGetPaymentMethodsForProfileQueryVariables = Exact<{
  profileId: Scalars['ID']['input'];
}>;

export type GqlGetPaymentMethodsForProfileQuery = {
  __typename?: 'Query';
  paymentMethodsForProfile: Array<{
    __typename?: 'PaymentMethod';
    name: string;
    qrCodeUrl?: string | null | undefined;
  }>;
};

export type GqlCreatePaymentMethodMutationVariables = Exact<{
  name: Scalars['String']['input'];
}>;

export type GqlCreatePaymentMethodMutation = {
  __typename?: 'Mutation';
  createPaymentMethod: { __typename?: 'PaymentMethod'; name: string; qrCodeUrl?: string | null | undefined };
};

export type GqlUpdatePaymentMethodMutationVariables = Exact<{
  currentName: Scalars['String']['input'];
  newName: Scalars['String']['input'];
}>;

export type GqlUpdatePaymentMethodMutation = {
  __typename?: 'Mutation';
  updatePaymentMethod: { __typename?: 'PaymentMethod'; name: string; qrCodeUrl?: string | null | undefined };
};

export type GqlDeletePaymentMethodMutationVariables = Exact<{
  name: Scalars['String']['input'];
}>;

export type GqlDeletePaymentMethodMutation = { __typename?: 'Mutation'; deletePaymentMethod: boolean };

export type GqlRequestPaymentMethodQrUploadMutationVariables = Exact<{
  paymentMethodName: Scalars['String']['input'];
}>;

export type GqlRequestPaymentMethodQrUploadMutation = {
  __typename?: 'Mutation';
  requestPaymentMethodQRCodeUpload: {
    __typename?: 'S3UploadInfo';
    uploadUrl: string;
    fields: Record<string, unknown>;
    s3Key: string;
  };
};

export type GqlConfirmPaymentMethodQrUploadMutationVariables = Exact<{
  paymentMethodName: Scalars['String']['input'];
  s3Key: Scalars['String']['input'];
}>;

export type GqlConfirmPaymentMethodQrUploadMutation = {
  __typename?: 'Mutation';
  confirmPaymentMethodQRCodeUpload: {
    __typename?: 'PaymentMethod';
    name: string;
    qrCodeUrl?: string | null | undefined;
  };
};

export type GqlDeletePaymentMethodQrCodeMutationVariables = Exact<{
  paymentMethodName: Scalars['String']['input'];
}>;

export type GqlDeletePaymentMethodQrCodeMutation = { __typename?: 'Mutation'; deletePaymentMethodQRCode: boolean };

export type GqlAdminUserFieldsFragment = {
  __typename?: 'AdminUser';
  accountId: string;
  email: string;
  displayName?: string | null | undefined;
  status: string;
  enabled: boolean;
  emailVerified: boolean;
  isAdmin: boolean;
  createdAt: string;
  lastModifiedAt?: string | null | undefined;
};

export type GqlAdminListUsersQueryVariables = Exact<{
  limit?: InputMaybe<Scalars['Int']['input']>;
  nextToken?: InputMaybe<Scalars['String']['input']>;
}>;

export type GqlAdminListUsersQuery = {
  __typename?: 'Query';
  adminListUsers: {
    __typename?: 'AdminUserConnection';
    nextToken?: string | null | undefined;
    users: Array<{
      __typename?: 'AdminUser';
      accountId: string;
      email: string;
      displayName?: string | null | undefined;
      status: string;
      enabled: boolean;
      emailVerified: boolean;
      isAdmin: boolean;
      createdAt: string;
      lastModifiedAt?: string | null | undefined;
    }>;
  };
};

export type GqlAdminSearchUserQueryVariables = Exact<{
  query: Scalars['String']['input'];
}>;

export type GqlAdminSearchUserQuery = {
  __typename?: 'Query';
  adminSearchUser: Array<{
    __typename?: 'AdminUser';
    accountId: string;
    email: string;
    displayName?: string | null | undefined;
    status: string;
    enabled: boolean;
    emailVerified: boolean;
    isAdmin: boolean;
    createdAt: string;
    lastModifiedAt?: string | null | undefined;
  }>;
};

export type GqlAdminGetUserProfilesQueryVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminGetUserProfilesQuery = {
  __typename?: 'Query';
  adminGetUserProfiles: Array<{
    __typename?: 'SellerProfile';
    profileId: string;
    ownerAccountId: string;
    sellerName: string;
    createdAt: string;
    updatedAt: string;
    isOwner: boolean;
    permissions?: Array<GqlPermissionType> | null | undefined;
  }>;
};

export type GqlAdminGetUserCatalogsQueryVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminGetUserCatalogsQuery = {
  __typename?: 'Query';
  adminGetUserCatalogs: Array<{
    __typename?: 'Catalog';
    catalogId: string;
    catalogName: string;
    catalogType: GqlCatalogType;
    isPublic: boolean;
    createdAt: string;
    updatedAt: string;
    products: Array<{
      __typename?: 'Product';
      productId: string;
      productName: string;
      description?: string | null | undefined;
      price: number;
      sortOrder: number;
    }>;
  }>;
};

export type GqlAdminGetUserCampaignsQueryVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminGetUserCampaignsQuery = {
  __typename?: 'Query';
  adminGetUserCampaigns: Array<{
    __typename?: 'Campaign';
    campaignId: string;
    profileId: string;
    campaignName: string;
    campaignYear: number;
    catalogId: string;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    sharedCampaignCode?: string | null | undefined;
    createdAt: string;
    updatedAt: string;
  }>;
};

export type GqlAdminGetUserSharedCampaignsQueryVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminGetUserSharedCampaignsQuery = {
  __typename?: 'Query';
  adminGetUserSharedCampaigns: Array<{
    __typename?: 'SharedCampaign';
    sharedCampaignCode: string;
    catalogId: string;
    campaignName: string;
    campaignYear: number;
    startDate?: string | null | undefined;
    endDate?: string | null | undefined;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    createdBy: string;
    createdByName: string;
    createdAt: string;
  }>;
};

export type GqlAdminGetProfileSharesQueryVariables = Exact<{
  profileId: Scalars['ID']['input'];
}>;

export type GqlAdminGetProfileSharesQuery = {
  __typename?: 'Query';
  adminGetProfileShares: Array<{
    __typename?: 'Share';
    shareId: string;
    profileId: string;
    targetAccountId: string;
    permissions: Array<GqlPermissionType>;
    createdAt: string;
    targetAccount?:
      | {
          __typename?: 'Account';
          accountId: string;
          email: string;
          givenName?: string | null | undefined;
          familyName?: string | null | undefined;
        }
      | null
      | undefined;
  }>;
};

export type GqlAdminResetUserPasswordMutationVariables = Exact<{
  email: Scalars['AWSEmail']['input'];
}>;

export type GqlAdminResetUserPasswordMutation = { __typename?: 'Mutation'; adminResetUserPassword: boolean };

export type GqlAdminPurgeUserAccountMutationVariables = Exact<{
  accountId: Scalars['ID']['input'];
  profileIds: Array<Scalars['ID']['input']> | Scalars['ID']['input'];
}>;

export type GqlAdminPurgeUserAccountMutation = { __typename?: 'Mutation'; adminPurgeUserAccount: boolean };

export type GqlAdminDeleteUserOrdersMutationVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminDeleteUserOrdersMutation = { __typename?: 'Mutation'; adminDeleteUserOrders: number };

export type GqlAdminDeleteUserCampaignsMutationVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminDeleteUserCampaignsMutation = { __typename?: 'Mutation'; adminDeleteUserCampaigns: number };

export type GqlAdminDeleteUserSharesMutationVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminDeleteUserSharesMutation = { __typename?: 'Mutation'; adminDeleteUserShares: number };

export type GqlAdminDeleteUserProfilesMutationVariables = Exact<{
  accountId: Scalars['ID']['input'];
}>;

export type GqlAdminDeleteUserProfilesMutation = { __typename?: 'Mutation'; adminDeleteUserProfiles: number };

export type GqlAdminDeleteShareMutationVariables = Exact<{
  profileId: Scalars['ID']['input'];
  targetAccountId: Scalars['ID']['input'];
}>;

export type GqlAdminDeleteShareMutation = { __typename?: 'Mutation'; adminDeleteShare: boolean };

export type GqlAdminUpdateCampaignSharedCodeMutationVariables = Exact<{
  campaignId: Scalars['ID']['input'];
  sharedCampaignCode?: InputMaybe<Scalars['String']['input']>;
}>;

export type GqlAdminUpdateCampaignSharedCodeMutation = {
  __typename?: 'Mutation';
  adminUpdateCampaignSharedCode: {
    __typename?: 'Campaign';
    campaignId: string;
    sharedCampaignCode?: string | null | undefined;
  };
};

export type GqlCreateManagedCatalogMutationVariables = Exact<{
  input: GqlCreateCatalogInput;
}>;

export type GqlCreateManagedCatalogMutation = {
  __typename?: 'Mutation';
  createManagedCatalog: {
    __typename?: 'Catalog';
    catalogId: string;
    catalogName: string;
    catalogType: GqlCatalogType;
    isPublic: boolean;
    createdAt: string;
    updatedAt: string;
    products: Array<{
      __typename?: 'Product';
      productId: string;
      productName: string;
      description?: string | null | undefined;
      price: number;
      sortOrder: number;
    }>;
  };
};

export type GqlGetCampaignPublicOrderSettingsQueryVariables = Exact<{
  campaignId: Scalars['ID']['input'];
}>;

export type GqlGetCampaignPublicOrderSettingsQuery = {
  __typename?: 'Query';
  getCampaignPublicOrderSettings?:
    | {
        __typename?: 'PublicOrderSettings';
        enabled: boolean;
        shareToken?: string | null | undefined;
        allowedPaymentMethods: Array<string>;
        acknowledgedAt?: string | null | undefined;
        ackVersion?: number | null | undefined;
        publicOrderCount?: number | null | undefined;
        campaignId: string;
        campaignName: string;
        campaignState: GqlCampaignState;
      }
    | null
    | undefined;
};

export type GqlUpdateCampaignPublicOrderSettingsMutationVariables = Exact<{
  input: GqlUpdateCampaignPublicOrderSettingsInput;
}>;

export type GqlUpdateCampaignPublicOrderSettingsMutation = {
  __typename?: 'Mutation';
  updateCampaignPublicOrderSettings: {
    __typename?: 'PublicOrderSettings';
    enabled: boolean;
    shareToken?: string | null | undefined;
    allowedPaymentMethods: Array<string>;
    acknowledgedAt?: string | null | undefined;
    ackVersion?: number | null | undefined;
    publicOrderCount?: number | null | undefined;
    campaignId: string;
    campaignName: string;
    campaignState: GqlCampaignState;
  };
};

export type GqlUnitFieldsFragment = {
  __typename?: 'Unit';
  unitId: string;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  displayName?: string | null | undefined;
  timezone: string;
  splitDefault: GqlSplitMethod;
  councilNeedBasis: GqlCouncilNeedBasis;
  adminCount: number;
  version: number;
  createdAt: string;
  updatedAt: string;
};

export type GqlMyUnitsQueryVariables = Exact<{
  page?: InputMaybe<GqlPageInput>;
}>;

export type GqlMyUnitsQuery = {
  __typename?: 'Query';
  myUnits: {
    __typename?: 'UnitConnection';
    items: Array<{
      __typename?: 'Unit';
      unitId: string;
      unitType: string;
      unitNumber: number;
      city: string;
      state: string;
      displayName?: string | null | undefined;
      timezone: string;
      splitDefault: GqlSplitMethod;
      councilNeedBasis: GqlCouncilNeedBasis;
      adminCount: number;
      version: number;
      createdAt: string;
      updatedAt: string;
    }>;
    pageInfo: { __typename?: 'PageInfo'; endCursor?: string | null | undefined; hasNextPage: boolean };
  };
};

export type GqlGetUnitQueryVariables = Exact<{
  unitId: Scalars['ID']['input'];
}>;

export type GqlGetUnitQuery = {
  __typename?: 'Query';
  unit?:
    | {
        __typename?: 'Unit';
        unitId: string;
        unitType: string;
        unitNumber: number;
        city: string;
        state: string;
        displayName?: string | null | undefined;
        timezone: string;
        splitDefault: GqlSplitMethod;
        councilNeedBasis: GqlCouncilNeedBasis;
        adminCount: number;
        version: number;
        createdAt: string;
        updatedAt: string;
      }
    | null
    | undefined;
};

export type GqlCreateUnitMutationVariables = Exact<{
  input: GqlCreateUnitInput;
}>;

export type GqlCreateUnitMutation = {
  __typename?: 'Mutation';
  createUnit: {
    __typename?: 'CreateUnitPayload';
    unit: {
      __typename?: 'Unit';
      unitId: string;
      unitType: string;
      unitNumber: number;
      city: string;
      state: string;
      displayName?: string | null | undefined;
      timezone: string;
      splitDefault: GqlSplitMethod;
      councilNeedBasis: GqlCouncilNeedBasis;
      adminCount: number;
      version: number;
      createdAt: string;
      updatedAt: string;
    };
    grant: { __typename?: 'UnitAccessGrant'; accountId: string; role: GqlUnitRole; unitId: string; createdAt: string };
  };
};

export type GqlUpdateUnitMutationVariables = Exact<{
  input: GqlUpdateUnitInput;
}>;

export type GqlUpdateUnitMutation = {
  __typename?: 'Mutation';
  updateUnit: {
    __typename?: 'Unit';
    unitId: string;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    displayName?: string | null | undefined;
    timezone: string;
    splitDefault: GqlSplitMethod;
    councilNeedBasis: GqlCouncilNeedBasis;
    adminCount: number;
    version: number;
    createdAt: string;
    updatedAt: string;
  };
};

export type GqlUnitGrantFieldsFragment = {
  __typename?: 'UnitAccessGrant';
  accountId: string;
  email?: string | null | undefined;
  name?: string | null | undefined;
  role: GqlUnitRole;
  unitId: string;
  createdAt: string;
  createdByAccountId: string;
};

export type GqlUnitAdminsQueryVariables = Exact<{
  unitId: Scalars['ID']['input'];
  page?: InputMaybe<GqlPageInput>;
}>;

export type GqlUnitAdminsQuery = {
  __typename?: 'Query';
  unitAdmins: {
    __typename?: 'UnitAccessGrantConnection';
    items: Array<{
      __typename?: 'UnitAccessGrant';
      accountId: string;
      email?: string | null | undefined;
      name?: string | null | undefined;
      role: GqlUnitRole;
      unitId: string;
      createdAt: string;
      createdByAccountId: string;
    }>;
    pageInfo: { __typename?: 'PageInfo'; endCursor?: string | null | undefined; hasNextPage: boolean };
  };
};

export type GqlUnitInvitesQueryVariables = Exact<{
  unitId: Scalars['ID']['input'];
  page?: InputMaybe<GqlPageInput>;
}>;

export type GqlUnitInvitesQuery = {
  __typename?: 'Query';
  unitInvites: {
    __typename?: 'UnitInviteConnection';
    items: Array<{
      __typename?: 'UnitInvite';
      inviteCode: string;
      unitId: string;
      createdByAccountId: string;
      createdAt: string;
      expiresAt: string;
    }>;
    pageInfo: { __typename?: 'PageInfo'; endCursor?: string | null | undefined; hasNextPage: boolean };
  };
};

export type GqlCreateUnitInviteMutationVariables = Exact<{
  input: GqlCreateUnitInviteInput;
}>;

export type GqlCreateUnitInviteMutation = {
  __typename?: 'Mutation';
  createUnitInvite: {
    __typename?: 'UnitInvite';
    inviteCode: string;
    unitId: string;
    createdByAccountId: string;
    createdAt: string;
    expiresAt: string;
  };
};

export type GqlRevokeUnitInviteMutationVariables = Exact<{
  input: GqlRevokeUnitInviteInput;
}>;

export type GqlRevokeUnitInviteMutation = { __typename?: 'Mutation'; revokeUnitInvite: boolean };

export type GqlRedeemUnitInviteMutationVariables = Exact<{
  input: GqlRedeemUnitInviteInput;
}>;

export type GqlRedeemUnitInviteMutation = {
  __typename?: 'Mutation';
  redeemUnitInvite: {
    __typename?: 'UnitAccessGrant';
    accountId: string;
    role: GqlUnitRole;
    unitId: string;
    createdAt: string;
  };
};

export type GqlRevokeUnitAccessGrantMutationVariables = Exact<{
  input: GqlRevokeUnitAccessGrantInput;
}>;

export type GqlRevokeUnitAccessGrantMutation = {
  __typename?: 'Mutation';
  revokeUnitAccessGrant: {
    __typename?: 'Unit';
    unitId: string;
    unitType: string;
    unitNumber: number;
    city: string;
    state: string;
    displayName?: string | null | undefined;
    timezone: string;
    splitDefault: GqlSplitMethod;
    councilNeedBasis: GqlCouncilNeedBasis;
    adminCount: number;
    version: number;
    createdAt: string;
    updatedAt: string;
  };
};

export type GqlUnitCampaignAdminFieldsFragment = {
  __typename?: 'UnitCampaignAdmin';
  unitCampaignId: string;
  unitId: string;
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  joinCode: string;
  isActive: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
  createdByAccountId: string;
  updatedByAccountId: string;
};

export type GqlUnitCampaignsQueryVariables = Exact<{
  unitId: Scalars['ID']['input'];
  isActive?: InputMaybe<Scalars['Boolean']['input']>;
  page?: InputMaybe<GqlPageInput>;
}>;

export type GqlUnitCampaignsQuery = {
  __typename?: 'Query';
  unitCampaigns: {
    __typename?: 'UnitCampaignConnection';
    items: Array<{
      __typename?: 'UnitCampaignAdmin';
      unitCampaignId: string;
      unitId: string;
      campaignName: string;
      campaignYear: number;
      catalogId: string;
      joinCode: string;
      isActive: boolean;
      version: number;
      createdAt: string;
      updatedAt: string;
      createdByAccountId: string;
      updatedByAccountId: string;
    }>;
    pageInfo: { __typename?: 'PageInfo'; endCursor?: string | null | undefined; hasNextPage: boolean };
  };
};

export type GqlCreateUnitCampaignMutationVariables = Exact<{
  input: GqlCreateUnitCampaignInput;
}>;

export type GqlCreateUnitCampaignMutation = {
  __typename?: 'Mutation';
  createUnitCampaign: {
    __typename?: 'UnitCampaignAdmin';
    unitCampaignId: string;
    unitId: string;
    campaignName: string;
    campaignYear: number;
    catalogId: string;
    joinCode: string;
    isActive: boolean;
    version: number;
    createdAt: string;
    updatedAt: string;
    createdByAccountId: string;
    updatedByAccountId: string;
  };
};

export type GqlUpdateUnitCampaignMutationVariables = Exact<{
  input: GqlUpdateUnitCampaignInput;
}>;

export type GqlUpdateUnitCampaignMutation = {
  __typename?: 'Mutation';
  updateUnitCampaign: {
    __typename?: 'UnitCampaignAdmin';
    unitCampaignId: string;
    unitId: string;
    campaignName: string;
    campaignYear: number;
    catalogId: string;
    joinCode: string;
    isActive: boolean;
    version: number;
    createdAt: string;
    updatedAt: string;
    createdByAccountId: string;
    updatedByAccountId: string;
  };
};

export type GqlUnitCampaignCatalogQueryVariables = Exact<{
  unitCampaignId: Scalars['ID']['input'];
}>;

export type GqlUnitCampaignCatalogQuery = {
  __typename?: 'Query';
  unitCampaignCatalog?:
    | {
        __typename?: 'UnitCampaignCatalog';
        catalogId: string;
        catalogName: string;
        products: Array<{ __typename?: 'Product'; productId: string; productName: string; price: number }>;
      }
    | null
    | undefined;
};

export type GqlUnitCampaignRosterQueryVariables = Exact<{
  unitCampaignId: Scalars['ID']['input'];
  status?: InputMaybe<GqlMembershipStatus>;
  page?: InputMaybe<GqlPageInput>;
}>;

export type GqlUnitCampaignRosterQuery = {
  __typename?: 'Query';
  unitCampaignRoster: {
    __typename?: 'UnitCampaignMembershipConnection';
    items: Array<{
      __typename?: 'UnitCampaignMembership';
      campaignId: string;
      profileId: string;
      unitCampaignId: string;
      unitId: string;
      status: GqlMembershipStatus;
      joinedAt: string;
      removedAt?: string | null | undefined;
      joinedByAccountId: string;
      removedByAccountId?: string | null | undefined;
      version: number;
    }>;
    pageInfo: { __typename?: 'PageInfo'; endCursor?: string | null | undefined; hasNextPage: boolean };
  };
};

export type GqlRemoveUnitCampaignMembershipMutationVariables = Exact<{
  input: GqlRemoveUnitCampaignMembershipInput;
}>;

export type GqlRemoveUnitCampaignMembershipMutation = {
  __typename?: 'Mutation';
  removeUnitCampaignMembership: {
    __typename?: 'UnitCampaignMembership';
    campaignId: string;
    profileId: string;
    status: GqlMembershipStatus;
    removedAt?: string | null | undefined;
    version: number;
  };
};

export type GqlJoinUnitCampaignMutationVariables = Exact<{
  input: GqlJoinUnitCampaignInput;
}>;

export type GqlJoinUnitCampaignMutation = {
  __typename?: 'Mutation';
  joinUnitCampaign: {
    __typename?: 'UnitCampaignMembership';
    campaignId: string;
    profileId: string;
    status: GqlMembershipStatus;
    unitCampaignId: string;
    unitId: string;
    version: number;
  };
};

export type GqlPublicGetOrderOfferQueryVariables = Exact<{
  campaignId: Scalars['ID']['input'];
  token: Scalars['String']['input'];
}>;

export type GqlPublicGetOrderOfferQuery = {
  __typename?: 'Query';
  publicGetOrderOffer: {
    __typename?: 'PublicOrderOffer';
    sellerName: string;
    campaignId: string;
    campaignName: string;
    products: Array<{
      __typename?: 'PublicProduct';
      productId: string;
      productName: string;
      price: number;
      description?: string | null | undefined;
      sortOrder?: number | null | undefined;
    }>;
    paymentMethods: Array<{ __typename?: 'PublicPaymentMethod'; name: string; qrCodeUrl?: string | null | undefined }>;
  };
};

export type GqlPublicCreateOrderMutationVariables = Exact<{
  input: GqlPublicCreateOrderInput;
}>;

export type GqlPublicCreateOrderMutation = {
  __typename?: 'Mutation';
  publicCreateOrder: {
    __typename?: 'PublicOrderReceipt';
    orderId: string;
    receiptUrl?: string | null | undefined;
    totalAmount: number;
    buyerEmailProvided: boolean;
    confirmationEmailSent: boolean;
  };
};

export type GqlPublicGetOrderReceiptQueryVariables = Exact<{
  campaignId: Scalars['ID']['input'];
  orderSuffix: Scalars['String']['input'];
  receiptToken: Scalars['String']['input'];
}>;

export type GqlPublicGetOrderReceiptQuery = {
  __typename?: 'Query';
  publicGetOrderReceipt: {
    __typename?: 'PublicOrderReceiptLookup';
    sellerName: string;
    orderId: string;
    orderDate: string;
    totalAmount: number;
    paymentMethodName: string;
    status: GqlOrderStatus;
    buyerFirstName: string;
    buyerLastName: string;
    lineItems: Array<{
      __typename?: 'PublicLineItem';
      productId: string;
      productName: string;
      quantity: number;
      pricePerUnit: number;
      subtotal: number;
    }>;
  };
};
