/**
 * Custom hook for managing shared campaign state and queries
 */
import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_SHARED_CAMPAIGN, LIST_MY_PROFILES } from '../lib/graphql';

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  };
  campaignName: string;
  campaignYear: number;
  startDate: string | null;
  endDate: string | null;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage: string;
  description: string | null;
  isActive: boolean;
}

interface SellerProfile {
  profileId: string;
  sellerName: string;
  isOwner: boolean;
  permissions: string[];
}

export const useSharedCampaignAndProfiles = (effectiveSharedCampaignCode: string | undefined) => {
  const {
    data: sharedCampaignData,
    loading: sharedCampaignLoading,
    error: sharedCampaignError,
  } = useQuery<{ getSharedCampaign: SharedCampaign | null }>(GET_SHARED_CAMPAIGN, {
    variables: { sharedCampaignCode: effectiveSharedCampaignCode },
    skip: !effectiveSharedCampaignCode,
  });

  const {
    data: profilesData,
    loading: profilesLoading,
    refetch: refetchProfiles,
  } = useQuery<{
    listMyProfiles: SellerProfile[];
  }>(LIST_MY_PROFILES);

  const sharedCampaign = useMemo(() => sharedCampaignData?.getSharedCampaign ?? null, [sharedCampaignData]);

  const profiles = useMemo(() => profilesData?.listMyProfiles ?? [], [profilesData]);

  const isSharedCampaignMode = useMemo(
    () => Boolean(effectiveSharedCampaignCode && sharedCampaign?.isActive),
    [effectiveSharedCampaignCode, sharedCampaign],
  );

  return {
    sharedCampaign,
    sharedCampaignLoading,
    sharedCampaignError,
    profiles,
    profilesLoading,
    refetchProfiles,
    isSharedCampaignMode,
  };
};
