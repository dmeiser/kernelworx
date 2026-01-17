/**
 * Custom hook for managing form state in CreateCampaignPage
 */
import { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export interface FormState {
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

export const useCreateCampaignFormState = () => {
  const location = useLocation();
  
  const [profileId, setProfileId] = useState('');
  const [campaignName, setCampaignName] = useState('');
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [unitType, setUnitType] = useState('');
  const [unitNumber, setUnitNumber] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [shareWithCreator, setShareWithCreator] = useState(true);
  const [unitSectionExpanded, setUnitSectionExpanded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [toastMessage, setToastMessage] = useState<{
    message: string;
    severity: 'success' | 'error';
  } | null>(null);

  // Initialize catalogId from location state if provided
  useEffect(() => {
    const preselectedCatalogId = (location.state as { catalogId?: string })?.catalogId;
    if (preselectedCatalogId) {
      setCatalogId(preselectedCatalogId);
    }
  }, [location.state]);

  return {
    profileId,
    setProfileId,
    campaignName,
    setCampaignName,
    campaignYear,
    setCampaignYear,
    catalogId,
    setCatalogId,
    startDate,
    setStartDate,
    endDate,
    setEndDate,
    unitType,
    setUnitType,
    unitNumber,
    setUnitNumber,
    city,
    setCity,
    state,
    setState,
    shareWithCreator,
    setShareWithCreator,
    unitSectionExpanded,
    setUnitSectionExpanded,
    submitting,
    setSubmitting,
    toastMessage,
    setToastMessage,
  };
};
