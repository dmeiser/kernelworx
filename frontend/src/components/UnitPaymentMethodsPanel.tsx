/**
 * Unit payment methods: what this Unit may sell against, and the QR image behind each
 * one (Show & Sell §4.1.3, on the surfaces §4.1.1 and §4.1.2 put on the wire).
 *
 * Four rules shape this screen, and every one of them is the server's — the controls
 * here only make the rule visible before a write has to refuse it:
 *
 * - Cash, Check, and Other are computed. They arrive with `version: 0`, no `createdAt`,
 *   and nothing to change, so their controls are disabled with the reason rather than
 *   missing: a method a Unit sells against has to stay visible, and an absent button
 *   reads as a bug where a disabled one reads as a rule.
 * - A custom method is renamed and retired, never deleted. A rename keeps
 *   `paymentMethodId` and the QR reference, and a sale already written keeps the name it
 *   was written under, so this screen edits the present without touching history.
 * - Every write carries the `version` this screen read plus a fresh idempotency key.
 *   `CONFLICT` is the answer to two different facts — this row moved, or the name and
 *   the 50th slot are taken — so only the first is offered as a reload; a taken name is
 *   answered by the server's own sentence, because the fix is a different word, not a
 *   fresher picture.
 * - A QR image is three calls — ask, post, confirm — because the object exists before
 *   the reference does. The image a Unit uploads is validated by the server on confirm,
 *   so a refusal can arrive after the bytes are already in the bucket: that refusal is
 *   shown in the dialog that is still open, next to the file that caused it.
 */

