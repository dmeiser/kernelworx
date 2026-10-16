/**
 * Share section for public order settings.
 *
 * Shows the campaign's share link plus the QR code the seller hands out.
 * The link and QR use the BARE campaign id (`/o/<id>/<token>`) — a raw
 * `CAMPAIGN#` prefix would break the URL, since `#` truncates the path.
 * The share view stays retrievable any time while enabled: URL, QR,
 * copy-to-clipboard, and a fullscreen mode for holding the phone up to a
 * buyer.
 */
import { useEffect, useState } from 'react';
import { Box, Button, Dialog, DialogContent, DialogTitle, IconButton, Stack, Typography } from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import QRCode from 'qrcode';
import { toUrlId } from '../../lib/ids';

interface PublicSettingsShareSectionProps {
  campaignId: string;
  shareToken: string | null;
  campaignName: string;
}

const FULLSCREEN_QR_SIZE = 320;

/** The QR + link view shown while a share URL exists (also in fullscreen). */
const ShareLinkView: React.FC<{ shareUrl: string; qrDataUrl: string | null; campaignName: string }> = ({
  shareUrl,
  qrDataUrl,
  campaignName,
}) => {
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [fullscreenOpen, setFullscreenOpen] = useState(false);

  // A new link invalidates the previous copy feedback.
  useEffect(() => {
    setCopyState('idle');
  }, [shareUrl]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  };

  return (
    <>
      <Typography variant="body2" gutterBottom>
        Share this link (or the QR code) to allow customers to place public orders:
      </Typography>
      <Typography variant="body2" fontFamily="monospace" gutterBottom data-testid="share-url">
        {shareUrl}
      </Typography>
      {qrDataUrl ? (
        <Box sx={{ my: 2 }}>
          <Box
            component="img"
            src={qrDataUrl}
            alt={`Share QR code for ${campaignName}`}
            data-testid="share-qr"
            sx={{ display: 'block', width: 200, height: 200 }}
          />
        </Box>
      ) : null}
      <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
        <Button variant="outlined" size="small" onClick={() => void handleCopy()}>
          Copy Link
        </Button>
        <Button variant="outlined" size="small" onClick={() => setFullscreenOpen(true)}>
          Fullscreen QR
        </Button>
      </Stack>
      {copyState === 'copied' ? (
        <Typography variant="body2" color="success.main" sx={{ mt: 1 }} data-testid="copy-copied">
          Link copied to clipboard.
        </Typography>
      ) : null}
      {copyState === 'failed' ? (
        <Typography variant="body2" color="error" sx={{ mt: 1 }} data-testid="copy-failed">
          Could not copy the link. Copy it manually above.
        </Typography>
      ) : null}
      <Dialog
        open={fullscreenOpen}
        onClose={() => setFullscreenOpen(false)}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle sx={{ pr: 6 }}>
          {campaignName} — public order link
          <IconButton
            aria-label="Close"
            onClick={() => setFullscreenOpen(false)}
            sx={{ position: 'absolute', right: 8, top: 8 }}
          >
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent sx={{ textAlign: 'center', pb: 3 }}>
          {qrDataUrl ? (
            <Box
              component="img"
              src={qrDataUrl}
              alt={`Fullscreen share QR code for ${campaignName}`}
              data-testid="fullscreen-share-qr"
              sx={{ width: FULLSCREEN_QR_SIZE, height: FULLSCREEN_QR_SIZE, mx: 'auto', mb: 2 }}
            />
          ) : null}
          <Typography variant="body2" fontFamily="monospace">
            {shareUrl}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            Hold this up for the buyer to scan.
          </Typography>
        </DialogContent>
      </Dialog>
    </>
  );
};

export const PublicSettingsShareSection: React.FC<PublicSettingsShareSectionProps> = ({
  campaignId,
  shareToken,
  campaignName,
}) => {
  const shareUrl = shareToken
    ? `${window.location.origin}/o/${toUrlId(campaignId)}/${shareToken}`
    : null;
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null);

  // Regenerate the QR whenever the share URL changes (fresh enable, rotation).
  useEffect(() => {
    if (!shareUrl) {
      setQrDataUrl(null);
      return;
    }
    let cancelled = false;
    QRCode.toDataURL(shareUrl, { width: 400, margin: 2 }).then(
      (dataUrl) => {
        if (!cancelled) setQrDataUrl(dataUrl);
      },
      () => {
        if (!cancelled) setQrDataUrl(null);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [shareUrl]);

  if (!shareUrl) {
    return (
      <Box sx={{ mb: 3 }}>
        <Typography variant="h6" gutterBottom>
          Share Link for {campaignName}
        </Typography>
        <Typography variant="body2" color="error">
          Share link not available. Enable public orders to generate a share link.
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="h6" gutterBottom>
        Share Link for {campaignName}
      </Typography>
      <ShareLinkView shareUrl={shareUrl} qrDataUrl={qrDataUrl} campaignName={campaignName} />
    </Box>
  );
};
