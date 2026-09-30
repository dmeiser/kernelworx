/**
 * Custom hook that combines all submission logic
 */
import { useCallback } from 'react';
import { useCreateCampaignSubmit } from './useCreateCampaignSubmit';
import { useCreateCampaignValidation } from './useCreateCampaignValidation';

interface FormState {
  profileId: string;
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  startDate: string;
  endDate: string;
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  shareWithCreator: boolean;
  submitting: boolean;
  toastMessage: {
    message: string;
    severity: 'success' | 'error';
  } | null;
  setProfileId: (id: string) => void;
  setCampaignName: (name: string) => void;
  setCampaignYear: (year: number) => void;
  setCatalogId: (id: string) => void;
  setStartDate: (date: string) => void;
  setEndDate: (date: string) => void;
  setUnitType: (type: string) => void;
  setUnitNumber: (number: string) => void;
  setCity: (city: string) => void;
  setState: (state: string) => void;
  setShareWithCreator: (share: boolean) => void;
  setSubmitting: (submitting: boolean) => void;
  setToastMessage: (
    message: {
      message: string;
      severity: 'success' | 'error';
    } | null,
  ) => void;
}

interface SubmitParams {
  isSharedCampaignMode: boolean;
  effectiveSharedCampaignCode: string | undefined;
  sharedCampaignCreatedByName: string | undefined;
}

export const useCreateCampaignSubmitHandler = (formState: FormState, isSharedCampaignMode: boolean = false) => {
  const { isFormValid, validateProfileSelection, validateUnitFields, validateCampaignYear } =
    useCreateCampaignValidation(
      formState.profileId,
      formState.campaignName,
      formState.catalogId,
      isSharedCampaignMode,
      formState.unitType,
      formState.unitNumber,
      formState.city,
      formState.state,
      formState.campaignYear,
    );

  const { handleSubmit: submitCampaign } = useCreateCampaignSubmit();

  const handleValidationError = useCallback(
    (error: string) => {
      formState.setToastMessage({
        message: error,
        severity: 'error',
      });
    },
    [formState],
  );

  /** The first validation failure, or null when the form may be submitted. */
  const firstValidationError = useCallback((): string | null => {
    for (const validate of [validateProfileSelection, validateUnitFields, validateCampaignYear]) {
      const result = validate();
      if (!result.isValid) {
        return result.error || 'Validation failed';
      }
    }
    return null;
  }, [validateProfileSelection, validateUnitFields, validateCampaignYear]);

  const handleSubmit = useCallback(
    async (params: SubmitParams) => {
      const validationError = firstValidationError();
      if (validationError) {
        handleValidationError(validationError);
        return;
      }

      formState.setSubmitting(true);
      try {
        await submitCampaign({
          profileId: formState.profileId,
          campaignName: formState.campaignName,
          campaignYear: formState.campaignYear,
          catalogId: formState.catalogId,
          unitType: formState.unitType,
          unitNumber: formState.unitNumber,
          city: formState.city,
          state: formState.state,
          startDate: formState.startDate,
          endDate: formState.endDate,
          isSharedCampaignMode: params.isSharedCampaignMode,
          effectiveSharedCampaignCode: params.effectiveSharedCampaignCode,
          shareWithCreator: formState.shareWithCreator,
          sharedCampaignCreatedByName: params.sharedCampaignCreatedByName,
          onSuccess: (message: string) => {
            formState.setToastMessage({
              message,
              severity: 'success',
            });
          },
          onError: (message: string) => {
            formState.setToastMessage({
              message,
              severity: 'error',
            });
          },
        });
      } finally {
        formState.setSubmitting(false);
      }
    },
    [firstValidationError, submitCampaign, formState, handleValidationError],
  );

  return { handleSubmit, isFormValid };
};
