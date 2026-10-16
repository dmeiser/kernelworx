/**
 * Generic "this link is not usable" state for the public order pages.
 *
 * The server answers a bad token, a disabled profile, a stale campaign and a
 * deleted order with the identical NOT_FOUND, so the copy must stay equally
 * generic: it must not leak which of those it was, and it must not show any
 * seller data.
 */

import { Alert, Box, Typography } from '@mui/material';

export const PUBLIC_UNAVAILABLE_TITLE = 'This order link is not available.';
export const PUBLIC_UNAVAILABLE_BODY =
  'The link may have expired, the seller may have stopped accepting public orders, or the address may be mistyped. Please ask the seller for a new link.';

export const PublicPageUnavailable: React.FC = () => (
  <Box sx={{ maxWidth: 600, mx: 'auto', py: 4 }}>
    <Alert severity="warning" sx={{ mb: 2 }}>
      <Typography variant="subtitle1" fontWeight="medium">
        {PUBLIC_UNAVAILABLE_TITLE}
      </Typography>
      <Typography variant="body2">{PUBLIC_UNAVAILABLE_BODY}</Typography>
    </Alert>
  </Box>
);

export default PublicPageUnavailable;