import React, { useCallback, useState } from 'react';
import { useLazyQuery, useMutation, useQuery } from '@apollo/client/react';
import {
  Box,
  Button,
  Card,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Link,
  Stack,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import {
  CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
  CREATE_UNIT_PAYMENT_METHOD,
  DEACTIVATE_UNIT_PAYMENT_METHOD,
  DELETE_UNIT_PAYMENT_METHOD_QR_CODE,
  GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD,
  LIST_UNIT_PAYMENT_METHODS,
  REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
  UPDATE_UNIT_PAYMENT_METHOD,
} from '../lib/graphql';
import { isPaymentMethodTakenError, isStaleVersionError, newIdempotencyKey, refreshQuery } from '../lib/units';
import { ConfirmDialog } from './ConfirmDialog';
import { ErrorNote } from './ErrorAlert';
import { FormDialog } from './FormDialog';
import { LoadingState } from './LoadingState';
import { QueryGate } from './QueryGate';
import { QRUploadDialog } from './QRUploadDialog';
import { QrCodeImage } from './QrCodeImage';
import type {
  GqlListUnitPaymentMethodsQuery,
  GqlS3UploadInfo,
  GqlUnit,
  GqlUnitPaymentMethod,
  GqlUnitPaymentMethodQrDownload,
} from '../types/graphql-generated';

/**
 * The ceiling on active custom methods, mirrored from the server's
 * `src/utils/unit_payment_models.py:MAX_ACTIVE_PAYMENT_METHODS`.
 *
 * It is repeated here only to explain a disabled button before the 51st write has to
 * refuse it; the server's count is the one that decides.
 */
const MAX_ACTIVE_CUSTOM_METHODS = 50;

/** Built-ins answer `createdAt: null`; a custom method always carries who made it. */
function isComputedMethod(method: GqlUnitPaymentMethod): boolean {
  return method.createdAt == null;
}

/** A name is submitted trimmed; the server trims too, and both must mean the same row. */
function isSubmittableName(name: string): boolean {
  const trimmed = name.trim();
  return trimmed.length > 0 && trimmed.length <= 100;
}

function readMethods(data?: GqlListUnitPaymentMethodsQuery | null): GqlUnitPaymentMethod[] {
  return data?.unitPaymentMethods ?? [];
}

/** Only custom, still-active methods occupy one of the 50 slots. */
function countActiveCustom(methods: GqlUnitPaymentMethod[]): number {
  return methods.filter((method) => !isComputedMethod(method) && method.isActive).length;
}

function readDownloadUrl(data?: { unitPaymentMethodQrDownloadUrl?: GqlUnitPaymentMethodQrDownload } | null): string | null {
  return data?.unitPaymentMethodQrDownloadUrl?.downloadUrl ?? null;
}

/** A dialog heading or field for a row that may already have closed under the reader. */
function nameOfMethod(method?: GqlUnitPaymentMethod | null): string {
  return method?.displayName ?? '';
}

function idOfMethod(method?: GqlUnitPaymentMethod | null): string {
  return method?.paymentMethodId ?? '';
}

interface UnitPaymentMethodsPanelProps {
  unit: GqlUnit;
}

/**
 * A create or rename in flight, with the key this attempt owns.
 *
 * A rename always names a row this screen read, so the row is part of the variant rather
 * than an optional field a later callback has to re-check.
 */
type NameDialog =
  | { kind: 'create'; idempotencyKey: string }
  | { kind: 'rename'; method: GqlUnitPaymentMethod; idempotencyKey: string };

/** A destructive write waiting on one confirmation. */
interface PendingWrite {
  kind: 'deactivate' | 'remove-qr';
  method: GqlUnitPaymentMethod;
  idempotencyKey: string;
}

export const UnitPaymentMethodsPanel: React.FC<UnitPaymentMethodsPanelProps> = ({ unit }) => {
  const [includeInactive, setIncludeInactive] = useState(false);
  const [nameDialog, setNameDialog] = useState<NameDialog | null>(null);
  const [pending, setPending] = useState<PendingWrite | null>(null);
  const [qrMethod, setQrMethod] = useState<GqlUnitPaymentMethod | null>(null);
  const [preview, setPreview] = useState<GqlUnitPaymentMethod | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const methods = useQuery<GqlListUnitPaymentMethodsQuery>(LIST_UNIT_PAYMENT_METHODS, {
    variables: { unitId: unit.unitId, includeInactive },
  });
  const [runQrDownload] = useLazyQuery<{
    unitPaymentMethodQrDownloadUrl: GqlUnitPaymentMethodQrDownload;
  }>(GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD);
  const writes = usePaymentMethodWrites({ unitId: unit.unitId, refetch: methods.refetch, setActionError });

  const listed = readMethods(methods.data);
  const activeCustom = countActiveCustom(listed);
  const atLimit = activeCustom >= MAX_ACTIVE_CUSTOM_METHODS;

  const askToRename = useCallback((method: GqlUnitPaymentMethod) => {
    setFormError(null);
    setNameDialog({ kind: 'rename', method, idempotencyKey: newIdempotencyKey() });
  }, []);

  const askToRetire = useCallback((method: GqlUnitPaymentMethod) => {
    setPending({ kind: 'deactivate', method, idempotencyKey: newIdempotencyKey() });
  }, []);

  const askToRemoveQr = useCallback((method: GqlUnitPaymentMethod) => {
    setPending({ kind: 'remove-qr', method, idempotencyKey: newIdempotencyKey() });
  }, []);

  /**
   * Opens the QR dialog and reads its image at the same moment.
   *
   * The pre-signed URL is short-lived, so it is asked for here rather than carried in
   * the list, and the dialog shows a spinner while it is on its way: a picture that has
   * not arrived is not yet a picture that failed.
   */
  const openPreview = useCallback(
    async (method: GqlUnitPaymentMethod): Promise<void> => {
      setPreviewError(null);
      setPreviewUrl(null);
      setPreviewLoading(true);
      setPreview(method);
      try {
        const result = await runQrDownload({
          variables: { unitId: unit.unitId, paymentMethodId: method.paymentMethodId },
        });
        const url = readDownloadUrl(result.data);
        if (!url) setPreviewError(qrDownloadFailure(undefined));
        else setPreviewUrl(url);
      } catch (error) {
        setPreviewError(qrDownloadFailure(error));
      } finally {
        setPreviewLoading(false);
      }
    },
    [runQrDownload, unit.unitId],
  );

  const submitName = useCallback(
    async (dialog: NameDialog, displayName: string): Promise<void> => {
      const failure = await writes.submitName(dialog, unit.unitId, displayName);
      setFormError(failure);
      if (!failure) setNameDialog(null);
    },
    [unit.unitId, writes],
  );

  const runPending = useCallback(
    async (write: PendingWrite): Promise<void> => {
      await writes.runPending(write);
      setPending(null);
    },
    [writes],
  );

  return (
    <QueryGate
      query={methods}
      loading={<LoadingState minHeight="200px" />}
      failure={<ErrorNote message="Could not load this Unit's payment methods." />}
    >
      <Box sx={{ pt: 2 }}>
        <ErrorNote message={actionError} onDismiss={() => setActionError(null)} />

        <MethodActions
          atLimit={atLimit}
          activeCustom={activeCustom}
          includeInactive={includeInactive}
          onToggleInactive={setIncludeInactive}
          onCreate={() => {
            setFormError(null);
            setNameDialog({ kind: 'create', idempotencyKey: newIdempotencyKey() });
          }}
        />

        <MethodTable
          methods={listed}
          onRename={askToRename}
          onQr={setQrMethod}
          onPreview={(method) => void openPreview(method)}
          onRemoveQr={askToRemoveQr}
          onDeactivate={askToRetire}
        />

        {nameDialog ? (
          <NameFormDialog
            dialog={nameDialog}
            formError={formError}
            onDismissError={() => setFormError(null)}
            onCancel={() => setNameDialog(null)}
            onSubmit={submitName}
          />
        ) : null}

        <QrUploadFlow method={qrMethod} onUpload={writes.uploadQr} onClose={() => setQrMethod(null)} />

        <QrPreviewDialog
          open={preview !== null}
          methodName={nameOfMethod(preview)}
          url={previewUrl}
          failure={previewError}
          loading={previewLoading}
          onClose={() => {
            setPreview(null);
            setPreviewUrl(null);
            setPreviewError(null);
          }}
        />

        {pending ? (
          <PendingWriteDialog pending={pending} onConfirm={(write) => void runPending(write)} onClose={() => setPending(null)} />
        ) : null}
      </Box>
    </QueryGate>
  );
};

/**
 * The six writes and what each failure means to the person holding the screen.
 *
 * A stale `CONFLICT` is answered as "this changed, reload it" and followed by an actual
 * re-read, because a second submit from the same stale picture would be refused again
 * for the same reason. Every other refusal is the server's own sentence: it names the
 * reserved name, the duplicate, the 50-method ceiling, the oversize image, or the foreign
 * key, and those words are more useful than a paraphrase of them.
 */
interface WritesArgs {
  unitId: string;
  refetch: () => unknown;
  setActionError: (message: string | null) => void;
}

function usePaymentMethodWrites({ unitId, refetch, setActionError }: WritesArgs) {
  const [createMethod] = useMutation(CREATE_UNIT_PAYMENT_METHOD);
  const [renameMethod] = useMutation(UPDATE_UNIT_PAYMENT_METHOD);
  const [deactivateMethod] = useMutation(DEACTIVATE_UNIT_PAYMENT_METHOD);
  const [requestQr] = useMutation<{ requestUnitPaymentMethodQrUpload: GqlS3UploadInfo }>(
    REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
  );
  const [confirmQr] = useMutation(CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD);
  const [deleteQr] = useMutation(DELETE_UNIT_PAYMENT_METHOD_QR_CODE);

  const failed = useCallback(
    async (error: unknown, fallback: string): Promise<string> => {
      if (isStaleWrite(error)) {
        await refreshQuery(refetch);
        return STALE_MESSAGE;
      }
      return serverSentence(error, fallback);
    },
    [refetch],
  );

  const submitName = useCallback(
    async (dialog: NameDialog, targetUnitId: string, displayName: string): Promise<string | null> => {
      try {
        if (dialog.kind === 'create') await createMethod({ variables: { input: createInput(dialog, targetUnitId, displayName) } });
        else await renameMethod({ variables: { input: renameInput(dialog, targetUnitId, displayName) } });
      } catch (error) {
        return failed(error, 'That payment method could not be saved.');
      }
      await refreshQuery(refetch);
      return null;
    },
    [createMethod, renameMethod, refetch, failed],
  );

  const runPending = useCallback(
    async (write: PendingWrite): Promise<void> => {
      const input = versionedInput(unitId, write);
      try {
        if (write.kind === 'deactivate') await deactivateMethod({ variables: { input } });
        else await deleteQr({ variables: { input } });
      } catch (error) {
        setActionError(await failed(error, 'That change could not be made.'));
      }
      await refreshQuery(refetch);
    },
    [unitId, deactivateMethod, deleteQr, refetch, failed, setActionError],
  );

  const uploadQr = useCallback(
    async (method: GqlUnitPaymentMethod, file: File): Promise<void> => {
      const requested = await requestQr({ variables: { input: await uploadRequestInput(unitId, method, file) } });
      const target = requested.data?.requestUnitPaymentMethodQrUpload;
      if (!target) throw new Error('The upload target could not be prepared.');
      await postToS3(target.uploadUrl, target.fields, file);
      await confirmQr({ variables: { input: confirmInput(unitId, method, target.s3Key) } });
      await refreshQuery(refetch);
    },
    [unitId, requestQr, confirmQr, refetch],
  );

  return { submitName, runPending, uploadQr };
}

const STALE_MESSAGE =
  'This payment method changed while you were working. The list has been reloaded — check it and try again.';

function createInput(dialog: NameDialog, unitId: string, displayName: string): Record<string, unknown> {
  return { unitId, displayName: displayName.trim(), idempotency: { idempotencyKey: dialog.idempotencyKey } };
}

function renameInput(dialog: Extract<NameDialog, { kind: 'rename' }>, unitId: string, displayName: string): Record<string, unknown> {
  return {
    unitId,
    paymentMethodId: dialog.method.paymentMethodId,
    displayName: displayName.trim(),
    version: { expectedVersion: dialog.method.version },
    idempotency: { idempotencyKey: dialog.idempotencyKey },
  };
}

/** A retire and a QR removal are the same shaped write: this row, at this version. */
function versionedInput(unitId: string, write: PendingWrite): Record<string, unknown> {
  return {
    unitId,
    paymentMethodId: write.method.paymentMethodId,
    version: { expectedVersion: write.method.version },
    idempotency: { idempotencyKey: write.idempotencyKey },
  };
}

async function uploadRequestInput(
  unitId: string,
  method: GqlUnitPaymentMethod,
  file: File,
): Promise<Record<string, unknown>> {
  return {
    unitId,
    paymentMethodId: method.paymentMethodId,
    contentType: file.type,
    sha256: await sha256Hex(file),
    idempotency: { idempotencyKey: newIdempotencyKey() },
  };
}

/**
 * The SHA-256 the upload request names its object after.
 *
 * The server puts this digest in the pre-signed key and the confirm step proves
 * the object in the bucket hashes to it, so the reference that ends up on the row
 * commits to the exact bytes this file holds. The hash is computed here, from the
 * same bytes being POSTed: a declared digest the browser did not actually
 * compute is worth nothing to that check.
 */
async function sha256Hex(file: File): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('');
}

