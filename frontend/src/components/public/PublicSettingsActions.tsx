/**
 * Action buttons for public order settings.
 *
 * Enable is additionally gated on `canEnable`: the server rejects
 * `enabled: true` with an empty method list or unaccepted acknowledgements,
 * so the button stays disabled until both prerequisites are met instead of
 * surfacing an error the seller cannot act on.
 */
import { Box, Button, Stack, Typography } from '@mui/material';

interface PublicSettingsActionsProps {
  onSave: () => void;
  enabled: boolean;
  onRotate: () => void;
  onDisable: () => void;
  onEnable: () => void;
  saving: boolean;
  /** Whether the enable prerequisites (acks + at least one method) are met. */
  canEnable?: boolean;
  /** Whether the save prerequisites are met. Defaults to true. */
  canSave?: boolean;
}

type SettingsAction = 'save' | 'enable' | 'disable';

/** The target-state or prerequisite check for save/enable/disable. */
const isActionBlocked = (action: SettingsAction, enabled: boolean, canEnable: boolean, canSave: boolean): boolean => {
  switch (action) {
    case 'enable':
      return enabled || !canEnable;
    case 'disable':
      return !enabled;
    case 'save':
      return !canSave;
  }
};

/** The save/enable/disable actions share disable rules: in flight, or unmet prerequisites / target state. */
const actionDisabled = (
  action: SettingsAction,
  saving: boolean,
  enabled: boolean,
  canEnable: boolean,
  canSave: boolean,
): boolean => saving || isActionBlocked(action, enabled, canEnable, canSave);

const rotateDisabled = (saving: boolean): boolean => saving;

const actionLabel = (saving: boolean, label: string): string => (saving ? 'Saving...' : label);

export const PublicSettingsActions: React.FC<PublicSettingsActionsProps> = ({
  enabled,
  onRotate,
  onDisable,
  onEnable,
  onSave,
  saving,
  canEnable = true,
  canSave = true,
}) => {
  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" gutterBottom>
        Actions
      </Typography>
      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <Button variant="contained" onClick={onSave} disabled={actionDisabled('save', saving, enabled, canEnable, canSave)}>
          {actionLabel(saving, 'Save')}
        </Button>
        <Button variant="contained" onClick={onEnable} disabled={actionDisabled('enable', saving, enabled, canEnable, canSave)}>
          {actionLabel(saving, 'Enable')}
        </Button>
        <Button
          variant="contained"
          onClick={onDisable}
          disabled={actionDisabled('disable', saving, enabled, canEnable, canSave)}
        >
          {actionLabel(saving, 'Disable')}
        </Button>
        <Button variant="outlined" onClick={onRotate} disabled={rotateDisabled(saving)}>
          Rotate Share Token
        </Button>
      </Stack>
    </Box>
  );
};
