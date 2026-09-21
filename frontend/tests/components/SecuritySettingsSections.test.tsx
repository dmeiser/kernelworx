/**
 * Tests for MfaSection and PasskeySection components
 * Verifies two-path coexistence messaging and admin guardrail guidance.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
