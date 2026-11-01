/**
 * Loading the offer behind a public order share link.
 *
 * This query opts into `no-cache` (the public client default is cache-first,
 * so that the immutable receipt read can be cached): the pre-signed QR URLs
 * inside the offer expire after 15 minutes, and a stale offer would hand the
 * buyer images that 403.
 *
 * The same `no-cache` (plus the public client's `errorPolicy: 'all'`) means a
 * *failed* refetch hands back no data at all. The buyer would then be swapped
 * from the form to the "link unavailable" screen and lose everything they had
 * typed, on a link that is still perfectly good — a network blip is not a
 * revoked link. So the last good offer is retained across refetch failures and
 * handed back while the page shows its refresh warning; a different campaign or
 * token (a different link) never inherits it.
 */

import { useEffect, useState } from 'react';
import { useQuery } from '@apollo/client/react';
import { PUBLIC_GET_ORDER_OFFER } from '../lib/publicOrderGraphQL';
import type { PublicOfferView } from '../components/public/publicOrderTypes';
import type { GqlPublicGetOrderOfferQuery, GqlPublicGetOrderOfferQueryVariables } from '../types/graphql-generated';

/** The retained offer is keyed by the link it belongs to. */
interface RetainedOffer {
  linkKey: string;
  offer: PublicOfferView;
}

/**
 * The retained offer for this exact link, or null. A different campaign or a
 * rotated token must never inherit another link's seller, prices, or methods.
 */
function retainedOfferFor(retained: RetainedOffer | null, linkKey: string): PublicOfferView | null {
  if (retained && retained.linkKey === linkKey) {
    return retained.offer;
  }
  return null;
}

export function usePublicOrderOffer(campaignId: string, token: string) {
  const { data, loading, error, refetch } = useQuery<GqlPublicGetOrderOfferQuery, GqlPublicGetOrderOfferQueryVariables>(
    PUBLIC_GET_ORDER_OFFER,
    { variables: { campaignId, token }, skip: !campaignId || !token, fetchPolicy: 'no-cache' },
  );

  const freshOffer = (data?.publicGetOrderOffer ?? null) as PublicOfferView | null;
  const [retained, setRetained] = useState<RetainedOffer | null>(null);
  const linkKey = `${campaignId}|${token}`;

  useEffect(() => {
    if (freshOffer) {
      setRetained({ linkKey, offer: freshOffer });
    }
  }, [freshOffer, linkKey]);

  const offer = freshOffer ?? retainedOfferFor(retained, linkKey);

  return { offer, loading, error, refetch };
}
