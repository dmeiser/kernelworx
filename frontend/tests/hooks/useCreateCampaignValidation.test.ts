import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useCreateCampaignValidation } from '../../src/hooks/useCreateCampaignValidation';

describe('useCreateCampaignValidation', () => {
  describe('validateProfileSelection', () => {
    it('returns invalid when profileId is empty', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('', 'Campaign', 'catalog-1', false, '', '', '', '', 2026),
      );

      const validation = result.current.validateProfileSelection();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('Please select a profile');
    });

    it('returns valid when profileId is provided', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2026),
      );

      const validation = result.current.validateProfileSelection();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });
  });

  describe('validateUnitFields', () => {
    it('returns valid in shared campaign mode regardless of unit fields', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', true, 'Pack', '', '', '', 2026),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });

    it('returns valid when no unit type is specified', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2026),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });

    it('returns invalid when unit type is set but other fields are missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, 'Pack', '', '', '', 2026),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('When specifying a unit, all fields (unit number, city, state) are required');
    });

    it('returns invalid when unit type is set but city is missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, 'Pack', '123', '', 'TX', 2026),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('When specifying a unit, all fields (unit number, city, state) are required');
    });

    it('returns valid when all unit fields are provided', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, 'Pack', '123', 'Austin', 'TX', 2026),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });
  });

  describe('isFormValid', () => {
    it('returns true in shared campaign mode when profileId is set', () => {
      const { result } = renderHook(() => useCreateCampaignValidation('profile-1', '', '', true, '', '', '', '', 2026));

      expect(result.current.isFormValid).toBe(true);
    });

    it('returns false in shared campaign mode when profileId is empty', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('', 'Campaign', 'catalog-1', true, '', '', '', '', 2026),
      );

      expect(result.current.isFormValid).toBe(false);
    });

    it('returns true in manual mode when profileId, campaignName, and catalogId are set', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2026),
      );

      expect(result.current.isFormValid).toBe(true);
    });

    it('returns false in manual mode when campaignName is missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', '', 'catalog-1', false, '', '', '', '', 2026),
      );

      expect(result.current.isFormValid).toBe(false);
    });

    it('returns false in manual mode when catalogId is missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', '', false, '', '', '', '', 2026),
      );

      expect(result.current.isFormValid).toBe(false);
    });
  });

  describe('validateCampaignYear', () => {
    it('accepts the upper bound of the range', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2050),
      );

      const validation = result.current.validateCampaignYear();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });

    it('rejects a year past the upper bound and names the range', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2051),
      );

      const validation = result.current.validateCampaignYear();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('Campaign year must be between 2020 and 2050');
    });

    it('rejects a year before the lower bound', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2019),
      );

      expect(result.current.validateCampaignYear().isValid).toBe(false);
    });

    it('rejects a year that is not a whole number', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', Number.NaN),
      );

      expect(result.current.validateCampaignYear().isValid).toBe(false);
    });

    it('does not range-check the year in shared campaign mode, where it is copied from the campaign', () => {
      const { result } = renderHook(() => useCreateCampaignValidation('profile-1', '', '', true, '', '', '', '', 2051));

      expect(result.current.validateCampaignYear().isValid).toBe(true);
    });

    it('reports an out-of-range year through validateCampaignYear rather than isFormValid', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', '', 2099),
      );

      expect(result.current.isFormValid).toBe(true);
      expect(result.current.validateCampaignYear().isValid).toBe(false);
    });
  });
});
