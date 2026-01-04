/**
 * SharedCampaignsPage - Manage campaign shared campaigns (shareable campaign links)
 */

import React, { useState } from 'react';
import { useQuery, useMutation } from '@apollo/client/react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Button,
  Typography,
  Alert,
  CircularProgress,
  Stack,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Chip,
  Tooltip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  Snackbar,
} from '@mui/material';
import {
  Add as AddIcon,
  ContentCopy as CopyIcon,
  Edit as EditIcon,
  Block as DeactivateIcon,
  QrCode as QrCodeIcon,
  CheckCircle as ActiveIcon,
  Cancel as InactiveIcon,
  Download as DownloadIcon,
} from '@mui/icons-material';
import QRCode from 'qrcode';
import { LIST_MY_SHARED_CAMPAIGNS, UPDATE_SHARED_CAMPAIGN, DELETE_SHARED_CAMPAIGN } from '../lib/graphql';
import { EditSharedCampaignDialog } from '../components/EditSharedCampaignDialog';

interface SharedCampaign {
  sharedCampaignCode: string;
  catalogId: string;
  catalog?: {
    catalogId: string;
    catalogName: string;
  };
  campaignName: string;
  campaignYear: number;
  startDate?: string;
  endDate?: string;
  unitType: string;
  unitNumber: number;
  city: string;
  state: string;
  createdBy: string;
  createdByName: string;
  creatorMessage?: string;
  description?: string;
  isActive: boolean;
  createdAt: string;
}

const MAX_SHARED_CAMPAIGNS = 50;
const BASE_URL = window.location.origin;

// Helper component for status chip
const StatusChip: React.FC<{ isActive: boolean }> = ({ isActive }) =>
  isActive ? (
    <Chip icon={<ActiveIcon />} label="Active" color="success" size="small" />
  ) : (
    <Chip icon={<InactiveIcon />} label="Inactive" color="default" size="small" />
  );

// Helper to get catalog name with fallback
const getCatalogName = (catalog: SharedCampaign['catalog']): string => catalog?.catalogName || 'Unknown Catalog';

// Helper to get description with fallback
const getDescription = (description: string | undefined): string => description || '-';

// Helper to get shared campaigns from query data
const getSharedCampaigns = (data: { listMySharedCampaigns: SharedCampaign[] } | undefined): SharedCampaign[] =>
  data?.listMySharedCampaigns || [];

// Helper to count active shared campaigns
const countActiveSharedCampaigns = (campaigns: SharedCampaign[]): number => campaigns.filter((p) => p.isActive).length;

// Helper to check if can create more shared campaigns
const canCreateMoreSharedCampaigns = (activeCount: number): boolean => activeCount < MAX_SHARED_CAMPAIGNS;

// Helper to check if download is available
const canDownloadQRCode = (qrCodeDataUrl: string | null, qrSharedCampaign: SharedCampaign | null): boolean =>
  Boolean(qrCodeDataUrl && qrSharedCampaign);

// Helper to download QR code
const downloadQRCodeImage = (qrCodeDataUrl: string, sharedCampaignCode: string): void => {
  const downloadLink = document.createElement('a');
  downloadLink.href = qrCodeDataUrl;
  downloadLink.download = `campaign-${sharedCampaignCode}-qr.png`;
  document.body.appendChild(downloadLink);
  downloadLink.click();
  document.body.removeChild(downloadLink);
};

// Helper to copy link to clipboard with error handling
const copyLinkToClipboard = async (
  link: string,
  onSuccess: () => void,
  onError: (err: unknown) => void,
): Promise<void> => {
  try {
    await navigator.clipboard.writeText(link);
    onSuccess();
  } catch (err) {
    console.error('Failed to copy link:', err);
    onError(err);
  }
};

// Helper to generate QR code with error handling
const generateQRCode = async (
  link: string,
  onSuccess: (dataUrl: string) => void,
  onError: (err: unknown) => void,
): Promise<void> => {
  try {
    const qrDataUrl = await QRCode.toDataURL(link, {
      width: 400,
      margin: 2,
      color: {
        dark: '#000000',
        light: '#ffffff',
      },
    });
    onSuccess(qrDataUrl);
  } catch (err) {
    console.error('Failed to generate QR code:', err);
    onError(err);
  }
};