function confirmInput(unitId: string, method: GqlUnitPaymentMethod, s3Key: string): Record<string, unknown> {
  return {
    unitId,
    paymentMethodId: method.paymentMethodId,
    s3Key,
    version: { expectedVersion: method.version },
    idempotency: { idempotencyKey: newIdempotencyKey() },
  };
}

/**
 * The pre-signed POST the browser makes directly to S3: fields first, file last.
 *
 * `fields` arrives as an object from codegen and as a JSON string from the wire, so both
 * shapes are read here rather than trusting one; the order matters because S3 refuses a
 * POST whose `file` part is not last.
 */
async function postToS3(uploadUrl: string, fields: string | Record<string, unknown>, file: File): Promise<void> {
  const parsed = typeof fields === 'string' ? JSON.parse(fields) : fields;
  const formData = new FormData();
  Object.entries(parsed as Record<string, string>).forEach(([key, value]) => {
    formData.append(key, value);
  });
  formData.append('file', file);
  const response = await fetch(uploadUrl, { method: 'POST', body: formData });
  if (!response.ok) throw new Error('The image could not be sent to storage.');
}

/**
 * What a refused read or write means, in the reader's terms.
 *
 * `CONFLICT` carries two different facts on the wire — this row moved, or the name and
 * the 50th slot are taken — and only the first is fixed by re-reading, so both signals
 * are consulted before a reader is told to start over. Anything else is the server's own
 * sentence, which already names the reserved word, the ceiling, the size, or the key that
 * belongs to another method.
 */
