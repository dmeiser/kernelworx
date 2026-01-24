import { describe, it, expect } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useCreateCampaignValidation } from '../../src/hooks/useCreateCampaignValidation';

describe('useCreateCampaignValidation', () => {
  describe('validateProfileSelection', () => {
    it('returns invalid when profileId is empty', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('', 'Campaign', 'catalog-1', false, '', '', '', ''),
      );

      const validation = result.current.validateProfileSelection();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('Please select a profile');
    });

    it('returns valid when profileId is provided', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', ''),
      );

      const validation = result.current.validateProfileSelection();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });
  });

  describe('validateUnitFields', () => {
    it('returns valid in shared campaign mode regardless of unit fields', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', true, 'Pack', '', '', ''),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });

    it('returns valid when no unit type is specified', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', ''),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });

    it('returns invalid when unit type is set but other fields are missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, 'Pack', '', '', ''),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('When specifying a unit, all fields (unit number, city, state) are required');
    });

    it('returns invalid when unit type is set but city is missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, 'Pack', '123', '', 'TX'),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(false);
      expect(validation.error).toBe('When specifying a unit, all fields (unit number, city, state) are required');
    });

    it('returns valid when all unit fields are provided', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, 'Pack', '123', 'Austin', 'TX'),
      );

      const validation = result.current.validateUnitFields();
      expect(validation.isValid).toBe(true);
      expect(validation.error).toBeNull();
    });
  });

  describe('isFormValid', () => {
    it('returns true in shared campaign mode when profileId is set', () => {
      const { result } = renderHook(() => useCreateCampaignValidation('profile-1', '', '', true, '', '', '', ''));

      expect(result.current.isFormValid).toBe(true);
    });

    it('returns false in shared campaign mode when profileId is empty', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('', 'Campaign', 'catalog-1', true, '', '', '', ''),
      );

      expect(result.current.isFormValid).toBe(false);
    });

    it('returns true in manual mode when profileId, campaignName, and catalogId are set', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', 'catalog-1', false, '', '', '', ''),
      );

      expect(result.current.isFormValid).toBe(true);
    });

    it('returns false in manual mode when campaignName is missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', '', 'catalog-1', false, '', '', '', ''),
      );

      expect(result.current.isFormValid).toBe(false);
    });

    it('returns false in manual mode when catalogId is missing', () => {
      const { result } = renderHook(() =>
        useCreateCampaignValidation('profile-1', 'Campaign', '', false, '', '', '', ''),
      );

      expect(result.current.isFormValid).toBe(false);
    });
  });
});
