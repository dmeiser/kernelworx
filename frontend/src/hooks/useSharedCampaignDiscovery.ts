/**
 * Custom hook for managing shared campaign discovery
 */
import { useCallback, useRef } from 'react';
import { useLazyQuery } from '@apollo/client/react';
import { FIND_SHARED_CAMPAIGNS } from '../lib/graphql';
import { SHARED_DISCOVERY_DEBOUNCE_MS } from '../lib/sharedCampaignDiscovery';

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

type DiscoveryParams = {
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  campaignName: string;
  campaignYear: number;
};

const hasAllParams = (params: DiscoveryParams) =>
  [params.unitType, params.unitNumber, params.city, params.state, params.campaignName, params.campaignYear].every(
    Boolean,
  );

const toVariables = (params: DiscoveryParams) => ({
  unitType: params.unitType,
  unitNumber: parseInt(params.unitNumber, 10),
  city: params.city,
  state: params.state,
  campaignName: params.campaignName,
  campaignYear: params.campaignYear,
});

export const useSharedCampaignDiscovery = () => {
  const [findSharedCampaigns, { data: discoveredSharedCampaignsData }] = useLazyQuery<{
    findSharedCampaigns: SharedCampaign[];
  }>(FIND_SHARED_CAMPAIGNS);

  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const discoveredSharedCampaigns = discoveredSharedCampaignsData?.findSharedCampaigns || [];

  const debouncedFindSharedCampaigns = useCallback(
    (params: DiscoveryParams) => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      if (!hasAllParams(params)) {
        return;
      }

      const variables = toVariables(params);
      timeoutRef.current = setTimeout(() => {
        findSharedCampaigns({ variables });
      }, SHARED_DISCOVERY_DEBOUNCE_MS);
    },
    [findSharedCampaigns],
  );

  return {
    discoveredSharedCampaigns,
    debouncedFindSharedCampaigns,
  };
};
