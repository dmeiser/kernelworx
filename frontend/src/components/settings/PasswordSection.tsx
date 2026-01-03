/**
 * Password change section for User Settings
 */
import { Paper, Stack, Typography, TextField, Button, Alert, CircularProgress } from '@mui/material';
import { VpnKey as PasswordIcon } from '@mui/icons-material';
import type { UsePasswordChangeReturn } from '../../hooks/usePasswordChange';

interface PasswordSectionProps {
  hook: UsePasswordChangeReturn;
}

export const PasswordSection: React.FC<PasswordSectionProps> = ({ hook }) => {
  return (
    <Paper sx={{ p: 3, mb: 3 }}>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
        <PasswordIcon color="primary" />
        <Typography variant="h6">Change Password</Typography>
      </Stack>

      <Typography variant="body2" color="text.secondary" paragraph>
        Update your password to keep your account secure. Use a strong password with at least 8 characters.
      </Typography>

      {hook.passwordSuccess && (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => hook.setPasswordSuccess(false)}>
          Password changed successfully!
        </Alert>
      )}

      {hook.passwordError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => hook.setPasswordError(null)}>
          {hook.passwordError}
        </Alert>
      )}

      <form onSubmit={hook.handlePasswordChange}>
        <Stack spacing={2}>
          <TextField
            label="Current Password"
            type="password"
            value={hook.currentPassword}
            onChange={(e) => hook.setCurrentPassword(e.target.value)}
            required
            fullWidth
            disabled={hook.passwordLoading}
            autoComplete="current-password"
          />
          <TextField
            label="New Password"
            type="password"
            value={hook.newPassword}
            onChange={(e) => hook.setNewPassword(e.target.value)}
            required
            fullWidth
            disabled={hook.passwordLoading}
            autoComplete="new-password"
            helperText="At least 8 characters with uppercase, lowercase, numbers, and symbols"
          />
          <TextField
            label="Confirm New Password"
            type="password"
            value={hook.confirmPassword}
            onChange={(e) => hook.setConfirmPassword(e.target.value)}
            required
            fullWidth
            disabled={hook.passwordLoading}
            autoComplete="new-password"
          />
          <Button type="submit" variant="contained" disabled={hook.passwordLoading} sx={{ alignSelf: 'flex-start' }}>
            {hook.passwordLoading ? <CircularProgress size={24} /> : 'Change Password'}
          </Button>
        </Stack>
      </form>
    </Paper>
  );
};
