/**
 * What this Unit may sell against, and the QR image behind each method (§4.1.3).
 *
 * The screen's job is to make the server's rules visible before a write has to refuse
 * them, and these tests are the record of which rule is whose:
 *
 * - Cash, Check, and Other are computed. They are listed and switched off, so a Unit
 *   cannot lose a method every sale may use, and the reason is on the row rather than in
 *   a control that has gone missing.
 * - `CONFLICT` is two facts on the wire. A name that is already taken is answered by the
 *   server's sentence about that name; only a row that moved underneath the reader is
 *   answered by a re-read — and the re-read is proven here by the list changing, not by a
 *   message that claims it.
 * - The deactivation race is that same rule one level up: every write carries the version
 *   this screen read, so a method retired in another window comes back `CONFLICT` and the
 *   screen shows what the re-read found instead of writing blind again.
 * - A failure that is not the reader's — a Unit they no longer administer — answers the
 *   same whether the Unit is gone or was never theirs.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import {
  CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
  CREATE_UNIT_PAYMENT_METHOD,
  DEACTIVATE_UNIT_PAYMENT_METHOD,
  DELETE_UNIT_PAYMENT_METHOD_QR_CODE,
  GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD,
  LIST_UNIT_PAYMENT_METHODS,
  REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
  UPDATE_UNIT_PAYMENT_METHOD,
} from '../src/lib/graphql';
import { UnitPaymentMethodsPanel } from '../src/components/UnitPaymentMethodsPanel';
import { unitFixture } from './helpers/unitFixtures';
import { clearAndType, typeInto } from './helpers/unitUi';
import type { GqlUnitPaymentMethod } from '../src/types/graphql-generated';

const UNIT_ID = 'UNIT#pack-3149';
const WISE = 'PM#wise';

const QR_KEY = 'payment-qr-codes/units/pack-3149/PM#wise/8f2a4c1e.png';
const SIGNED_URL = 'https://kernelworx-exports-ue1-dev.s3.amazonaws.com/payment-qr-codes/units/pack-3149?X-Amz-Signature=abc';
const STALE_COPY = 'This payment method changed while you were working. The list has been reloaded — check it and try again.';
const RACE_SENTENCE = 'The resource changed underneath this request. Re-read and try again.';

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', {
    randomUUID: () => `test-idem-${++keySequence}`,
    // A fixed 32 bytes, so the upload request's declared digest is knowable by
    // the mocks below; the digest's real arithmetic is proved by the one test
    // that swaps in Node's own WebCrypto.
    subtle: { digest: async () => new Uint8Array(32).buffer },
  });
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:mock-preview');
  globalThis.URL.revokeObjectURL = vi.fn();
});

function refused(code: string, message: string): GraphQLError {
  return new GraphQLError(message, { extensions: { code } });
}

/**
 * A refusal in the shape the deployed Unit resolvers actually send.
 *
 * `tofu/application/appsync/js-resolvers/lambda_unit_resolver.js` reports a handler
 * failure with `util.error(message, errorCode, null, { errorCode })`, and AppSync puts
 * those on the GraphQL error as its own top-level `errorType` and `errorInfo` — there is
 * no `extensions` object, and `AppError.details` (where a subcode would live) never
 * crosses the boundary. Apollo Client hands that payload over unchanged, so this is the
 * shape every code-based decision on this screen has to read. The `extensions` form above
 * is what a bare `GraphQLError` from a direct link rejection carries, and both are kept
 * because the fallback reader in `units.ts` still knows it.
 */
function refused_by_the_api(code: string, message: string): { data: null; errors: { message: string; errorType: string; errorInfo: { errorCode: string } }[] } {
  return { data: null, errors: [{ message, errorType: code, errorInfo: { errorCode: code } }] };
}

/** A built-in: computed, so no `createdAt`, and version 0 because there is no row to version. */
function builtIn(paymentMethodId: string, displayName: string): GqlUnitPaymentMethod {
  return {
    __typename: 'UnitPaymentMethod',
    paymentMethodId,
    unitId: UNIT_ID,
    displayName,
    isActive: true,
    qrCodeS3Key: null,
    createdAt: null,
    version: 0,
  };
}

/** A method this Unit created, at the version the read answered. */
function customMethod(overrides: Record<string, unknown> = {}): GqlUnitPaymentMethod {
  return {
    __typename: 'UnitPaymentMethod',
    paymentMethodId: WISE,
    unitId: UNIT_ID,
    displayName: 'Wise',
    isActive: true,
    qrCodeS3Key: null,
    createdAt: '2026-02-01T15:00:00Z',
    version: 2,
    ...overrides,
  };
}