function isStaleWrite(error: unknown): boolean {
  return isStaleVersionError(error) && !isPaymentMethodTakenError(error);
}

/** The server's own reason, which already names the reserved word or the oversize image. */
function serverSentence(error: unknown, fallback: string): string {
  return (error as Error)?.message || fallback;
}

function qrUploadFailure(error: unknown): string {
  if (isStaleWrite(error)) return STALE_MESSAGE;
  return serverSentence(error, 'The QR image could not be uploaded.');
}

function qrDownloadFailure(error: unknown): string {
  if (isStaleWrite(error)) return STALE_MESSAGE;
  return serverSentence(error, 'The QR image could not be opened.');
}

const MethodActions: React.FC<{
  atLimit: boolean;
  activeCustom: number;
  includeInactive: boolean;
  onToggleInactive: (next: boolean) => void;
  onCreate: () => void;
}> = ({ atLimit, activeCustom, includeInactive, onToggleInactive, onCreate }) => (
  <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap">
    <Tooltip title={atLimit ? `A Unit keeps at most ${MAX_ACTIVE_CUSTOM_METHODS} active methods.` : ''}>
      <span>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={onCreate}
          disabled={atLimit}
          data-testid="create-payment-method"
        >
          Add payment method
        </Button>
      </span>
    </Tooltip>
    <Typography variant="body2" color="text.secondary" data-testid="active-method-count">
      {activeCustom} active custom method{activeCustom === 1 ? '' : 's'}
    </Typography>
    <Stack direction="row" spacing={1} alignItems="center">
      <Typography variant="body2" color="text.secondary" component="label" htmlFor="show-inactive-methods">
        Show retired methods
      </Typography>
      <Switch
        id="show-inactive-methods"
        checked={includeInactive}
        onChange={(event) => onToggleInactive(event.target.checked)}
        data-testid="show-inactive-methods"
      />
    </Stack>
  </Stack>
);

