/**
 * Tests for NoEmailConfirmDialog.
 *
 * The dialog is the last gate before an anonymous order is written, and v1 has
 * no idempotency key: a second "continue" tap is a second order burning a second
 * slot of the campaign's cap. So while the mutation is in flight both actions
 * are disabled and the dialog refuses to close, and the primary button says
 * what is happening rather than still inviting a tap.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { NoEmailConfirmDialog, NO_EMAIL_WARNING } from '../../../src/components/public/NoEmailConfirmDialog';

const renderDialog = (props: { open?: boolean; submitting?: boolean } = {}) => {
  const onGoBack = vi.fn();
  const onContinue = vi.fn();
  render(
    <NoEmailConfirmDialog
      open={props.open ?? true}
      submitting={props.submitting}
      onGoBack={onGoBack}
      onContinue={onContinue}
    />,
  );
  return { onGoBack, onContinue };
};

describe('NoEmailConfirmDialog', () => {
  it('states the consequence before the buyer proceeds', () => {
    renderDialog();
    expect(screen.getByText(NO_EMAIL_WARNING)).toBeInTheDocument();
  });

  it('continues only on an explicit choice', () => {
    const { onContinue, onGoBack } = renderDialog();
    fireEvent.click(screen.getByTestId('no-email-continue'));
    expect(onContinue).toHaveBeenCalledTimes(1);
    expect(onGoBack).not.toHaveBeenCalled();
  });

  it('goes back without submitting', () => {
    const { onContinue, onGoBack } = renderDialog();
    fireEvent.click(screen.getByTestId('no-email-go-back'));
    expect(onGoBack).toHaveBeenCalledTimes(1);
    expect(onContinue).not.toHaveBeenCalled();
  });

  it('renders nothing when closed', () => {
    renderDialog({ open: false });
    expect(screen.queryByTestId('no-email-continue')).toBeNull();
  });
});

describe('NoEmailConfirmDialog while submitting', () => {
  it('disables both actions so a second tap cannot place a second order', () => {
    renderDialog({ submitting: true });
    expect(screen.getByTestId('no-email-continue')).toBeDisabled();
    expect(screen.getByTestId('no-email-go-back')).toBeDisabled();
  });

  it('ignores a click on the disabled continue button', () => {
    const { onContinue } = renderDialog({ submitting: true });
    fireEvent.click(screen.getByTestId('no-email-continue'));
    expect(onContinue).not.toHaveBeenCalled();
  });

  it('relabels the primary action while the order is in flight', () => {
    renderDialog({ submitting: true });
    expect(screen.getByTestId('no-email-continue')).toHaveTextContent('Placing your order');
  });

  it('leaves the actions enabled when submitting is not passed', () => {
    renderDialog();
    expect(screen.getByTestId('no-email-continue')).toBeEnabled();
    expect(screen.getByTestId('no-email-go-back')).toBeEnabled();
    expect(screen.getByTestId('no-email-continue')).toHaveTextContent('Continue without email');
  });
});
