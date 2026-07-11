/**
 * QRUploadDialog - Dialog for uploading QR code images for payment methods
 *
 * Features:
 * - File input for PNG/JPG/WEBP images
 * - File size validation (max 5MB)
 * - Image preview before upload
 * - Direct S3 upload using pre-signed POST
 * - Loading state during upload
 */

import React, { useState, useEffect, useRef } from 'react';
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  Alert,
  CircularProgress,
  LinearProgress,
} from '@mui/material';
import { CloudUpload as UploadIcon } from '@mui/icons-material';

// Constants for file validation
const MAX_FILE_SIZE = 5 * 1024 * 1024; // 5MB
const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/webp'];
const ACCEPTED_EXTENSIONS = '.png,.jpg,.jpeg,.webp';

interface QRUploadDialogProps {
  open: boolean;
  onClose: () => void;
  onUpload: (file: File) => Promise<void>;
  methodName: string;
  isLoading?: boolean;
  /** External upload error to display inline in the dialog */
  uploadError?: string | null;
}

/* eslint-disable complexity -- Dialog with file validation and upload logic */
export const QRUploadDialog: React.FC<QRUploadDialogProps> = ({
  open,
  onClose,
  onUpload,
  methodName,
  isLoading = false,
  uploadError = null,
}) => {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const previewUrlRef = useRef<string | null>(null);

  // Reset state when dialog opens/closes
  useEffect(() => {
    if (open) {
      setSelectedFile(null);
      setPreviewUrl(null);
      previewUrlRef.current = null;
      setError(null);
    }
  }, [open]);

  // Cleanup preview URL when component unmounts
  useEffect(() => {
    return () => {
      if (previewUrlRef.current) {
        URL.revokeObjectURL(previewUrlRef.current);
      }
    };
  }, []);

  // Generate preview URL when file is selected
  useEffect(() => {
    if (selectedFile) {
      const url = URL.createObjectURL(selectedFile);
      setPreviewUrl(url);
      previewUrlRef.current = url;
      return () => URL.revokeObjectURL(url);
    }
    return undefined;
  }, [selectedFile]);

  const validateFile = (file: File): string | null => {
    if (!ACCEPTED_TYPES.includes(file.type)) {
      return 'Please select a PNG, JPG, or WEBP image file';
    }

    if (file.size > MAX_FILE_SIZE) {
      const sizeMB = (file.size / (1024 * 1024)).toFixed(1);
      return `File is too large (${sizeMB}MB). Maximum size is 5MB`;
    }

    return null;
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setError(null);

    if (!file) {
      setSelectedFile(null);
      return;
    }

    const validationError = validateFile(file);
    if (validationError) {
      setError(validationError);
      setSelectedFile(null);
      /* v8 ignore start -- fileInputRef is always attached in the rendered dialog; the defensive null check is not reachable in jsdom */
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      /* v8 ignore stop */
      return;
    }

    setSelectedFile(file);
  };

  const handleUpload = async () => {
    // Upload button is disabled when no file is selected, so this guard is not reachable in jsdom
    /* v8 ignore start */
    if (!selectedFile) return;
    /* v8 ignore stop */

    try {
      await onUpload(selectedFile);
      onClose();
    } catch {
      // Error handling is done in parent component
    }
  };

  const handleSelectFile = () => {
    fileInputRef.current?.click();
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Upload QR Code for {methodName}</DialogTitle>
      <DialogContent>
        {/* Show local validation errors */}
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        {/* Show external upload/confirm errors */}
        {uploadError && !error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {uploadError}
          </Alert>
        )}

        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: 2,
            py: 2,
          }}
        >
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS}
            onChange={handleFileChange}
            style={{ display: 'none' }}
            aria-label="Select QR code image"
          />

          {/* Preview area */}
          {previewUrl ? (
            <Box
              sx={{
                border: '1px solid',
                borderColor: 'divider',
                borderRadius: 1,
                p: 1,
                maxWidth: '100%',
              }}
            >
              <img
                src={previewUrl}
                alt="QR code preview"
                style={{
                  maxWidth: '100%',
                  maxHeight: '300px',
                  display: 'block',
                }}
              />
            </Box>
          ) : (
            <Box
              sx={{
                border: '2px dashed',
                borderColor: 'divider',
                borderRadius: 1,
                p: 4,
                textAlign: 'center',
                width: '100%',
                cursor: 'pointer',
                '&:hover': {
                  borderColor: 'primary.main',
                  bgcolor: 'action.hover',
                },
              }}
              onClick={handleSelectFile}
            >
              <UploadIcon sx={{ fontSize: 48, color: 'text.secondary', mb: 1 }} />
              <Typography>Click to select an image</Typography>
              <Typography variant="body2" color="text.secondary">
                PNG, JPG, or WEBP (max 5MB)
              </Typography>
            </Box>
          )}

          {/* Selected file info */}
          {selectedFile && (
            <Box sx={{ textAlign: 'center' }}>
              <Typography variant="body2">{selectedFile.name}</Typography>
              <Typography variant="caption" color="text.secondary">
                {(selectedFile.size / 1024).toFixed(1)} KB
              </Typography>
            </Box>
          )}

          {/* Change file button */}
          {selectedFile && (
            <Button variant="outlined" size="small" onClick={handleSelectFile} disabled={isLoading}>
              Choose Different Image
            </Button>
          )}
        </Box>

        {/* Upload progress */}
        {isLoading && (
          <Box sx={{ mt: 2 }}>
            <LinearProgress />
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1, textAlign: 'center' }}>
              Uploading...
            </Typography>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isLoading}>
          Cancel
        </Button>
        <Button
          onClick={handleUpload}
          variant="contained"
          disabled={isLoading || !selectedFile}
          startIcon={isLoading ? <CircularProgress size={16} /> : <UploadIcon />}
        >
          {isLoading ? 'Uploading...' : 'Upload'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};
/* eslint-enable complexity */