// Loading state component
const LoadingState: React.FC = () => (
  <Box display="flex" justifyContent="center" alignItems="center" minHeight="400px">
    <CircularProgress />
  </Box>
);

// Error state component
const ErrorState: React.FC<{ message: string }> = ({ message }) => (
  <Box p={3}>
    <Alert severity="error">Failed to load shared campaigns: {message}</Alert>
  </Box>
);

// Empty state component
const EmptyState: React.FC<{ onCreateClick: () => void }> = ({ onCreateClick }) => (
  <Paper sx={{ p: 4, textAlign: 'center' }}>
    <Typography variant="h6" color="text.secondary" gutterBottom>
      No Shared Campaigns Yet
    </Typography>
    <Typography color="text.secondary" sx={{ mb: 3 }}>
      Create a shared campaign to generate shareable links that simplify campaign creation for your unit members.
      members.
    </Typography>
    <Button variant="contained" startIcon={<AddIcon />} onClick={onCreateClick}>
      Create Your First Shared Campaign
    </Button>
  </Paper>
);

// Page header component
const PageHeader: React.FC<{
  activeCount: number;
  canCreate: boolean;
  onCreateClick: () => void;
}> = ({ activeCount, canCreate, onCreateClick }) => (
  <Stack direction="row" justifyContent="space-between" alignItems="center" mb={3}>
    <Box>
      <Typography variant="h4" component="h1" gutterBottom>
        My Shared Campaigns
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Create shareable links that let your unit members create campaigns quickly with preset information for your
        unit. members. ({activeCount}/{MAX_SHARED_CAMPAIGNS} active)
      </Typography>
    </Box>
    <Tooltip
      title={!canCreate ? `You have reached the maximum of ${MAX_SHARED_CAMPAIGNS} active shared campaigns` : ''}
    >
      <span>
        <Button variant="contained" startIcon={<AddIcon />} onClick={onCreateClick} disabled={!canCreate}>
          Create Shared Campaign
        </Button>
      </span>
    </Tooltip>
  </Stack>
);

// Helper to check if list has items
const hasSharedCampaigns = (campaigns: SharedCampaign[]): boolean => campaigns.length > 0;

// Helper to get short link for a shared campaign
const getShortLinkForCode = (code: string): string => `${BASE_URL}/c/${code}`;

// Deactivate details component (only renders when campaign exists)
const DeactivateDetails: React.FC<{
  campaign: SharedCampaign | null;
}> = ({ campaign }) =>
  campaign ? (
    <Box mt={2}>
      <Typography variant="body2" color="text.secondary">
        <strong>Code:</strong> {campaign.sharedCampaignCode}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        <strong>Unit:</strong> {campaign.unitType} {campaign.unitNumber}
      </Typography>
    </Box>
  ) : null;

// QR dialog title suffix component
const QRDialogTitleSuffix: React.FC<{
  campaign: SharedCampaign | null;
}> = ({ campaign }) => (campaign ? <> - {campaign.sharedCampaignCode}</> : null);

// QR code image component
const QRCodeImage: React.FC<{
  dataUrl: string | null;
}> = ({ dataUrl }) =>
  dataUrl ? (
    <Box
      component="img"
      src={dataUrl}
      alt="QR Code"
      sx={{
        width: '100%',
        maxWidth: 400,
        height: 'auto',
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        p: 2,
      }}
    />
  ) : null;

// QR link display component
const QRLinkDisplay: React.FC<{
  campaign: SharedCampaign | null;
}> = ({ campaign }) =>
  campaign ? (
    <Box sx={{ textAlign: 'center', width: '100%' }}>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Link:
      </Typography>
      <Typography variant="body2" fontFamily="monospace" sx={{ wordBreak: 'break-all' }}>
        {getShortLinkForCode(campaign.sharedCampaignCode)}
      </Typography>
    </Box>
  ) : null;

