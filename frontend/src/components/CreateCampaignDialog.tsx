/**
 * CreateCampaignDialog component - Dialog for creating a new sales campaign
 */

import React, { useCallback, useState } from 'react';
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

interface Catalog {
  catalogId: string;
  catalogName: string;
  catalogType: string;
  isDeleted?: boolean;
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
      value={campaignYear}
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

export const CreateCampaignDialog: React.FC<CreateCampaignDialogProps> = ({ open, onClose, onSubmit }) => {
  const [campaignName, setCampaignName] = useState('');
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [catalogId, setCatalogId] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [loading, setLoading] = useState(false);
  const { filteredMyCatalogs, filteredPublicCatalogs, catalogsLoading } = useCatalogsData(false);

  const resetForm = useCallback(() => {
    setCampaignName('');
    setCampaignYear(new Date().getFullYear());
    setCatalogId('');
    setStartDate('');
    setEndDate('');
  }, []);

  const submitCampaign = async (name: string, start?: string, end?: string) => {
    await onSubmit(name, campaignYear, catalogId, start, end);
    resetForm();
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
    const trimmedName = campaignName.trim();
    if (!trimmedName || !catalogId) return;

    await withLoading(() => submitCampaign(trimmedName, startDate || undefined, endDate || undefined));
  };

  const handleClose = () => {
    if (!loading) {
      resetForm();
      onClose();
    }
  };

  const isFormValid = Boolean(campaignName.trim() && catalogId);

  return (
    <CreateCampaignDialogView
      open={open}
      loading={loading}
      onClose={handleClose}
      onSubmit={handleSubmit}
      isFormValid={isFormValid}
      campaignName={campaignName}
      campaignYear={campaignYear}
      startDate={startDate}
      endDate={endDate}
      catalogId={catalogId}
      catalogsLoading={catalogsLoading}
      filteredMyCatalogs={filteredMyCatalogs}
      filteredPublicCatalogs={filteredPublicCatalogs}
      setCampaignName={setCampaignName}
      setCampaignYear={setCampaignYear}
      setStartDate={setStartDate}
      setEndDate={setEndDate}
      setCatalogId={setCatalogId}
    />
  );
};
