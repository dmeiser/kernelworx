/**
 * CreateSharedCampaignDialog - Dialog for creating a new shared campaign
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  Alert,
  AlertTitle,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Box,
  CircularProgress,
} from '@mui/material';
import { LIST_MANAGED_CATALOGS, LIST_MY_CATALOGS, CREATE_SHARED_CAMPAIGN } from '../lib/graphql';
import { useFormState } from '../hooks/useFormState';
import { StateAutocomplete } from './StateAutocomplete';
import { CatalogSelect } from './CatalogSelect';
import type { Catalog } from '../types';

interface CreateSharedCampaignDialogProps {
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
  canCreate: boolean;
}

const UNIT_TYPES = ['Pack', 'Troop', 'Crew', 'Ship', 'Post'];

const BASE_URL = window.location.origin;
const MAX_CREATOR_MESSAGE_LENGTH = 300;

interface FormState {
  catalogId: string;
  campaignName: string;
  campaignYear: number;
  startDate: string;
  endDate: string;
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  creatorMessage: string;
  description: string;
}

const hasCatalogAndCampaign = (formState: FormState): boolean =>
  Boolean(formState.catalogId && formState.campaignName.trim() && formState.campaignYear);

const hasUnitInfo = (formState: FormState): boolean =>
  Boolean(formState.unitType && formState.unitNumber && formState.city.trim() && formState.state);

const hasRequiredFields = (formState: FormState): boolean => hasCatalogAndCampaign(formState) && hasUnitInfo(formState);

const isMessageValid = (creatorMessage: string): boolean => creatorMessage.length <= MAX_CREATOR_MESSAGE_LENGTH;

const validateForm = (formState: FormState): boolean =>
  hasRequiredFields(formState) && isMessageValid(formState.creatorMessage);

const useCatalogLists = (open: boolean) => {
  const { data: publicCatalogsData, loading: publicLoading } = useQuery<{
    listManagedCatalogs: Catalog[];
  }>(LIST_MANAGED_CATALOGS, { skip: !open });

  const { data: myCatalogsData, loading: myLoading } = useQuery<{
    listMyCatalogs: Catalog[];
  }>(LIST_MY_CATALOGS, { skip: !open });

  const publicCatalogs = useMemo(() => publicCatalogsData?.listManagedCatalogs || [], [publicCatalogsData]);

  const ownedCatalogs = useMemo(() => myCatalogsData?.listMyCatalogs || [], [myCatalogsData]);

  const catalogLists = useMemo(() => {
    const myIdSet = new Set(ownedCatalogs.map((c) => c.catalogId));
    const filteredPublicCatalogs = publicCatalogs.filter((catalog) => !myIdSet.has(catalog.catalogId));

    return { filteredPublicCatalogs, ownedCatalogs };
  }, [ownedCatalogs, publicCatalogs]);

  return {
    filteredPublicCatalogs: catalogLists.filteredPublicCatalogs,
    myCatalogs: catalogLists.ownedCatalogs,
    catalogsLoading: publicLoading || myLoading,
  };
};

const useFormReset = (open: boolean, reset: () => void) => {
  useEffect(() => {
    if (open) {
      reset();
    }
  }, [open, reset]);
};

interface FormSetters {
  setCatalogId: (v: string) => void;
  setCampaignName: (v: string) => void;
  setCampaignYear: (v: number) => void;
  setStartDate: (v: string) => void;
  setEndDate: (v: string) => void;
  setUnitType: (v: string) => void;
  setUnitNumber: (v: string) => void;
  setCity: (v: string) => void;
  setState: (v: string) => void;
  setCreatorMessage: (v: string) => void;
  setDescription: (v: string) => void;
}

const getInitialFormValues = (): FormState => ({
  catalogId: '',
  campaignName: '',
  campaignYear: new Date().getFullYear(),
  startDate: '',
  endDate: '',
  unitType: '',
  unitNumber: '',
  city: '',
  state: '',
  creatorMessage: '',
  description: '',
});

const useSharedCampaignForm = (open: boolean) => {
  const {
    values: formState,
    setValue,
    reset,
  } = useFormState<FormState>({
    initialValues: getInitialFormValues(),
  });

  useFormReset(open, reset);

  const formSetters: FormSetters = useMemo(
    () => ({
      setCatalogId: (v: string) => setValue('catalogId', v),
      setCampaignName: (v: string) => setValue('campaignName', v),
      setCampaignYear: (v: number) => setValue('campaignYear', v),
      setStartDate: (v: string) => setValue('startDate', v),
      setEndDate: (v: string) => setValue('endDate', v),
      setUnitType: (v: string) => setValue('unitType', v),
      setUnitNumber: (v: string) => setValue('unitNumber', v),
      setCity: (v: string) => setValue('city', v),
      setState: (v: string) => setValue('state', v),
      setCreatorMessage: (v: string) => setValue('creatorMessage', v),
      setDescription: (v: string) => setValue('description', v),
    }),
    [setValue],
  );

  const isFormValid = useMemo(() => validateForm(formState), [formState]);

  return { formState, formSetters, isFormValid };
};

const buildInput = (formState: FormState) => ({
  catalogId: formState.catalogId,
  campaignName: formState.campaignName.trim(),
  campaignYear: formState.campaignYear,
  startDate: formState.startDate || undefined,
  endDate: formState.endDate || undefined,
  unitType: formState.unitType,
  unitNumber: parseInt(formState.unitNumber, 10),
  city: formState.city.trim(),
  state: formState.state,
  creatorMessage: formState.creatorMessage.trim() || undefined,
  description: formState.description.trim() || undefined,
});

interface CampaignFormFieldsProps {
  formState: FormState;
  formSetters: FormSetters;
  catalogsLoading: boolean;
  filteredPublicCatalogs: Catalog[];
  myCatalogs: Catalog[];
}

const CampaignFormFields: React.FC<CampaignFormFieldsProps> = ({
  formState,
  formSetters,
  catalogsLoading,
  filteredPublicCatalogs,
  myCatalogs,
}) => (
  <>
    {/* Catalog Selection */}
    <CatalogSelect
      value={formState.catalogId}
      onChange={formSetters.setCatalogId}
      myCatalogs={myCatalogs}
      publicCatalogs={filteredPublicCatalogs}
      loading={catalogsLoading}
      required
    />

    {/* Catalog Access Warning - only show if catalog is selected */}
    {formState.catalogId && (
      <Alert severity="warning">
        <AlertTitle>⚠️ Participants Will Access This Catalog</AlertTitle>
        Anyone who joins this campaign will be able to view this catalog's products and prices.
      </Alert>
    )}

    {/* Campaign Information */}
    <Stack direction="row" spacing={2}>
      <TextField
        label="Campaign Name"
        value={formState.campaignName}
        onChange={(e) => formSetters.setCampaignName(e.target.value)}
        placeholder="e.g., Fall, Spring"
        required
        fullWidth
      />
      <TextField
        label="Campaign Year"
        type="number"
        value={formState.campaignYear}
        onChange={(e) => formSetters.setCampaignYear(parseInt(e.target.value, 10) || 0)}
        required
        sx={{ width: 150 }}
        inputProps={{ min: 2020, max: 2100 }}
      />
    </Stack>

    {/* Optional Dates */}
    <Stack direction="row" spacing={2}>
      <TextField
        label="Start Date (Optional)"
        type="date"
        value={formState.startDate}
        onChange={(e) => formSetters.setStartDate(e.target.value)}
        fullWidth
        InputLabelProps={{ shrink: true }}
      />
      <TextField
        label="End Date (Optional)"
        type="date"
        value={formState.endDate}
        onChange={(e) => formSetters.setEndDate(e.target.value)}
        fullWidth
        InputLabelProps={{ shrink: true }}
      />
    </Stack>

    {/* Unit Information */}
    <Typography variant="subtitle2" color="text.secondary">
      Unit Information (Required)
    </Typography>
    <Stack direction="row" spacing={2}>
      <FormControl required sx={{ minWidth: 150 }}>
        <InputLabel>Unit Type</InputLabel>
        <Select value={formState.unitType} onChange={(e) => formSetters.setUnitType(e.target.value)} label="Unit Type">
          {UNIT_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {type}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      <TextField
        label="Unit Number"
        type="number"
        value={formState.unitNumber}
        onChange={(e) => formSetters.setUnitNumber(e.target.value)}
        required
        sx={{ width: 150 }}
        inputProps={{ min: 1 }}
      />
      <TextField
        label="City"
        value={formState.city}
        onChange={(e) => formSetters.setCity(e.target.value)}
        required
        fullWidth
      />
      <StateAutocomplete
        value={formState.state}
        onChange={formSetters.setState}
        required
        sx={{ minWidth: 100 }}
      />
    </Stack>

    {/* Creator Message */}
    <TextField
      label="Message to Scouts (Optional)"
      value={formState.creatorMessage}
      onChange={(e) => formSetters.setCreatorMessage(e.target.value)}
      placeholder="Enter a message that will be shown to scouts when they use this link"
      multiline
      rows={2}
      fullWidth
      inputProps={{ maxLength: MAX_CREATOR_MESSAGE_LENGTH }}
      helperText={`${formState.creatorMessage.length}/${MAX_CREATOR_MESSAGE_LENGTH} characters`}
      error={formState.creatorMessage.length > MAX_CREATOR_MESSAGE_LENGTH}
    />

    {/* Description (for internal use) */}
    <TextField
      label="Description (For Your Reference)"
      value={formState.description}
      onChange={(e) => formSetters.setDescription(e.target.value)}
      placeholder="Internal description to help you manage your shared campaigns"
      fullWidth
    />
  </>
);

