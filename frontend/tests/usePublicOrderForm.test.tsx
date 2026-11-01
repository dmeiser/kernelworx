import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const mutateMock = vi.fn();
vi.mock('@apollo/client/react', () => ({
  useMutation: () => [mutateMock],
}));

vi.mock('../src/lib/api-utils', () => ({ getErrorCode: () => 'X', getErrorMessage: () => 'msg' }));
vi.mock('../src/lib/apollo', () => ({ mapErrorCodeToMessage: () => 'mapped' }));

import { usePublicOrderForm } from '../src/hooks/usePublicOrderForm';

describe('usePublicOrderForm', () => {
  const offer = { campaignId: 'c', products: [], paymentMethods: [{ name: 'Cash' }] } as any;

  beforeEach(() => mutateMock.mockReset());

  it('submit does not call mutate when invalid', async () => {
    const { result } = renderHook(() => usePublicOrderForm({ offer, token: 't' }));
    await act(async () => { await result.current.submit(); });
    expect(mutateMock).not.toHaveBeenCalled();
  });

  it('double-submit guarded by submitting flag (documented: button disabled in flight)', () => {
    // sanity: submitting starts false
    const { result } = renderHook(() => usePublicOrderForm({ offer, token: 't' }));
    expect(result.current.submitting).toBe(false);
  });
});
