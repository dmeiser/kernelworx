/**
 * Tests for the public offer view types and the cap predicate.
 *
 * The view shapes are derived from the generated `PublicGetOrderOffer`
 * operation type rather than hand-copied, so the assignability check below is
 * the part that matters: the page passes query results straight into these
 * components, and a hand-written copy would have let the two drift the moment
 * the schema or query document gained a field.
 *
 * `remainingOrders` and `isSoldOut` are the one hand-written part, because they
 * are additive and nullable: a read taken before they exist carries neither, and
 * that must not read as "sold out".
 */
import { describe, it, expect, expectTypeOf } from 'vitest';
import {
  offerHasReachedCap,
  type PublicOfferView,
  type PublicProductView,
  type PublicPaymentMethodView,
} from '../../src/components/public/publicOrderTypes';
import type { GqlPublicGetOrderOfferQuery } from '../../src/types/graphql-generated';

type GeneratedOffer = GqlPublicGetOrderOfferQuery['publicGetOrderOffer'];

const offer = (cap: Partial<Pick<PublicOfferView, 'remainingOrders' | 'isSoldOut'>> = {}): PublicOfferView => ({
  sellerName: 'Acme Troop',
  campaignId: 'CAMPAIGN#c1',
  campaignName: 'Spring Sale',
  products: [{ productId: 'PROD#1', productName: 'Cookie Box', price: 10 }],
  paymentMethods: [{ name: 'Venmo', qrCodeUrl: null }],
  ...cap,
});

describe('public offer view types', () => {
  it('accepts the generated query result without a cast', () => {
    const fromQuery: GeneratedOffer = {
      __typename: 'PublicOrderOffer',
      sellerName: 'Acme Troop',
      campaignId: 'CAMPAIGN#c1',
      campaignName: 'Spring Sale',
      products: [
        { __typename: 'PublicProduct', productId: 'PROD#1', productName: 'Cookie Box', price: 10, description: null, sortOrder: 1 },
      ],
      paymentMethods: [{ __typename: 'PublicPaymentMethod', name: 'Venmo', qrCodeUrl: null }],
    };
    // The page hands this straight to the components; the view type must carry
    // every generated field, including ones added later.
    const asView: PublicOfferView = fromQuery;
    expect(asView.products[0].productName).toBe('Cookie Box');
  });

  it('keeps the generated field set rather than a hand-copied subset', () => {
    expectTypeOf<PublicOfferView>().toMatchTypeOf<GeneratedOffer>();
    expectTypeOf<PublicProductView>().toEqualTypeOf<GeneratedOffer['products'][number]>();
    expectTypeOf<PublicPaymentMethodView>().toEqualTypeOf<GeneratedOffer['paymentMethods'][number]>();
  });
});

describe('offerHasReachedCap', () => {
  it('is false for an offer read that predates the cap fields', () => {
    expect(offerHasReachedCap(offer())).toBe(false);
  });

  it('is false when both cap fields are null', () => {
    expect(offerHasReachedCap(offer({ remainingOrders: null, isSoldOut: null }))).toBe(false);
  });

  it('is true only on an explicit isSoldOut', () => {
    expect(offerHasReachedCap(offer({ isSoldOut: true }))).toBe(true);
    expect(offerHasReachedCap(offer({ isSoldOut: false }))).toBe(false);
  });

  it('is true only when remainingOrders is exactly zero', () => {
    expect(offerHasReachedCap(offer({ remainingOrders: 0 }))).toBe(true);
    expect(offerHasReachedCap(offer({ remainingOrders: 1 }))).toBe(false);
    expect(offerHasReachedCap(offer({ remainingOrders: 400 }))).toBe(false);
  });

  it('does not treat an absent remainingOrders as zero', () => {
    // The whole point of the optional field: undefined must not satisfy === 0.
    expect(offerHasReachedCap(offer({ remainingOrders: undefined }))).toBe(false);
  });

  it('is true when either half says the cap is reached', () => {
    expect(offerHasReachedCap(offer({ remainingOrders: 5, isSoldOut: true }))).toBe(true);
    expect(offerHasReachedCap(offer({ remainingOrders: 0, isSoldOut: false }))).toBe(true);
  });
});
