/**
 * CreateCampaignPage component - Page for creating a new sales campaign
 *
 * Supports two modes:
 * 1. Shared Campaign mode: Accessed via /c/:sharedCampaignCode - all fields locked except profile selection
 * 2. Manual mode: Accessed via /create-campaign - all fields editable with optional unit info
 */

import React, { useEffect } from 'react';
import { useParams } from 'react-router-dom';
import {
  Box,
  Typography,
  Button,
  Stack,
  Paper,
  Container,
  CircularProgress,
  Alert,
  AlertTitle,
  Divider,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  FormControlLabel,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material';
import { ArrowBack as BackIcon, Save as SaveIcon, ExpandMore as ExpandMoreIcon } from '@mui/icons-material';
import { useCreateCampaignPageSetup } from '../hooks/useCreateCampaignPageSetup';
import { CatalogSection } from '../components/CatalogSection';
import { StateAutocomplete } from '../components/StateAutocomplete';
import { UNIT_TYPES } from '../constants/unitTypes';
import type { SharedCampaign, SellerProfile } from '../types';

type Profile = Pick<SellerProfile, 'profileId' | 'sellerName' | 'isOwner'>;

// ============================================================================
// Loading & Error States
// ============================================================================

const LoadingState: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="50vh">
    <CircularProgress />
  </Box>
);

const CampaignNotFoundError: React.FC<{ onBack: () => void }> = ({ onBack }) => (
  <Container maxWidth="md" sx={{ py: 3 }}>
    <Button startIcon={<BackIcon />} onClick={onBack} sx={{ mb: 2 }}>
      Back
    </Button>
    <Alert severity="error">
      <AlertTitle>Campaign Not Found</AlertTitle>
      This campaign link is no longer valid. The campaign may have been deactivated or the link may be incorrect.
    </Alert>
  </Container>
);

const CampaignErrorState: React.FC<{ error: Error; onBack: () => void }> = ({ error, onBack }) => (
  <Container maxWidth="md" sx={{ py: 3 }}>
    <Button startIcon={<BackIcon />} onClick={onBack} sx={{ mb: 2 }}>
      Back
    </Button>
    <Alert severity="error">
      <AlertTitle>Error Loading Campaign</AlertTitle>
      {error.message}
    </Alert>
  </Container>
);

// ============================================================================
// Form Sections
// ============================================================================

interface ProfileSectionProps {
  profileId: string;
  onProfileChange: (id: string) => void;
  profiles: Profile[];
  profilesLoading: boolean;
  submitting: boolean;
}

