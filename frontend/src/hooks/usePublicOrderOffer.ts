/**
 * Loading the offer behind a public order share link.
 *
 * `no-cache` on the public client means every mount re-reads the offer: the
 * pre-signed QR URLs inside it expire after 15 minutes, and a stale offer would
 * hand the buyer images that 403.
 */

import { useQuery } from '@apollo/client/react';
import { PUBLIC_GET_ORDER_OFFER } from '../lib/publicOrderGraphQL';
import type { PublicOfferView } from '../components/public/publicOrderTypes';
import type { GqlPublicGetOrderOfferQuery, GqlPublicGetOrderOfferQueryVariables } from '../types/graphql-generated';

export function usePublicOrderOffer(profileId: string, token: string) {
  const { data, loading, error, refetch } = useQuery<GqlPublicGetOrderOfferQuery, GqlPublicGetOrderOfferQueryVariables>(
    PUBLIC_GET_ORDER_OFFER,
    { variables: { profileId, token }, skip: !profileId || !token },
  );

  return { offer: (data?.publicGetOrderOffer ?? null) as PublicOfferView | null, loading, error, refetch };
}
