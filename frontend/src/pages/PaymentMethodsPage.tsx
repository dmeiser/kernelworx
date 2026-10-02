/**
 * PaymentMethodsPage - Manage custom payment methods with optional QR codes
 *
 * Features:
 * - List all payment methods (alphabetically sorted)
 * - Create new custom payment methods
 * - Edit/rename payment methods
 * - Upload/delete QR codes for payment methods
 * - Delete payment methods
 *
 * Authorization: Owner only can create/update/delete. Cash and Check are global and read-only.
 */

import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@apollo/client/react';
import { Box, Stack, Button, Alert } from '@mui/material';
import { Add as AddIcon } from '@mui/icons-material';

import {
  GET_MY_PAYMENT_METHODS,
  CREATE_PAYMENT_METHOD,
  UPDATE_PAYMENT_METHOD,
  DELETE_PAYMENT_METHOD,
  REQUEST_PAYMENT_METHOD_QR_UPLOAD,
  CONFIRM_PAYMENT_METHOD_QR_UPLOAD,
  DELETE_PAYMENT_METHOD_QR_CODE,
} from '../lib/graphql';
import { PageHeader } from '../components/PageHeader';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { EmptyState } from '../components/EmptyState';
import { PaymentMethodCard } from '../components/PaymentMethodCard';
import { CreatePaymentMethodDialog } from '../components/CreatePaymentMethodDialog';
import { EditPaymentMethodDialog } from '../components/EditPaymentMethodDialog';
import { DeletePaymentMethodDialog } from '../components/DeletePaymentMethodDialog';
import { QRUploadDialog } from '../components/QRUploadDialog';

interface PaymentMethod {
  name: string;
  qrCodeUrl: string | null;
}

interface S3UploadInfo {
  uploadUrl: string;
  fields: string;
  s3Key: string;
}

interface RequestQRUploadData {
  requestPaymentMethodQRCodeUpload: S3UploadInfo;
}

// Import shared validation constants and functions
import { isReservedName } from '../lib/paymentMethodValidation';

// Presentational subcomponent: the payment-method dialog tree. Kept out of the
// page component so its render tree stays a plain pass-through.
interface PaymentMethodDialogsProps {
  createOpen: boolean;
  createIsLoading: boolean;
  data: { myPaymentMethods: PaymentMethod[] } | undefined;
  onCreate: (name: string) => Promise<void>;
  onCloseCreate: () => void;

  editOpen: boolean;
  editIsLoading: boolean;
  currentName: string;
  onUpdate: (oldName: string, newName: string) => Promise<void>;
  onCloseEdit: () => void;

  deleteOpen: boolean;
  deleteIsLoading: boolean;
  onDelete: () => Promise<void>;
  onCloseDelete: () => void;

  qrOpen: boolean;
  qrIsLoading: boolean;
  qrError: string | null;
  onUpload: (file: File) => Promise<void>;
  onCloseQr: () => void;
}

const PaymentMethodDialogs: React.FC<PaymentMethodDialogsProps> = ({
  createOpen,
  createIsLoading,
  data,
  onCreate,
  onCloseCreate,
  editOpen,
  editIsLoading,
  currentName,
  onUpdate,
  onCloseEdit,
  deleteOpen,
  deleteIsLoading,
  onDelete,
  onCloseDelete,
  qrOpen,
  qrIsLoading,
  qrError,
  onUpload,
  onCloseQr,
}) => {
  const existingNames = (data?.myPaymentMethods ?? []).map((m) => m.name);

  return (
    <>
    <CreatePaymentMethodDialog
      open={createOpen}
      onClose={onCloseCreate}
      onCreate={onCreate}
      existingNames={existingNames}
      isLoading={createIsLoading}
    />

    <EditPaymentMethodDialog
      open={editOpen}
      onClose={onCloseEdit}
      onUpdate={onUpdate}
      currentName={currentName}
      existingNames={existingNames}
      isLoading={editIsLoading}
    />

    <DeletePaymentMethodDialog
      open={deleteOpen}
      onClose={onCloseDelete}
      onDelete={onDelete}
      methodName={currentName}
      isLoading={deleteIsLoading}
    />

    <QRUploadDialog
      open={qrOpen}
      onClose={onCloseQr}
      onUpload={onUpload}
      methodName={currentName}
      isLoading={qrIsLoading}
      uploadError={qrError}
    />
  </>
  );
};

