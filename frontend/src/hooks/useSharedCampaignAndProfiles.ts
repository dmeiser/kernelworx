/**
 * Custom hook for managing shared campaign state and queries
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useApolloClient, useQuery } from '@apollo/client/react';
import { GET_SHARED_CAMPAIGN } from '../lib/graphql';
import { fetchAllMyProfiles, type MyProfile } from '../lib/myProfiles';

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  } | null;
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
  createdByAccountId: string;
  creatorMessage: string;
  description: string | null;
  isActive: boolean;
}

export const useSharedCampaignAndProfiles = (effectiveSharedCampaignCode: string | undefined) => {
  const apolloClient = useApolloClient();
  const {
    data: sharedCampaignData,
    loading: sharedCampaignLoading,
    error: sharedCampaignError,
  } = useQuery<{ getSharedCampaign: SharedCampaign | null }>(GET_SHARED_CAMPAIGN, {
    variables: { sharedCampaignCode: effectiveSharedCampaignCode },
    skip: !effectiveSharedCampaignCode,
  });

  // listMyProfiles is server-side paginated (capped pages, #328), so walk all
  // nextToken pages instead of relying on a single useQuery response.
  const [profiles, setProfiles] = useState<MyProfile[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(true);
  const [profilesError, setProfilesError] = useState<Error | null>(null);

  const loadProfiles = useCallback(async () => {
    setProfilesLoading(true);
    try {
      setProfiles(await fetchAllMyProfiles(apolloClient));
      setProfilesError(null);
    } catch (err) {
      setProfilesError(err as Error);
    } finally {
      setProfilesLoading(false);
    }
  }, [apolloClient]);

  useEffect(() => {
    void loadProfiles();
  }, [loadProfiles]);

  const refetchProfiles = useCallback(() => loadProfiles(), [loadProfiles]);

  const sharedCampaign = useMemo(() => sharedCampaignData?.getSharedCampaign ?? null, [sharedCampaignData]);

  const isSharedCampaignMode = useMemo(
    () => Boolean(effectiveSharedCampaignCode && sharedCampaign?.isActive && sharedCampaign?.catalog),
    [effectiveSharedCampaignCode, sharedCampaign],
  );

  return {
    sharedCampaign,
    sharedCampaignLoading,
    sharedCampaignError,
    profiles,
    profilesLoading,
    profilesError,
    refetchProfiles,
    isSharedCampaignMode,
  };
};
