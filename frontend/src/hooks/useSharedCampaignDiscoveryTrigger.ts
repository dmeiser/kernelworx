/**
 * Custom hook for shared campaign discovery trigger effect
 */
import { useEffect, useMemo } from "react";

export const useSharedCampaignDiscoveryTrigger = (
  isSharedCampaignMode: boolean,
  unitType: string,
  unitNumber: string,
  city: string,
  state: string,
  campaignName: string,
  campaignYear: number,
  debouncedFindSharedCampaigns: (params: {
    unitType: string;
    unitNumber: string;
    city: string;
    state: string;
    campaignName: string;
    campaignYear: number;
  }) => void,
) => {
  const shouldTriggerDiscovery = useMemo(
    () =>
      !isSharedCampaignMode && Boolean(unitType && unitNumber && city && state),
    [isSharedCampaignMode, unitType, unitNumber, city, state],
  );

  useEffect(() => {
    if (!shouldTriggerDiscovery) return;

    debouncedFindSharedCampaigns({
      unitType,
      unitNumber,
      city,
      state,
      campaignName,
      campaignYear,
    });
  }, [
    shouldTriggerDiscovery,
    campaignName,
    campaignYear,
    debouncedFindSharedCampaigns,
    unitType,
    unitNumber,
    city,
    state,
  ]);
};