// Presentational subcomponent: the payment-methods list. Owns the derivation
// from the raw query data (optional chaining, sorting, empty-state check) so the
// page component's render tree stays a flat pass-through.
interface PaymentMethodsListProps {
  data: { myPaymentMethods: PaymentMethod[] } | undefined;
  selectedMethod: PaymentMethod | null;
  uploadingQR: boolean;
  deletingQRMethod: string | null;
  anyMutationLoading: boolean;
  onEdit: (method: PaymentMethod) => void;
  onDelete: (method: PaymentMethod) => void;
  onUploadQR: (method: PaymentMethod) => void;
  onDeleteQR: (method: PaymentMethod) => Promise<void>;
}

const PaymentMethodsList: React.FC<PaymentMethodsListProps> = ({
  data,
  selectedMethod,
  uploadingQR,
  deletingQRMethod,
  anyMutationLoading,
  onEdit,
  onDelete,
  onUploadQR,
  onDeleteQR,
}) => {
  // v8 ignore next - data is defined when query succeeds; defensive fallback
  const paymentMethods = [...(data?.myPaymentMethods ?? [])].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
  );

  return (
    <Stack spacing={2}>
      {paymentMethods.map((method) => (
        <PaymentMethodCard
          key={method.name}
          method={method}
          isReserved={isReservedName(method.name)}
          onEdit={() => onEdit(method)}
          onDelete={() => onDelete(method)}
          onUploadQR={() => onUploadQR(method)}
          onDeleteQR={() => {
            void onDeleteQR(method);
          }}
          isDeleting={anyMutationLoading || deletingQRMethod === method.name}
          isUploadingQR={uploadingQR && selectedMethod?.name === method.name}
        />
      ))}

      {paymentMethods.length === 0 && (
        <EmptyState
          title="No Payment Methods Yet"
          message="Cash and Check are always available. Add custom methods and QR codes for apps like Venmo or PayPal."
        />
      )}
    </Stack>
  );
};

// Message alerts component
interface MessageAlertsProps {
  successMessage: string | null;
  error: string | null;
  onDismissSuccess: () => void;
  onDismissError: () => void;
}

const MessageAlerts: React.FC<MessageAlertsProps> = ({ successMessage, error, onDismissSuccess, onDismissError }) => (
  <>
    {successMessage && (
      <Alert severity="success" sx={{ mb: 2 }} onClose={onDismissSuccess}>
        {successMessage}
      </Alert>
    )}
    {error && (
      <Alert severity="error" sx={{ mb: 2 }} onClose={onDismissError}>
        {error}
      </Alert>
    )}
  </>
);

