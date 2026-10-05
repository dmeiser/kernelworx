/**
 * Status messaging for the public order settings surface.
 *
 * `campaignState` is the server's staleness flag on the settings read: MISSING
 * covers a deleted anchor (including a pointer left by a partial delete the
 * auto-disable step never reached) and INACTIVE a deactivated one. Both must be
 * surfaced, because a live share link over a dead anchor reads to the buyer as
 * a broken link rather than as a seller-side configuration problem.
 */

import { Alert } from '@mui/material';
import { ErrorAlert } from '../ErrorAlert';

export const CAMPAIGN_MISSING_COPY =
  'The campaign this link points to no longer exists. Pick a new campaign to accept public orders again.';
export const CAMPAIGN_INACTIVE_COPY =
  'The linked campaign is deactivated. Buyers see “not available” until you pick an active campaign.';

interface PublicSettingsMessagesProps {
  campaignState: string | null | undefined;
  actionError: string | null;
  savedOnce: boolean;
}

export const PublicSettingsMessages: React.FC<PublicSettingsMessagesProps> = ({ campaignState, actionError, savedOnce }) => {
  if (campaignState === 'MISSING') {
    return (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="campaign-missing">
        {CAMPAIGN_MISSING_COPY}
      </Alert>
    );
  }
  if (campaignState === 'INACTIVE') {
    return (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="campaign-inactive">
        {CAMPAIGN_INACTIVE_COPY}
      </Alert>
    );
  }
  if (actionError) return <ErrorAlert message={actionError} />;
  if (savedOnce) {
    return (
      <Alert severity="success" sx={{ mb: 2 }} data-testid="settings-saved">
        Public order settings saved.
      </Alert>
    );
  }
  return null;
};

export default PublicSettingsMessages;