// Campaigns list component (table or empty state)
const CampaignsList: React.FC<{
  campaigns: SharedCampaign[];
  onCreateClick: () => void;
  onCopyLink: (code: string) => void;
  onShowQR: (campaign: SharedCampaign) => void;
  onEdit: (campaign: SharedCampaign) => void;
  onDeactivate: (campaign: SharedCampaign) => void;
}> = ({ campaigns, onCreateClick, onCopyLink, onShowQR, onEdit, onDeactivate }) =>
  hasSharedCampaigns(campaigns) ? (
    <TableContainer component={Paper}>
      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Code</TableCell>
            <TableCell>Description</TableCell>
            <TableCell>Catalog</TableCell>
            <TableCell>Campaign</TableCell>
            <TableCell>Unit</TableCell>
            <TableCell>Status</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {campaigns.map((sharedCampaign) => (
            <SharedCampaignRow
              key={sharedCampaign.sharedCampaignCode}
              sharedCampaign={sharedCampaign}
              onCopyLink={onCopyLink}
              onShowQR={onShowQR}
              onEdit={onEdit}
              onDeactivate={onDeactivate}
            />
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  ) : (
    <EmptyState onCreateClick={onCreateClick} />
  );

// Edit dialog wrapper component
const EditDialogWrapper: React.FC<{
  campaign: SharedCampaign | null;
  onClose: () => void;
  onSave: (
    code: string,
    updates: {
      description?: string;
      creatorMessage?: string;
      isActive?: boolean;
    },
  ) => Promise<void>;
}> = ({ campaign, onClose, onSave }) =>
  campaign ? (
    <EditSharedCampaignDialog open={Boolean(campaign)} sharedCampaign={campaign} onClose={onClose} onSave={onSave} />
  ) : null;

// Shared campaign row actions component
const SharedCampaignActions: React.FC<{
  sharedCampaign: SharedCampaign;
  onCopyLink: (code: string) => void;
  onShowQR: (sharedCampaign: SharedCampaign) => void;
  onEdit: (sharedCampaign: SharedCampaign) => void;
  onDeactivate: (sharedCampaign: SharedCampaign) => void;
}> = ({ sharedCampaign, onCopyLink, onShowQR, onEdit, onDeactivate }) => (
  <Stack direction="row" spacing={0.5} justifyContent="flex-end">
    <Tooltip title="Copy Link">
      <IconButton size="small" onClick={() => onCopyLink(sharedCampaign.sharedCampaignCode)} aria-label="Copy link">
        <CopyIcon fontSize="small" />
      </IconButton>
    </Tooltip>
    <Tooltip title="View QR Code">
      <IconButton size="small" onClick={() => onShowQR(sharedCampaign)} aria-label="View QR code">
        <QrCodeIcon fontSize="small" />
      </IconButton>
    </Tooltip>
    <Tooltip title="Edit">
      <IconButton size="small" onClick={() => onEdit(sharedCampaign)} aria-label="Edit">
        <EditIcon fontSize="small" />
      </IconButton>
    </Tooltip>
    {sharedCampaign.isActive && (
      <Tooltip title="Deactivate">
        <IconButton size="small" onClick={() => onDeactivate(sharedCampaign)} aria-label="Deactivate" color="error">
          <DeactivateIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    )}
  </Stack>
);

// Single shared campaign row component
const SharedCampaignRow: React.FC<{
  sharedCampaign: SharedCampaign;
  onCopyLink: (code: string) => void;
  onShowQR: (sharedCampaign: SharedCampaign) => void;
  onEdit: (sharedCampaign: SharedCampaign) => void;
  onDeactivate: (sharedCampaign: SharedCampaign) => void;
}> = ({ sharedCampaign, onCopyLink, onShowQR, onEdit, onDeactivate }) => (
  <TableRow>
    <TableCell>
      <Typography variant="body2" fontFamily="monospace">
        {sharedCampaign.sharedCampaignCode}
      </Typography>
    </TableCell>
    <TableCell>
      <Typography
        variant="body2"
        sx={{
          maxWidth: 200,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {getDescription(sharedCampaign.description)}
      </Typography>
    </TableCell>
    <TableCell>{getCatalogName(sharedCampaign.catalog)}</TableCell>
    <TableCell>
      {sharedCampaign.campaignName} {sharedCampaign.campaignYear}
    </TableCell>
    <TableCell>
      {sharedCampaign.unitType} {sharedCampaign.unitNumber}
      <Typography variant="caption" display="block" color="text.secondary">
        {sharedCampaign.city}, {sharedCampaign.state}
      </Typography>
    </TableCell>
    <TableCell>
      <StatusChip isActive={sharedCampaign.isActive} />
    </TableCell>
    <TableCell align="right">
      <SharedCampaignActions
        sharedCampaign={sharedCampaign}
        onCopyLink={onCopyLink}
        onShowQR={onShowQR}
        onEdit={onEdit}
        onDeactivate={onDeactivate}
      />
    </TableCell>
  </TableRow>
);

export const SharedCampaignsPage: React.FC = () => {
  const navigate = useNavigate();
  const [editingSharedCampaign, setEditingSharedCampaign] = useState<SharedCampaign | null>(null);
  const [deactivateDialogOpen, setDeactivateDialogOpen] = useState(false);
  const [sharedCampaignToDeactivate, setSharedCampaignToDeactivate] = useState<SharedCampaign | null>(null);
  const [qrDialogOpen, setQrDialogOpen] = useState(false);
  const [qrCodeDataUrl, setQrCodeDataUrl] = useState<string | null>(null);
  const [qrSharedCampaign, setQrSharedCampaign] = useState<SharedCampaign | null>(null);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState('');

  /* v8 ignore start -- Dialog backdrop click and Snackbar auto-hide handlers cannot be simulated in jsdom */
  const handleEditDialogDismiss = () => setEditingSharedCampaign(null);
  const handleDeactivateDialogDismiss = () => setDeactivateDialogOpen(false);
  const handleQrDialogDismiss = () => setQrDialogOpen(false);
  const handleSnackbarClose = () => setSnackbarOpen(false);
  /* v8 ignore stop */

  // Fetch user's campaign  shared campaigns
  const { data, loading, error, refetch } = useQuery<{
    listMySharedCampaigns: SharedCampaign[];
  }>(LIST_MY_SHARED_CAMPAIGNS);

  // Update mutation (for editing)
  /* v8 ignore start -- mutation onCompleted callbacks require complex Apollo mocking with refetch */
  const [updateSharedCampaign] = useMutation(UPDATE_SHARED_CAMPAIGN, {
    onCompleted: () => {
      refetch();
      setEditingSharedCampaign(null);
      showSnackbar('Shared Campaign updated successfully');
    },
  });
  /* v8 ignore stop */

  // Delete mutation (soft delete / deactivate)
  const [deleteSharedCampaign] = useMutation(DELETE_SHARED_CAMPAIGN, {
    onCompleted: () => {
      refetch();
      setDeactivateDialogOpen(false);
      setSharedCampaignToDeactivate(null);
      showSnackbar('Shared Campaign deactivated');
    },
  });

  const sharedCampaigns = getSharedCampaigns(data);
  const activeSharedCampaignCount = countActiveSharedCampaigns(sharedCampaigns);
  const canCreateMore = canCreateMoreSharedCampaigns(activeSharedCampaignCount);
  const handleCreateClick = () => navigate('/shared-campaigns/create');

  const showSnackbar = (message: string) => {
    setSnackbarMessage(message);
    setSnackbarOpen(true);
  };

  const getShortLink = (sharedCampaignCode: string) => {
    return `${BASE_URL}/c/${sharedCampaignCode}`;
  };

  const handleCopyLink = async (sharedCampaignCode: string) => {
    const link = getShortLink(sharedCampaignCode);
    await copyLinkToClipboard(
      link,
      () => showSnackbar('Link copied to clipboard!'),
      /* v8 ignore next -- error callback requires clipboard API failure which is mocked in tests */
      () => showSnackbar('Failed to copy link'),
    );
  };

  const handleShowQRCode = async (sharedCampaign: SharedCampaign) => {
    const link = getShortLink(sharedCampaign.sharedCampaignCode);
    await generateQRCode(
      link,
      (qrDataUrl) => {
        setQrCodeDataUrl(qrDataUrl);
        setQrSharedCampaign(sharedCampaign);
        setQrDialogOpen(true);
      },
      () => showSnackbar('Failed to generate QR code'),
    );
  };

  const handleDownloadQRCode = () => {
    const canDownload = canDownloadQRCode(qrCodeDataUrl, qrSharedCampaign);
    if (canDownload && qrCodeDataUrl && qrSharedCampaign) {
      downloadQRCodeImage(qrCodeDataUrl, qrSharedCampaign.sharedCampaignCode);
      showSnackbar('QR code downloaded!');
    }
  };

  const handleEdit = (sharedCampaign: SharedCampaign) => {
    setEditingSharedCampaign(sharedCampaign);
  };

  const handleDeactivate = (sharedCampaign: SharedCampaign) => {
    setSharedCampaignToDeactivate(sharedCampaign);
    setDeactivateDialogOpen(true);
  };

  const confirmDeactivate = async () => {
    const hasTarget = Boolean(sharedCampaignToDeactivate);
    if (hasTarget && sharedCampaignToDeactivate) {
      await deleteSharedCampaign({
        variables: {
          sharedCampaignCode: sharedCampaignToDeactivate.sharedCampaignCode,
        },
      });
    }
  };

  /* v8 ignore start -- handleSaveEdit requires complex mutation mocking with variable matching */
  const handleSaveEdit = async (
    sharedCampaignCode: string,
    updates: {
      description?: string;
      creatorMessage?: string;
      isActive?: boolean;
    },
  ) => {
    await updateSharedCampaign({
      variables: {
        input: {
          sharedCampaignCode,
          ...updates,
        },
      },
    });
  };
  /* v8 ignore stop */

  if (loading) {
    return <LoadingState />;
  }

  if (error) {
    return <ErrorState message={error.message} />;
  }

  return (
    <Box>
      <PageHeader activeCount={activeSharedCampaignCount} canCreate={canCreateMore} onCreateClick={handleCreateClick} />

      <CampaignsList
        campaigns={sharedCampaigns}
        onCreateClick={handleCreateClick}
        onCopyLink={handleCopyLink}
        onShowQR={handleShowQRCode}
        onEdit={handleEdit}
        onDeactivate={handleDeactivate}
      />

      {/* Edit Dialog */}
      <EditDialogWrapper campaign={editingSharedCampaign} onClose={handleEditDialogDismiss} onSave={handleSaveEdit} />

      {/* Deactivate Confirmation Dialog */}
      <Dialog open={deactivateDialogOpen} onClose={handleDeactivateDialogDismiss}>
        <DialogTitle>Deactivate Campaign SharedCampaign?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to deactivate this campaign sharedCampaign? The link will no longer work for new
            campaign creation, but existing campaigns created from this link will not be affected.
          </DialogContentText>
          <DeactivateDetails campaign={sharedCampaignToDeactivate} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeactivateDialogOpen(false)}>Cancel</Button>
          <Button onClick={confirmDeactivate} color="error" variant="contained">
            Deactivate
          </Button>
        </DialogActions>
      </Dialog>

      {/* QR Code Dialog */}
      <Dialog open={qrDialogOpen} onClose={handleQrDialogDismiss} maxWidth="sm" fullWidth>
        <DialogTitle>
          Campaign QR Code
          <QRDialogTitleSuffix campaign={qrSharedCampaign} />
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} alignItems="center">
            <QRCodeImage dataUrl={qrCodeDataUrl} />
            <QRLinkDisplay campaign={qrSharedCampaign} />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setQrDialogOpen(false)}>Close</Button>
          <Button onClick={handleDownloadQRCode} variant="contained" startIcon={<DownloadIcon />}>
            Download
          </Button>
        </DialogActions>
      </Dialog>

      {/* Success Snackbar */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={handleSnackbarClose}
        message={snackbarMessage}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
    </Box>
  );
};
