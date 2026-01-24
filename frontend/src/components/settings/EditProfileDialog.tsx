/**
 * Edit Profile Dialog component for User Settings
 */
import { Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField, Stack, MenuItem } from '@mui/material';
import type { UseProfileEditReturn } from '../../hooks/useProfileEdit';

interface EditProfileDialogProps {
  profileHook: UseProfileEditReturn;
  updating: boolean;
  onSave: () => void;
}

export const EditProfileDialog: React.FC<EditProfileDialogProps> = ({ profileHook, updating, onSave }) => {
  return (
    <Dialog
      open={profileHook.editDialogOpen}
      onClose={() => profileHook.setEditDialogOpen(false)}
      maxWidth="sm"
      fullWidth
    >
      <DialogTitle>Edit Profile Information</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <TextField
            label="First Name"
            value={profileHook.givenName}
            onChange={(e) => profileHook.setGivenName(e.target.value)}
            fullWidth
            helperText="Optional"
          />
          <TextField
            label="Last Name"
            value={profileHook.familyName}
            onChange={(e) => profileHook.setFamilyName(e.target.value)}
            fullWidth
            helperText="Optional"
          />
          <TextField
            label="City"
            value={profileHook.city}
            onChange={(e) => profileHook.setCity(e.target.value)}
            fullWidth
            helperText="Optional"
          />
          <TextField
            label="State"
            value={profileHook.state}
            onChange={(e) => profileHook.setState(e.target.value.toUpperCase())}
            fullWidth
            helperText="Optional (e.g., CA, TX, NY)"
            inputProps={{ maxLength: 2 }}
          />
          <TextField
            select
            label="Unit Type"
            value={profileHook.unitType}
            onChange={(e) => profileHook.setUnitType(e.target.value)}
            fullWidth
            helperText="Optional"
          >
            <MenuItem value="">None</MenuItem>
            <MenuItem value="Pack">Pack</MenuItem>
            <MenuItem value="Troop">Troop</MenuItem>
            <MenuItem value="Crew">Crew</MenuItem>
            <MenuItem value="Ship">Ship</MenuItem>
            <MenuItem value="Post">Post</MenuItem>
            <MenuItem value="Club">Club</MenuItem>
          </TextField>
          <TextField
            label="Unit Number"
            type="number"
            value={profileHook.unitNumber}
            onChange={(e) => profileHook.setUnitNumber(e.target.value)}
            fullWidth
            helperText="Optional"
            inputProps={{ min: 1, step: 1 }}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => profileHook.setEditDialogOpen(false)} disabled={updating}>
          Cancel
        </Button>
        <Button onClick={onSave} variant="contained" disabled={updating}>
          {updating ? 'Saving...' : 'Save Changes'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
