/**
 * Hook that initializes all the queries for CreateCampaignPage
 */
import { useQuery } from '@apollo/client/react';
import { useMemo } from 'react';
import { GET_SHARED_CAMPAIGN } from '../lib/graphql';
import { useCreateCampaignFormState } from './useCreateCampaignFormState';
import { useSharedCampaignAndProfiles } from './useSharedCampaignAndProfiles';
import { useCatalogsData } from './useCatalogsData';
import { useProfileEffects } from './useProfileEffects';
import { useProfileRefetch } from './useProfileRefetch';
import { useSharedCampaignFormInit } from './useSharedCampaignFormInit';
import { useSharedCampaignDiscovery } from './useSharedCampaignDiscovery';
import { useSharedCampaignDiscoveryTrigger } from './useSharedCampaignDiscoveryTrigger';
import { useCreateCampaignSubmitHandler } from './useCreateCampaignSubmitHandler';
import { useNavigate } from 'react-router-dom';
import type { SharedCampaign } from '../types/entities';

export const useCreateCampaignPageSetup = (effectiveSharedCampaignCode: string | undefined) => {
  const navigate = useNavigate();
  const rawFormState = useCreateCampaignFormState();

  // Memoize formState to prevent object reference from changing on every render
  // This is critical for child components like CatalogSelection which rely on callback stability
  const formState = useMemo(() => rawFormState, [rawFormState]);

  // Query shared campaign
  const {
    data: sharedCampaignData,
    loading: sharedCampaignLoading,
    error: sharedCampaignError,
  } = useQuery<{ getSharedCampaign: SharedCampaign | null }>(GET_SHARED_CAMPAIGN, {
    variables: { sharedCampaignCode: effectiveSharedCampaignCode },
    skip: !effectiveSharedCampaignCode,
  });

  const sharedCampaign = sharedCampaignData?.getSharedCampaign;

  // Use custom hooks for shared campaign and profiles
  const { profiles, profilesLoading, refetchProfiles, isSharedCampaignMode } =
    useSharedCampaignAndProfiles(effectiveSharedCampaignCode);

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
  useProfileRefetch(refetchProfiles);

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

  // Shared campaign discovery
  const { discoveredSharedCampaigns, debouncedFindSharedCampaigns } = useSharedCampaignDiscovery();

  // Trigger shared campaign discovery
  useSharedCampaignDiscoveryTrigger(
    isSharedCampaignMode,
    formState.unitType,
    formState.unitNumber,
    formState.city,
    formState.state,
    formState.campaignName,
    formState.campaignYear,
    debouncedFindSharedCampaigns,
  );

  // Submit handler
  const { handleSubmit, isFormValid } = useCreateCampaignSubmitHandler(formState);

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
    discoveredSharedCampaigns,
    handleSubmit,
    isFormValid,
    navigate,
    effectiveSharedCampaignCode,
  };
};
