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
import type { SettingsActionMessage } from '../../hooks/usePublicOrderSettings';
import { ErrorAlert } from '../ErrorAlert';

export const CAMPAIGN_MISSING_COPY =
  'The campaign this link points to no longer exists. Pick a new campaign to accept public orders again.';
export const CAMPAIGN_INACTIVE_COPY =
  'The linked campaign is deactivated. Buyers see “not available” until you pick an active campaign.';

interface PublicSettingsMessagesProps {
  campaignState: string | null | undefined;
  actionMessage: SettingsActionMessage;
}

export const PublicSettingsMessages: React.FC<PublicSettingsMessagesProps> = ({ campaignState, actionMessage }) => {
  // A staleness flag never replaces feedback for the action the seller just
  // took: a failed save or rotate must show its error next to the warning, and
  // a successful one its confirmation. Success and failure are states of one
  // message model, so they can never shadow each other.
  const staleness =
    campaignState === 'MISSING' ? (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="campaign-missing">
        {CAMPAIGN_MISSING_COPY}
      </Alert>
    ) : campaignState === 'INACTIVE' ? (
      <Alert severity="warning" sx={{ mb: 2 }} data-testid="campaign-inactive">
        {CAMPAIGN_INACTIVE_COPY}
      </Alert>
    ) : null;

  const feedback =
    actionMessage.kind === 'failed' ? (
      <ErrorAlert message={actionMessage.message} />
    ) : actionMessage.kind === 'saved' ? (
      <Alert severity="success" sx={{ mb: 2 }} data-testid="settings-saved">
        Public order settings saved.
      </Alert>
    ) : null;

  if (!staleness) return feedback;
  if (!feedback) return staleness;
  return (
    <>
      {staleness}
      {feedback}
    </>
  );
};

export default PublicSettingsMessages;
