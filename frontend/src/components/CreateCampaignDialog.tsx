/**
 * CreateCampaignDialog component - Dialog for creating a new sales campaign
 */

import React, { useState } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Stack,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Alert,
  CircularProgress,
} from '@mui/material';
import { useCatalogsData } from '../hooks/useCatalogsData';
import { useFormState } from '../hooks/useFormState';
import type { Catalog } from '../types';

interface CreateCampaignDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (
    campaignName: string,
    campaignYear: number,
    catalogId: string,
    startDate?: string,
    endDate?: string,
  ) => Promise<void>;
}

const CatalogGroup: React.FC<{ title: string; catalogs: Catalog[] }> = ({ title, catalogs }) => (
  <>
    <MenuItem key={`${title}-header`} disabled sx={{ fontWeight: 600, backgroundColor: '#f5f5f5', opacity: 1 }}>
      {title}
    </MenuItem>
    {catalogs.map((catalog) => (
      <MenuItem key={catalog.catalogId} value={catalog.catalogId}>
        {catalog.catalogName}
        {catalog.catalogType === 'ADMIN_MANAGED' && ' (Official)'}
      </MenuItem>
    ))}
  </>
);

const buildCatalogGroups = (filteredMyCatalogs: Catalog[], filteredPublicCatalogs: Catalog[]) => {
  const groups: React.ReactNode[] = [];

  if (filteredMyCatalogs.length) {
    groups.push(<CatalogGroup key="my-catalogs" title="My Catalogs" catalogs={filteredMyCatalogs} />);
  }

  if (filteredPublicCatalogs.length) {
    groups.push(<CatalogGroup key="public-catalogs" title="Public Catalogs" catalogs={filteredPublicCatalogs} />);
  }

  return groups;
};

const CatalogMenuItems: React.FC<{
  catalogsLoading: boolean;
  filteredMyCatalogs: Catalog[];
  filteredPublicCatalogs: Catalog[];
}> = ({ catalogsLoading, filteredMyCatalogs, filteredPublicCatalogs }) => {
  if (catalogsLoading) {
    return (
      <MenuItem disabled>
        <CircularProgress size={20} sx={{ mr: 1 }} />
        Loading catalogs...
      </MenuItem>
    );
  }

  const catalogGroups = buildCatalogGroups(filteredMyCatalogs, filteredPublicCatalogs);

  if (!catalogGroups.length) {
    return <MenuItem disabled>No catalogs available</MenuItem>;
  }

  return <>{catalogGroups}</>;
};

const CatalogSelector: React.FC<{
  catalogId: string;
  onChange: (value: string) => void;
  disabled: boolean;
  filteredMyCatalogs: Catalog[];
  filteredPublicCatalogs: Catalog[];
  catalogsLoading: boolean;
  // eslint-disable-next-line complexity -- Component has multiple conditional states for catalog display
}> = ({ catalogId, onChange, disabled, filteredMyCatalogs, filteredPublicCatalogs, catalogsLoading }) => {
  const noCatalogsAvailable =
    !catalogsLoading && filteredMyCatalogs.length === 0 && filteredPublicCatalogs.length === 0;

  return (
    <>
      <FormControl fullWidth disabled={disabled || catalogsLoading}>
        <InputLabel>Product Catalog</InputLabel>
        <Select
          value={catalogId}
          onChange={(e) => onChange(e.target.value)}
          label="Product Catalog"
          disabled={disabled || catalogsLoading}
          MenuProps={{
            slotProps: {
              paper: {
                sx: {
                  maxHeight: 300,
                },
              },
            },
          }}
        >
          <CatalogMenuItems
            catalogsLoading={catalogsLoading}
            filteredMyCatalogs={filteredMyCatalogs}
            filteredPublicCatalogs={filteredPublicCatalogs}
          />
        </Select>
      </FormControl>

      {noCatalogsAvailable && (
        <Alert severity="warning">No product catalogs are available. You'll need a catalog to create a campaign.</Alert>
      )}
    </>
  );
};

const CampaignFields: React.FC<{
  campaignName: string;
  campaignYear: number;
  loading: boolean;
  onNameChange: (value: string) => void;
  onYearChange: (value: number) => void;
}> = ({ campaignName, campaignYear, loading, onNameChange, onYearChange }) => (
  <>
    <TextField
      fullWidth
      label="Campaign Name"
      value={campaignName}
      onChange={(e) => onNameChange(e.target.value)}
      disabled={loading}
      helperText="Name for this sales campaign (e.g., Fall 2025, Spring Fundraiser)"
    />

    <TextField
      fullWidth
      label="Year"
      type="number"
      value={isNaN(campaignYear) ? '' : campaignYear}
      onChange={(e) => onYearChange(parseInt(e.target.value, 10))}
      disabled={loading}
      inputProps={{
        min: 2020,
        max: new Date().getFullYear() + 5,
        step: 1,
      }}
      helperText="Year of this sales campaign"
    />
  </>
);

