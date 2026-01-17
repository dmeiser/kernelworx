/**
 * Custom hook for managing form state in CreateCampaignPage
 * Uses the same pattern as CreateSharedCampaignDialog with useFormState + memoized setters
 */
import { useMemo } from 'react';
import { useLocation } from 'react-router-dom';
import { useFormState } from './useFormState';

export interface FormStateValues {
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
  unitSectionExpanded: boolean;
  submitting: boolean;
  toastMessage: {
    message: string;
    severity: 'success' | 'error';
  } | null;
}

interface FormSetters {
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
  setUnitSectionExpanded: (expanded: boolean) => void;
  setSubmitting: (submitting: boolean) => void;
  setToastMessage: (message: { message: string; severity: 'success' | 'error' } | null) => void;
  reset: () => void;
}

export type FormState = FormStateValues & FormSetters;

export const useCreateCampaignFormState = () => {
  const location = useLocation();
  const preselectedCatalogId = (location.state as { catalogId?: string })?.catalogId;

  const initialFormState: FormStateValues = useMemo(
    () => ({
      profileId: '',
      campaignName: '',
      campaignYear: new Date().getFullYear(),
      catalogId: preselectedCatalogId || '',
      startDate: '',
      endDate: '',
      unitType: '',
      unitNumber: '',
      city: '',
      state: '',
      shareWithCreator: true,
      unitSectionExpanded: false,
      submitting: false,
      toastMessage: null,
    }),
    [preselectedCatalogId],
  );

  const { values, setValue, reset: resetValues } = useFormState<FormStateValues>({
    initialValues: initialFormState,
  });

  const formSetters: FormSetters = useMemo(
    () => ({
      setProfileId: (v: string) => setValue('profileId', v),
      setCampaignName: (v: string) => setValue('campaignName', v),
      setCampaignYear: (v: number) => setValue('campaignYear', v),
      setCatalogId: (v: string) => setValue('catalogId', v),
      setStartDate: (v: string) => setValue('startDate', v),
      setEndDate: (v: string) => setValue('endDate', v),
      setUnitType: (v: string) => setValue('unitType', v),
      setUnitNumber: (v: string) => setValue('unitNumber', v),
      setCity: (v: string) => setValue('city', v),
      setState: (v: string) => setValue('state', v),
      setShareWithCreator: (v: boolean) => setValue('shareWithCreator', v),
      setUnitSectionExpanded: (v: boolean) => setValue('unitSectionExpanded', v),
      setSubmitting: (v: boolean) => setValue('submitting', v),
      setToastMessage: (v: { message: string; severity: 'success' | 'error' } | null) =>
        setValue('toastMessage', v),
      reset: resetValues,
    }),
    [setValue, resetValues],
  );

  return {
    ...values,
    ...formSetters,
  };
};