const ProfileSection: React.FC<ProfileSectionProps> = ({
  profileId,
  onProfileChange,
  profiles,
  profilesLoading,
  submitting,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Select Profile *
    </Typography>
    <FormControl fullWidth disabled={submitting}>
      <InputLabel id="profile-select-label">Select Profile</InputLabel>
      <Select
        labelId="profile-select-label"
        value={profileId}
        onChange={(e) => onProfileChange(e.target.value)}
        label="Select Profile"
      >
        {profilesLoading && (
          <MenuItem disabled>
            <CircularProgress size={20} sx={{ mr: 1 }} />
            Loading profiles...
          </MenuItem>
        )}
        {profiles.length === 0 && !profilesLoading && <MenuItem disabled>No profiles available</MenuItem>}
        {profiles.map((profile) => (
          <MenuItem key={profile.profileId} value={profile.profileId}>
            {profile.sellerName}
            {profile.isOwner ? ' (Owner)' : ' (Shared)'}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  </Box>
);

interface CampaignNameYearSectionProps {
  campaignName: string;
  onCampaignNameChange: (value: string) => void;
  campaignYear: number;
  onCampaignYearChange: (value: number) => void;
  submitting: boolean;
}

const CampaignNameYearSection: React.FC<CampaignNameYearSectionProps> = ({
  campaignName,
  onCampaignNameChange,
  campaignYear,
  onCampaignYearChange,
  submitting,
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
          placeholder="e.g., Fall 2026, Spring Fundraiser"
          required
          fullWidth
          disabled={submitting}
        />
        <TextField
          label="Year"
          type="number"
          value={campaignYear}
          onChange={(e) => onCampaignYearChange(parseInt(e.target.value, 10))}
          required
          disabled={submitting}
          sx={{ minWidth: { xs: '100%', sm: 120 } }}
          inputProps={{
            min: 2020,
            max: new Date().getFullYear() + 5,
            step: 1,
          }}
        />
      </Stack>
    </Stack>
  </Box>
);

interface DateRangeSectionProps {
  startDate: string;
  onStartDateChange: (value: string) => void;
  endDate: string;
  onEndDateChange: (value: string) => void;
  submitting: boolean;
  disabled?: boolean;
}

const DateRangeSection: React.FC<DateRangeSectionProps> = ({
  startDate,
  onStartDateChange,
  endDate,
  onEndDateChange,
  submitting,
  disabled = false,
}) => (
  <Box>
    <Typography variant="h6" gutterBottom>
      Campaign Dates (Optional)
    </Typography>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
      <TextField
        fullWidth
        label="Start Date"
        type="date"
        value={startDate}
        onChange={(e) => onStartDateChange(e.target.value)}
        disabled={submitting || disabled}
        InputLabelProps={{ shrink: true }}
      />
      <TextField
        fullWidth
        label="End Date"
        type="date"
        value={endDate}
        onChange={(e) => onEndDateChange(e.target.value)}
        disabled={submitting || disabled}
        InputLabelProps={{ shrink: true }}
      />
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
  submitting: boolean;
  expanded: boolean;
  onExpandChange: (expanded: boolean) => void;
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
  submitting,
  expanded,
  onExpandChange,
}) => {
  const fieldDisabled = submitting || !unitType;

  return (
    <Accordion expanded={expanded} onChange={(_, isExpanded) => onExpandChange(isExpanded)}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography>
          Unit Information (Optional) {unitType && <span> - {unitType} {unitNumber}</span>}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2} sx={{ width: '100%' }}>
          <Alert severity="info">
            Adding unit information enables participation in unit reports and allows coordination with other unit
            members.
          </Alert>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <FormControl fullWidth disabled={submitting}>
              <InputLabel>Unit Type</InputLabel>
              <Select value={unitType} onChange={(e) => onUnitTypeChange(e.target.value)} label="Unit Type">
                {UNIT_TYPES.map((option) => (
                  <MenuItem key={`unit-${option.value}`} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label="Unit Number"
              type="number"
              value={unitNumber}
              onChange={(e) => onUnitNumberChange(e.target.value)}
              disabled={fieldDisabled}
              inputProps={{ min: 1, step: 1 }}
              helperText={unitType ? 'Required' : 'Select unit type first'}
            />
          </Stack>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
            <TextField
              fullWidth
              label="City"
              value={city}
              onChange={(e) => onCityChange(e.target.value)}
              disabled={fieldDisabled}
              helperText={unitType ? 'Required for unit identification' : ''}
            />
            <StateAutocomplete
              value={state}
              onChange={onStateChange}
              disabled={fieldDisabled}
              fullWidth
            />
          </Stack>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
};

interface SharedCampaignSectionProps {
  sharedCampaign: SharedCampaign;
}

const SharedCampaignSection: React.FC<SharedCampaignSectionProps> = ({ sharedCampaign }) => (
  <Box sx={{ bgcolor: 'info.light', p: 2, borderRadius: 1 }}>
    <Typography variant="h6" color="info.dark" gutterBottom>
      Campaign by {sharedCampaign.createdByName}
    </Typography>
    {sharedCampaign.creatorMessage && (
      <Typography variant="body2" sx={{ mb: 2, fontStyle: 'italic' }}>
        "{sharedCampaign.creatorMessage}"
      </Typography>
    )}
    <Stack spacing={1}>
      <TextField fullWidth label="Catalog" value={sharedCampaign.catalog?.catalogName ?? ''} disabled />
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField fullWidth label="Campaign" value={sharedCampaign.campaignName} disabled />
        <TextField fullWidth label="Year" value={sharedCampaign.campaignYear} disabled />
      </Stack>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField fullWidth label="Unit Type" value={sharedCampaign.unitType} disabled />
        <TextField fullWidth label="Unit Number" value={sharedCampaign.unitNumber} disabled />
      </Stack>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <TextField fullWidth label="City" value={sharedCampaign.city} disabled />
        <TextField fullWidth label="State" value={sharedCampaign.state} disabled />
      </Stack>
    </Stack>
  </Box>
);

interface ShareWithCreatorSectionProps {
  shareWithCreator: boolean;
  onShareChange: (share: boolean) => void;
  createdByName: string;
  submitting: boolean;
}

const ShareWithCreatorSection: React.FC<ShareWithCreatorSectionProps> = ({
  shareWithCreator,
  onShareChange,
  createdByName,
  submitting,
}) => (
  <Box sx={{ bgcolor: 'warning.light', p: 2, borderRadius: 1 }}>
    <FormControlLabel
      control={
        <Checkbox
          checked={shareWithCreator}
          onChange={(e) => onShareChange(e.target.checked)}
          disabled={submitting}
        />
      }
      label={`Share this profile with ${createdByName}`}
    />
    <Alert severity="warning" sx={{ mt: 1 }}>
      <AlertTitle>Important</AlertTitle>
      Sharing gives {createdByName} read access to ALL current and future campaigns for this profile. You can revoke
      this access at any time from your profile settings.
    </Alert>
  </Box>
);

interface ActionButtonsSectionProps {
  onBack: () => void;
  onSubmit: () => Promise<void>;
  isSubmitting: boolean;
  isFormValid: boolean;
}

const ActionButtonsSection: React.FC<ActionButtonsSectionProps> = ({
  onBack,
  onSubmit,
  isSubmitting,
  isFormValid,
}) => (
  <Stack direction={{ xs: 'column-reverse', sm: 'row' }} spacing={2} justifyContent="flex-end">
    <Button onClick={onBack} disabled={isSubmitting} fullWidth={false} sx={{ minWidth: { xs: '100%', sm: 120 } }}>
      Cancel
    </Button>
    <Button
      onClick={onSubmit}
      variant="contained"
      disabled={!isFormValid || isSubmitting}
      startIcon={isSubmitting ? <CircularProgress size={16} /> : <SaveIcon />}
      fullWidth={false}
      sx={{ minWidth: { xs: '100%', sm: 120 } }}
    >
      {isSubmitting ? 'Creating...' : 'Create Campaign'}
    </Button>
  </Stack>
);

// ============================================================================
// Main Component
// ============================================================================

export const CreateCampaignPage: React.FC = () => {
  const { sharedCampaignCode } = useParams<{ sharedCampaignCode: string }>();
  const setup = useCreateCampaignPageSetup(sharedCampaignCode);

  // Cleanup aria-hidden on mount
  useEffect(() => {
    const root = document.getElementById('root');
    if (root && root.getAttribute('aria-hidden') === 'true') {
      root.removeAttribute('aria-hidden');
    }
  }, []);

  // Guard states
  const hasSharedCode = Boolean(setup.effectiveSharedCampaignCode);
  const sharedCampaignLoading = hasSharedCode && setup.sharedCampaignLoading;
  const sharedCampaignInactive = hasSharedCode && (!setup.sharedCampaign || !setup.sharedCampaign.isActive);

  // Handle loading
  if (sharedCampaignLoading) return <LoadingState />;

  // Handle error
  if (setup.sharedCampaignError) {
    const error = setup.sharedCampaignError instanceof Error ? setup.sharedCampaignError : new Error(String(setup.sharedCampaignError));
    return <CampaignErrorState error={error} onBack={() => setup.navigate('/scouts')} />;
  }

  // Handle inactive campaign
  if (sharedCampaignInactive) {
    return <CampaignNotFoundError onBack={() => setup.navigate('/scouts')} />;
  }

  const handleSubmitClick = async () => {
    await setup.handleSubmit({
      isSharedCampaignMode: setup.isSharedCampaignMode,
      effectiveSharedCampaignCode: setup.effectiveSharedCampaignCode,
      sharedCampaignCreatedByName: setup.sharedCampaign?.createdByName,
    });
  };

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      {/* Header with back button */}
      <Stack direction="row" alignItems="center" spacing={2} sx={{ mb: 3 }}>
        <Button startIcon={<BackIcon />} onClick={() => setup.navigate('/scouts')} disabled={setup.formState.submitting}>
          Back
        </Button>
        <Typography variant="h4" component="h1">
          Create New Campaign
        </Typography>
      </Stack>

      <Paper sx={{ p: { xs: 2, sm: 3 } }}>
        <Stack spacing={3}>
          {/* Profile Selection - Always visible */}
          <ProfileSection
            profileId={setup.formState.profileId}
            onProfileChange={setup.formState.setProfileId}
            profiles={setup.profiles}
            profilesLoading={setup.profilesLoading}
            submitting={setup.formState.submitting}
          />

          <Divider />

          {/* Shared Campaign Mode */}
          {setup.isSharedCampaignMode && setup.sharedCampaign && (
            <>
              <SharedCampaignSection sharedCampaign={setup.sharedCampaign} />
              <ShareWithCreatorSection
                shareWithCreator={setup.formState.shareWithCreator}
                onShareChange={setup.formState.setShareWithCreator}
                createdByName={setup.sharedCampaign?.createdByName || ''}
                submitting={setup.formState.submitting}
              />
            </>
          )}

          {/* Manual Campaign Mode */}
          {!setup.isSharedCampaignMode && (
            <>
              <CatalogSection
                catalogId={setup.formState.catalogId}
                onCatalogChange={setup.formState.setCatalogId}
                catalogsLoading={setup.catalogsLoading}
                myCatalogs={setup.filteredMyCatalogs}
                filteredPublicCatalogs={setup.filteredPublicCatalogs}
              />

              <Divider />

              <CampaignNameYearSection
                campaignName={setup.formState.campaignName}
                onCampaignNameChange={setup.formState.setCampaignName}
                campaignYear={setup.formState.campaignYear}
                onCampaignYearChange={setup.formState.setCampaignYear}
                submitting={setup.formState.submitting}
              />

              <Divider />

              <UnitInfoSection
                unitType={setup.formState.unitType}
                onUnitTypeChange={setup.formState.setUnitType}
                unitNumber={setup.formState.unitNumber}
                onUnitNumberChange={setup.formState.setUnitNumber}
                city={setup.formState.city}
                onCityChange={setup.formState.setCity}
                state={setup.formState.state}
                onStateChange={setup.formState.setState}
                submitting={setup.formState.submitting}
                expanded={setup.formState.unitSectionExpanded}
                onExpandChange={setup.formState.setUnitSectionExpanded}
              />
            </>
          )}

          {/* Date Range - Show for all modes */}
          <Divider />

          <DateRangeSection
            startDate={setup.formState.startDate}
            onStartDateChange={setup.formState.setStartDate}
            endDate={setup.formState.endDate}
            onEndDateChange={setup.formState.setEndDate}
            submitting={setup.formState.submitting}
            disabled={setup.isSharedCampaignMode}
          />

          <Divider />

          {/* Action Buttons */}
          <ActionButtonsSection
            onBack={() => setup.navigate('/scouts')}
            onSubmit={handleSubmitClick}
            isSubmitting={setup.formState.submitting}
            isFormValid={setup.isFormValid}
          />
        </Stack>
      </Paper>

      {/* Toast for feedback */}
      {setup.formState.toastMessage && (
        <Alert severity={setup.formState.toastMessage.severity} sx={{ mt: 2 }}>
          {setup.formState.toastMessage.message}
        </Alert>
      )}
    </Container>
  );
};
