/**
 * Hook that initializes all the queries for CreateCampaignPage
 */
import { useCreateCampaignFormState } from './useCreateCampaignFormState';
import { useSharedCampaignAndProfiles } from './useSharedCampaignAndProfiles';
import { useCatalogsData } from './useCatalogsData';
import { useProfileEffects } from './useProfileEffects';
import { useProfileRefetch } from './useProfileRefetch';
import { useSharedCampaignFormInit } from './useSharedCampaignFormInit';
import { useCreateCampaignSubmitHandler } from './useCreateCampaignSubmitHandler';
import { useNavigate } from 'react-router-dom';

export const useCreateCampaignPageSetup = (effectiveSharedCampaignCode: string | undefined) => {
  const navigate = useNavigate();
  const formState = useCreateCampaignFormState();

  // Use custom hooks for shared campaign and profiles
  const {
    sharedCampaign,
    sharedCampaignLoading,
    sharedCampaignError,
    profiles,
    profilesLoading,
    refetchProfiles,
    isSharedCampaignMode,
  } = useSharedCampaignAndProfiles(effectiveSharedCampaignCode);

  // Use custom hooks for catalogs
  const { filteredPublicCatalogs, filteredMyCatalogs, catalogsLoading } = useCatalogsData(isSharedCampaignMode);

  // Profile effects
  useProfileEffects(
    formState.profileId,
    formState.setProfileId,
    profiles,
    profilesLoading,
    isSharedCampaignMode,
    effectiveSharedCampaignCode,
    navigate,
  );

  // Profile refetch effect
  useProfileRefetch(() => {
    void refetchProfiles();
  });

  // Shared campaign form initialization
  useSharedCampaignFormInit(
    sharedCampaign,
    formState.setCampaignName,
    formState.setCampaignYear,
    formState.setCatalogId,
    formState.setStartDate,
    formState.setEndDate,
    formState.setUnitType,
    formState.setUnitNumber,
    formState.setCity,
    formState.setState,
  );

  // Submit handler
  const { handleSubmit, isFormValid } = useCreateCampaignSubmitHandler(formState, isSharedCampaignMode);

  return {
    formState,
    sharedCampaign,
    sharedCampaignLoading,
    sharedCampaignError,
    profiles,
    profilesLoading,
    isSharedCampaignMode,
    filteredPublicCatalogs,
    filteredMyCatalogs,
    catalogsLoading,
    handleSubmit,
    isFormValid,
    navigate,
    effectiveSharedCampaignCode,
  };
};