const DateFields: React.FC<{
  startDate: string;
  endDate: string;
  loading: boolean;
  onStartChange: (value: string) => void;
  onEndChange: (value: string) => void;
}> = ({ startDate, endDate, loading, onStartChange, onEndChange }) => (
  <>
    <TextField
      fullWidth
      label="Start Date (Optional)"
      type="date"
      value={startDate}
      onChange={(e) => onStartChange(e.target.value)}
      disabled={loading}
      InputLabelProps={{
        shrink: true,
      }}
      slotProps={{
        input: {
          inputProps: {
            max: endDate || undefined,
          },
        },
      }}
      helperText="When sales campaign begins"
    />

    <TextField
      fullWidth
      label="End Date (Optional)"
      type="date"
      value={endDate}
      onChange={(e) => onEndChange(e.target.value)}
      disabled={loading}
      InputLabelProps={{
        shrink: true,
      }}
      slotProps={{
        input: {
          inputProps: {
            min: startDate || undefined,
          },
        },
      }}
      helperText="When sales campaign ends"
    />
  </>
);

const CreateCampaignDialogView: React.FC<{
  open: boolean;
  loading: boolean;
  onClose: () => void;
  onSubmit: () => void;
  isFormValid: boolean;
  campaignName: string;
  campaignYear: number;
  startDate: string;
  endDate: string;
  catalogId: string;
  catalogsLoading: boolean;
  filteredMyCatalogs: Catalog[];
  filteredPublicCatalogs: Catalog[];
  setCampaignName: (value: string) => void;
  setCampaignYear: (value: number) => void;
  setStartDate: (value: string) => void;
  setEndDate: (value: string) => void;
  setCatalogId: (value: string) => void;
}> = ({
  open,
  loading,
  onClose,
  onSubmit,
  isFormValid,
  campaignName,
  campaignYear,
  startDate,
  endDate,
  catalogId,
  catalogsLoading,
  filteredMyCatalogs,
  filteredPublicCatalogs,
  setCampaignName,
  setCampaignYear,
  setStartDate,
  setEndDate,
  setCatalogId,
}) => (
  <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
    <DialogTitle>Create New Sales Campaign</DialogTitle>
    <DialogContent>
      <Stack spacing={3} pt={1}>
        <CampaignFields
          campaignName={campaignName}
          campaignYear={campaignYear}
          loading={loading}
          onNameChange={setCampaignName}
          onYearChange={setCampaignYear}
        />

        <DateFields
          startDate={startDate}
          endDate={endDate}
          loading={loading}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
        />

        <CatalogSelector
          catalogId={catalogId}
          onChange={setCatalogId}
          disabled={loading}
          filteredMyCatalogs={filteredMyCatalogs}
          filteredPublicCatalogs={filteredPublicCatalogs}
          catalogsLoading={catalogsLoading}
        />
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={loading}>
        Cancel
      </Button>
      <Button onClick={onSubmit} variant="contained" disabled={!isFormValid || loading}>
        {loading ? 'Creating...' : 'Create Campaign'}
      </Button>
    </DialogActions>
  </Dialog>
);

interface CampaignFormValues {
  campaignName: string;
  campaignYear: number;
  catalogId: string;
  startDate: string;
  endDate: string;
}

const getInitialFormValues = (): CampaignFormValues => ({
  campaignName: '',
  campaignYear: new Date().getFullYear(),
  catalogId: '',
  startDate: '',
  endDate: '',
});

export const CreateCampaignDialog: React.FC<CreateCampaignDialogProps> = ({ open, onClose, onSubmit }) => {
  const { values, setValue, reset } = useFormState<CampaignFormValues>({
    initialValues: getInitialFormValues(),
  });
  const [loading, setLoading] = useState(false);
  const { filteredMyCatalogs, filteredPublicCatalogs, catalogsLoading } = useCatalogsData(false);

  const submitCampaign = async (name: string, start?: string, end?: string) => {
    await onSubmit(name, values.campaignYear, values.catalogId, start, end);
    reset();
    onClose();
  };

  const withLoading = async (action: () => Promise<void>) => {
    setLoading(true);
    try {
      await action();
    } catch (error) {
      console.error('Failed to create campaign:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async () => {
    const trimmedName = values.campaignName.trim();
    if (!trimmedName || !values.catalogId) return;

    await withLoading(() => submitCampaign(trimmedName, values.startDate || undefined, values.endDate || undefined));
  };

  const handleClose = () => {
    if (!loading) {
      reset();
      onClose();
    }
  };

  const isFormValid = Boolean(values.campaignName.trim() && values.catalogId);

  return (
    <CreateCampaignDialogView
      open={open}
      loading={loading}
      onClose={handleClose}
      onSubmit={handleSubmit}
      isFormValid={isFormValid}
      campaignName={values.campaignName}
      campaignYear={values.campaignYear}
      startDate={values.startDate}
      endDate={values.endDate}
      catalogId={values.catalogId}
      catalogsLoading={catalogsLoading}
      filteredMyCatalogs={filteredMyCatalogs}
      filteredPublicCatalogs={filteredPublicCatalogs}
      setCampaignName={(v) => setValue('campaignName', v)}
      setCampaignYear={(v) => setValue('campaignYear', v)}
      setStartDate={(v) => setValue('startDate', v)}
      setEndDate={(v) => setValue('endDate', v)}
      setCatalogId={(v) => setValue('catalogId', v)}
    />
  );
};
