/**
 * CreateSharedCampaignPage - Dedicated page for creating campaign shared campaigns
 * Mobile-friendly full-page form
 */

import React, { useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Typography,
  Box,
  Button,
  TextField,
  Stack,
  Alert,
  AlertTitle,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Divider,
  CircularProgress,
  Paper,
  Container,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material';
import { ArrowBack as BackIcon, Save as SaveIcon } from '@mui/icons-material';
import {
  LIST_MANAGED_CATALOGS,
  LIST_MY_CATALOGS,
  CREATE_SHARED_CAMPAIGN,
  LIST_MY_SHARED_CAMPAIGNS,
} from '../lib/graphql';
import { StateAutocomplete } from '../components/StateAutocomplete';
import type { Catalog, SharedCampaign } from '../types';

const UNIT_TYPES = ['Pack', 'Troop', 'Crew', 'Ship', 'Post'];

const BASE_URL = window.location.origin;
const MAX_CREATOR_MESSAGE_LENGTH = 300;
const MAX_ACTIVE_SHARED_CAMPAIGNS = 50;

// ============================================================================
// Form Validation Helpers
// ============================================================================

interface FormData {
  catalogId: string;
  campaignName: string;
  campaignYear: number;
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  creatorMessage: string;
}

function hasRequiredCampaignFields(catalogId: string, campaignName: string, campaignYear: number): boolean {
  return Boolean(catalogId && campaignName.trim() && campaignYear);
}

function hasRequiredUnitFields(unitType: string, unitNumber: string, city: string, state: string): boolean {
  return Boolean(unitType && unitNumber && city.trim() && state);
}

function validateCreatorMessageLength(message: string): boolean {
  return message.length <= MAX_CREATOR_MESSAGE_LENGTH;
}

function isFormValid(data: FormData): boolean {
  const { catalogId, campaignName, campaignYear, unitType, unitNumber, city, state, creatorMessage } = data;
  const hasCampaignFields = hasRequiredCampaignFields(catalogId, campaignName, campaignYear);
  const hasUnitFields = hasRequiredUnitFields(unitType, unitNumber, city, state);
  return hasCampaignFields && hasUnitFields && validateCreatorMessageLength(creatorMessage);
}

// ============================================================================
// Sub-Components
// ============================================================================

interface CatalogSectionProps {
  catalogId: string;
  onCatalogChange: (value: string) => void;
  catalogsLoading: boolean;
  filteredPublicCatalogs: Catalog[];
  myCatalogs: Catalog[];
}

const CatalogSection: React.FC<CatalogSectionProps> = ({
  catalogId,
  onCatalogChange,
  catalogsLoading,
  filteredPublicCatalogs,
  myCatalogs,
}) => {
  const handleChange = (e: SelectChangeEvent<string>) => onCatalogChange(e.target.value);
  const noCatalogs = !catalogsLoading && filteredPublicCatalogs.length === 0 && myCatalogs.length === 0;
  const allCatalogs = [...filteredPublicCatalogs, ...myCatalogs];

  return (
    <Box>
      <Typography variant="h6" gutterBottom>
        Product Catalog
      </Typography>
      <FormControl fullWidth required disabled={catalogsLoading}>
        <InputLabel>Select Catalog</InputLabel>
        <Select
          value={catalogId}
          onChange={handleChange}
          label="Select Catalog"
          renderValue={(value) => {
            if (!value) return '';
            const catalog = allCatalogs.find((c) => c.catalogId === value);
            return catalog ? catalog.catalogName : '';
          }}
        >
          {catalogsLoading && <MenuItem disabled>Loading catalogs...</MenuItem>}
          {noCatalogs && <MenuItem disabled>No catalogs available</MenuItem>}

          {filteredPublicCatalogs.length > 0 && (
            <MenuItem disabled sx={{ fontWeight: 'bold', py: 1 }}>
              Public Catalogs
            </MenuItem>
          )}
          {filteredPublicCatalogs.map((catalog) => (
            <MenuItem key={`public-${catalog.catalogId}`} value={catalog.catalogId} sx={{ pl: 4 }}>
              {catalog.catalogName}
            </MenuItem>
          ))}

          {myCatalogs.length > 0 && (
            <MenuItem disabled sx={{ fontWeight: 'bold', py: 1 }}>
              My Catalogs
            </MenuItem>
          )}
          {myCatalogs.map((catalog) => (
            <MenuItem key={`my-${catalog.catalogId}`} value={catalog.catalogId} sx={{ pl: 4 }}>
              {catalog.catalogName}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </Box>
  );
};

interface CampaignInfoSectionProps {
  campaignName: string;
  onCampaignNameChange: (value: string) => void;
  campaignYear: number;
  onCampaignYearChange: (value: number) => void;
  startDate: string;
  onStartDateChange: (value: string) => void;
  endDate: string;
  onEndDateChange: (value: string) => void;
}

const CampaignInfoSection: React.FC<CampaignInfoSectionProps> = ({
  campaignName,
  onCampaignNameChange,
  campaignYear,
  onCampaignYearChange,
  startDate,
  onStartDateChange,
  endDate,
  onEndDateChange,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Campaign Information
    </Typography>
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField
          label="Campaign Name"
          value={campaignName}
          onChange={(e) => onCampaignNameChange(e.target.value)}
          placeholder="e.g., Fall, Spring"
          required
          fullWidth
        />
        <TextField
          label="Campaign Year"
          type="number"
          value={campaignYear}
          onChange={(e) => onCampaignYearChange(parseInt(e.target.value, 10) || 0)}
          required
          sx={{ minWidth: { xs: '100%', sm: 150 } }}
          inputProps={{ min: 2020, max: 2100 }}
        />
      </Stack>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField
          label="Start Date (Optional)"
          type="date"
          value={startDate}
          onChange={(e) => onStartDateChange(e.target.value)}
          fullWidth
          InputLabelProps={{ shrink: true }}
        />
        <TextField
          label="End Date (Optional)"
          type="date"
          value={endDate}
          onChange={(e) => onEndDateChange(e.target.value)}
          fullWidth
          InputLabelProps={{ shrink: true }}
        />
      </Stack>
    </Stack>
  </Box>
);

interface UnitInfoSectionProps {
  unitType: string;
  onUnitTypeChange: (value: string) => void;
  unitNumber: string;
  onUnitNumberChange: (value: string) => void;
  city: string;
  onCityChange: (value: string) => void;
  state: string;
  onStateChange: (value: string) => void;
}

const UnitInfoSection: React.FC<UnitInfoSectionProps> = ({
  unitType,
  onUnitTypeChange,
  unitNumber,
  onUnitNumberChange,
  city,
  onCityChange,
  state,
  onStateChange,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Unit Information
    </Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
      All fields required
    </Typography>
    <Stack spacing={2}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <FormControl required fullWidth>
          <InputLabel>Unit Type</InputLabel>
          <Select value={unitType} onChange={(e) => onUnitTypeChange(e.target.value)} label="Unit Type">
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
          value={unitNumber}
          onChange={(e) => onUnitNumberChange(e.target.value)}
          required
          fullWidth
          inputProps={{ min: 1 }}
        />
      </Stack>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField label="City" value={city} onChange={(e) => onCityChange(e.target.value)} required fullWidth />
        <StateAutocomplete value={state} onChange={onStateChange} required fullWidth />
      </Stack>
    </Stack>
  </Box>
);

interface AdditionalInfoSectionProps {
  creatorMessage: string;
  onCreatorMessageChange: (value: string) => void;
  description: string;
  onDescriptionChange: (value: string) => void;
}

const AdditionalInfoSection: React.FC<AdditionalInfoSectionProps> = ({
  creatorMessage,
  onCreatorMessageChange,
  description,
  onDescriptionChange,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Additional Information
    </Typography>
    <Stack spacing={2}>
      <TextField
        label="Message to Scouts (Optional)"
        value={creatorMessage}
        onChange={(e) => onCreatorMessageChange(e.target.value)}
        placeholder="Enter a message that will be shown to scouts when they use this link"
        multiline
        rows={3}
        fullWidth
        inputProps={{ maxLength: MAX_CREATOR_MESSAGE_LENGTH }}
        helperText={`${creatorMessage.length}/${MAX_CREATOR_MESSAGE_LENGTH} characters`}
        error={creatorMessage.length > MAX_CREATOR_MESSAGE_LENGTH}
      />
      <TextField
        label="Description (For Your Reference)"
        value={description}
        onChange={(e) => onDescriptionChange(e.target.value)}
        placeholder="Internal description to help you manage your shared campaigns"
        fullWidth
      />
    </Stack>
  </Box>
);

const LinkPreviewSection: React.FC = () => {
  const previewLink = `${BASE_URL}/c/[generated-code]`;
  return (
    <Box sx={{ bgcolor: 'grey.100', p: 2, borderRadius: 1 }}>
      <Typography variant="subtitle2" gutterBottom>
        Shareable Link Preview:
      </Typography>
      <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all', mb: 1 }}>
        {previewLink}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        The actual code will be generated when you create the shared campaign
      </Typography>
    </Box>
  );
};

interface ActionButtonsSectionProps {
  onCancel: () => void;
  onSubmit: () => void;
  isSubmitting: boolean;
  isValid: boolean;
  canCreate: boolean;
}

const ActionButtonsSection: React.FC<ActionButtonsSectionProps> = ({
  onCancel,
  onSubmit,
  isSubmitting,
  isValid,
  canCreate,
}) => (
  <Stack direction={{ xs: 'column-reverse', sm: 'row' }} spacing={2} justifyContent="flex-end">
    <Button onClick={onCancel} disabled={isSubmitting} fullWidth={false} sx={{ minWidth: { xs: '100%', sm: 120 } }}>
      Cancel
    </Button>
    <Button
      onClick={onSubmit}
      variant="contained"
      disabled={!isValid || isSubmitting || !canCreate}
      startIcon={isSubmitting ? <CircularProgress size={16} /> : <SaveIcon />}
      fullWidth={false}
      sx={{ minWidth: { xs: '100%', sm: 200 } }}
    >
      {isSubmitting ? 'Creating...' : 'Create Shared Campaign'}
    </Button>
  </Stack>
);

const WarningAlert: React.FC = () => (
  <Alert severity="warning">
    <AlertTitle>Important</AlertTitle>
    If someone stops sharing their profile with you, you will lose access to their data. The share is controlled by the
    profile owner.
  </Alert>
);

const MaxCampaignsAlert: React.FC = () => (
  <Alert severity="error">
    You have reached the maximum of {MAX_ACTIVE_SHARED_CAMPAIGNS} active shared campaigns. Please deactivate an existing
    shared campaign before creating a new one.
  </Alert>
);

interface AlertsSectionProps {
  canCreate: boolean;
  error: string | null;
}

const AlertsSection: React.FC<AlertsSectionProps> = ({ canCreate, error }) => (
  <>
    <WarningAlert />
    {!canCreate && <MaxCampaignsAlert />}
    {error && <Alert severity="error">{error}</Alert>}
  </>
);

// ============================================================================
// Hooks
// ============================================================================

function getArrayOrEmpty<T>(arr: T[] | undefined | null): T[] {
  return arr ?? [];
}

function filterDuplicateCatalogs(publicCatalogs: Catalog[], myCatalogs: Catalog[]): Catalog[] {
  const myIdSet = new Set(myCatalogs.map((c) => c.catalogId));
  return publicCatalogs.filter((c) => !myIdSet.has(c.catalogId));
}

function usePublicCatalogs() {
  const { data, loading } = useQuery<{ listManagedCatalogs: Catalog[] }>(LIST_MANAGED_CATALOGS);
  const allCatalogs = getArrayOrEmpty(data?.listManagedCatalogs);
  // Only include admin-managed catalogs for shared campaigns
  const catalogs = allCatalogs.filter((c) => c.catalogType === 'ADMIN_MANAGED');
  return { catalogs, loading };
}

function useMyCatalogs() {
  const { data, loading } = useQuery<{ listMyCatalogs: Catalog[] }>(LIST_MY_CATALOGS);
  return { catalogs: getArrayOrEmpty(data?.listMyCatalogs), loading };
}

function useCatalogs() {
  const { catalogs: publicCatalogs, loading: publicLoading } = usePublicCatalogs();
  const { catalogs: myCatalogs, loading: myLoading } = useMyCatalogs();
  const filteredPublicCatalogs = filterDuplicateCatalogs(publicCatalogs, myCatalogs);
  const catalogsLoading = publicLoading || myLoading;
  return { filteredPublicCatalogs, myCatalogs, catalogsLoading };
}

function useCanCreateSharedCampaign() {
  const { data } = useQuery<{ listMySharedCampaigns: SharedCampaign[] }>(LIST_MY_SHARED_CAMPAIGNS, {
    fetchPolicy: 'network-only',
  });
  const sharedCampaigns = getArrayOrEmpty(data?.listMySharedCampaigns);
  const activeCount = sharedCampaigns.filter((p) => p.isActive).length;
  return activeCount < MAX_ACTIVE_SHARED_CAMPAIGNS;
}

// ============================================================================
// Main Component
// ============================================================================

export const CreateSharedCampaignPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const preselectedCatalogId = (location.state as { catalogId?: string })?.catalogId;

  // Form state
  const [catalogId, setCatalogId] = useState(preselectedCatalogId || '');
  const [campaignName, setCampaignName] = useState('');
  const [campaignYear, setCampaignYear] = useState(new Date().getFullYear());
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [unitType, setUnitType] = useState('');
  const [unitNumber, setUnitNumber] = useState('');
  const [city, setCity] = useState('');
  const [state, setState] = useState('');
  const [creatorMessage, setCreatorMessage] = useState('');
  const [description, setDescription] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Use custom hooks for data fetching
  const canCreate = useCanCreateSharedCampaign();
  const { filteredPublicCatalogs, myCatalogs, catalogsLoading } = useCatalogs();

  // Create mutation
  const [createSharedCampaign] = useMutation(CREATE_SHARED_CAMPAIGN);

  // Form data for validation
  const formData: FormData = {
    catalogId,
    campaignName,
    campaignYear,
    unitType,
    unitNumber,
    city,
    state,
    creatorMessage,
  };

  const formIsValid = isFormValid(formData);

  // Build input object for mutation
  const buildMutationInput = () => ({
    catalogId,
    campaignName: campaignName.trim(),
    campaignYear,
    startDate: startDate || undefined,
    endDate: endDate || undefined,
    unitType,
    unitNumber: parseInt(unitNumber, 10),
    city: city.trim(),
    state,
    creatorMessage: creatorMessage.trim() || undefined,
    description: description.trim() || undefined,
  });

  const scrollToTop = () => window.scrollTo({ top: 0, behavior: 'smooth' });

  const showValidationError = () => {
    setError('Please fill in all required fields');
    scrollToTop();
  };

  const handleMutationError = (err: unknown) => {
    const errorMessage = err instanceof Error ? err.message : 'Failed to create shared campaign';
    setError(errorMessage);
    scrollToTop();
  };

  const handleSubmit = async () => {
    if (!formIsValid) {
      showValidationError();
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await createSharedCampaign({
        variables: { input: buildMutationInput() },
      });
      navigate('/shared-campaigns');
    } catch (err) {
      handleMutationError(err);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = () => navigate(-1);
  const handleBack = () => navigate(-1);

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 3 }}>
        <Button startIcon={<BackIcon />} onClick={handleBack} disabled={isSubmitting}>
          Back
        </Button>
        <Typography variant="h4" component="h1">
          Create Shared Campaign
        </Typography>
      </Stack>

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Stack spacing={3}>
          <AlertsSection canCreate={canCreate} error={error} />

          <CatalogSection
            catalogId={catalogId}
            onCatalogChange={setCatalogId}
            catalogsLoading={catalogsLoading}
            filteredPublicCatalogs={filteredPublicCatalogs}
            myCatalogs={myCatalogs}
          />

          <Divider />

          <CampaignInfoSection
            campaignName={campaignName}
            onCampaignNameChange={setCampaignName}
            campaignYear={campaignYear}
            onCampaignYearChange={setCampaignYear}
            startDate={startDate}
            onStartDateChange={setStartDate}
            endDate={endDate}
            onEndDateChange={setEndDate}
          />

          <Divider />

          <UnitInfoSection
            unitType={unitType}
            onUnitTypeChange={setUnitType}
            unitNumber={unitNumber}
            onUnitNumberChange={setUnitNumber}
            city={city}
            onCityChange={setCity}
            state={state}
            onStateChange={setState}
          />

          <Divider />

          <AdditionalInfoSection
            creatorMessage={creatorMessage}
            onCreatorMessageChange={setCreatorMessage}
            description={description}
            onDescriptionChange={setDescription}
          />

          <Divider />

          <LinkPreviewSection />

          <ActionButtonsSection
            onCancel={handleCancel}
            onSubmit={handleSubmit}
            isSubmitting={isSubmitting}
            isValid={formIsValid}
            canCreate={canCreate}
          />
        </Stack>
      </Paper>
    </Container>
  );
};
