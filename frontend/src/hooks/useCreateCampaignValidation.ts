/**
 * Custom hook for form validation logic
 */
import { useCallback } from "react";

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
) => {
  const validateProfileSelection = useCallback((): ValidationResult => {
    if (!profileId) {
      return {
        isValid: false,
        error: "Please select a profile",
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
        error:
          "When specifying a unit, all fields (unit number, city, state) are required",
      };
    }

    return { isValid: true, error: null };
  }, [isSharedCampaignMode, unitType, unitNumber, city, state]);

  const isFormValid = isSharedCampaignMode
    ? !!profileId
    : !!profileId && !!campaignName && !!catalogId;

  return {
    isFormValid,
    validateProfileSelection,
    validateUnitFields,
  };
};
