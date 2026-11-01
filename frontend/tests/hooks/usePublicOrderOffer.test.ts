/**
 * Tests for usePublicOrderOffer.
 *
 * The public client runs `fetchPolicy: 'no-cache'` with `errorPolicy: 'all'`, so
 * a failed refetch hands the hook no data at all. Before the retention below the
 * page read that as a dead link: a network blip during the 15-minute QR-expiry
 * refetch swapped the form for the unavailable screen and threw away everything
 * the buyer had typed. These cases pin that the last good offer survives a
 * failed refetch of the *same* link, and that a different link never inherits
 * it — a stale offer from another campaign would show the wrong seller, prices,
 * and payment methods.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { usePublicOrderOffer } from '../../src/hooks/usePublicOrderOffer';
import type { GqlPublicGetOrderOfferQuery } from '../../src/types/graphql-generated';

const { useQueryMock } = vi.hoisted(() => ({ useQueryMock: vi.fn() }));

vi.mock('@apollo/client/react', () => ({ useQuery: useQueryMock }));

const CAMPAIGN = 'CAMPAIGN#c1';
const TOKEN = 'tok-1';

const offerFor = (sellerName: string): GqlPublicGetOrderOfferQuery['publicGetOrderOffer'] => ({
  __typename: 'PublicOrderOffer',
  sellerName,
  campaignId: CAMPAIGN,
  campaignName: 'Spring Sale',
  products: [{ __typename: 'PublicProduct', productId: 'PROD#1', productName: 'Cookie Box', price: 10 }],
  paymentMethods: [{ __typename: 'PublicPaymentMethod', name: 'Venmo', qrCodeUrl: null }],
});

/** Drives the hook the way Apollo would across a mount and a refetch. */
const setQuery = (state: {
  data?: GqlPublicGetOrderOfferQuery;
  loading?: boolean;
  error?: unknown;
}) => {
  useQueryMock.mockReturnValue({ loading: false, error: undefined, refetch: vi.fn(), ...state });
};

const renderOffer = (campaignId = CAMPAIGN, token = TOKEN) =>
  renderHook(({ cid, tok }) => usePublicOrderOffer(cid, tok), {
    initialProps: { cid: campaignId, tok: token },
  });

describe('usePublicOrderOffer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns the offer a successful read carried', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Acme Troop') } });
    const { result } = renderOffer();
    expect(result.current.offer?.sellerName).toBe('Acme Troop');
    expect(result.current.error).toBeUndefined();
  });

  it('passes the campaign and token through as query variables', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Acme Troop') } });
    renderOffer();
    const options = useQueryMock.mock.calls[0][1] as { variables: Record<string, string> };
    expect(options.variables).toEqual({ campaignId: CAMPAIGN, token: TOKEN });
  });

  it('skips the query when the link is incomplete', () => {
    setQuery({ loading: false });
    renderOffer('', '');
    const options = useQueryMock.mock.calls[0][1] as { skip: boolean };
    expect(options.skip).toBe(true);
  });

  it('reports loading while the first read is in flight', () => {
    useQueryMock.mockReturnValue({ loading: true, error: undefined, refetch: vi.fn() });
    const { result } = renderOffer();
    expect(result.current.offer).toBeNull();
    expect(result.current.loading).toBe(true);
  });
});

describe('usePublicOrderOffer retention across a failed refetch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('keeps the last good offer when a refetch fails', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Acme Troop') } });
    const hook = renderOffer();
    expect(hook.result.current.offer?.sellerName).toBe('Acme Troop');

    // The way Apollo reports a failed no-cache refetch: no data, error set.
    setQuery({ data: undefined, error: new Error('Network request failed') });
    hook.rerender({ cid: CAMPAIGN, tok: TOKEN });

    expect(hook.result.current.offer?.sellerName).toBe('Acme Troop');
    expect(hook.result.current.error).toBeTruthy();
  });

  it('keeps the offer across a refetch that returns an error with no data at all', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Acme Troop') } });
    const hook = renderOffer();
    setQuery({});
    hook.rerender({ cid: CAMPAIGN, tok: TOKEN });
    expect(hook.result.current.offer?.sellerName).toBe('Acme Troop');
  });

  it('takes the newer offer once a later refetch succeeds', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Old Seller') } });
    const hook = renderOffer();
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('New Seller') } });
    hook.rerender({ cid: CAMPAIGN, tok: TOKEN });
    expect(hook.result.current.offer?.sellerName).toBe('New Seller');
  });

  it('does not hand a retained offer to a different link', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Acme Troop') } });
    const hook = renderOffer();
    setQuery({ data: undefined, error: new Error('gone') });
    hook.rerender({ cid: 'CAMPAIGN#c2', tok: 'tok-2' });
    expect(hook.result.current.offer).toBeNull();
  });

  it('does not hand a retained offer to the same campaign under a rotated token', () => {
    setQuery({ data: { __typename: 'Query', publicGetOrderOffer: offerFor('Acme Troop') } });
    const hook = renderOffer();
    setQuery({ data: undefined, error: new Error('rotated') });
    hook.rerender({ cid: CAMPAIGN, tok: 'tok-rotated' });
    expect(hook.result.current.offer).toBeNull();
  });

  it('stays null when the very first read fails', () => {
    setQuery({ data: undefined, error: new Error('Network request failed') });
    const { result } = renderOffer();
    expect(result.current.offer).toBeNull();
    expect(result.current.error).toBeTruthy();
  });
});
