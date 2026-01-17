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
  AWSDate: { input: string; output: string };
  AWSDateTime: { input: string; output: string };
  AWSEmail: { input: string; output: string };
  AWSJSON: { input: Record<string, unknown>; output: Record<string, unknown> };
  AWSPhone: { input: string; output: string };
  AWSURL: { input: string; output: string };
};

export type GqlAccount = {
  __typename?: 'Account';
  accountId: Scalars['ID']['output'];
  city?: Maybe<Scalars['String']['output']>;
  createdAt: Scalars['AWSDateTime']['output'];
  email: Scalars['AWSEmail']['output'];
  familyName?: Maybe<Scalars['String']['output']>;
  givenName?: Maybe<Scalars['String']['output']>;
  preferences?: Maybe<Scalars['AWSJSON']['output']>;
  state?: Maybe<Scalars['String']['output']>;
  unitNumber?: Maybe<Scalars['Int']['output']>;
  unitType?: Maybe<Scalars['String']['output']>;
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlAddress = {
  __typename?: 'Address';
  city?: Maybe<Scalars['String']['output']>;
  state?: Maybe<Scalars['String']['output']>;
  street?: Maybe<Scalars['String']['output']>;
  zipCode?: Maybe<Scalars['String']['output']>;
};

export type GqlAddressInput = {
  city?: InputMaybe<Scalars['String']['input']>;
  state?: InputMaybe<Scalars['String']['input']>;
  street?: InputMaybe<Scalars['String']['input']>;
  zipCode?: InputMaybe<Scalars['String']['input']>;
};

export type GqlCampaign = {
  __typename?: 'Campaign';
  campaignId: Scalars['ID']['output'];
  campaignName: Scalars['String']['output'];
  campaignYear: Scalars['Int']['output'];
  catalog?: Maybe<GqlCatalog>;
  catalogId: Scalars['ID']['output'];
  city?: Maybe<Scalars['String']['output']>;
  createdAt: Scalars['AWSDateTime']['output'];
  endDate?: Maybe<Scalars['AWSDateTime']['output']>;
  profileId: Scalars['ID']['output'];
  sharedCampaignCode?: Maybe<Scalars['String']['output']>;
  startDate?: Maybe<Scalars['AWSDateTime']['output']>;
  state?: Maybe<Scalars['String']['output']>;
  totalOrders?: Maybe<Scalars['Int']['output']>;
  totalRevenue?: Maybe<Scalars['Float']['output']>;
  unitNumber?: Maybe<Scalars['Int']['output']>;
  unitType?: Maybe<Scalars['String']['output']>;
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlCampaignReport = {
  __typename?: 'CampaignReport';
  campaignId: Scalars['ID']['output'];
  createdAt: Scalars['AWSDateTime']['output'];
  expiresAt?: Maybe<Scalars['AWSDateTime']['output']>;
  profileId: Scalars['ID']['output'];
  reportId: Scalars['ID']['output'];
  reportUrl?: Maybe<Scalars['AWSURL']['output']>;
  status: Scalars['String']['output'];
};

export type GqlCatalog = {
  __typename?: 'Catalog';
  catalogId: Scalars['ID']['output'];
  catalogName: Scalars['String']['output'];
  catalogType: GqlCatalogType;
  createdAt: Scalars['AWSDateTime']['output'];
  isPublic: Scalars['Boolean']['output'];
  products: Array<GqlProduct>;
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlCatalogType = 'ADMIN_MANAGED' | 'USER_CREATED';

export type GqlCreateCampaignInput = {
  campaignName?: InputMaybe<Scalars['String']['input']>;
  campaignYear?: InputMaybe<Scalars['Int']['input']>;
  catalogId?: InputMaybe<Scalars['ID']['input']>;
  city?: InputMaybe<Scalars['String']['input']>;
  endDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  profileId: Scalars['ID']['input'];
  shareWithCreator?: InputMaybe<Scalars['Boolean']['input']>;
  sharedCampaignCode?: InputMaybe<Scalars['String']['input']>;
  startDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  state?: InputMaybe<Scalars['String']['input']>;
  unitNumber?: InputMaybe<Scalars['Int']['input']>;
  unitType?: InputMaybe<Scalars['String']['input']>;
};

export type GqlCreateCatalogInput = {
  catalogName: Scalars['String']['input'];
  isPublic: Scalars['Boolean']['input'];
  products: Array<GqlProductInput>;
};

export type GqlCreateOrderInput = {
  campaignId: Scalars['ID']['input'];
  customerAddress?: InputMaybe<GqlAddressInput>;
  customerName: Scalars['String']['input'];
  customerPhone?: InputMaybe<Scalars['String']['input']>;
  lineItems: Array<GqlLineItemInput>;
  notes?: InputMaybe<Scalars['String']['input']>;
  orderDate: Scalars['AWSDateTime']['input'];
  paymentMethod: Scalars['String']['input'];
  profileId: Scalars['ID']['input'];
};

export type GqlCreateProfileInviteInput = {
  expiresInDays?: InputMaybe<Scalars['Int']['input']>;
  permissions: Array<GqlPermissionType>;
  profileId: Scalars['ID']['input'];
};

export type GqlCreateSellerProfileInput = {
  sellerName: Scalars['String']['input'];
};

export type GqlCreateSharedCampaignInput = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  catalogId: Scalars['ID']['input'];
  city: Scalars['String']['input'];
  creatorMessage?: InputMaybe<Scalars['String']['input']>;
  description?: InputMaybe<Scalars['String']['input']>;
  endDate?: InputMaybe<Scalars['AWSDate']['input']>;
  startDate?: InputMaybe<Scalars['AWSDate']['input']>;
  state: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

export type GqlLineItem = {
  __typename?: 'LineItem';
  pricePerUnit: Scalars['Float']['output'];
  productId: Scalars['ID']['output'];
  productName: Scalars['String']['output'];
  quantity: Scalars['Int']['output'];
  subtotal: Scalars['Float']['output'];
};

export type GqlLineItemInput = {
  productId: Scalars['ID']['input'];
  quantity: Scalars['Int']['input'];
};

export type GqlMutation = {
  __typename?: 'Mutation';
  confirmPaymentMethodQRCodeUpload: GqlPaymentMethod;
  createCampaign: GqlCampaign;
  createCatalog: GqlCatalog;
  createOrder: GqlOrder;
  createPaymentMethod: GqlPaymentMethod;
  createProfileInvite: GqlProfileInvite;
  createSellerProfile: GqlSellerProfile;
  createSharedCampaign: GqlSharedCampaign;
  deleteCampaign: Scalars['Boolean']['output'];
  deleteCatalog: Scalars['Boolean']['output'];
  deleteOrder: Scalars['Boolean']['output'];
  deletePaymentMethod: Scalars['Boolean']['output'];
  deletePaymentMethodQRCode: Scalars['Boolean']['output'];
  deleteProfileInvite: Scalars['Boolean']['output'];
  deleteSellerProfile: Scalars['Boolean']['output'];
  deleteSharedCampaign: Scalars['Boolean']['output'];
  redeemProfileInvite: GqlShare;
  requestCampaignReport: GqlCampaignReport;
  requestPaymentMethodQRCodeUpload: GqlS3UploadInfo;
  revokeShare: Scalars['Boolean']['output'];
  shareProfileDirect: GqlShare;
  transferProfileOwnership: GqlSellerProfile;
  updateCampaign: GqlCampaign;
  updateCatalog: GqlCatalog;
  updateMyAccount: GqlAccount;
  updateMyPreferences: GqlAccount;
  updateOrder: GqlOrder;
  updatePaymentMethod: GqlPaymentMethod;
  updateSellerProfile: GqlSellerProfile;
  updateSharedCampaign: GqlSharedCampaign;
};

export type GqlMutation_ConfirmPaymentMethodQrCodeUploadArgs = {
  paymentMethodName: Scalars['String']['input'];
  s3Key: Scalars['String']['input'];
};

export type GqlMutation_CreateCampaignArgs = {
  input: GqlCreateCampaignInput;
};

export type GqlMutation_CreateCatalogArgs = {
  input: GqlCreateCatalogInput;
};

export type GqlMutation_CreateOrderArgs = {
  input: GqlCreateOrderInput;
};

export type GqlMutation_CreatePaymentMethodArgs = {
  name: Scalars['String']['input'];
};

export type GqlMutation_CreateProfileInviteArgs = {
  input: GqlCreateProfileInviteInput;
};

export type GqlMutation_CreateSellerProfileArgs = {
  input: GqlCreateSellerProfileInput;
};

export type GqlMutation_CreateSharedCampaignArgs = {
  input: GqlCreateSharedCampaignInput;
};

export type GqlMutation_DeleteCampaignArgs = {
  campaignId: Scalars['ID']['input'];
};

export type GqlMutation_DeleteCatalogArgs = {
  catalogId: Scalars['ID']['input'];
};

export type GqlMutation_DeleteOrderArgs = {
  orderId: Scalars['ID']['input'];
};

export type GqlMutation_DeletePaymentMethodArgs = {
  name: Scalars['String']['input'];
};

export type GqlMutation_DeletePaymentMethodQrCodeArgs = {
  paymentMethodName: Scalars['String']['input'];
};

export type GqlMutation_DeleteProfileInviteArgs = {
  inviteCode: Scalars['ID']['input'];
  profileId: Scalars['ID']['input'];
};

export type GqlMutation_DeleteSellerProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlMutation_DeleteSharedCampaignArgs = {
  sharedCampaignCode: Scalars['String']['input'];
};

export type GqlMutation_RedeemProfileInviteArgs = {
  input: GqlRedeemProfileInviteInput;
};

export type GqlMutation_RequestCampaignReportArgs = {
  input: GqlRequestCampaignReportInput;
};

export type GqlMutation_RequestPaymentMethodQrCodeUploadArgs = {
  paymentMethodName: Scalars['String']['input'];
};

export type GqlMutation_RevokeShareArgs = {
  input: GqlRevokeShareInput;
};

export type GqlMutation_ShareProfileDirectArgs = {
  input: GqlShareProfileDirectInput;
};

export type GqlMutation_TransferProfileOwnershipArgs = {
  input: GqlTransferProfileOwnershipInput;
};

export type GqlMutation_UpdateCampaignArgs = {
  input: GqlUpdateCampaignInput;
};

export type GqlMutation_UpdateCatalogArgs = {
  catalogId: Scalars['ID']['input'];
  input: GqlCreateCatalogInput;
};

export type GqlMutation_UpdateMyAccountArgs = {
  input: GqlUpdateMyAccountInput;
};

export type GqlMutation_UpdateMyPreferencesArgs = {
  preferences: Scalars['AWSJSON']['input'];
};

export type GqlMutation_UpdateOrderArgs = {
  input: GqlUpdateOrderInput;
};

export type GqlMutation_UpdatePaymentMethodArgs = {
  currentName: Scalars['String']['input'];
  newName: Scalars['String']['input'];
};

export type GqlMutation_UpdateSellerProfileArgs = {
  input: GqlUpdateSellerProfileInput;
};

export type GqlMutation_UpdateSharedCampaignArgs = {
  input: GqlUpdateSharedCampaignInput;
};

export type GqlOrder = {
  __typename?: 'Order';
  campaignId: Scalars['ID']['output'];
  createdAt: Scalars['AWSDateTime']['output'];
  customerAddress?: Maybe<GqlAddress>;
  customerName: Scalars['String']['output'];
  customerPhone?: Maybe<Scalars['String']['output']>;
  lineItems: Array<GqlLineItem>;
  notes?: Maybe<Scalars['String']['output']>;
  orderDate: Scalars['AWSDateTime']['output'];
  orderId: Scalars['ID']['output'];
  paymentMethod: Scalars['String']['output'];
  profileId: Scalars['ID']['output'];
  totalAmount: Scalars['Float']['output'];
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlPaymentMethod = {
  __typename?: 'PaymentMethod';
  name: Scalars['String']['output'];
  qrCodeUrl?: Maybe<Scalars['String']['output']>;
};

export type GqlPermissionType = 'READ' | 'WRITE';

export type GqlProduct = {
  __typename?: 'Product';
  description?: Maybe<Scalars['String']['output']>;
  price: Scalars['Float']['output'];
  productId: Scalars['ID']['output'];
  productName: Scalars['String']['output'];
  sortOrder: Scalars['Int']['output'];
};

export type GqlProductInput = {
  description?: InputMaybe<Scalars['String']['input']>;
  price: Scalars['Float']['input'];
  productName: Scalars['String']['input'];
  sortOrder: Scalars['Int']['input'];
};

export type GqlProfileInvite = {
  __typename?: 'ProfileInvite';
  createdAt: Scalars['AWSDateTime']['output'];
  createdByAccountId: Scalars['ID']['output'];
  expiresAt: Scalars['AWSDateTime']['output'];
  inviteCode: Scalars['ID']['output'];
  permissions: Array<GqlPermissionType>;
  profileId: Scalars['ID']['output'];
};

export type GqlQuery = {
  __typename?: 'Query';
  findSharedCampaigns: Array<GqlSharedCampaign>;
  getCampaign?: Maybe<GqlCampaign>;
  getCatalog?: Maybe<GqlCatalog>;
  getMyAccount: GqlAccount;
  getOrder?: Maybe<GqlOrder>;
  getProfile?: Maybe<GqlSellerProfile>;
  getSharedCampaign?: Maybe<GqlSharedCampaign>;
  getUnitReport?: Maybe<GqlUnitReport>;
  listCampaignsByProfile: Array<GqlCampaign>;
  listInvitesByProfile: Array<GqlProfileInvite>;
  listManagedCatalogs: Array<GqlCatalog>;
  listMyCatalogs: Array<GqlCatalog>;
  listMyProfiles: Array<GqlSellerProfile>;
  listMySharedCampaigns: Array<GqlSharedCampaign>;
  listMyShares: Array<GqlSharedProfile>;
  listOrdersByCampaign: Array<GqlOrder>;
  listOrdersByProfile: Array<GqlOrder>;
  listSharesByProfile: Array<GqlShare>;
  listUnitCampaignCatalogs: Array<GqlCatalog>;
  listUnitCatalogs: Array<GqlCatalog>;
  myPaymentMethods: Array<GqlPaymentMethod>;
  paymentMethodsForProfile: Array<GqlPaymentMethod>;
};

export type GqlQuery_FindSharedCampaignsArgs = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  city: Scalars['String']['input'];
  state: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

export type GqlQuery_GetCampaignArgs = {
  campaignId: Scalars['ID']['input'];
};

export type GqlQuery_GetCatalogArgs = {
  catalogId: Scalars['ID']['input'];
};

export type GqlQuery_GetOrderArgs = {
  orderId: Scalars['ID']['input'];
};

export type GqlQuery_GetProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlQuery_GetSharedCampaignArgs = {
  sharedCampaignCode: Scalars['String']['input'];
};

export type GqlQuery_GetUnitReportArgs = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  catalogId: Scalars['ID']['input'];
  city?: InputMaybe<Scalars['String']['input']>;
  state?: InputMaybe<Scalars['String']['input']>;
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

export type GqlQuery_ListCampaignsByProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlQuery_ListInvitesByProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlQuery_ListOrdersByCampaignArgs = {
  campaignId: Scalars['ID']['input'];
};

export type GqlQuery_ListOrdersByProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlQuery_ListSharesByProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlQuery_ListUnitCampaignCatalogsArgs = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  city: Scalars['String']['input'];
  state: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

export type GqlQuery_ListUnitCatalogsArgs = {
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
  unitNumber: Scalars['Int']['input'];
  unitType: Scalars['String']['input'];
};

export type GqlQuery_PaymentMethodsForProfileArgs = {
  profileId: Scalars['ID']['input'];
};

export type GqlRedeemProfileInviteInput = {
  inviteCode: Scalars['ID']['input'];
};

export type GqlRequestCampaignReportInput = {
  campaignId: Scalars['ID']['input'];
  format?: InputMaybe<Scalars['String']['input']>;
};

export type GqlRevokeShareInput = {
  profileId: Scalars['ID']['input'];
  targetAccountId: Scalars['ID']['input'];
};

export type GqlS3UploadInfo = {
  __typename?: 'S3UploadInfo';
  fields: Scalars['AWSJSON']['output'];
  s3Key: Scalars['String']['output'];
  uploadUrl: Scalars['String']['output'];
};

export type GqlSellerProfile = {
  __typename?: 'SellerProfile';
  createdAt: Scalars['AWSDateTime']['output'];
  isOwner: Scalars['Boolean']['output'];
  ownerAccountId: Scalars['ID']['output'];
  permissions?: Maybe<Array<GqlPermissionType>>;
  profileId: Scalars['ID']['output'];
  sellerName: Scalars['String']['output'];
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlShare = {
  __typename?: 'Share';
  createdAt: Scalars['AWSDateTime']['output'];
  createdByAccountId: Scalars['ID']['output'];
  permissions: Array<GqlPermissionType>;
  profileId: Scalars['ID']['output'];
  shareId: Scalars['ID']['output'];
  targetAccount?: Maybe<GqlAccount>;
  targetAccountId: Scalars['ID']['output'];
};

export type GqlShareInfo = {
  __typename?: 'ShareInfo';
  permissions: Array<GqlPermissionType>;
  profileId: Scalars['ID']['output'];
};

export type GqlShareProfileDirectInput = {
  permissions: Array<GqlPermissionType>;
  profileId: Scalars['ID']['input'];
  targetAccountEmail: Scalars['AWSEmail']['input'];
};

export type GqlSharedCampaign = {
  __typename?: 'SharedCampaign';
  campaignName: Scalars['String']['output'];
  campaignYear: Scalars['Int']['output'];
  catalog: GqlCatalog;
  catalogId: Scalars['ID']['output'];
  city: Scalars['String']['output'];
  createdAt: Scalars['AWSDateTime']['output'];
  createdBy: Scalars['ID']['output'];
  createdByName: Scalars['String']['output'];
  creatorMessage?: Maybe<Scalars['String']['output']>;
  description?: Maybe<Scalars['String']['output']>;
  endDate?: Maybe<Scalars['AWSDate']['output']>;
  isActive: Scalars['Boolean']['output'];
  sharedCampaignCode: Scalars['String']['output'];
  startDate?: Maybe<Scalars['AWSDate']['output']>;
  state: Scalars['String']['output'];
  unitNumber: Scalars['Int']['output'];
  unitType: Scalars['String']['output'];
};

export type GqlSharedProfile = {
  __typename?: 'SharedProfile';
  createdAt: Scalars['AWSDateTime']['output'];
  isOwner: Scalars['Boolean']['output'];
  ownerAccountId: Scalars['ID']['output'];
  permissions: Array<GqlPermissionType>;
  profileId: Scalars['ID']['output'];
  sellerName: Scalars['String']['output'];
  unitNumber?: Maybe<Scalars['Int']['output']>;
  unitType?: Maybe<Scalars['String']['output']>;
  updatedAt: Scalars['AWSDateTime']['output'];
};

export type GqlTransferProfileOwnershipInput = {
  newOwnerAccountId: Scalars['ID']['input'];
  profileId: Scalars['ID']['input'];
};

export type GqlUnitOrderDetail = {
  __typename?: 'UnitOrderDetail';
  customerName: Scalars['String']['output'];
  lineItems: Array<GqlLineItem>;
  orderDate: Scalars['AWSDateTime']['output'];
  orderId: Scalars['ID']['output'];
  totalAmount: Scalars['Float']['output'];
};

export type GqlUnitReport = {
  __typename?: 'UnitReport';
  campaignName: Scalars['String']['output'];
  campaignYear: Scalars['Int']['output'];
  sellers: Array<GqlUnitSellerSummary>;
  totalOrders: Scalars['Int']['output'];
  totalSales: Scalars['Float']['output'];
  unitNumber: Scalars['Int']['output'];
  unitType: Scalars['String']['output'];
};

export type GqlUnitSellerSummary = {
  __typename?: 'UnitSellerSummary';
  orderCount: Scalars['Int']['output'];
  orders: Array<GqlUnitOrderDetail>;
  profileId: Scalars['ID']['output'];
  sellerName: Scalars['String']['output'];
  totalSales: Scalars['Float']['output'];
};

export type GqlUpdateCampaignInput = {
  campaignId: Scalars['ID']['input'];
  campaignName?: InputMaybe<Scalars['String']['input']>;
  campaignYear?: InputMaybe<Scalars['Int']['input']>;
  catalogId?: InputMaybe<Scalars['ID']['input']>;
  endDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  startDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
};

export type GqlUpdateMyAccountInput = {
  city?: InputMaybe<Scalars['String']['input']>;
  familyName?: InputMaybe<Scalars['String']['input']>;
  givenName?: InputMaybe<Scalars['String']['input']>;
  state?: InputMaybe<Scalars['String']['input']>;
  unitNumber?: InputMaybe<Scalars['Int']['input']>;
  unitType?: InputMaybe<Scalars['String']['input']>;
};

export type GqlUpdateOrderInput = {
  customerAddress?: InputMaybe<GqlAddressInput>;
  customerName?: InputMaybe<Scalars['String']['input']>;
  customerPhone?: InputMaybe<Scalars['String']['input']>;
  lineItems?: InputMaybe<Array<GqlLineItemInput>>;
  notes?: InputMaybe<Scalars['String']['input']>;
  orderDate?: InputMaybe<Scalars['AWSDateTime']['input']>;
  orderId: Scalars['ID']['input'];
  paymentMethod?: InputMaybe<Scalars['String']['input']>;
};

export type GqlUpdateSellerProfileInput = {
  profileId: Scalars['ID']['input'];
  sellerName: Scalars['String']['input'];
};

export type GqlUpdateSharedCampaignInput = {
  creatorMessage?: InputMaybe<Scalars['String']['input']>;
  description?: InputMaybe<Scalars['String']['input']>;
  isActive?: InputMaybe<Scalars['Boolean']['input']>;
  sharedCampaignCode: Scalars['String']['input'];
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

export type GqlListMyProfilesQueryVariables = Exact<{ [key: string]: never }>;

export type GqlListMyProfilesQuery = {
  __typename?: 'Query';
  listMyProfiles: Array<{
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
}>;

export type GqlListCampaignsByProfileQuery = {
  __typename?: 'Query';
  listCampaignsByProfile: Array<{
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
    createdAt: string;
    updatedAt: string;
    totalOrders?: number | null | undefined;
    totalRevenue?: number | null | undefined;
  }>;
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
}>;

export type GqlListOrdersByCampaignQuery = {
  __typename?: 'Query';
  listOrdersByCampaign: Array<{
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

export type GqlRequestCampaignReportMutationVariables = Exact<{
  input: GqlRequestCampaignReportInput;
}>;

export type GqlRequestCampaignReportMutation = {
  __typename?: 'Mutation';
  requestCampaignReport: {
    __typename?: 'CampaignReport';
    reportId: string;
    campaignId: string;
    profileId: string;
    reportUrl?: string | null | undefined;
    status: string;
    createdAt: string;
    expiresAt?: string | null | undefined;
  };
};

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

export type GqlShareProfileDirectMutationVariables = Exact<{
  input: GqlShareProfileDirectInput;
}>;

export type GqlShareProfileDirectMutation = {
  __typename?: 'Mutation';
  shareProfileDirect: {
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

export type GqlListUnitCatalogsQueryVariables = Exact<{
  unitType: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
}>;

export type GqlListUnitCatalogsQuery = {
  __typename?: 'Query';
  listUnitCatalogs: Array<{
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
  catalog: { __typename?: 'Catalog'; catalogId: string; catalogName: string };
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
        catalog: { __typename?: 'Catalog'; catalogId: string; catalogName: string };
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
    catalog: { __typename?: 'Catalog'; catalogId: string; catalogName: string };
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
    catalog: { __typename?: 'Catalog'; catalogId: string; catalogName: string };
  }>;
};

export type GqlListUnitCampaignCatalogsQueryVariables = Exact<{
  unitType: Scalars['String']['input'];
  unitNumber: Scalars['Int']['input'];
  city: Scalars['String']['input'];
  state: Scalars['String']['input'];
  campaignName: Scalars['String']['input'];
  campaignYear: Scalars['Int']['input'];
}>;

export type GqlListUnitCampaignCatalogsQuery = {
  __typename?: 'Query';
  listUnitCampaignCatalogs: Array<{
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
    catalog: { __typename?: 'Catalog'; catalogId: string; catalogName: string };
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
    catalog: { __typename?: 'Catalog'; catalogId: string; catalogName: string };
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
