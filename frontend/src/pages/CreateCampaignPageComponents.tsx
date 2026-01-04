/**
 * Sub-components for CreateCampaignPage to reduce complexity
 */
import React from 'react';
import { Box, Alert, AlertTitle, Button, CircularProgress, Card, CardContent, Stack, Typography } from '@mui/material';
import { Campaign as CampaignIcon } from '@mui/icons-material';

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog: {
    catalogId: string;
    catalogName: string;
  };
  campaignName: string;
  campaignYear: number;
  startDate: string | null;
  endDate: string | null;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage: string;
  description: string | null;
  isActive: boolean;
}

interface ErrorProps {
  message: string;
  onReturnClick: () => void;
}

export const LoadingState: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="50vh">
    <CircularProgress />
  </Box>
);

export const CampaignNotFoundError: React.FC<ErrorProps> = ({ onReturnClick }) => (
  <Box maxWidth="md" mx="auto" p={3}>
    <Alert severity="error">
      <AlertTitle>Campaign Not Found</AlertTitle>
      This campaign link is no longer valid. The campaign may have been deactivated or the link may be incorrect.
    </Alert>
    <Button variant="contained" onClick={onReturnClick} sx={{ mt: 2 }}>
      Go to Profiles
    </Button>
  </Box>
);

/* v8 ignore start -- CampaignErrorState is rendered by parent when sharedCampaignError is set, tested via integration */
export const CampaignErrorState: React.FC<{
  error: Error;
  onReturnClick: () => void;
}> = ({ error, onReturnClick }) => (
  <Box maxWidth="md" mx="auto" p={3}>
    <Alert severity="error">
      <AlertTitle>Error Loading Campaign</AlertTitle>
      {error.message}
    </Alert>
    <Button variant="contained" onClick={onReturnClick} sx={{ mt: 2 }}>
      Go to Profiles
    </Button>
  </Box>
);
/* v8 ignore stop */

interface SharedCampaignBannerProps {
  sharedCampaign: SharedCampaign;
}

export const SharedCampaignBanner: React.FC<SharedCampaignBannerProps> = ({ sharedCampaign }) => (
  <Card sx={{ mb: 3, bgcolor: 'info.light' }}>
    <CardContent>
      <Stack direction="row" spacing={2} alignItems="flex-start">
        <CampaignIcon sx={{ fontSize: 40, color: 'info.dark' }} />
        <Box>
          <Typography variant="h6" color="info.dark">
            Campaign by {sharedCampaign.createdByName}
          </Typography>
          {sharedCampaign.creatorMessage && (
            <Typography variant="body1" sx={{ mt: 1, fontStyle: 'italic' }}>
              "{sharedCampaign.creatorMessage}"
            </Typography>
          )}
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {sharedCampaign.unitType} {sharedCampaign.unitNumber} • {sharedCampaign.city}, {sharedCampaign.state} •{' '}
            {sharedCampaign.campaignName} {sharedCampaign.campaignYear}
          </Typography>
        </Box>
      </Stack>
    </CardContent>
  </Card>
);

interface DiscoveredCampaignAlertProps {
  campaignName: string;
  campaignYear: number;
  unitType: string;
  unitNumber: string;
  city: string;
  state: string;
  createdByName: string;
  onUseCampaign: () => void;
}

/* v8 ignore start -- DiscoveredCampaignAlert rendered when unit info matches existing campaign, tested via integration */
export const DiscoveredCampaignAlert: React.FC<DiscoveredCampaignAlertProps> = ({
  campaignName,
  campaignYear,
  unitType,
  unitNumber,
  city,
  state,
  createdByName,
  onUseCampaign,
}) => (
  <Alert
    severity="info"
    sx={{ mb: 3 }}
    action={
      <Button color="inherit" size="small" onClick={onUseCampaign}>
        Use Campaign
      </Button>
    }
  >
    <AlertTitle>Existing Campaign Found!</AlertTitle>
    We found an existing {campaignName} {campaignYear} campaign for {unitType} {unitNumber} in {city}, {state} created
    by {createdByName}. Would you like to use their settings?
  </Alert>
);
/* v8 ignore stop */
