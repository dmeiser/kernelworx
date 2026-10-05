/**
 * The "no email was entered" choice shown before submitting a public order.
 *
 * Both paths matter: "go back" must return to the form with everything the
 * buyer already typed intact (losing a filled-in form to a confirmation dialog
 * is how buyers give up), and "continue" must be an explicit acknowledgement
 * that no confirmation email — and therefore no receipt link — will exist.
 */

import { Button, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle } from '@mui/material';

export const NO_EMAIL_WARNING = 'You will not receive a confirmation email.';

interface NoEmailConfirmDialogProps {
  open: boolean;
  onGoBack: () => void;
  onContinue: () => void;
}

export const NoEmailConfirmDialog: React.FC<NoEmailConfirmDialogProps> = ({ open, onGoBack, onContinue }) => (
  <Dialog open={open} onClose={onGoBack} aria-labelledby="no-email-dialog-title">
    <DialogTitle id="no-email-dialog-title">{NO_EMAIL_WARNING}</DialogTitle>
    <DialogContent>
      <DialogContentText>
        Without an email address we cannot send you a copy of this order or a link to your receipt.
      </DialogContentText>
    </DialogContent>
    <DialogActions>
      <Button onClick={onGoBack} data-testid="no-email-go-back">
        Go back and add email
      </Button>
      <Button onClick={onContinue} variant="contained" data-testid="no-email-continue">
        Continue without email
      </Button>
    </DialogActions>
  </Dialog>
);

export default NoEmailConfirmDialog;
