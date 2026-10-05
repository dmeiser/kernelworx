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

export const REFRESH_FAILED_COPY =
  'Your settings were saved, but we could not refresh the page. Reload to see the latest values.';
export const UNSAVED_CHANGES_COPY = 'You have unsaved changes.';
export const CAMPAIGN_MISSING_COPY =
  'The campaign this link points to no longer exists. Pick a new campaign to accept public orders again.';
export const CAMPAIGN_INACTIVE_COPY =
  'The linked campaign is deactivated. Buyers see “not available” until you pick an active campaign.';

interface PublicSettingsMessagesProps {
  campaignState: string | null | undefined;
  actionMessage: SettingsActionMessage;
}

/** A staleness flag must be surfaced next to any action feedback, never instead of it. */
function stalenessNotice(campaignState: string | null | undefined) {
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
  return null;
}

/** The retryable refresh-failed notice rides every confirmation kind. */
function refreshFailedNotice() {
  return (
    <Alert severity="warning" sx={{ mb: 2 }} data-testid="refresh-failed">
      {REFRESH_FAILED_COPY}
    </Alert>
  );
}

/** Success and failure are states of one message model and never shadow each other. */
function savedFeedback(actionMessage: Extract<SettingsActionMessage, { kind: 'saved' }>) {
  if (!actionMessage.refreshFailed) {
    return (
      <Alert severity="success" sx={{ mb: 2 }} data-testid="settings-saved">
        Public order settings saved.
      </Alert>
    );
  }
  return (
    <>
      <Alert severity="success" sx={{ mb: 2 }} data-testid="settings-saved">
        Public order settings saved.
      </Alert>
      {refreshFailedNotice()}
    </>
  );
}

function actionFeedback(actionMessage: SettingsActionMessage) {
  if (actionMessage.kind === 'failed') return <ErrorAlert message={actionMessage.message} />;
  if (actionMessage.kind === 'saved') return savedFeedback(actionMessage);
  if (actionMessage.kind === 'unsaved') {
    return (
      <>
        <Alert severity="info" sx={{ mb: 2 }} data-testid="unsaved-changes">
          {UNSAVED_CHANGES_COPY}
        </Alert>
        {actionMessage.refreshFailed ? refreshFailedNotice() : null}
      </>
    );
  }
  return null;
}

export const PublicSettingsMessages: React.FC<PublicSettingsMessagesProps> = ({ campaignState, actionMessage }) => {
  const staleness = stalenessNotice(campaignState);
  const feedback = actionFeedback(actionMessage);

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
