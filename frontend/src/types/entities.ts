/**
 * Core entity type definitions.
 *
 * These match the GraphQL schema and should be used across all components.
 * Auto-generated types from GraphQL schema would be ideal future enhancement.
 */

/**
 * SellerProfile represents a Scout (seller).
 */
export interface SellerProfile {
  profileId: string;
  ownerAccountId: string;
  sellerName: string;
  unitType?: string;
  unitNumber?: number;
  isOwner?: boolean;
  permissions?: string[];
  latestCampaign?: {
    campaignId: string;
    campaignName: string;
    campaignYear: number;
    isActive: boolean;
  };
  createdAt: string;
  updatedAt: string;
}

/**
 * Campaign represents a fundraising campaign for a seller.
 */
export interface Campaign {
  campaignId: string;
  profileId: string;
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  startDate?: string;
  endDate?: string;
  goalAmount?: number;
  unitType?: string;
  unitNumber?: number;
  city?: string;
  state?: string;
  isShared?: boolean;
  sharedCampaignCode?: string;
  isActive: boolean; // Whether campaign is active (default true)
  totalOrders?: number;
  totalRevenue?: number;
  createdAt?: string;
  updatedAt?: string;
}

/**
 * Product in a catalog.
 */
export interface Product {
  productId: string;
  productName: string;
  price: number;
  description?: string;
  category?: string;
  sku?: string;
}

/**
 * Product input for creating/editing (without productId).
 */
export interface ProductInput {
  productName: string;
  description?: string;
  price: number;
}

/**
 * Catalog of products.
 */
export interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType?: string;
  ownerAccountId?: string;
  isPublic?: boolean;
  isDeleted?: boolean;
  products?: Product[];
  createdAt?: string;
  updatedAt?: string;
}

/**
 * Customer delivery address.
 */
export interface OrderAddress {
  street: string;
  city: string;
  state: string;
  zipCode: string;
}

/**
 * Individual line item in an order.
 * Note: Field names match the GraphQL schema (pricePerUnit, subtotal)
 */
export interface OrderLineItem {
  productId: string;
  productName: string;
  quantity: number;
  pricePerUnit: number;
  subtotal: number;
}

/**
 * Payment method for orders.
 */
export type PaymentMethod = 'CASH' | 'CHECK' | 'CREDIT_CARD' | 'ONLINE' | 'OTHER';

/**
 * Order placed by a customer.
 */
export interface Order {
  orderId: string;
  campaignId: string;
  profileId: string;
  customerName: string;
  customerPhone?: string;
  customerAddress?: OrderAddress;
  lineItems: OrderLineItem[];
  totalAmount: number;
  paymentMethod: PaymentMethod;
  notes?: string;
  orderDate?: string;
  createdAt?: string;
  updatedAt?: string;
}

/**
 * Permission level for shared profiles.
 */
export type SharePermission = 'READ' | 'WRITE';

/**
 * Share permissions granted to an account.
 */
export interface Share {
  shareId?: string;
  profileId: string;
  targetAccountId: string;
  targetAccount?: {
    accountId: string;
    email: string;
    givenName?: string;
    familyName?: string;
  };
  permissions: SharePermission[];
  createdAt?: string;
  createdByAccountId?: string;
  updatedAt?: string;
}

/**
 * Profile invite for sharing.
 */
export interface ProfileInvite {
  inviteCode: string;
  profileId: string;
  permissions: SharePermission[];
  expiresAt: string;
  createdAt: string;
  createdByAccountId?: string;
  usedAt?: string;
  usedByAccountId?: string;
}

/**
 * Shared campaign template.
 */
export interface SharedCampaign {
  sharedCampaignCode: string;
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  catalog?: {
    catalogId: string;
    catalogName: string;
  };
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  startDate?: string;
  endDate?: string;
  description?: string;
  creatorMessage?: string;
  isActive: boolean;
  createdByAccountId: string;
  createdBy?: string;
  createdByName?: string;
  createdAt?: string;
  updatedAt?: string;
}
