/**
 * Custom hook for form validation logic
 */
import { useCallback } from 'react';
import { CAMPAIGN_YEAR_MAX, CAMPAIGN_YEAR_MIN, isCampaignYearInRange } from '../constants/campaign';

interface ValidationResult {
  isValid: boolean;
  error: string | null;
}

export const useCreateCampaignValidation = (
  profileId: string,
  campaignName: string,
  catalogId: string,
  isSharedCampaignMode: boolean,
  unitType: string,
  unitNumber: string,
  city: string,
  state: string,
  campaignYear: number,
) => {
  const validateProfileSelection = useCallback((): ValidationResult => {
    if (!profileId) {
      return {
        isValid: false,
        error: 'Please select a profile',
      };
    }
    return { isValid: true, error: null };
  }, [profileId]);

  const validateUnitFields = useCallback((): ValidationResult => {
    if (isSharedCampaignMode || !unitType) {
      return { isValid: true, error: null };
    }

    const hasAllUnitDetails = [unitNumber, city, state].every(Boolean);
    if (!hasAllUnitDetails) {
      return {
        isValid: false,
        error: 'When specifying a unit, all fields (unit number, city, state) are required',
      };
    }

    return { isValid: true, error: null };
  }, [isSharedCampaignMode, unitType, unitNumber, city, state]);

  // The year is range-checked at submit (like the unit fields) rather than in
  // `isFormValid`, so the user gets the reason the campaign cannot be created.
  // In shared-campaign mode the year is copied from the campaign being joined
  // rather than chosen here, so it is not range-checked at all.
  const validateCampaignYear = useCallback((): ValidationResult => {
    if (isSharedCampaignMode || isCampaignYearInRange(campaignYear)) {
      return { isValid: true, error: null };
    }
    return {
      isValid: false,
      error: `Campaign year must be between ${CAMPAIGN_YEAR_MIN} and ${CAMPAIGN_YEAR_MAX}`,
    };
  }, [isSharedCampaignMode, campaignYear]);

  const isFormValid = isSharedCampaignMode ? !!profileId : !!profileId && !!campaignName && !!catalogId;

  return {
    isFormValid,
    validateProfileSelection,
    validateUnitFields,
    validateCampaignYear,
  };
};
