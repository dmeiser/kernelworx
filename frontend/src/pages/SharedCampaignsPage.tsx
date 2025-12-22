/**
 * SharedCampaignsPage - Manage campaign shared campaigns (shareable campaign links)
 */

import React, { useState } from "react";
import { useQuery, useMutation } from "@apollo/client/react";
import { useNavigate } from "react-router-dom";
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
} from "@mui/material";
import {
  Add as AddIcon,
  ContentCopy as CopyIcon,
  Edit as EditIcon,
  Block as DeactivateIcon,
  QrCode as QrCodeIcon,
  CheckCircle as ActiveIcon,
  Cancel as InactiveIcon,
  Download as DownloadIcon,
} from "@mui/icons-material";
import QRCode from "qrcode";
import {
  LIST_MY_SHARED_CAMPAIGNS,
  UPDATE_SHARED_CAMPAIGN,
  DELETE_SHARED_CAMPAIGN,
} from "../lib/graphql";
import { EditSharedCampaignDialog } from "../components/EditSharedCampaignDialog";

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

export const SharedCampaignsPage: React.FC = () => {
  const navigate = useNavigate();
  const [editingSharedCampaign, setEditingSharedCampaign] = useState<SharedCampaign | null>(
    null,
  );
  const [deactivateDialogOpen, setDeactivateDialogOpen] = useState(false);
  const [sharedCampaignToDeactivate, setSharedCampaignToDeactivate] =
    useState<SharedCampaign | null>(null);
  const [qrDialogOpen, setQrDialogOpen] = useState(false);
  const [qrCodeDataUrl, setQrCodeDataUrl] = useState<string | null>(null);
  const [qrSharedCampaign, setQrSharedCampaign] = useState<SharedCampaign | null>(null);
  const [snackbarOpen, setSnackbarOpen] = useState(false);
  const [snackbarMessage, setSnackbarMessage] = useState("");

  // Fetch user's campaign  shared campaigns
  const { data, loading, error, refetch } = useQuery<{
    listMySharedCampaigns: SharedCampaign[];
  }>(LIST_MY_SHARED_CAMPAIGNS);

  // Update mutation (for editing)
  const [updateSharedCampaign] = useMutation(UPDATE_SHARED_CAMPAIGN, {
    onCompleted: () => {
      refetch();
      setEditingSharedCampaign(null);
      showSnackbar("Shared Campaign updated successfully");
    },
  });

  // Delete mutation (soft delete / deactivate)
  const [deleteSharedCampaign] = useMutation(DELETE_SHARED_CAMPAIGN, {
    onCompleted: () => {
      refetch();
      setDeactivateDialogOpen(false);
      setSharedCampaignToDeactivate(null);
      showSnackbar("Shared Campaign deactivated");
    },
  });

  const sharedCampaigns = data?.listMySharedCampaigns || [];
  const activeSharedCampaignCount = sharedCampaigns.filter((p) => p.isActive).length;
  const canCreateMore = activeSharedCampaignCount < MAX_SHARED_CAMPAIGNS;

  const showSnackbar = (message: string) => {
    setSnackbarMessage(message);
    setSnackbarOpen(true);
  };

  const getShortLink = (sharedCampaignCode: string) => {
    return `${BASE_URL}/c/${sharedCampaignCode}`;
  };

  const handleCopyLink = async (sharedCampaignCode: string) => {
    const link = getShortLink(sharedCampaignCode);
    try {
      await navigator.clipboard.writeText(link);
      showSnackbar("Link copied to clipboard!");
    } catch (err) {
      console.error("Failed to copy link:", err);
      showSnackbar("Failed to copy link");
    }
  };

  const handleShowQRCode = async (sharedCampaign: SharedCampaign) => {
    const link = getShortLink(sharedCampaign.sharedCampaignCode);
    try {
      const qrDataUrl = await QRCode.toDataURL(link, {
        width: 400,
        margin: 2,
        color: {
          dark: "#000000",
          light: "#ffffff",
        },
      });

      setQrCodeDataUrl(qrDataUrl);
      setQrSharedCampaign(sharedCampaign);
      setQrDialogOpen(true);
    } catch (err) {
      console.error("Failed to generate QR code:", err);
      showSnackbar("Failed to generate QR code");
    }
  };

  const handleDownloadQRCode = () => {
    if (!qrCodeDataUrl || !qrSharedCampaign) return;

    const downloadLink = document.createElement("a");
    downloadLink.href = qrCodeDataUrl;
    downloadLink.download = `campaign-${qrSharedCampaign.sharedCampaignCode}-qr.png`;
    document.body.appendChild(downloadLink);
    downloadLink.click();
    document.body.removeChild(downloadLink);

    showSnackbar("QR code downloaded!");
  };

  const handleEdit = (sharedCampaign: SharedCampaign) => {
    setEditingSharedCampaign(sharedCampaign);
  };

  const handleDeactivate = (sharedCampaign: SharedCampaign) => {
    setSharedCampaignToDeactivate(sharedCampaign);
    setDeactivateDialogOpen(true);
  };

  const confirmDeactivate = async () => {
    if (sharedCampaignToDeactivate) {
      await deleteSharedCampaign({
        variables: { sharedCampaignCode: sharedCampaignToDeactivate.sharedCampaignCode },
      });
    }
  };

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

  if (loading) {
    return (
      <Box
        display="flex"
        justifyContent="center"
        alignItems="center"
        minHeight="400px"
      >
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box p={3}>
        <Alert severity="error">
          Failed to load shared campaigns: {error.message}
        </Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        mb={3}
      >
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            My Shared Campaigns
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Create shareable links that let your unit members create campaigns quickly with preset information for your unit.
            members. ({activeSharedCampaignCount}/{MAX_SHARED_CAMPAIGNS} active)
          </Typography>
        </Box>
        <Tooltip
          title={
            !canCreateMore
              ? `You have reached the maximum of ${MAX_SHARED_CAMPAIGNS} active shared campaigns`
              : ""
          }
        >
          <span>
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => navigate("/shared-campaigns/create")}
              disabled={!canCreateMore}
            >
              Create Shared Campaign
            </Button>
          </span>
        </Tooltip>
      </Stack>

      {sharedCampaigns.length === 0 ? (
        <Paper sx={{ p: 4, textAlign: "center" }}>
          <Typography variant="h6" color="text.secondary" gutterBottom>
            No Shared Campaigns Yet
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 3 }}>
            Create a shared campaign to generate shareable links that simplify campaign creation for your unit members.
            members.
          </Typography>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => navigate("/shared-campaigns/create")}
          >
            Create Your First Shared Campaign
          </Button>
        </Paper>
      ) : (
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
              {sharedCampaigns.map((sharedCampaign) => (
                <TableRow key={sharedCampaign.sharedCampaignCode}>
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
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {sharedCampaign.description || "-"}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    {sharedCampaign.catalog?.catalogName || "Unknown Catalog"}
                  </TableCell>
                  <TableCell>
                    {sharedCampaign.campaignName} {sharedCampaign.campaignYear}
                  </TableCell>
                  <TableCell>
                    {sharedCampaign.unitType} {sharedCampaign.unitNumber}
                    <Typography
                      variant="caption"
                      display="block"
                      color="text.secondary"
                    >
                      {sharedCampaign.city}, {sharedCampaign.state}
                    </Typography>
                  </TableCell>
                  <TableCell>
                    {sharedCampaign.isActive ? (
                      <Chip
                        icon={<ActiveIcon />}
                        label="Active"
                        color="success"
                        size="small"
                      />
                    ) : (
                      <Chip
                        icon={<InactiveIcon />}
                        label="Inactive"
                        color="default"
                        size="small"
                      />
                    )}
                  </TableCell>
                  <TableCell align="right">
                    <Stack
                      direction="row"
                      spacing={0.5}
                      justifyContent="flex-end"
                    >
                      <Tooltip title="Copy Link">
                        <IconButton
                          size="small"
                          onClick={() => handleCopyLink(sharedCampaign.sharedCampaignCode)}
                          aria-label="Copy link"
                        >
                          <CopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="View QR Code">
                        <IconButton
                          size="small"
                          onClick={() => handleShowQRCode(sharedCampaign)}
                          aria-label="View QR code"
                        >
                          <QrCodeIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      <Tooltip title="Edit">
                        <IconButton
                          size="small"
                          onClick={() => handleEdit(sharedCampaign)}
                          aria-label="Edit"
                        >
                          <EditIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                      {sharedCampaign.isActive && (
                        <Tooltip title="Deactivate">
                          <IconButton
                            size="small"
                            onClick={() => handleDeactivate(sharedCampaign)}
                            aria-label="Deactivate"
                            color="error"
                          >
                            <DeactivateIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      )}
                    </Stack>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {/* Edit Dialog */}
      {editingSharedCampaign && (
        <EditSharedCampaignDialog
          open={!!editingSharedCampaign}
          sharedCampaign={editingSharedCampaign}
          onClose={() => setEditingSharedCampaign(null)}
          onSave={handleSaveEdit}
        />
      )}

      {/* Deactivate Confirmation Dialog */}
      <Dialog
        open={deactivateDialogOpen}
        onClose={() => setDeactivateDialogOpen(false)}
      >
        <DialogTitle>Deactivate Campaign SharedCampaign?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Are you sure you want to deactivate this campaign sharedCampaign? The link
            will no longer work for new campaign creation, but existing campaigns
            created from this link will not be affected.
          </DialogContentText>
          {sharedCampaignToDeactivate && (
            <Box mt={2}>
              <Typography variant="body2" color="text.secondary">
                <strong>Code:</strong> {sharedCampaignToDeactivate.sharedCampaignCode}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                <strong>Unit:</strong> {sharedCampaignToDeactivate.unitType}{" "}
                {sharedCampaignToDeactivate.unitNumber}
              </Typography>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeactivateDialogOpen(false)}>Cancel</Button>
          <Button onClick={confirmDeactivate} color="error" variant="contained">
            Deactivate
          </Button>
        </DialogActions>
      </Dialog>

      {/* QR Code Dialog */}
      <Dialog
        open={qrDialogOpen}
        onClose={() => setQrDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          Campaign QR Code
          {qrSharedCampaign && ` - ${qrSharedCampaign.sharedCampaignCode}`}
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2} alignItems="center">
            {qrCodeDataUrl && (
              <Box
                component="img"
                src={qrCodeDataUrl}
                alt="QR Code"
                sx={{
                  width: "100%",
                  maxWidth: 400,
                  height: "auto",
                  border: "1px solid",
                  borderColor: "divider",
                  borderRadius: 1,
                  p: 2,
                }}
              />
            )}
            {qrSharedCampaign && (
              <Box sx={{ textAlign: "center", width: "100%" }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  Link:
                </Typography>
                <Typography
                  variant="body2"
                  fontFamily="monospace"
                  sx={{ wordBreak: "break-all" }}
                >
                  {getShortLink(qrSharedCampaign.sharedCampaignCode)}
                </Typography>
              </Box>
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setQrDialogOpen(false)}>Close</Button>
          <Button
            onClick={handleDownloadQRCode}
            variant="contained"
            startIcon={<DownloadIcon />}
          >
            Download
          </Button>
        </DialogActions>
      </Dialog>

      {/* Success Snackbar */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={() => setSnackbarOpen(false)}
        message={snackbarMessage}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </Box>
  );
};
