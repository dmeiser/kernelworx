/**
 * Fixtures for the Show & Sell Unit screens (§1.6).
 *
 * They mirror the shape the fragments ask the server for, including `__typename`,
 * so a component that reads a field the fragment does not request still fails in
 * review rather than passing against a fixture that quietly supplied it.
 */

import { SHOW_SELL_PREVIEW_GROUP } from '../../src/hooks/useShowSellPreview';
import type { GqlUnit } from '../../src/types/graphql-generated';

export const PREVIEW_GROUP = SHOW_SELL_PREVIEW_GROUP;

export function unitFixture(overrides: Partial<GqlUnit> = {}): GqlUnit {
  return {
    __typename: 'Unit',
    unitId: 'UNIT#pack-3149',
    unitType: 'Pack',
    unitNumber: 3149,
    city: 'Springfield',
    state: 'IL',
    displayName: null,
    timezone: 'America/Chicago',
    splitDefault: 'EQUAL',
    councilNeedBasis: 'PHYSICAL_STOCK',
    adminCount: 2,
    version: 3,
    createdAt: '2026-01-04T15:00:00Z',
    updatedAt: '2026-01-04T15:00:00Z',
    createdByAccountId: 'account-avery',
    ...overrides,
  };
}

export function grantFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitAccessGrant',
    unitId: 'UNIT#pack-3149',
    accountId: 'account-casey',
    role: 'UNIT_ADMIN',
    email: 'casey@example.com',
    name: 'Casey Admin',
    createdByAccountId: 'account-avery',
    createdAt: '2026-01-04T15:00:00Z',
    ...overrides,
  };
}

export function inviteFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitInvite',
    inviteCode: 'ABCD1234EFGH5678',
    unitId: 'UNIT#pack-3149',
    createdByAccountId: 'account-avery',
    createdAt: '2026-01-04T15:00:00Z',
    expiresAt: '2026-01-18T15:00:00Z',
    ...overrides,
  };
}

export function campaignFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitCampaignAdmin',
    unitCampaignId: 'UNITCAMP#pack-3149-fall',
    unitId: 'UNIT#pack-3149',
    campaignName: 'Fall Popcorn',
    campaignYear: 2026,
    catalogId: 'CATALOG#popcorn-2026',
    joinCode: 'JOIN1234CODE5678',
    isActive: true,
    version: 1,
    createdAt: '2026-01-05T15:00:00Z',
    updatedAt: '2026-01-05T15:00:00Z',
    createdByAccountId: 'account-avery',
    updatedByAccountId: 'account-avery',
    ...overrides,
  };
}

export function membershipFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitCampaignMembership',
    unitCampaignId: 'UNITCAMP#pack-3149-fall',
    unitId: 'UNIT#pack-3149',
    campaignId: 'CAMPAIGN#devon',
    profileId: 'PROFILE#devon',
    scoutName: 'Devon Scout',
    campaignName: 'Devon Fall Campaign',
    scoutCampaignCatalogId: 'CATALOG#fixture-default',
    status: 'ACTIVE',
    joinedByAccountId: 'account-devon',
    joinedAt: '2026-01-06T15:00:00Z',
    removedByAccountId: null,
    removedAt: null,
    version: 1,
    guardVersion: 1,
    ...overrides,
  };
}

export function catalogViewFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitCampaignCatalog',
    catalogId: 'CATALOG#popcorn-2026',
    catalogName: 'Popcorn 2026',
    products: [
      {
        __typename: 'Product',
        productId: 'PROD#cheese',
        productName: 'Cheese',
        description: 'Cheese popcorn',
        price: 10,
        sortOrder: 1,
      },
      {
        __typename: 'Product',
        productId: 'PROD#caramel',
        productName: 'Caramel',
        description: null,
        price: 3.5,
        sortOrder: 2,
      },
    ],
    ...overrides,
  };
}

export function joinPreviewFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'UnitCampaignJoinPreview',
    unitDisplayName: 'Pack 3149 (Springfield, IL)',
    campaignName: 'Fall Popcorn',
    campaignYear: 2026,
    catalogName: 'Popcorn 2026',
    isActive: true,
    ...overrides,
  };
}

export function scoutProfileFixture(overrides: Record<string, unknown> = {}) {
  return {
    __typename: 'SellerProfile',
    profileId: 'PROFILE#devon',
    ownerAccountId: 'ACCOUNT#devon',
    sellerName: 'Devon Scout',
    createdAt: '2026-01-02T15:00:00Z',
    updatedAt: '2026-01-02T15:00:00Z',
    isOwner: true,
    permissions: [],
    latestCampaign: {
      __typename: 'Campaign',
      campaignId: 'CAMPAIGN#devon',
      campaignName: 'Devon 2026',
      campaignYear: 2026,
      isActive: true,
    },
    ...overrides,
  };
}

export function graphQlError(code: string, message = 'denied'): Error {
  const error = new Error(message) as Error & { graphQLErrors?: unknown[] };
  error.graphQLErrors = [{ message, extensions: { code } }];
  return error;
}
