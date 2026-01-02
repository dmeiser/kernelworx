/**
 * Custom hook for profile edit dialog functionality
 */
import { useState } from "react";

interface Account {
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitType?: string;
  unitNumber?: string;
}

export interface UseProfileEditReturn {
  editDialogOpen: boolean;
  setEditDialogOpen: (value: boolean) => void;
  givenName: string;
  setGivenName: (value: string) => void;
  familyName: string;
  setFamilyName: (value: string) => void;
  city: string;
  setCity: (value: string) => void;
  state: string;
  setState: (value: string) => void;
  unitType: string;
  setUnitType: (value: string) => void;
  unitNumber: string;
  setUnitNumber: (value: string) => void;
  updateSuccess: boolean;
  setUpdateSuccess: (value: boolean) => void;
  updateError: string | null;
  setUpdateError: (value: string | null) => void;
  handleOpenEditDialog: (account: Account | undefined) => void;
}

export const useProfileEdit = (): UseProfileEditReturn => {
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [givenName, setGivenName] = useState("");
  const [familyName, setFamilyName] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [unitType, setUnitType] = useState("");
  const [unitNumber, setUnitNumber] = useState("");
  const [updateSuccess, setUpdateSuccess] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  const handleOpenEditDialog = (account: Account | undefined) => {
    setGivenName(account?.givenName || "");
    setFamilyName(account?.familyName || "");
    setCity(account?.city || "");
    setState(account?.state || "");
    setUnitType(account?.unitType || "");
    setUnitNumber(account?.unitNumber?.toString() || "");
    setEditDialogOpen(true);
  };

  return {
    editDialogOpen,
    setEditDialogOpen,
    givenName,
    setGivenName,
    familyName,
    setFamilyName,
    city,
    setCity,
    state,
    setState,
    unitType,
    setUnitType,
    unitNumber,
    setUnitNumber,
    updateSuccess,
    setUpdateSuccess,
    updateError,
    setUpdateError,
    handleOpenEditDialog,
  };
};