const builtIns = [builtIn('CASH', 'Cash'), builtIn('CHECK', 'Check'), builtIn('OTHER', 'Other')];

const listRequest = (includeInactive: boolean) => ({ query: LIST_UNIT_PAYMENT_METHODS, variables: { unitId: UNIT_ID, includeInactive } });

/**
 * One read of the list. `maxUsageCount` is how a test says "this same read answers the
 * re-read too"; a mock left at its default of one is what makes a second read prove
 * something, because the next mock in line carries the different rows.
 */
function listRead(methods: GqlUnitPaymentMethod[], includeInactive = false, maxUsageCount = 1) {
  return {
    request: listRequest(includeInactive),
    result: { data: { unitPaymentMethods: [...builtIns, ...methods] } },
    maxUsageCount,
  };
}

function renderPanel(mocks: unknown[]) {
  render(
    <MockedProvider mocks={mocks as never}>
      <UnitPaymentMethodsPanel unit={unitFixture()} />
    </MockedProvider>,
  );
}

/** The three controls a row offers, read as accessibility state rather than markup. */
async function rowControls(paymentMethodId: string) {
  const rename = await screen.findByTestId(`rename-${paymentMethodId}`);
  return {
    rename,
    qr: screen.getByTestId(`qr-${paymentMethodId}`),
    deactivate: screen.getByTestId(`deactivate-${paymentMethodId}`),
  };
}

const qrFile = () => new File([new ArrayBuffer(1024)], 'qr.png', { type: 'image/png' });

/** Opens the upload dialog, chooses the file, and presses the dialog's own Upload button. */
async function chooseAndUpload(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(screen.getByLabelText('Select QR code image'), qrFile());
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Upload' }));
}

