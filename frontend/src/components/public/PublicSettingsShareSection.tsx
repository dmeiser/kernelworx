/**
 * The share view: retrievable any time while the feature is enabled, not only
 * at the moment of enabling. The URL and QR are re-rendered client-side from the
 * `shareToken` the settings read returns, so navigating away and back (or
 * reloading) reproduces the same scannable link.
 */

import { Paper, Typography } from '@mui/material';
import { ShareQrPanel } from './ShareQrPanel';

interface PublicSettingsShareSectionProps {
  shareUrl: string | null;
}

export const PublicSettingsShareSection: React.FC<PublicSettingsShareSectionProps> = ({ shareUrl }) => {
  if (!shareUrl) return null;
  return (
    <Paper elevation={0} sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Share link
      </Typography>
      <ShareQrPanel shareUrl={shareUrl} />
    </Paper>
  );
};

export default PublicSettingsShareSection;
