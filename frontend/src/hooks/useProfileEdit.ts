/**
 * Custom hook for profile edit dialog functionality
 */
import { useState } from 'react';

interface Account {
  givenName?: string;
  familyName?: string;
  city?: string;
  state?: string;
  unitType?: string;
  unitNumber?: string;
}

// Get string field with default
const getField = (value: string | undefined): string => value ?? '';

// Get unit number as string with default
const getUnitNumber = (value: string | undefined): string => {
  return value?.toString() ?? '';
};

// Extract field values from account with defaults
const extractAccountFields = (account: Account | undefined) => {
  if (!account) {
    return {
      givenName: '',
      familyName: '',
      city: '',
      state: '',
      unitType: '',
      unitNumber: '',
    };
  }
  return {
    givenName: getField(account.givenName),
    familyName: getField(account.familyName),
    city: getField(account.city),
    state: getField(account.state),
    unitType: getField(account.unitType),
    unitNumber: getUnitNumber(account.unitNumber),
  };
};

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
  const [givenName, setGivenName] = useState('');
  const [familyName, setFamilyName] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [unitType, setUnitType] = useState('');
  const [unitNumber, setUnitNumber] = useState('');
  const [updateSuccess, setUpdateSuccess] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);

  const handleOpenEditDialog = (account: Account | undefined) => {
    const fields = extractAccountFields(account);
    setGivenName(fields.givenName);
    setFamilyName(fields.familyName);
    setCity(fields.city);
    setState(fields.state);
    setUnitType(fields.unitType);
    setUnitNumber(fields.unitNumber);
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
