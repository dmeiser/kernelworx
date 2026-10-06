/**
 * Save / disable / rotate controls for the public order settings.
 *
 * Every mutating control is disabled and visibly pending while one settings
 * action is outstanding: exactly one save/rotate/disable may be in flight.
 * Rotate is offered whenever a token exists (including while disabled —
 * rotating a parked link is legal and is the only revocation path), and Disable
 * keeps the token so the URL stays stable.
 */

import { Button, Stack } from '@mui/material';

interface PublicSettingsActionsProps {
  saveDisabled: boolean;
  submitting: boolean;
  enabled: boolean;
  hasToken: boolean;
  onSave: () => void;
  onDisable: () => void;
  onRotate: () => void;
}

export const PublicSettingsActions: React.FC<PublicSettingsActionsProps> = ({
  saveDisabled,
  submitting,
  enabled,
  hasToken,
  onSave,
  onDisable,
  onRotate,
}) => (
  <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
    <Button variant="contained" onClick={onSave} disabled={saveDisabled} data-testid="save-settings">
      {submitting ? 'Saving…' : 'Save'}
    </Button>
    {enabled ? (
      <Button onClick={onDisable} disabled={submitting} data-testid="disable-public-orders">
        Disable
      </Button>
    ) : null}
    {hasToken ? (
      <Button onClick={onRotate} disabled={submitting} data-testid="rotate-token">
        {submitting ? 'Working…' : 'Rotate link'}
      </Button>
    ) : null}
  </Stack>
);

export default PublicSettingsActions;
