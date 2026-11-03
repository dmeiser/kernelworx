import { describe, it, expect, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

vi.mock('react-router-dom', () => ({
  useLocation: () => ({ state: null }),
}));

import { useCreateCampaignFormState } from '../../src/hooks/useCreateCampaignFormState';

describe('useCreateCampaignFormState', () => {
  it('returns initial values', () => {
    const { result } = renderHook(() => useCreateCampaignFormState());

    expect(result.current.profileId).toBe('');
    expect(result.current.campaignName).toBe('');
    expect(result.current.catalogId).toBe('');
    expect(result.current.submitting).toBe(false);
    expect(result.current.unitSectionExpanded).toBe(false);
    expect(result.current.toastMessage).toBeNull();
    expect(result.current.shareWithCreator).toBe(true);
  });

  it('setUnitSectionExpanded updates unitSectionExpanded', () => {
    const { result } = renderHook(() => useCreateCampaignFormState());

    act(() => {
      result.current.setUnitSectionExpanded(true);
    });

    expect(result.current.unitSectionExpanded).toBe(true);
  });

  it('setSubmitting updates submitting', () => {
    const { result } = renderHook(() => useCreateCampaignFormState());

    act(() => {
      result.current.setSubmitting(true);
    });

    expect(result.current.submitting).toBe(true);
  });

  it('setToastMessage updates toastMessage', () => {
    const { result } = renderHook(() => useCreateCampaignFormState());
    const message = { message: 'Campaign created!', severity: 'success' as const };

    act(() => {
      result.current.setToastMessage(message);
    });

    expect(result.current.toastMessage).toEqual(message);
  });

  it('setToastMessage can be cleared with null', () => {
    const { result } = renderHook(() => useCreateCampaignFormState());

    act(() => {
      result.current.setToastMessage({ message: 'test', severity: 'error' });
    });
    act(() => {
      result.current.setToastMessage(null);
    });

    expect(result.current.toastMessage).toBeNull();
  });

  it('preserves object identity across rerenders when values do not change', () => {
    const { result, rerender } = renderHook(() => useCreateCampaignFormState());
    const initialReference = result.current;

    rerender();

    expect(result.current).toBe(initialReference);
  });

  it('updates object identity when a field value changes', () => {
    const { result } = renderHook(() => useCreateCampaignFormState());
    const initialReference = result.current;

    act(() => {
      result.current.setCampaignName('Fall Fundraiser');
    });

    expect(result.current).not.toBe(initialReference);
    expect(result.current.campaignName).toBe('Fall Fundraiser');
  });
});
