/**
 * Custom hook for shared campaign form initialization
 */
import { useEffect } from 'react';
import type { SharedCampaign } from '../types/entities';

interface FormSetters {
  setCampaignName: (name: string) => void;
  setCampaignYear: (year: number) => void;
  setCatalogId: (id: string) => void;
  setStartDate: (date: string) => void;
  setEndDate: (date: string) => void;
  setUnitType: (type: string) => void;
  setUnitNumber: (number: string) => void;
  setCity: (city: string) => void;
  setState: (state: string) => void;
}

const applySharedCampaignToForm = (sharedCampaign: SharedCampaign, setters: FormSetters): void => {
  setters.setCampaignName(sharedCampaign.campaignName);
  setters.setCampaignYear(sharedCampaign.campaignYear);
  setters.setCatalogId(sharedCampaign.catalogId);
  setters.setStartDate(sharedCampaign.startDate ?? '');
  setters.setEndDate(sharedCampaign.endDate ?? '');
  setters.setUnitType(sharedCampaign.unitType);
  setters.setUnitNumber(String(sharedCampaign.unitNumber));
  setters.setCity(sharedCampaign.city);
  setters.setState(sharedCampaign.state);
};

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
    if (!sharedCampaign?.isActive || !sharedCampaign.catalog) {
      return;
    }
    applySharedCampaignToForm(sharedCampaign, {
      setCampaignName,
      setCampaignYear,
      setCatalogId,
      setStartDate,
      setEndDate,
      setUnitType,
      setUnitNumber,
      setCity,
      setState,
    });
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
