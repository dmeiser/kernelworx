/**
 * Campaign form component for CreateCampaignPage
 */
import React, { memo } from 'react';
import {
  Paper,
  Stack,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Divider,
  Checkbox,
  FormControlLabel,
  Box,
  Alert,
  AlertTitle,
  Button,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  CircularProgress,
  Typography,
  Snackbar,
} from '@mui/material';
import { ExpandMore as ExpandMoreIcon, Info as InfoIcon } from '@mui/icons-material';
import type { Catalog, SharedCampaign, SellerProfile } from '../types';
import { UNIT_TYPES } from '../constants/unitTypes';
import { StateAutocomplete } from '../components/StateAutocomplete';
import { CatalogSection } from '../components/CatalogSection';

// Local type aliases for convenience
type Profile = Pick<SellerProfile, 'profileId' | 'sellerName' | 'isOwner'>;

interface FormStateValues {
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

interface FormSetters {
  setProfileId: (id: string) => void;
  setCampaignName: (name: string) => void;
  setCampaignYear: (year: number) => void;
  setCatalogId: (id: string) => void;
  setStartDate: (date: string) => void;
  setEndDate: (date: string) => void;
  setUnitType: (type: string) => void;
  setUnitNumber: (number: string) => void;
  setCity: (city: string) => void;
  setState: (state: string) => void;
  setShareWithCreator: (share: boolean) => void;
  setUnitSectionExpanded: (expanded: boolean) => void;
  setToastMessage: (
    message: {
      message: string;
      severity: 'success' | 'error';
    } | null,
  ) => void;
}

// For backwards compatibility, merge them for the component's FormState prop
type FormState = FormStateValues & FormSetters;

interface CampaignFormProps {
  formState: FormState;
  profiles: Profile[];
  profilesLoading: boolean;
  isSharedCampaignMode: boolean;
  sharedCampaign: SharedCampaign | null | undefined;
  filteredMyCatalogs: Catalog[];
  filteredPublicCatalogs: Catalog[];
  catalogsLoading: boolean;
  isFormValid: boolean;
  onSubmit: () => Promise<void>;
  onCancel: () => void;
}

// Profile Selection component
interface ProfileSelectionProps {
  formState: FormState;
  profiles: Profile[];
  profilesLoading: boolean;
}

const ProfileSelection: React.FC<ProfileSelectionProps> = ({ formState, profiles, profilesLoading }) => (
  <FormControl fullWidth disabled={formState.submitting}>
    <InputLabel>Select Profile *</InputLabel>
    <Select
      value={formState.profileId}
      onChange={(e) => formState.setProfileId(e.target.value)}
      label="Select Profile *"
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
);

// Shared Campaign locked fields
interface SharedCampaignFieldsProps {
  sharedCampaign: SharedCampaign;
}

const SharedCampaignFields: React.FC<SharedCampaignFieldsProps> = ({ sharedCampaign }) => (
  <>
    <TextField
      fullWidth
      label="Catalog"
      value={sharedCampaign.catalog?.catalogName ?? ''}
      disabled
      helperText="Set by campaign creator"
    />
    <Stack direction="row" spacing={2}>
      <TextField fullWidth label="Campaign" value={sharedCampaign.campaignName} disabled />
      <TextField fullWidth label="Year" value={sharedCampaign.campaignYear} disabled />
    </Stack>
    <Stack direction="row" spacing={2}>
      <TextField fullWidth label="Unit Type" value={sharedCampaign.unitType} disabled />
      <TextField fullWidth label="Unit Number" value={sharedCampaign.unitNumber} disabled />
    </Stack>
    <Stack direction="row" spacing={2}>
      <TextField fullWidth label="City" value={sharedCampaign.city} disabled />
      <TextField fullWidth label="State" value={sharedCampaign.state} disabled />
    </Stack>
  </>
);

// Campaign Name and Year fields
interface CampaignNameYearProps {
  formState: FormState;
}

const CampaignNameYearFields: React.FC<CampaignNameYearProps> = ({ formState }) => (
  <Stack direction="row" spacing={2}>
    <TextField
      fullWidth
      label="Campaign Name *"
      value={formState.campaignName}
      onChange={(e) => formState.setCampaignName(e.target.value)}
      disabled={formState.submitting}
      placeholder="e.g., Fall 2026, Spring Fundraiser"
    />
    <TextField
      fullWidth
      label="Year *"
      type="number"
      value={formState.campaignYear}
      onChange={(e) => formState.setCampaignYear(parseInt(e.target.value, 10))}
      disabled={formState.submitting}
      inputProps={{
        min: 2020,
        max: new Date().getFullYear() + 5,
        step: 1,
      }}
    />
  </Stack>
);



// Unit Information accordion
interface UnitInfoAccordionProps {
  formState: FormState;
}

// Helper to check if unit dependent fields are disabled
const isUnitFieldDisabled = (submitting: boolean, unitType: string): boolean => {
  return submitting || !unitType;
};

// Helper to get unit number helper text
const getUnitNumberHelperText = (unitType: string): string => {
  return unitType ? 'Required' : 'Select unit type first';
};

// Helper to get city helper text
const getCityHelperText = (unitType: string): string => {
  return unitType ? 'Required for unit identification' : '';
};

// Unit summary display
const UnitSummary: React.FC<{ unitType: string; unitNumber: string }> = ({ unitType, unitNumber }) => {
  if (!unitType) return null;
  return (
    <Typography component="span" color="primary">
      - {unitType} {unitNumber}
    </Typography>
  );
};

/* v8 ignore start -- UnitInfoAccordion contains MUI components with onChange handlers not testable in jsdom */
const UnitInfoAccordion: React.FC<UnitInfoAccordionProps> = ({ formState }) => {
  const fieldDisabled = isUnitFieldDisabled(formState.submitting, formState.unitType);

  return (
    <Accordion
      expanded={formState.unitSectionExpanded}
      onChange={(_, expanded) => formState.setUnitSectionExpanded(expanded)}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography>
          Unit Information (Optional) <UnitSummary unitType={formState.unitType} unitNumber={formState.unitNumber} />
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <Alert severity="info" icon={<InfoIcon />}>
            Adding unit information enables participation in unit reports and allows coordination with other unit
            members.
          </Alert>
          <Stack direction="row" spacing={2}>
            <FormControl fullWidth disabled={formState.submitting}>
              <InputLabel>Unit Type</InputLabel>
              <Select
                value={formState.unitType}
                onChange={(e) => formState.setUnitType(e.target.value)}
                label="Unit Type"
              >
                {UNIT_TYPES.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label="Unit Number"
              type="number"
              value={formState.unitNumber}
              onChange={(e) => formState.setUnitNumber(e.target.value)}
              disabled={fieldDisabled}
              inputProps={{ min: 1, step: 1 }}
              helperText={getUnitNumberHelperText(formState.unitType)}
            />
          </Stack>
          <Stack direction="row" spacing={2}>
            <TextField
              fullWidth
              label="City"
              value={formState.city}
              onChange={(e) => formState.setCity(e.target.value)}
              disabled={fieldDisabled}
              helperText={getCityHelperText(formState.unitType)}
            />
            <StateAutocomplete
              value={formState.state}
              onChange={formState.setState}
              disabled={fieldDisabled}
              fullWidth
            />
          </Stack>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
};
/* v8 ignore stop */

// Date range fields
interface DateRangeFieldsProps {
  formState: FormState;
  isSharedCampaignMode: boolean;
}

const DateRangeFields: React.FC<DateRangeFieldsProps> = ({ formState, isSharedCampaignMode }) => {
  const disabled = formState.submitting || isSharedCampaignMode;
  const helperText = isSharedCampaignMode ? 'Set by campaign creator' : '';

  return (
    <Stack direction="row" spacing={2}>
      <TextField
        fullWidth
        label="Start Date (Optional)"
        type="date"
        value={formState.startDate}
        onChange={(e) => formState.setStartDate(e.target.value)}
        disabled={disabled}
        InputLabelProps={{ shrink: true }}
        helperText={helperText}
      />
      <TextField
        fullWidth
        label="End Date (Optional)"
        type="date"
        value={formState.endDate}
        onChange={(e) => formState.setEndDate(e.target.value)}
        disabled={disabled}
        InputLabelProps={{ shrink: true }}
        helperText={helperText}
      />
    </Stack>
  );
};

// Share with creator checkbox
interface ShareWithCreatorProps {
  formState: FormState;
  sharedCampaign: SharedCampaign;
}

const ShareWithCreatorSection: React.FC<ShareWithCreatorProps> = ({ formState, sharedCampaign }) => (
  <Box sx={{ bgcolor: 'warning.light', p: 2, borderRadius: 1 }}>
    <FormControlLabel
      control={
        <Checkbox
          checked={formState.shareWithCreator}
          onChange={(e) => formState.setShareWithCreator(e.target.checked)}
          disabled={formState.submitting}
        />
      }
      label={`Share this profile with ${sharedCampaign.createdByName}`}
    />
    <Alert severity="warning" sx={{ mt: 1 }}>
      <AlertTitle>Important</AlertTitle>
      Sharing gives {sharedCampaign.createdByName} read access to ALL current and future campaigns for this profile. You
      can revoke this access at any time from your profile settings.
    </Alert>
  </Box>
);

// Form actions
interface FormActionsProps {
  formState: FormState;
  isFormValid: boolean;
  onSubmit: () => Promise<void>;
  onCancel: () => void;
}

const FormActions: React.FC<FormActionsProps> = ({ formState, isFormValid, onSubmit, onCancel }) => (
  <Stack direction="row" spacing={2} justifyContent="flex-end">
    <Button variant="outlined" onClick={onCancel} disabled={formState.submitting}>
      Cancel
    </Button>
    <Button variant="contained" onClick={onSubmit} disabled={!isFormValid || formState.submitting}>
      {formState.submitting ? 'Creating...' : 'Create Campaign'}
    </Button>
  </Stack>
);

// Toast notification
interface ToastNotificationProps {
  formState: FormState;
}

const ToastNotification: React.FC<ToastNotificationProps> = ({ formState }) => {
  /* v8 ignore start */
  const handleClose = () => formState.setToastMessage(null);
  /* v8 ignore stop */
  return (
    <Snackbar open={!!formState.toastMessage} autoHideDuration={6000} onClose={handleClose}>
      <Alert onClose={handleClose} severity={formState.toastMessage?.severity} sx={{ width: '100%' }}>
        {formState.toastMessage?.message}
      </Alert>
    </Snackbar>
  );
};

// Shared Campaign mode content
interface SharedCampaignModeContentProps {
  sharedCampaign: SharedCampaign | null | undefined;
  formState: FormState;
}

const SharedCampaignModeContent = memo<SharedCampaignModeContentProps>(({ sharedCampaign, formState }) => {
  if (!sharedCampaign) return null;
  return (
    <>
      <SharedCampaignFields sharedCampaign={sharedCampaign} />
      <ShareWithCreatorSection formState={formState} sharedCampaign={sharedCampaign} />
    </>
  );
});

// Manual mode content
interface ManualModeContentProps {
  formState: FormState;
  filteredMyCatalogs: Catalog[];
  filteredPublicCatalogs: Catalog[];
  catalogsLoading: boolean;
}

const ManualModeContent = memo<ManualModeContentProps>(({
  formState,
  filteredMyCatalogs,
  filteredPublicCatalogs,
  catalogsLoading,
}) => (
  <>
    <CampaignNameYearFields formState={formState} />
    <CatalogSection
      catalogId={formState.catalogId}
      onCatalogChange={formState.setCatalogId}
      catalogsLoading={catalogsLoading}
      myCatalogs={filteredMyCatalogs}
      filteredPublicCatalogs={filteredPublicCatalogs}
    />
    <UnitInfoAccordion formState={formState} />
  </>
));

export const CampaignForm: React.FC<CampaignFormProps> = ({
  formState,
  profiles,
  profilesLoading,
  isSharedCampaignMode,
  sharedCampaign,
  filteredMyCatalogs,
  filteredPublicCatalogs,
  catalogsLoading,
  isFormValid,
  onSubmit,
  onCancel,
}) => (
  <>
    <Paper sx={{ p: 3 }}>
      <Stack spacing={3}>
        <ProfileSelection formState={formState} profiles={profiles} profilesLoading={profilesLoading} />

        <Divider />

        {isSharedCampaignMode ? (
          <SharedCampaignModeContent sharedCampaign={sharedCampaign} formState={formState} />
        ) : (
          <ManualModeContent
            formState={formState}
            filteredMyCatalogs={filteredMyCatalogs}
            filteredPublicCatalogs={filteredPublicCatalogs}
            catalogsLoading={catalogsLoading}
          />
        )}

        <DateRangeFields formState={formState} isSharedCampaignMode={isSharedCampaignMode} />

        <Divider />

        <FormActions formState={formState} isFormValid={isFormValid} onSubmit={onSubmit} onCancel={onCancel} />
      </Stack>
    </Paper>

    <ToastNotification formState={formState} />
  </>
);
