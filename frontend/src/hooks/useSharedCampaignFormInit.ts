/**
 * Custom hook for shared campaign form initialization
 */
import { useEffect } from 'react';

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

export const useSharedCampaignFormInit = (
  sharedCampaign: SharedCampaign | null | undefined,
  setCampaignName: (name: string) => void,
  setCampaignYear: (year: number) => void,
  setCatalogId: (id: string) => void,
  setStartDate: (date: string) => void,
  setEndDate: (date: string) => void,
  setUnitType: (type: string) => void,
  setUnitNumber: (number: string) => void,
  setCity: (city: string) => void,
  setState: (state: string) => void,
) => {
  useEffect(() => {
    if (sharedCampaign && sharedCampaign.isActive) {
      setCampaignName(sharedCampaign.campaignName);
      setCampaignYear(sharedCampaign.campaignYear);
      setCatalogId(sharedCampaign.catalogId);
      setStartDate(sharedCampaign.startDate || '');
      setEndDate(sharedCampaign.endDate || '');
      setUnitType(sharedCampaign.unitType);
      setUnitNumber(String(sharedCampaign.unitNumber));
      setCity(sharedCampaign.city);
      setState(sharedCampaign.state);
    }
  }, [
    sharedCampaign,
    setCampaignName,
    setCampaignYear,
    setCatalogId,
    setStartDate,
    setEndDate,
    setUnitType,
    setUnitNumber,
    setCity,
    setState,
  ]);
};
