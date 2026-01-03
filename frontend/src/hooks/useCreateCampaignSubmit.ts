/**
 * Custom hook for campaign creation submission
 */
import { useCallback } from 'react';
import { useMutation } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import { CREATE_CAMPAIGN, LIST_MY_PROFILES, LIST_CAMPAIGNS_BY_PROFILE } from '../lib/graphql';
import { ensureProfileId, ensureCatalogId, toUrlId } from '../lib/ids';

interface CreateCampaignInput {
  profileId: string;
  sharedCampaignCode?: string;
  campaignName?: string;
  campaignYear?: number;
  catalogId?: string | null;
  unitType?: string;
  unitNumber?: number;
  city?: string;
  state?: string;
  startDate?: string;
  endDate?: string;
  shareWithCreator?: boolean;
}

interface SubmitHandlerParams {
  profileId: string;
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  startDate: string;
  endDate: string;
  isSharedCampaignMode: boolean;
  effectiveSharedCampaignCode: string | undefined;
  shareWithCreator: boolean;
  sharedCampaignCreatedByName: string | undefined;
  onSuccess: (message: string) => void;
  onError: (message: string) => void;
}

export const useCreateCampaignSubmit = () => {
  const navigate = useNavigate();
  const [createCampaign] = useMutation<{
    createCampaign: {
      campaignId: string;
      campaignName: string;
      campaignYear: number;
    };
  }>(CREATE_CAMPAIGN, {
    refetchQueries: [{ query: LIST_MY_PROFILES }],
  });

  const buildManualInput = (
    base: CreateCampaignInput,
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    unitType: string,
    unitNumber: string,
    city: string,
    state: string,
  ): CreateCampaignInput => {
    const input = {
      ...base,
      campaignName,
      campaignYear,
      catalogId: ensureCatalogId(catalogId),
    };
    if (unitType && unitNumber && city && state) {
      input.unitType = unitType;
      input.unitNumber = parseInt(unitNumber, 10);
      input.city = city;
      input.state = state;
    }
    return input;
  };

  const buildSharedInput = (
    base: CreateCampaignInput,
    effectiveSharedCampaignCode: string | undefined,
    shareWithCreator: boolean,
  ): CreateCampaignInput => {
    if (!effectiveSharedCampaignCode) return base;
    return {
      ...base,
      sharedCampaignCode: effectiveSharedCampaignCode,
      shareWithCreator,
    };
  };

  const buildCreateInput = useCallback(
    (
      profileId: string,
      campaignName: string,
      campaignYear: number,
      catalogId: string,
      unitType: string,
      unitNumber: string,
      city: string,
      state: string,
      startDate: string,
      endDate: string,
      isSharedCampaignMode: boolean,
      effectiveSharedCampaignCode: string | undefined,
      shareWithCreator: boolean,
    ): CreateCampaignInput => {
      const base: CreateCampaignInput = {
        profileId,
        startDate: startDate ? new Date(startDate).toISOString() : undefined,
        endDate: endDate ? new Date(endDate).toISOString() : undefined,
      };

      return isSharedCampaignMode
        ? buildSharedInput(base, effectiveSharedCampaignCode, shareWithCreator)
        : buildManualInput(base, campaignName, campaignYear, catalogId, unitType, unitNumber, city, state);
    },
    [],
  );

  const handleSubmit = useCallback(
    async (params: SubmitHandlerParams): Promise<void> => {
      const {
        profileId,
        campaignName,
        campaignYear,
        catalogId,
        unitType,
        unitNumber,
        city,
        state,
        startDate,
        endDate,
        isSharedCampaignMode,
        effectiveSharedCampaignCode,
        shareWithCreator,
        sharedCampaignCreatedByName,
        onSuccess,
        onError,
      } = params;

      const getSuccessMessage = () => {
        if (isSharedCampaignMode && shareWithCreator && sharedCampaignCreatedByName) {
          return `Campaign created and shared with ${sharedCampaignCreatedByName}!`;
        }
        return 'Campaign created successfully!';
      };

      const refetchQueries = [
        { query: LIST_MY_PROFILES },
        {
          query: LIST_CAMPAIGNS_BY_PROFILE,
          variables: { profileId: ensureProfileId(profileId) },
        },
      ];

      try {
        const input = buildCreateInput(
          profileId,
          campaignName,
          campaignYear,
          catalogId,
          unitType,
          unitNumber,
          city,
          state,
          startDate,
          endDate,
          isSharedCampaignMode,
          effectiveSharedCampaignCode,
          shareWithCreator,
        );

        const { data } = await createCampaign({
          variables: { input },
          refetchQueries,
        });

        const createdCampaign = data?.createCampaign;
        if (createdCampaign) {
          onSuccess(getSuccessMessage());
          navigate(`/scouts/${toUrlId(profileId)}/campaigns/${toUrlId(createdCampaign.campaignId)}`);
        }
      } catch (error) {
        console.error('Failed to create campaign:', error);
        onError('Failed to create campaign. Please try again.');
      }
    },
    [createCampaign, navigate, buildCreateInput],
  );

  return { handleSubmit };
};