const LinkPreview: React.FC = () => (
  <Box sx={{ bgcolor: 'grey.100', p: 2, borderRadius: 1 }}>
    <Typography variant="caption" color="text.secondary">
      Shareable Link Preview:
    </Typography>
    <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all' }}>
      {`${BASE_URL}/c/[generated-code]`}
    </Typography>
    <Typography variant="caption" color="text.secondary">
      (The actual code will be generated when you create the shared campaign)
    </Typography>
  </Box>
);

const LimitWarning: React.FC<{ canCreate: boolean }> = ({ canCreate }) =>
  canCreate ? null : (
    <Alert severity="error">
      You have reached the maximum of 50 active shared campaigns. Please deactivate an existing shared campaign before
      creating a new one.
    </Alert>
  );

const ErrorAlert: React.FC<{ error: string | null }> = ({ error }) =>
  error ? <Alert severity="error">{error}</Alert> : null;

export const CreateSharedCampaignDialog: React.FC<CreateSharedCampaignDialogProps> = ({
  open,
  onClose,
  onSuccess,
  canCreate,
}) => {
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { formState, formSetters, isFormValid } = useSharedCampaignForm(open);
  const { filteredPublicCatalogs, myCatalogs, catalogsLoading } = useCatalogLists(open);
  const [createSharedCampaign] = useMutation(CREATE_SHARED_CAMPAIGN);

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);

    try {
      await createSharedCampaign({
        variables: { input: buildInput(formState) },
      });
      onSuccess();
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to create campaign sharedCampaign';
      setError(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>Create Shared Campaign</DialogTitle>
      <DialogContent>
        <Stack spacing={3} sx={{ mt: 1 }}>
          <Alert severity="warning">
            <AlertTitle>Important</AlertTitle>
            If someone stops sharing their profile with you, you will lose access to their data. The share is controlled
            by the profile owner.
          </Alert>

          <LimitWarning canCreate={canCreate} />
          <ErrorAlert error={error} />

          <CampaignFormFields
            formState={formState}
            formSetters={formSetters}
            catalogsLoading={catalogsLoading}
            filteredPublicCatalogs={filteredPublicCatalogs}
            myCatalogs={myCatalogs}
          />

          <LinkPreview />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isSubmitting}>
          Cancel
        </Button>
        <Button
          onClick={handleSubmit}
          variant="contained"
          disabled={!isFormValid || isSubmitting || !canCreate}
          startIcon={isSubmitting ? <CircularProgress size={16} /> : undefined}
        >
          {isSubmitting ? 'Creating...' : 'Create Shared Campaign'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
