/**
 * Save / disable / rotate controls for the public order settings.
 *
 * Save stays disabled while a save is in flight and while the acknowledgements
 * are required but not both checked. Rotate is offered whenever a token exists
 * (including while disabled — rotating a parked link is legal and is the only
 * revocation path), and Disable keeps the token so the URL stays stable.
 */

import { Button, Stack } from '@mui/material';

interface PublicSettingsActionsProps {
  saveDisabled: boolean;
  enabled: boolean;
  hasToken: boolean;
  onSave: () => void;
  onDisable: () => void;
  onRotate: () => void;
}

export const PublicSettingsActions: React.FC<PublicSettingsActionsProps> = ({
  saveDisabled,
  enabled,
  hasToken,
  onSave,
  onDisable,
  onRotate,
}) => (
  <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
    <Button variant="contained" onClick={onSave} disabled={saveDisabled} data-testid="save-settings">
      Save
    </Button>
    {enabled ? (
      <Button onClick={onDisable} data-testid="disable-public-orders">
        Disable
      </Button>
    ) : null}
    {hasToken ? (
      <Button onClick={onRotate} data-testid="rotate-token">
        Rotate link
      </Button>
    ) : null}
  </Stack>
);

export default PublicSettingsActions;
