/**
 * The seller's share view: the public order URL, a copy button, and a
 * client-generated QR encoding that URL.
 *
 * This QR is the one the seller hands to a buyer at an event — it is distinct
 * from the payment QR images the buyer sees once inside the page. It is
 * generated in the browser from the returned share token, so the share view can
 * be re-rendered at any time while the feature is enabled (no server round trip
 * and no stored image), including the fullscreen mode used to hold a phone up
 * for someone else to scan.
 */

import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { Box, Button, Dialog, DialogContent, IconButton, Stack, TextField, Tooltip, Typography } from '@mui/material';
import { ContentCopy as CopyIcon, Fullscreen as FullscreenIcon } from '@mui/icons-material';

export interface ShareQrPanelProps {
  shareUrl: string;
  onCopied?: () => void;
}

/** Generate the QR data URL; a generation failure simply hides the image. */
async function generateQrDataUrl(value: string): Promise<string | null> {
  try {
    return await QRCode.toDataURL(value, { width: 400, margin: 2, color: { dark: '#000000', light: '#ffffff' } });
  } catch {
    return null;
  }
}

export const ShareQrPanel: React.FC<ShareQrPanelProps> = ({ shareUrl, onCopied }) => {
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void generateQrDataUrl(shareUrl).then((dataUrl) => {
      if (!cancelled) setQrDataUrl(dataUrl);
    });
    return () => {
      cancelled = true;
    };
  }, [shareUrl]);

  const copyUrl = () => {
    void navigator.clipboard.writeText(shareUrl).then(() => onCopied?.());
  };

  return (
    <Box data-testid="share-qr-panel">
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Share this link, or show the code to a buyer.
      </Typography>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
        <TextField
          size="small"
          value={shareUrl}
          inputProps={{ 'aria-label': 'Public order share URL', readOnly: true }}
          onChange={() => undefined}
          sx={{ flexGrow: 1, minWidth: 260 }}
        />
        <Button startIcon={<CopyIcon />} onClick={copyUrl} size="small" data-testid="copy-share-url">
          Copy
        </Button>
        <Tooltip title="Show the code full screen">
          <IconButton
            onClick={() => setFullscreen(true)}
            size="small"
            aria-label="Show QR full screen"
            data-testid="fullscreen-qr"
          >
            <FullscreenIcon />
          </IconButton>
        </Tooltip>
      </Stack>
      {qrDataUrl ? (
        <Box component="img" src={qrDataUrl} alt="Public order share QR code" sx={{ width: 220, height: 220 }} />
      ) : null}

      <Dialog
        open={fullscreen}
        onClose={() => setFullscreen(false)}
        maxWidth={false}
        data-testid="fullscreen-qr-dialog"
      >
        <DialogContent>
          {qrDataUrl ? (
            <Box
              component="img"
              src={qrDataUrl}
              alt="Public order share QR code, enlarged"
              sx={{ width: '80vmin', height: '80vmin' }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </Box>
  );
};

export default ShareQrPanel;