const MethodTable: React.FC<{
  methods: GqlUnitPaymentMethod[];
  onRename: (method: GqlUnitPaymentMethod) => void;
  onQr: (method: GqlUnitPaymentMethod) => void;
  onPreview: (method: GqlUnitPaymentMethod) => void;
  onRemoveQr: (method: GqlUnitPaymentMethod) => void;
  onDeactivate: (method: GqlUnitPaymentMethod) => void;
}> = ({ methods, onRename, onQr, onPreview, onRemoveQr, onDeactivate }) => (
  <Card variant="outlined">
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>Method</TableCell>
          <TableCell>QR image</TableCell>
          <TableCell align="right">Actions</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {methods.map((method) => (
          <MethodRow
            key={method.paymentMethodId}
            method={method}
            onRename={onRename}
            onQr={onQr}
            onPreview={onPreview}
            onRemoveQr={onRemoveQr}
            onDeactivate={onDeactivate}
          />
        ))}
      </TableBody>
    </Table>
  </Card>
);

const MethodRow: React.FC<{
  method: GqlUnitPaymentMethod;
  onRename: (method: GqlUnitPaymentMethod) => void;
  onQr: (method: GqlUnitPaymentMethod) => void;
  onPreview: (method: GqlUnitPaymentMethod) => void;
  onRemoveQr: (method: GqlUnitPaymentMethod) => void;
  onDeactivate: (method: GqlUnitPaymentMethod) => void;
}> = ({ method, onRename, onQr, onPreview, onRemoveQr, onDeactivate }) => (
  <TableRow data-testid={`method-row-${method.paymentMethodId}`}>
    <TableCell>
      <MethodLabel method={method} />
    </TableCell>
    <QrCell method={method} onPreview={onPreview} />
    <MethodControls
      method={method}
      onRename={onRename}
      onQr={onQr}
      onRemoveQr={onRemoveQr}
      onDeactivate={onDeactivate}
    />
  </TableRow>
);

/**
 * Why a computed method's controls are switched off, said in the row itself.
 *
 * The built-ins are the same three everywhere and carry no name, version, or image of
 * their own; a Unit that wants a different spelling adds a custom method. A retired one
 * stays listed because a sale already made names it, and a reader of that sale has to be
 * able to see the same words.
 */
const MethodLabel: React.FC<{ method: GqlUnitPaymentMethod }> = ({ method }) => (
  <Stack direction="row" spacing={1} alignItems="center">
    <Typography>{method.displayName}</Typography>
    {isComputedMethod(method) ? (
      <Typography variant="caption" color="text.secondary" data-testid={`computed-${method.paymentMethodId}`}>
        always available
      </Typography>
    ) : null}
    {!method.isActive ? (
      <Typography variant="caption" color="text.secondary" data-testid={`retired-${method.paymentMethodId}`}>
        retired — sales already made still read this way
      </Typography>
    ) : null}
  </Stack>
);

