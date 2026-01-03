/**
 * Custom hook for managing form state in CreateCampaignPage
 */
import { useState } from "react";

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
    severity: "success" | "error";
  } | null;
}

export const useCreateCampaignFormState = () => {
  const [profileId, setProfileId] = useState("");
  const [campaignName, setCampaignName] = useState("Fall");
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [unitType, setUnitType] = useState("");
  const [unitNumber, setUnitNumber] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [shareWithCreator, setShareWithCreator] = useState(true);
  const [unitSectionExpanded, setUnitSectionExpanded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [toastMessage, setToastMessage] = useState<{
    message: string;
    severity: "success" | "error";
  } | null>(null);

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