export const PaymentMethodsPage: React.FC = () => {
  const navigate = useNavigate();

  // Dialog states
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [qrUploadDialogOpen, setQrUploadDialogOpen] = useState(false);
  const [selectedMethod, setSelectedMethod] = useState<PaymentMethod | null>(null);

  // Error/success states
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const successTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
    };
  }, []);

  // Helper to show success message with auto-dismiss
  const showSuccess = (message: string) => {
    setSuccessMessage(message);
    if (successTimeoutRef.current) clearTimeout(successTimeoutRef.current);
    successTimeoutRef.current = setTimeout(() => setSuccessMessage(null), 3000);
  };

  // Query payment methods
  const {
    data,
    loading,
    error: queryError,
    refetch,
  } = useQuery<{ myPaymentMethods: PaymentMethod[] }>(GET_MY_PAYMENT_METHODS, {
    fetchPolicy: 'network-only',
  });

  // Mutation error handler
  const handleMutationError = (err: Error) => setError(err.message);

  // Mutations
  const [createPaymentMethod, { loading: creating }] = useMutation(CREATE_PAYMENT_METHOD, {
    onCompleted: () => {
      showSuccess('Payment method created successfully');
      setCreateDialogOpen(false);
      refetch().catch(handleMutationError);
    },
    onError: handleMutationError,
  });

  const [updatePaymentMethod, { loading: updating }] = useMutation(UPDATE_PAYMENT_METHOD, {
    onCompleted: () => {
      showSuccess('Payment method updated successfully');
      setEditDialogOpen(false);
      setSelectedMethod(null);
      refetch().catch(handleMutationError);
    },
    onError: handleMutationError,
  });

  const [deletePaymentMethod, { loading: deleting }] = useMutation(DELETE_PAYMENT_METHOD, {
    onCompleted: () => {
      showSuccess('Payment method deleted successfully');
      setDeleteDialogOpen(false);
      setSelectedMethod(null);
      refetch().catch(handleMutationError);
    },
    onError: handleMutationError,
  });

  // QR code upload/delete states
  const [uploadingQR, setUploadingQR] = useState(false);
  const [qrUploadError, setQrUploadError] = useState<string | null>(null);
  const [requestQRUpload] = useMutation<RequestQRUploadData>(REQUEST_PAYMENT_METHOD_QR_UPLOAD);
  const [confirmQRUpload] = useMutation(CONFIRM_PAYMENT_METHOD_QR_UPLOAD);
  const [deleteQRCode] = useMutation(DELETE_PAYMENT_METHOD_QR_CODE, {
    onCompleted: () => {
      showSuccess('QR code deleted successfully');
      refetch().catch(handleMutationError);
    },
    onError: handleMutationError,
  });

  // Handlers
  const handleCreate = async (name: string) => {
    setError(null);
    await createPaymentMethod({ variables: { name } });
  };

  const handleEdit = (method: PaymentMethod) => {
    setSelectedMethod(method);
    setEditDialogOpen(true);
    setError(null);
  };

  const handleUpdate = async (oldName: string, newName: string) => {
    setError(null);
    await updatePaymentMethod({
      variables: { currentName: oldName, newName },
    });
  };

  const handleDeleteClick = (method: PaymentMethod) => {
    setSelectedMethod(method);
    setDeleteDialogOpen(true);
    setError(null);
  };

  const handleDelete = async () => {
    /* v8 ignore start - Dialog only opens when a method is selected; defensive guard */
    if (!selectedMethod) return;
    /* v8 ignore stop */
    setError(null);
    await deletePaymentMethod({ variables: { name: selectedMethod.name } });
  };

  const handleQRUploadClick = (method: PaymentMethod) => {
    setSelectedMethod(method);
    setQrUploadDialogOpen(true);
    setError(null);
    setQrUploadError(null);
  };

  // Helper to parse S3 fields and upload file
  const uploadToS3 = async (uploadUrl: string, fields: string, file: File): Promise<void> => {
    const parsedFields = typeof fields === 'string' ? JSON.parse(fields) : fields;
    const formData = new FormData();
    Object.entries(parsedFields).forEach(([key, value]) => {
      formData.append(key, value as string);
    });
    formData.append('file', file);

    const uploadResponse = await fetch(uploadUrl, { method: 'POST', body: formData });
    if (!uploadResponse.ok) {
      throw new Error('Failed to upload file to S3');
    }
  };

  const handleQRUpload = async (file: File): Promise<void> => {
    /* v8 ignore start - Dialog only opens when a method is selected; defensive guard */
    if (!selectedMethod) return;
    /* v8 ignore stop */
    setError(null);
    setQrUploadError(null);
    setUploadingQR(true);

    try {
      // Request pre-signed upload URL
      const { data: uploadData } = await requestQRUpload({
        variables: { paymentMethodName: selectedMethod.name },
      });

      /* v8 ignore start - Apollo Client returns data on success; defensive null check */
      if (!uploadData) {
        throw new Error('Failed to get upload URL');
      }
      /* v8 ignore stop */

      const { uploadUrl, fields, s3Key } = uploadData.requestPaymentMethodQRCodeUpload;

      // Upload to S3
      await uploadToS3(uploadUrl, fields, file);

      // Confirm upload
      await confirmQRUpload({
        variables: {
          paymentMethodName: selectedMethod.name,
          s3Key,
        },
      });

      await refetch().catch(() => {});
      showSuccess('QR code uploaded successfully');
      setQrUploadDialogOpen(false);
      setSelectedMethod(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to upload QR code';
      setQrUploadError(message);
      throw err; // Re-throw to let dialog handle error state
    } finally {
      setUploadingQR(false);
    }
  };

  const handleDeleteQRCode = async (method: PaymentMethod) => {
    setError(null);
    setDeletingQRMethod(method.name);
    try {
      await deleteQRCode({ variables: { paymentMethodName: method.name } });
    } finally {
      setDeletingQRMethod(null);
    }
  };

  // Dialog close handlers
  const closeCreateDialog = () => setCreateDialogOpen(false);
  const closeEditDialog = () => {
    setEditDialogOpen(false);
    setSelectedMethod(null);
  };
  const closeDeleteDialog = () => {
    setDeleteDialogOpen(false);
    setSelectedMethod(null);
  };
  const closeQrUploadDialog = () => {
    setQrUploadDialogOpen(false);
    setSelectedMethod(null);
    setQrUploadError(null);
  };

  // Track which method is having its QR deleted
  const [deletingQRMethod, setDeletingQRMethod] = useState<string | null>(null);

  // Dialogs need the selected method's name; the existing-names list for
  // validation is derived inside PaymentMethodDialogs where it is consumed.
  const selectedName = selectedMethod ? selectedMethod.name : '';

  if (loading) {
    return <LoadingState />;
  }

  if (queryError) {
    return <ErrorAlert message={`Failed to load payment methods: ${queryError.message}`} />;
  }

  return (
    <Box>
      {/* Header */}
      <PageHeader
        title="Payment Methods"
        subtitle="Cash and Check are always available. Create custom methods and add QR codes for apps like Venmo or PayPal."
        backButton={{
          onClick: () => {
            void navigate('/settings');
          },
          label: 'Back',
          'aria-label': 'Back to settings',
        }}
        action={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setError(null);
              setCreateDialogOpen(true);
            }}
          >
            Add Payment Method
          </Button>
        }
      />

      {/* Success/Error Messages */}
      <MessageAlerts
        successMessage={successMessage}
        error={error}
        onDismissSuccess={() => setSuccessMessage(null)}
        onDismissError={() => setError(null)}
      />

      {/* Payment Methods List */}
      <PaymentMethodsList
        data={data}
        selectedMethod={selectedMethod}
        uploadingQR={uploadingQR}
        deletingQRMethod={deletingQRMethod}
        anyMutationLoading={deleting}
        onEdit={handleEdit}
        onDelete={handleDeleteClick}
        onUploadQR={handleQRUploadClick}
        onDeleteQR={handleDeleteQRCode}
      />

      <PaymentMethodDialogs
        createOpen={createDialogOpen}
        createIsLoading={creating}
        data={data}
        onCreate={handleCreate}
        onCloseCreate={closeCreateDialog}
        editOpen={editDialogOpen}
        editIsLoading={updating}
        currentName={selectedName}
        onUpdate={handleUpdate}
        onCloseEdit={closeEditDialog}
        deleteOpen={deleteDialogOpen}
        deleteIsLoading={deleting}
        onDelete={handleDelete}
        onCloseDelete={closeDeleteDialog}
        qrOpen={qrUploadDialogOpen}
        qrIsLoading={uploadingQR}
        qrError={qrUploadError}
        onUpload={handleQRUpload}
        onCloseQr={closeQrUploadDialog}
      />
    </Box>
  );
};
