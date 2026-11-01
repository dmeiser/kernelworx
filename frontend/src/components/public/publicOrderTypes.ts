/**
 * View shapes shared by the public order page's components.
 *
 * They are derived from the generated operation type for `PublicGetOrderOffer`
 * rather than hand-copied from the schema: a hand-written copy drifts the moment
 * the schema or the query document gains a field, and the page passes query
 * results straight into these components. What stays hand-written is only what
 * the generated type cannot carry — the order-cap fields below, which the offer
 * resolver is still gaining and which an older read simply omits.
 */

import type { GqlPublicGetOrderOfferQuery } from '../../types/graphql-generated';

type GeneratedOffer = GqlPublicGetOrderOfferQuery['publicGetOrderOffer'];

/** A catalog product as the buyer sees it. */
export type PublicProductView = GeneratedOffer['products'][number];

/** One of the seller's allowlisted payment methods. */
export type PublicPaymentMethodView = GeneratedOffer['paymentMethods'][number];

export interface PublicOfferView extends GeneratedOffer {
  /**
   * Orders still available under the campaign's public-order cap, or null when
   * the seller set no cap. Absent on an offer read predating the field.
   */
  remainingOrders?: number | null;
  /** Whether the campaign has reached that cap. Absent on older reads. */
  isSoldOut?: boolean | null;
}

/**
 * Whether the offer's order-cap fields close this link.
 *
 * Both fields are additive and nullable, so a read that predates them carries
 * neither and must stay orderable: only an explicit `isSoldOut: true` or a
 * `remainingOrders` of exactly 0 counts. A missing field is never read as 0.
 */
export function offerHasReachedCap(offer: PublicOfferView): boolean {
  return offer.isSoldOut === true || offer.remainingOrders === 0;
}
