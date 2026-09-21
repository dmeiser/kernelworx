/**
 * Tests for MfaSection and PasskeySection components
 * Verifies two-path coexistence messaging and admin guardrail guidance.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { MfaSection } from '../../src/components/settings/MfaSection';
import { PasskeySection } from '../../src/components/settings/PasskeySection';
import type { UseMfaReturn } from '../../src/hooks/useMfa';
import type { UsePasskeysReturn } from '../../src/hooks/usePasskeys';

const createMockMfaHook = (overrides?: Partial<UseMfaReturn>): UseMfaReturn => ({
  mfaSetupCode: null,
  qrCodeUrl: null,
  mfaVerificationCode: '',
  setMfaVerificationCode: vi.fn(),
  mfaError: null,
  setMfaError: vi.fn(),
  mfaSuccess: false,
  setMfaSuccess: vi.fn(),
  mfaLoading: false,
  mfaEnabled: false,
  pendingConfirmation: null,
  handleSetupMFA: vi.fn().mockResolvedValue(undefined),
  confirmSetupMFA: vi.fn().mockResolvedValue(undefined),
  handleVerifyMFA: vi.fn().mockResolvedValue(undefined),
  handleDisableMFA: vi.fn(),
  confirmDisableMFA: vi.fn().mockResolvedValue(undefined),
  cancelMfaConfirmation: vi.fn(),
  checkMfaStatus: vi.fn().mockResolvedValue(undefined),
  setMfaEnabled: vi.fn(),
  resetMfaSetup: vi.fn(),
  ...overrides,
});

const createMockPasskeyHook = (overrides?: Partial<UsePasskeysReturn>): UsePasskeysReturn => ({
  passkeys: [],
  passkeyName: '',
  setPasskeyName: vi.fn(),
  passkeyError: null,
  setPasskeyError: vi.fn(),
  passkeySuccess: false,
  setPasskeySuccess: vi.fn(),
  passkeyLoading: false,
  pendingConfirmation: null,
  loadPasskeys: vi.fn().mockResolvedValue(undefined),
  handleRegisterPasskey: vi.fn().mockResolvedValue(undefined),
  confirmPasskeyAction: vi.fn().mockResolvedValue(undefined),
  cancelPasskeyConfirmation: vi.fn(),
  handleDeletePasskey: vi.fn(),
  ...overrides,
});

describe('MfaSection', () => {
  it('renders coexistence messaging and does not render conflict warnings', () => {
    const mfaHook = createMockMfaHook();
    render(<MfaSection mfaHook={mfaHook} passkeyCount={2} onSetupMFA={vi.fn()} />);

    // Should indicate both are supported together
    expect(screen.getByText(/Both an authenticator app and passkeys are supported together/i)).toBeInTheDocument();

    // Must NOT show old exclusivity text
    expect(screen.queryByText(/cannot be used together/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Enabling MFA will delete/i)).not.toBeInTheDocument();
  });

  it('renders admin guidance when isAdmin is true', () => {
    const mfaHook = createMockMfaHook();
    render(<MfaSection mfaHook={mfaHook} onSetupMFA={vi.fn()} isAdmin={true} />);

    expect(
      screen.getByText(/Admin operations need an authenticator app \(TOTP\) enrolled; a passkey alone signs you in but does not grant admin\./i),
    ).toBeInTheDocument();
  });

  it('does not render admin guidance when isAdmin is false', () => {
    const mfaHook = createMockMfaHook();
    render(<MfaSection mfaHook={mfaHook} onSetupMFA={vi.fn()} isAdmin={false} />);

    expect(
      screen.queryByText(/Admin operations need an authenticator app \(TOTP\) enrolled/i),
    ).not.toBeInTheDocument();
  });

  it('shows the enabled state and never the QR setup block when MFA is enabled (TOTP or passkey)', () => {
    const mfaHook = createMockMfaHook({ mfaEnabled: true });
    render(<MfaSection mfaHook={mfaHook} onSetupMFA={vi.fn()} />);

    expect(screen.getByText('MFA is currently enabled')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Set Up MFA/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Scan QR Code/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Disable MFA/i })).toBeInTheDocument();
  });

  it('shows the forced setup block when the user has no MFA', () => {
    const mfaHook = createMockMfaHook({ mfaEnabled: false });
    render(<MfaSection mfaHook={mfaHook} onSetupMFA={vi.fn()} />);

    expect(screen.queryByText('MFA is currently enabled')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Set Up MFA/i })).toBeInTheDocument();
  });
});

describe('PasskeySection', () => {
  it('renders coexistence messaging and does not render conflict warnings', () => {
    const passkeyHook = createMockPasskeyHook();
    render(<PasskeySection passkeyHook={passkeyHook} mfaEnabled={true} onRegisterPasskey={vi.fn()} />);

    // Should indicate both are supported together
    expect(screen.getAllByText(/Both an authenticator app and passkeys are supported together/i).length).toBeGreaterThan(0);

    // Must NOT show old exclusivity text
    expect(screen.queryByText(/cannot be used together/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Registering a passkey will disable your current MFA setup/i)).not.toBeInTheDocument();
  });

  it('renders admin guidance when isAdmin is true', () => {
    const passkeyHook = createMockPasskeyHook();
    render(<PasskeySection passkeyHook={passkeyHook} onRegisterPasskey={vi.fn()} isAdmin={true} />);

    expect(
      screen.getByText(/Admin operations need an authenticator app \(TOTP\) enrolled; a passkey alone signs you in but does not grant admin\./i),
    ).toBeInTheDocument();
  });

  it('does not render admin guidance when isAdmin is false', () => {
    const passkeyHook = createMockPasskeyHook();
    render(<PasskeySection passkeyHook={passkeyHook} onRegisterPasskey={vi.fn()} isAdmin={false} />);

    expect(
      screen.queryByText(/Admin operations need an authenticator app \(TOTP\) enrolled/i),
    ).not.toBeInTheDocument();
  });
});

describe('MfaSection states and interactions', () => {
  it('closes the success and error alerts', () => {
    const setMfaSuccess = vi.fn();
    const setMfaError = vi.fn();
    render(
      <MfaSection
        mfaHook={createMockMfaHook({ mfaSuccess: true, mfaError: 'totp exploded', setMfaSuccess, setMfaError })}
        onSetupMFA={vi.fn()}
      />,
    );

    expect(screen.getByText('MFA has been successfully enabled!')).toBeInTheDocument();
    expect(screen.getByText('totp exploded')).toBeInTheDocument();

    const closeButtons = screen.getAllByRole('button', { name: 'Close' });
    expect(closeButtons).toHaveLength(2);
    fireEvent.click(closeButtons[0]);
    expect(setMfaSuccess).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getAllByRole('button', { name: 'Close' })[1]);
    expect(setMfaError).toHaveBeenCalledWith(null);
  });

  it('offers setup when MFA is disabled and forwards the click to onSetupMFA', () => {
    const onSetupMFA = vi.fn();
    render(<MfaSection mfaHook={createMockMfaHook()} onSetupMFA={onSetupMFA} />);

    const setupButton = screen.getByRole('button', { name: /Set Up MFA/i });
    expect(setupButton).toBeEnabled();
    fireEvent.click(setupButton);
    expect(onSetupMFA).toHaveBeenCalledTimes(1);
  });

  it('disables the setup and disable buttons while loading', () => {
    render(<MfaSection mfaHook={createMockMfaHook({ mfaLoading: true, mfaEnabled: true })} onSetupMFA={vi.fn()} />);

    const disableButton = screen.getByRole('button', { name: /Disable MFA/i });
    expect(disableButton).toBeDisabled();
  });

  it('wires the disable button to handleDisableMFA', () => {
    const handleDisableMFA = vi.fn();
    render(<MfaSection mfaHook={createMockMfaHook({ mfaEnabled: true, handleDisableMFA })} onSetupMFA={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: /Disable MFA/i }));
    expect(handleDisableMFA).toHaveBeenCalledTimes(1);
  });

  it('renders the two-step setup block with QR and manual code', () => {
    render(
      <MfaSection
        mfaHook={createMockMfaHook({ mfaSetupCode: 'JBSWY3DPEHPK3PXP', qrCodeUrl: 'data:image/png;base64,qr' })}
        onSetupMFA={vi.fn()}
      />,
    );

    expect(screen.getByText('Step 1: Scan QR Code')).toBeInTheDocument();
    expect(screen.getByText('Step 2: Verify Code')).toBeInTheDocument();
    expect(screen.getByAltText('MFA QR Code')).toHaveAttribute('src', 'data:image/png;base64,qr');
    expect(screen.getByText('JBSWY3DPEHPK3PXP')).toBeInTheDocument();
  });

  it('does not render the setup block when only one of code/QR is present', () => {
    render(
      <MfaSection mfaHook={createMockMfaHook({ mfaSetupCode: 'JBSWY3DPEHPK3PXP', qrCodeUrl: null })} onSetupMFA={vi.fn()} />,
    );

    expect(screen.queryByText('Step 1: Scan QR Code')).not.toBeInTheDocument();
  });

  it('filters the verification input to up to 6 digits', () => {
    const setMfaVerificationCode = vi.fn();
    render(
      <MfaSection
        mfaHook={createMockMfaHook({ mfaSetupCode: 'SECRET', qrCodeUrl: 'data:qr', setMfaVerificationCode })}
        onSetupMFA={vi.fn()}
      />,
    );

    const input = screen.getByLabelText(/Verification Code/);
    fireEvent.change(input, { target: { value: '12a4b67' } });
    expect(setMfaVerificationCode).toHaveBeenCalledWith('12467'.substring(0, 6));
  });

  it('submits the verification form and cancels setup', () => {
    const handleVerifyMFA = vi.fn();
    const resetMfaSetup = vi.fn();
    render(
      <MfaSection
        mfaHook={
          createMockMfaHook({
            mfaSetupCode: 'SECRET',
            qrCodeUrl: 'data:qr',
            mfaVerificationCode: '123456',
            handleVerifyMFA,
            resetMfaSetup,
          })
        }
        onSetupMFA={vi.fn()}
      />,
    );

    const verifyButton = screen.getByRole('button', { name: 'Verify & Enable' });
    expect(verifyButton).toBeEnabled();
    fireEvent.click(verifyButton);
    expect(handleVerifyMFA).toHaveBeenCalledTimes(1);
    expect(typeof handleVerifyMFA.mock.calls[0][0].preventDefault).toBe('function');

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(resetMfaSetup).toHaveBeenCalledTimes(1);
  });

  it('keeps the verify button disabled until six digits are entered', () => {
    render(
      <MfaSection
        mfaHook={createMockMfaHook({ mfaSetupCode: 'SECRET', qrCodeUrl: 'data:qr', mfaVerificationCode: '123' })}
        onSetupMFA={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Verify & Enable' })).toBeDisabled();
  });

  it('shows the disable confirmation dialog with cancel and confirm paths', () => {
    const cancelMfaConfirmation = vi.fn();
    const confirmDisableMFA = vi.fn();
    render(
      <MfaSection
        mfaHook={
          createMockMfaHook({
            mfaEnabled: true,
            pendingConfirmation: { type: 'disable', message: 'Sure about it?' },
            cancelMfaConfirmation,
            confirmDisableMFA,
          })
        }
        onSetupMFA={vi.fn()}
      />,
    );

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Disable MFA?')).toBeInTheDocument();
    expect(within(dialog).getByText('Sure about it?')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(cancelMfaConfirmation).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disable' }));
    expect(confirmDisableMFA).toHaveBeenCalledTimes(1);
  });
});

describe('PasskeySection states and interactions', () => {
  it('closes the success and error alerts', () => {
    const setPasskeySuccess = vi.fn();
    const setPasskeyError = vi.fn();
    render(
      <PasskeySection
        passkeyHook={createMockPasskeyHook({
          passkeySuccess: true,
          passkeyError: 'webauthn exploded',
          setPasskeySuccess,
          setPasskeyError,
        })}
        onRegisterPasskey={vi.fn()}
      />,
    );

    expect(screen.getByText('Passkey registered successfully!')).toBeInTheDocument();
    expect(screen.getByText('webauthn exploded')).toBeInTheDocument();

    const closeButtons = screen.getAllByRole('button', { name: 'Close' });
    expect(closeButtons).toHaveLength(2);
    fireEvent.click(closeButtons[0]);
    expect(setPasskeySuccess).toHaveBeenCalledWith(false);
    fireEvent.click(screen.getAllByRole('button', { name: 'Close' })[1]);
    expect(setPasskeyError).toHaveBeenCalledWith(null);
  });

  it('lists registered passkeys with names and dates, and enables deletion only for named credentials', () => {
    const handleDeletePasskey = vi.fn();
    const handleDelete = () => {
      const buttons = screen.getAllByRole('button', { name: 'Delete passkey' });
      fireEvent.click(buttons[0]);
    };
    render(
      <PasskeySection
        passkeyHook={
          createMockPasskeyHook({
            passkeys: [
              {
                credentialId: 'cred-1',
                friendlyCredentialName: 'My iPhone',
                createdAt: new Date('2025-01-15T00:00:00Z'),
                relyingPartyId: 'login.dev.kernelworx.app',
                authenticatorTransports: ['internal'],
              },
              {
                credentialId: undefined,
                friendlyCredentialName: undefined,
                createdAt: undefined,
                relyingPartyId: undefined,
                authenticatorTransports: undefined,
              },
            ],
            handleDeletePasskey,
          }) as any
        }
        onRegisterPasskey={vi.fn()}
      />,
    );

    expect(screen.getByText('Registered Passkeys')).toBeInTheDocument();
    expect(screen.getByText('My iPhone')).toBeInTheDocument();
    expect(screen.getByText(/1\/15\/2025/)).toBeInTheDocument();
    expect(screen.getByText('Unnamed Passkey')).toBeInTheDocument();
    expect(screen.getByText('Unknown date')).toBeInTheDocument();

    const deleteButtons = screen.getAllByRole('button', { name: 'Delete passkey' });
    expect(deleteButtons[0]).toBeEnabled();
    expect(deleteButtons[1]).toBeDisabled();

    handleDelete();
    expect(handleDeletePasskey).toHaveBeenCalledWith('cred-1');
  });

  it('disables passkey deletion while loading', () => {
    render(
      <PasskeySection
        passkeyHook={
          createMockPasskeyHook({
            passkeys: [
              {
                credentialId: 'cred-1',
                friendlyCredentialName: 'My iPhone',
                createdAt: undefined,
                relyingPartyId: 'login.dev.kernelworx.app',
                authenticatorTransports: ['internal'],
              },
            ],
            passkeyLoading: true,
          }) as any
        }
        onRegisterPasskey={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Delete passkey' })).toBeDisabled();
  });

  it('does not render the registered list when there are no passkeys', () => {
    render(<PasskeySection passkeyHook={createMockPasskeyHook()} onRegisterPasskey={vi.fn()} />);

    expect(screen.queryByText('Registered Passkeys')).not.toBeInTheDocument();
  });

  it('registers a passkey when a name is present', () => {
    const onRegisterPasskey = vi.fn();
    render(
      <PasskeySection
        passkeyHook={createMockPasskeyHook({ passkeyName: 'My Phone' })}
        onRegisterPasskey={onRegisterPasskey}
      />,
    );

    const registerButton = screen.getByRole('button', { name: 'Register' });
    expect(registerButton).toBeEnabled();
    fireEvent.click(registerButton);
    expect(onRegisterPasskey).toHaveBeenCalledTimes(1);
  });

  it('disables register without a name', () => {
    render(
      <PasskeySection passkeyHook={createMockPasskeyHook({ passkeyName: '  ' })} onRegisterPasskey={vi.fn()} />,
    );

    expect(screen.getByRole('button', { name: 'Register' })).toBeDisabled();
  });

  it('disables register and the name field while loading', () => {
    render(
      <PasskeySection
        passkeyHook={createMockPasskeyHook({ passkeyName: 'My Phone', passkeyLoading: true })}
        onRegisterPasskey={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Register' })).toBeDisabled();
    expect(screen.getByLabelText('Passkey Name')).toBeDisabled();
  });

  it('forwards name edits to setPasskeyName', () => {
    const setPasskeyName = vi.fn();
    render(<PasskeySection passkeyHook={createMockPasskeyHook({ setPasskeyName })} onRegisterPasskey={vi.fn()} />);

    fireEvent.change(screen.getByLabelText('Passkey Name'), { target: { value: 'My Phone' } });
    expect(setPasskeyName).toHaveBeenCalledWith('My Phone');
  });

  it('disables the setup button while MFA is loading (spinner replaces the label)', () => {
    render(<MfaSection mfaHook={createMockMfaHook({ mfaLoading: true })} onSetupMFA={vi.fn()} />);

    // While loading the button label is a spinner, so the button is the only one rendered
    expect(screen.getByRole('button')).toBeDisabled();
  });

  it('disables the setup form actions while MFA is loading', () => {
    render(
      <MfaSection
        mfaHook={createMockMfaHook({
          mfaLoading: true,
          mfaSetupCode: 'SECRET',
          qrCodeUrl: 'data:qr',
          mfaVerificationCode: '123456',
        })}
        onSetupMFA={vi.fn()}
      />,
    );

    // While loading, Verify & Enable shows a spinner (no text label); both
    // form actions must be disabled
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toBeDisabled();
  });

  it('shows the delete confirmation dialog with cancel and confirm paths', () => {
    const cancelPasskeyConfirmation = vi.fn();
    const confirmPasskeyAction = vi.fn();
    render(
      <PasskeySection
        passkeyHook={
          createMockPasskeyHook({
            pendingConfirmation: { type: 'delete', message: 'Delete this passkey?', credentialId: 'cred-1' },
            cancelPasskeyConfirmation,
            confirmPasskeyAction,
          })
        }
        onRegisterPasskey={vi.fn()}
      />,
    );

    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Delete Passkey?')).toBeInTheDocument();
    expect(within(dialog).getByText('Delete this passkey?')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(cancelPasskeyConfirmation).toHaveBeenCalledTimes(1);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Delete' }));
    expect(confirmPasskeyAction).toHaveBeenCalledTimes(1);
  });
});