const QrCell: React.FC<{ method: GqlUnitPaymentMethod; onPreview: (method: GqlUnitPaymentMethod) => void }> = ({
  method,
  onPreview,
}) => (
  <TableCell data-testid={`qr-state-${method.paymentMethodId}`}>
    {method.qrCodeS3Key ? (
      <Button size="small" onClick={() => onPreview(method)} data-testid={`view-qr-${method.paymentMethodId}`}>
        View QR
      </Button>
    ) : (
      <Typography variant="body2" color="text.secondary">
        None
      </Typography>
    )}
  </TableCell>
);

/**
 * The row's controls.
 *
 * A computed method gets disabled controls rather than none, and a retired method gets
 * no second retire: the server refuses both, and showing the refusal before the click is
 * the cheaper answer.
 */
const MethodControls: React.FC<{
  method: GqlUnitPaymentMethod;
  onRename: (method: GqlUnitPaymentMethod) => void;
  onQr: (method: GqlUnitPaymentMethod) => void;
  onRemoveQr: (method: GqlUnitPaymentMethod) => void;
  onDeactivate: (method: GqlUnitPaymentMethod) => void;
}> = ({ method, onRename, onQr, onRemoveQr, onDeactivate }) => {
  const computed = isComputedMethod(method);
  const id = method.paymentMethodId;
  return (
    <TableCell align="right">
      <Stack direction="row" spacing={1} justifyContent="flex-end">
        <Button size="small" onClick={() => onRename(method)} disabled={computed} data-testid={`rename-${id}`}>
          Rename
        </Button>
        <Button size="small" onClick={() => onQr(method)} disabled={computed} data-testid={`qr-${id}`}>
          {QrActionLabel(method)}
        </Button>
        {QrRemovalControl(method, onRemoveQr)}
        <Button
          size="small"
          color="error"
          onClick={() => onDeactivate(method)}
          disabled={computed || !method.isActive}
          data-testid={`deactivate-${id}`}
        >
          Deactivate
        </Button>
      </Stack>
    </TableCell>
  );
};

function QrActionLabel(method: GqlUnitPaymentMethod): string {
  return method.qrCodeS3Key ? 'Replace QR' : 'Upload QR';
}

function QrRemovalControl(
  method: GqlUnitPaymentMethod,
  onRemoveQr: (method: GqlUnitPaymentMethod) => void,
): React.ReactElement | null {
  if (isComputedMethod(method) || !method.qrCodeS3Key) return null;
  return (
    <Button size="small" onClick={() => onRemoveQr(method)} data-testid={`remove-qr-${method.paymentMethodId}`}>
      Remove QR
    </Button>
  );
}

/** The words a name dialog shows, derived once from what is being named. */
function nameDialogCopy(dialog: NameDialog): { title: string; confirmLabel: string } {
  if (dialog.kind === 'create') return { title: 'Add a payment method', confirmLabel: 'Add method' };
  return { title: `Rename ${nameOfMethod(rowInDialog(dialog))}`, confirmLabel: 'Save name' };
}

/** The row a rename is editing; a create has no row yet, so nothing is pre-filled. */
function rowInDialog(dialog: NameDialog): GqlUnitPaymentMethod | null {
  return dialog.kind === 'rename' ? dialog.method : null;
}

/** The local complaint wins over the one the server sent, because it is the nearer one. */
function shownError(local: string | null, server: string | null): string | null {
  return local ?? server;
}

/**
 * The name field, in a real form.
 *
 * The form is what makes Enter mean "save" for a keyboard user, and `preventDefault` is
 * what stops that Enter from being a page navigation. A second Enter cannot create a
 * second method: both presses carry the same idempotency key, so the server replays the
 * first intent rather than recording a new one.
 */
const NameFormDialog: React.FC<{
  dialog: NameDialog;
  formError: string | null;
  onDismissError: () => void;
  onCancel: () => void;
  onSubmit: (dialog: NameDialog, displayName: string) => Promise<void>;
}> = ({ dialog, formError, onDismissError, onCancel, onSubmit }) => {
  const [name, setName] = useState(nameOfMethod(rowInDialog(dialog)));
  const [localError, setLocalError] = useState<string | null>(null);
  const copy = nameDialogCopy(dialog);

  const submit = async (): Promise<void> => {
    if (!isSubmittableName(name)) {
      setLocalError('A method needs a name of 1 to 100 characters.');
      return;
    }
    setLocalError(null);
    await onSubmit(dialog, name);
  };

  return (
    <FormDialog
      title={copy.title}
      confirmLabel={copy.confirmLabel}
      onCancel={onCancel}
      onConfirm={() => void submit()}
      error={shownError(localError, formError)}
      onDismissError={() => {
        setLocalError(null);
        onDismissError();
      }}
    >
      <Box
        component="form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
        sx={{ pt: 1 }}
      >
        <TextField
          autoFocus
          fullWidth
          label="Method name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          helperText="Cash, Check, and Other are reserved. A name must be different from every other method on this Unit, ignoring capitalization."
          inputProps={{ maxLength: 100, 'aria-label': 'Payment method name' }}
          data-testid="method-name-field"
          data-method-id={idOfMethod(rowInDialog(dialog))}
        />
      </Box>
    </FormDialog>
  );
};