describe('UnitPaymentMethodsPanel', () => {
  it('lists the three built-ins and switches their controls off, with the reason on the row', async () => {
    renderPanel([listRead([])]);

    const cash = await rowControls('CASH');
    expect(cash.rename).toBeDisabled();
    expect(cash.qr).toBeDisabled();
    expect(cash.deactivate).toBeDisabled();
    expect(screen.getByTestId('computed-CASH')).toHaveTextContent('always available');
    // Off, not absent: a method every sale may use has to stay visible.
    expect(screen.getByText('Check')).toBeInTheDocument();
    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.getByTestId('qr-state-CASH')).toHaveTextContent('None');
  });

  it('offers rename, QR, and retire on a method the Unit created', async () => {
    renderPanel([listRead([customMethod()])]);

    const wise = await rowControls(WISE);
    expect(wise.rename).toBeEnabled();
    expect(wise.qr).toBeEnabled();
    expect(wise.deactivate).toBeEnabled();
    expect(wise.qr).toHaveTextContent('Upload QR');
    expect(screen.queryByTestId(`computed-${WISE}`)).not.toBeInTheDocument();
  });

  it('creates a method with the name typed, trimmed, and one intent per dialog', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([]),
      {
        request: {
          query: CREATE_UNIT_PAYMENT_METHOD,
          variables: { input: { unitId: UNIT_ID, displayName: 'Wise', idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        result: { data: { createUnitPaymentMethod: customMethod() } },
      },
      listRead([customMethod()], false, 2),
    ]);

    await user.click(await screen.findByTestId('create-payment-method'));
    await typeInto('method-name-field', ' Wise ', user);
    await user.click(screen.getByRole('button', { name: 'Add method' }));

    expect(await screen.findByTestId(`method-row-${WISE}`)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Add method' })).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('a taken name is answered by the server’s sentence, and the dialog keeps the typing', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod()]),
      {
        request: {
          query: CREATE_UNIT_PAYMENT_METHOD,
          variables: { input: { unitId: UNIT_ID, displayName: 'wise', idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        error: refused('CONFLICT', 'This Unit already has a payment method with this name.'),
      },
    ]);

    await user.click(await screen.findByTestId('create-payment-method'));
    await typeInto('method-name-field', 'wise', user);
    await user.click(screen.getByRole('button', { name: 'Add method' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This Unit already has a payment method with this name.');
    // The same code covers a stale version, and the two want different answers.
    expect(alert).not.toHaveTextContent(STALE_COPY);
    expect(screen.getByTestId('method-name-field')).toBeInTheDocument();
  });

  it('a reserved name is refused with the three names that are spoken for', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([]),
      {
        request: {
          query: CREATE_UNIT_PAYMENT_METHOD,
          variables: { input: { unitId: UNIT_ID, displayName: 'cash', idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        error: refused('INVALID_INPUT', 'Cash, Check, and Other are built-in payment methods; choose a different name.'),
      },
    ]);

    await user.click(await screen.findByTestId('create-payment-method'));
    await typeInto('method-name-field', '  cash  ', user);
    await user.click(screen.getByRole('button', { name: 'Add method' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Cash, Check, and Other are built-in payment methods');
    // The dialog is still open with the typing intact, because the fix is a different word.
    expect(screen.getByTestId('method-name-field')).toBeInTheDocument();
  });

  it('an empty name is stopped here, where it costs no write', async () => {
    const user = userEvent.setup();
    renderPanel([listRead([])]);

    await user.click(await screen.findByTestId('create-payment-method'));
    await typeInto('method-name-field', '   ', user);
    await user.click(screen.getByRole('button', { name: 'Add method' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('A method needs a name of 1 to 100 characters.');
    expect(screen.getByTestId('method-name-field')).toBeInTheDocument();
  });

  it('a rename against a stale version re-reads the list instead of writing again', async () => {
    const user = userEvent.setup();
    renderPanel([
      // The first read says Wise at version 2. The re-read says what the other admin
      // actually wrote, and the screen has to show that name.
      listRead([customMethod({ version: 2 })]),
      {
        request: {
          query: UPDATE_UNIT_PAYMENT_METHOD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              displayName: 'Wise Pay',
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: refused('CONFLICT', RACE_SENTENCE),
      },
      listRead([customMethod({ displayName: 'Wise Pay', version: 4 })], false, 2),
    ]);

    await user.click(await screen.findByTestId(`rename-${WISE}`));
    await clearAndType('method-name-field', 'Wise Pay', user);
    await user.click(screen.getByRole('button', { name: 'Save name' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(STALE_COPY);
    expect(await screen.findByText('Wise Pay')).toBeInTheDocument();
  });

  it('retiring a method asks once, says what happens to history, and then drops it from the default read', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod()]),
      {
        request: {
          query: DEACTIVATE_UNIT_PAYMENT_METHOD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { deactivateUnitPaymentMethod: customMethod({ isActive: false, version: 3 }) } },
      },
      // The default read is what a new sale may select, so the retired row is gone from it.
      listRead([], false, 2),
    ]);

    await user.click(await screen.findByTestId(`deactivate-${WISE}`));
    expect(await screen.findByTestId('pending-write-warning')).toHaveTextContent('It stops appearing for new sales.');
    await user.click(screen.getByRole('button', { name: 'Retire method' }));

    // The default read is what a new sale may select, so the re-read that follows the
    // write drops the retired row.
    await waitFor(() => expect(screen.queryByTestId(`method-row-${WISE}`)).not.toBeInTheDocument());
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('the deactivation race: a method retired in another window comes back CONFLICT and the list shows the truth', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ version: 2 })]),
      {
        request: {
          query: DEACTIVATE_UNIT_PAYMENT_METHOD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: refused('CONFLICT', RACE_SENTENCE),
      },
      // The other admin retired it, and the reader never asked for history, so the
      // re-read answers without the row — no second control to press blind.
      listRead([], false, 2),
    ]);

    await user.click(await screen.findByTestId(`deactivate-${WISE}`));
    await user.click(screen.getByRole('button', { name: 'Retire method' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(STALE_COPY);
    // The re-read that answered the CONFLICT is the same read that shows the row is gone
    // from what a new sale may select — the screen does not offer a second blind write.
    await waitFor(() => expect(screen.queryByTestId(`deactivate-${WISE}`)).not.toBeInTheDocument());
  });

  it('a retired method appears when history is asked for, with no second retire', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod()], false, 2),
      listRead([customMethod({ isActive: false, version: 3 })], true, 2),
    ]);

    await user.click(await screen.findByRole('switch', { name: 'Show retired methods' }));

    const row = await screen.findByTestId(`method-row-${WISE}`);
    expect(within(row).getByText('retired — sales already made still read this way')).toBeInTheDocument();
    expect(within(row).getByTestId(`deactivate-${WISE}`)).toBeDisabled();
    // The built-ins are still there, still three, still always available.
    expect(screen.getAllByTestId(/^computed-/)).toHaveLength(3);
  });

  it('the QR image is asked for when it is opened, and the save control carries its file name', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY })]),
      {
        request: { query: GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD, variables: { unitId: UNIT_ID, paymentMethodId: WISE } },
        result: {
          data: {
            unitPaymentMethodQrDownloadUrl: {
              __typename: 'UnitPaymentMethodQrDownload',
              downloadUrl: SIGNED_URL,
              expiresAt: '2026-02-06T15:05:00Z',
            },
          },
        },
      },
    ]);

    await user.click(await screen.findByTestId(`view-qr-${WISE}`));

    const dialog = await screen.findByRole('dialog');
    const image = await within(dialog).findByAltText('QR code for Wise');
    expect(image).toHaveAttribute('src', SIGNED_URL);
    // The save control is a button, not a link: nothing here can navigate the page away.
    expect(within(dialog).getByTestId('save-qr-file')).toHaveTextContent('Save image');
    expect(within(dialog).queryByTestId('qr-download-link')).not.toBeInTheDocument();
  });

  it('saving the QR image fetches the bytes and hands over a file, without leaving the screen', async () => {
    const user = userEvent.setup();
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
    const fetchSave = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob([bytes], { type: 'image/png' }) });
    vi.stubGlobal('fetch', fetchSave);

    const saved: { download: string; href: string }[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push({ download: this.download, href: this.href });
    });
    const objectUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:kernelworx/qr-file');
    const revoked = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
    const navigated = vi.spyOn(Storage.prototype, 'setItem');

    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY })]),
      {
        request: { query: GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD, variables: { unitId: UNIT_ID, paymentMethodId: WISE } },
        result: {
          data: {
            unitPaymentMethodQrDownloadUrl: {
              __typename: 'UnitPaymentMethodQrDownload',
              downloadUrl: SIGNED_URL,
              expiresAt: '2026-02-06T15:05:00Z',
            },
          },
        },
      },
    ]);

    await user.click(await screen.findByTestId(`view-qr-${WISE}`));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByTestId('save-qr-file'));

    await waitFor(() => expect(saved).toHaveLength(1));
    // The bytes are read from the signed URL, and the file that arrives is named for the
    // object it was stored under — not `download.png`, and not the URL's signature.
    expect(fetchSave).toHaveBeenCalledWith(SIGNED_URL);
    expect(saved[0]).toEqual({ download: '8f2a4c1e.png', href: 'blob:kernelworx/qr-file' });
    expect(objectUrl.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect((objectUrl.mock.calls[0][0] as Blob).size).toBe(bytes.length);
    expect(revoked).toHaveBeenCalledWith('blob:kernelworx/qr-file');
    // The screen is still the screen: no navigation, and the list is untouched.
    expect(navigated).not.toHaveBeenCalled();
    expect(window.location.href).toBe('http://localhost:3000/');
    expect(within(dialog).getByAltText('QR code for Wise')).toBeInTheDocument();
    expect(click.mock.calls).toHaveLength(1);
  });

  it('a QR image that cannot be saved says so without closing the dialog', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 403 }));

    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY })]),
      {
        request: { query: GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD, variables: { unitId: UNIT_ID, paymentMethodId: WISE } },
        result: {
          data: {
            unitPaymentMethodQrDownloadUrl: {
              __typename: 'UnitPaymentMethodQrDownload',
              downloadUrl: SIGNED_URL,
              expiresAt: '2026-02-06T15:05:00Z',
            },
          },
        },
      },
    ]);

    await user.click(await screen.findByTestId(`view-qr-${WISE}`));
    const dialog = await screen.findByRole('dialog');
    await user.click(await within(dialog).findByTestId('save-qr-file'));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The image could not be saved: storage answered 403');
    expect(within(dialog).getByAltText('QR code for Wise')).toBeInTheDocument();
  });

  it('a QR image that cannot be opened says so in the dialog, with no broken picture', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY })]),
      {
        request: { query: GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD, variables: { unitId: UNIT_ID, paymentMethodId: WISE } },
        error: refused('INTERNAL_ERROR', 'The QR object could not be read.'),
      },
    ]);

    await user.click(await screen.findByTestId(`view-qr-${WISE}`));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The QR object could not be read.');
    expect(within(dialog).queryByRole('img')).not.toBeInTheDocument();
    expect(within(dialog).queryByTestId('qr-download-link')).not.toBeInTheDocument();
  });

  it('uploads a QR image as ask, post, confirm, and the confirm names the key the ask returned', async () => {
    const user = userEvent.setup();
    const fetchPost = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchPost);
    renderPanel([
      listRead([customMethod({ version: 3 })]),
      {
        request: {
          query: REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
          unitId: UNIT_ID,
          paymentMethodId: WISE,
          contentType: 'image/png',
          sha256: '0'.repeat(64),
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
          },
        },
        result: {
          data: {
            requestUnitPaymentMethodQrUpload: {
              __typename: 'S3UploadInfo',
              uploadUrl: 'https://kernelworx-exports-ue1-dev.s3.amazonaws.com',
              fields: `{"key":"${QR_KEY}","policy":"p","x-amz-signature":"s"}`,
              s3Key: QR_KEY,
            },
          },
        },
      },
      {
        request: {
          query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              s3Key: QR_KEY,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: { data: { confirmUnitPaymentMethodQrUpload: customMethod({ qrCodeS3Key: QR_KEY, version: 4 }) } },
      },
      // The re-read is what puts 'View QR' on the row: the screen never claims an image
      // it has not read back.
      listRead([customMethod({ qrCodeS3Key: QR_KEY, version: 4 })], false, 2),
    ]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    expect(await screen.findByTestId(`view-qr-${WISE}`)).toBeInTheDocument();
    expect(screen.getByTestId(`qr-${WISE}`)).toHaveTextContent('Replace QR');
    expect(fetchPost.mock.calls[0][0]).toBe('https://kernelworx-exports-ue1-dev.s3.amazonaws.com');
    // `file` is last because S3 refuses a POST whose file part is not last.
    const form = (fetchPost.mock.calls[0][1] as RequestInit).body as FormData;
    expect([...form.keys()].pop()).toBe('file');
    expect(form.get('key')).toBe(QR_KEY);
  });

  it('declares the SHA-256 of the bytes it posts, which is what the confirm step proves', async () => {
    // Node's own WebCrypto for this one: the digest has to be the real arithmetic
    // the server compares against the stored object, not a stand-in.
    const { webcrypto } = await import('node:crypto');
    keySequence = 0;
    vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}`, subtle: webcrypto.subtle });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    renderPanel([
      listRead([customMethod({ version: 3 })]),
      {
        request: {
          query: REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              contentType: 'image/png',
              // sha256 of the four bytes \x89PNG — the file this test chooses.
              sha256: '0f4636c78f65d3639ece5a064b5ae753e3408614a14fb18ab4d7540d2c248543',
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: {
          data: {
            requestUnitPaymentMethodQrUpload: {
              __typename: 'S3UploadInfo',
              uploadUrl: 'https://kernelworx-exports-ue1-dev.s3.amazonaws.com',
              fields: `{"key":"${QR_KEY}"}`,
              s3Key: QR_KEY,
            },
          },
        },
      },
      {
        request: {
          query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              s3Key: QR_KEY,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: { data: { confirmUnitPaymentMethodQrUpload: customMethod({ qrCodeS3Key: QR_KEY, version: 4 }) } },
      },
      listRead([customMethod({ qrCodeS3Key: QR_KEY, version: 4 })], false, 2),
    ]);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await user.upload(
      screen.getByLabelText('Select QR code image'),
      new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], 'qr.png', { type: 'image/png' }),
    );
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Upload' }));

    // Every mock above matches its input exactly, so the row reading 'View QR'
    // means the ask went out with that digest and no other change to it.
    expect(await screen.findByTestId(`view-qr-${WISE}`)).toBeInTheDocument();
  });

  it('a QR the server turns down stays in the dialog that still holds the file', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    renderPanel([
      listRead([customMethod({ version: 3 })]),
      {
        request: {
          query: REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
          unitId: UNIT_ID,
          paymentMethodId: WISE,
          contentType: 'image/png',
          sha256: '0'.repeat(64),
          idempotency: { idempotencyKey: 'test-idem-1' },
        },
          },
        },
        result: {
          data: {
            requestUnitPaymentMethodQrUpload: {
              __typename: 'S3UploadInfo',
              uploadUrl: 'https://kernelworx-exports-ue1-dev.s3.amazonaws.com',
              fields: `{"key":"${QR_KEY}"}`,
              s3Key: QR_KEY,
            },
          },
        },
      },
      {
        request: {
          query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              s3Key: QR_KEY,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        error: refused('INVALID_INPUT', 'The image content does not match its declared type.'),
      },
    ]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The image content does not match its declared type.');
    expect(within(dialog).getByText('qr.png')).toBeInTheDocument();
    expect(screen.queryByTestId(`view-qr-${WISE}`)).not.toBeInTheDocument();
  });

  it('removing a QR image says what it does not touch, and the row reads None afterwards', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY, version: 4 })]),
      {
        request: {
          query: DELETE_UNIT_PAYMENT_METHOD_QR_CODE,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              version: { expectedVersion: 4 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { deleteUnitPaymentMethodQrCode: customMethod({ version: 5 }) } },
      },
      listRead([customMethod({ version: 5 })], false, 2),
    ]);

    await user.click(await screen.findByTestId(`remove-qr-${WISE}`));
    expect(await screen.findByTestId('pending-write-warning')).toHaveTextContent('The method itself and every sale made with it are untouched.');
    await user.click(screen.getByRole('button', { name: 'Remove QR image' }));

    await waitFor(() => expect(screen.queryByTestId(`view-qr-${WISE}`)).not.toBeInTheDocument());
    expect(screen.getByTestId(`qr-state-${WISE}`)).toHaveTextContent('None');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('a Unit the caller no longer administers and a Unit that is gone answer identically', async () => {
    renderPanel([{ request: listRequest(false), error: refused('NOT_FOUND', 'Unit not found') }]);

    expect(await screen.findByRole('alert')).toHaveTextContent("Could not load this Unit's payment methods.");
    expect(screen.queryByTestId('create-payment-method')).not.toBeInTheDocument();
  });

  it('the 50th active method is the last one offered, and the count says so', async () => {
    const full = Array.from({ length: 50 }, (_, index) => customMethod({ paymentMethodId: `PM#m-${index}`, displayName: `Method ${index}` }));
    renderPanel([listRead(full)]);

    expect(await screen.findByTestId('create-payment-method')).toBeDisabled();
    expect(screen.getByTestId('active-method-count')).toHaveTextContent('50 active custom methods');
  });

  it('an image the server has but cannot hand back is a refusal, not a broken picture', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY })]),
      {
        request: { query: GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD, variables: { unitId: UNIT_ID, paymentMethodId: WISE } },
        result: { data: { unitPaymentMethodQrDownloadUrl: null } },
      },
    ]);

    await user.click(await screen.findByTestId(`view-qr-${WISE}`));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The QR image could not be opened.');
    expect(within(dialog).queryByRole('img')).not.toBeInTheDocument();
    expect(within(dialog).queryByTestId('qr-download-link')).not.toBeInTheDocument();

    // Closing it leaves nothing behind: the next open asks for a fresh, short-lived URL.
    await user.click(within(dialog).getByTestId('close-qr-preview'));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('an image read answered by a row that moved says it changed, not that the picture is gone', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ qrCodeS3Key: QR_KEY })]),
      {
        request: { query: GET_UNIT_PAYMENT_METHOD_QR_DOWNLOAD, variables: { unitId: UNIT_ID, paymentMethodId: WISE } },
        error: refused('CONFLICT', RACE_SENTENCE),
      },
    ]);

    await user.click(await screen.findByTestId(`view-qr-${WISE}`));

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(STALE_COPY);
  });

  it('a storage POST that refuses the bytes never reaches the confirm', async () => {
    const user = userEvent.setup();
    const fetchPost = vi.fn().mockResolvedValue({ ok: false, status: 403 });
    vi.stubGlobal('fetch', fetchPost);
    renderPanel([listRead([customMethod({ version: 3 })]), uploadAsk(`{"key":"${QR_KEY}"}`)]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    // There is no confirm mock in this run: the sentence proves the confirm was never sent,
    // because a stray confirm would answer "no more mocked responses" instead.
    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The image could not be sent to storage.');
    expect(within(dialog).getByText('qr.png')).toBeInTheDocument();
    expect(fetchPost).toHaveBeenCalledTimes(1);
  });

  it('an ask that answers without a target says so instead of posting nowhere', async () => {
    const user = userEvent.setup();
    const fetchPost = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchPost);
    renderPanel([listRead([customMethod({ version: 3 })]), uploadAsk(`{"key":"${QR_KEY}"}`, null)]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('The upload target could not be prepared.');
    expect(fetchPost).not.toHaveBeenCalled();
  });

  it('the pre-signed fields also arrive as an object, and post with the file last all the same', async () => {
    const user = userEvent.setup();
    const fetchPost = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal('fetch', fetchPost);
    renderPanel([
      listRead([customMethod({ version: 3 })]),
      uploadAsk({ key: QR_KEY, policy: 'p', 'x-amz-signature': 's' }),
      {
        request: {
          query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              s3Key: QR_KEY,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: { data: { confirmUnitPaymentMethodQrUpload: customMethod({ qrCodeS3Key: QR_KEY, version: 4 }) } },
      },
      listRead([customMethod({ qrCodeS3Key: QR_KEY, version: 4 })], false, 2),
    ]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    expect(await screen.findByTestId(`view-qr-${WISE}`)).toBeInTheDocument();
    const form = (fetchPost.mock.calls[0][1] as RequestInit).body as FormData;
    expect(form.get('key')).toBe(QR_KEY);
    expect(form.get('x-amz-signature')).toBe('s');
    expect([...form.keys()].pop()).toBe('file');
  });

  it('a confirm that finds a newer row says it changed, with the file still in the dialog', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    renderPanel([listRead([customMethod({ version: 3 })]), uploadAsk(`{"key":"${QR_KEY}"}`), uploadConfirmRefused('CONFLICT', RACE_SENTENCE)]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(STALE_COPY);
    expect(within(dialog).getByText('qr.png')).toBeInTheDocument();
    expect(screen.queryByTestId(`view-qr-${WISE}`)).not.toBeInTheDocument();
  });

  it('a write the server refuses stays on screen until the reader dismisses it', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ version: 2 })], false, 2),
      {
        request: {
          query: DEACTIVATE_UNIT_PAYMENT_METHOD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: refused('FORBIDDEN', 'Only an admin of this Unit can change its payment methods.'),
      },
    ]);

    await user.click(await screen.findByTestId(`deactivate-${WISE}`));
    await user.click(screen.getByRole('button', { name: 'Retire method' }));

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Only an admin of this Unit can change its payment methods.');

    await user.click(within(alert).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    // The row is still offered: dismissing an error is not undoing the read that followed it.
    expect(screen.getByTestId(`deactivate-${WISE}`)).toBeEnabled();
  });

  it('closing the name dialog writes nothing, and its own complaint clears when dismissed', async () => {
    const user = userEvent.setup();
    renderPanel([listRead([])]);

    await user.click(await screen.findByTestId('create-payment-method'));
    const dialog = await screen.findByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Add method' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('A method needs a name of 1 to 100 characters.');

    await user.click(within(within(dialog).getByRole('alert')).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(within(dialog).queryByRole('alert')).not.toBeInTheDocument());

    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByTestId('method-name-field')).not.toBeInTheDocument());
    // There is no create mutation mocked in this run, so a write would have named itself.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('Enter in the name field saves the name exactly as the dialog button does', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([]),
      {
        request: {
          query: CREATE_UNIT_PAYMENT_METHOD,
          variables: {
            input: { unitId: UNIT_ID, displayName: 'Wise', idempotency: { idempotencyKey: 'test-idem-1' } },
          },
        },
        result: { data: { createUnitPaymentMethod: customMethod() } },
      },
      listRead([customMethod()], false, 2),
    ]);

    await user.click(await screen.findByTestId('create-payment-method'));
    await clearAndType('method-name-field', 'Wise', user);
    await user.keyboard('{Enter}');

    // The form keeps its own submit: Enter may not reload the page or close the dialog
    // on its own, so the write is what answers, and the row appears from the re-read.
    const row = await screen.findByTestId(`method-row-${WISE}`);
    expect(within(row).getByText('Wise')).toBeInTheDocument();
  });

  it('a refusal in the shape the deployed resolver sends is still read as a version race', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod({ version: 2 })]),
      {
        request: {
          query: DEACTIVATE_UNIT_PAYMENT_METHOD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              version: { expectedVersion: 2 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: refused_by_the_api('CONFLICT', RACE_SENTENCE),
      },
      // The re-read only happens if the code was read. Had this screen fallen back to
      // matching the sentence, it would show these words and leave a stale row on screen.
      listRead([customMethod({ version: 3, isActive: false })], false, 2),
    ]);

    await user.click(await screen.findByTestId(`deactivate-${WISE}`));
    await user.click(screen.getByRole('button', { name: 'Retire method' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(STALE_COPY);
    const row = await screen.findByTestId(`method-row-${WISE}`);
    expect(within(row).getByText('retired — sales already made still read this way')).toBeInTheDocument();
    expect(within(row).getByTestId(`deactivate-${WISE}`)).toBeDisabled();
  });

  it('a taken name in the deployed shape keeps its sentence and writes nothing again', async () => {
    const user = userEvent.setup();
    renderPanel([
      listRead([customMethod()]),
      {
        request: {
          query: CREATE_UNIT_PAYMENT_METHOD,
          variables: { input: { unitId: UNIT_ID, displayName: 'wise', idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        result: refused_by_the_api('CONFLICT', 'This Unit already has a payment method with this name.'),
      },
    ]);

    await user.click(await screen.findByTestId('create-payment-method'));
    await typeInto('method-name-field', 'wise', user);
    await user.click(screen.getByRole('button', { name: 'Add method' }));

    // Same code, different fact: the name rule is answered by the server's sentence, and a
    // re-read here would fail this run — there is no second list mock to answer it.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This Unit already has a payment method with this name.');
    expect(alert).not.toHaveTextContent(STALE_COPY);
    expect(screen.getByTestId('method-name-field')).toBeInTheDocument();
    expect(screen.getByTestId(`method-row-${WISE}`)).toBeInTheDocument();
  });

  it('a confirm the API refuses for a moved row is retried at the version the re-read answered', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
    renderPanel([
      listRead([customMethod({ version: 3 })]),
      uploadAsk(`{"key":"${QR_KEY}"}`),
      {
        request: {
          query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              s3Key: QR_KEY,
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-2' },
            },
          },
        },
        result: refused_by_the_api('CONFLICT', RACE_SENTENCE),
      },
      // Another admin retired and re-created the row at 5; this read is what the next
      // attempt has to be built from. One use only, so the read that follows the
      // successful retry is a different answer and not this same stale row again.
      listRead([customMethod({ version: 5 })]),
      uploadAsk(`{"key":"${QR_KEY}"}`, undefined, 'test-idem-3'),
      {
        request: {
          query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
          variables: {
            input: {
              unitId: UNIT_ID,
              paymentMethodId: WISE,
              s3Key: QR_KEY,
              version: { expectedVersion: 5 },
              idempotency: { idempotencyKey: 'test-idem-4' },
            },
          },
        },
        result: { data: { confirmUnitPaymentMethodQrUpload: customMethod({ qrCodeS3Key: QR_KEY, version: 6 }) } },
      },
      listRead([customMethod({ qrCodeS3Key: QR_KEY, version: 6 })], false, 3),
    ]);

    await user.click(await screen.findByTestId(`qr-${WISE}`));
    await chooseAndUpload(user);

    const dialog = await screen.findByRole('dialog');
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(STALE_COPY);
    expect(within(dialog).getByText('qr.png')).toBeInTheDocument();

    // The second attempt is the point: the same file, and the version the re-read answered.
    await chooseAndUpload(user);
    await waitFor(() => expect(screen.getByTestId(`qr-state-${WISE}`)).toHaveTextContent('View QR'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

/** The ask half of an upload, with the fields the server handed back in either shape. */
function uploadAsk(fields: unknown, target: unknown = undefined, idempotencyKey = 'test-idem-1') {
  const info =
    target === null
      ? null
      : {
          __typename: 'S3UploadInfo',
          uploadUrl: 'https://kernelworx-exports-ue1-dev.s3.amazonaws.com',
          fields,
          s3Key: QR_KEY,
        };
  return {
    request: {
      query: REQUEST_UNIT_PAYMENT_METHOD_QR_UPLOAD,
      variables: {
        input: {
          unitId: UNIT_ID,
          paymentMethodId: WISE,
          contentType: 'image/png',
          sha256: '0'.repeat(64),
          idempotency: { idempotencyKey },
        },
      },
    },
    result: { data: { requestUnitPaymentMethodQrUpload: info } },
  };
}

function uploadConfirmRefused(code: string, message: string, expectedVersion = 3, idempotencyKey = 'test-idem-2') {
  return {
    request: {
      query: CONFIRM_UNIT_PAYMENT_METHOD_QR_UPLOAD,
      variables: {
        input: {
          unitId: UNIT_ID,
          paymentMethodId: WISE,
          s3Key: QR_KEY,
          version: { expectedVersion },
          idempotency: { idempotencyKey },
        },
      },
    },
    error: refused(code, message),
  };
}