/**
 * Ask, post, confirm — with the failure left on screen.
 *
 * The dialog stays open when confirm refuses, because the bytes already reached storage
 * and the reader needs to see which file the server turned down.
 */
const QrUploadFlow: React.FC<{
  method: GqlUnitPaymentMethod | null;
  onUpload: (method: GqlUnitPaymentMethod, file: File) => Promise<void>;
  onClose: () => void;
}> = ({ method, onUpload, onClose }) => {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const upload = async (file: File): Promise<void> => {
    if (!method) return;
    setBusy(true);
    setError(null);
    try {
      await onUpload(method, file);
    } catch (uploadError) {
      setError(qrUploadFailure(uploadError));
      throw uploadError;
    } finally {
      setBusy(false);
    }
  };

  return (
    <QRUploadDialog
      open={method !== null}
      onClose={() => {
        setError(null);
        onClose();
      }}
      onUpload={(file) => upload(file)}
      methodName={nameOfMethod(method)}
      isLoading={busy}
      uploadError={error}
    />
  );
};

/**
 * The QR image itself, read at the moment it is asked for.
 *
 * The pre-signed URL expires, so the image is fetched when the dialog opens rather than
 * carried in the list, and the link beside it is the same short-lived URL: a saved link
 * stops working, which is the point of a QR image that belongs to one Unit.
 */
const QrPreviewDialog: React.FC<{
  open: boolean;
  methodName: string;
  url: string | null;
  failure: string | null;
  loading: boolean;
  onClose: () => void;
}> = ({ open, methodName, url, failure, loading, onClose }) => (
  <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
    <DialogTitle>QR code for {methodName}</DialogTitle>
    <DialogContent>
      <QrPreviewBody url={url} failure={failure} loading={loading} methodName={methodName} />
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} data-testid="close-qr-preview">
        Close
      </Button>
    </DialogActions>
  </Dialog>
);

/**
 * The three things the image can be: on its way, here, or not available.
 *
 * A picture that has not arrived yet is not a picture that failed, so the wait gets a
 * spinner and only a settled read is allowed to say the image could not be opened.
 */
const QrPreviewBody: React.FC<{
  url: string | null;
  failure: string | null;
  loading: boolean;
  methodName: string;
}> = ({ url, failure, loading, methodName }) => {
  if (url) {
    return (
      <>
        <QrCodeImage qrCodeUrl={url} methodName={methodName} />
        <Link href={url} data-testid="qr-download-link" download>
          Download this image
        </Link>
      </>
    );
  }
  if (loading) return <LoadingState minHeight="160px" />;
  return <ErrorNote message={failure ?? 'The QR image could not be opened.'} />;
};

/** The two confirmations say what actually happens to history, in their own words. */
function pendingCopy(pending: PendingWrite): { title: string; label: string; notice: string } {
  if (pending.kind === 'deactivate') {
    return {
      title: 'Retire this payment method?',
      label: 'Retire method',
      notice:
        'It stops appearing for new sales. Sales already made under it keep their own copy of the name, and it stays readable in history.',
    };
  }
  return {
    title: 'Remove this QR image?',
    label: 'Remove QR image',
    notice: 'The image is deleted and unattached. The method itself and every sale made with it are untouched.',
  };
}

const PendingWriteDialog: React.FC<{
  pending: PendingWrite;
  onConfirm: (write: PendingWrite) => void;
  onClose: () => void;
}> = ({ pending, onConfirm, onClose }) => {
  const copy = pendingCopy(pending);
  return (
    <ConfirmDialog
      open
      title={copy.title}
      confirmLabel={copy.label}
      confirmColor="error"
      onClose={onClose}
      onConfirm={() => onConfirm(pending)}
    >
      <Typography data-testid="pending-write-warning">{copy.notice}</Typography>
    </ConfirmDialog>
  );
};
