/**
 * Tests for the settings sub-components: the staleness flags, the cap copy,
 * the campaign picker, the method checklist, the acknowledgement gate, the
 * action buttons and the share section.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {
  PublicSettingsMessages,
  CAMPAIGN_INACTIVE_COPY,
  CAMPAIGN_MISSING_COPY,
  REFRESH_FAILED_COPY,
  UNSAVED_CHANGES_COPY,
} from '../../src/components/public/PublicSettingsMessages';
import { PublicSettingsCapNotice } from '../../src/components/public/PublicSettingsCapNotice';
import { PublicSettingsCampaignSelect } from '../../src/components/public/PublicSettingsCampaignSelect';
import { PublicSettingsMethodChecklist } from '../../src/components/public/PublicSettingsMethodChecklist';
import { PublicSettingsAckCheckboxes } from '../../src/components/public/PublicSettingsAckCheckboxes';
import { PublicSettingsActions } from '../../src/components/public/PublicSettingsActions';
import { PublicSettingsShareSection } from '../../src/components/public/PublicSettingsShareSection';
import { PUBLIC_ORDER_ACKNOWLEDGEMENTS } from '../../src/constants/publicOrders';
import type { SettingsActionMessage } from '../../src/hooks/usePublicOrderSettings';
import type { SettingsDraft } from '../../src/lib/publicOrderSettings';
import type { GqlCampaign } from '../../src/types';

const campaign = (id: string, name: string): GqlCampaign =>
  ({ campaignId: id, campaignName: name, campaignYear: 2026 }) as GqlCampaign;

const idle: SettingsActionMessage = { kind: 'idle' };
const saved: SettingsActionMessage = { kind: 'saved', refreshFailed: false };
const failed: SettingsActionMessage = { kind: 'failed', message: 'Invalid input provided.' };

const messagesWith = (overrides: { campaignState?: string; actionMessage?: SettingsActionMessage } = {}) => (
  <PublicSettingsMessages campaignState={overrides.campaignState ?? 'OK'} actionMessage={overrides.actionMessage ?? idle} />
);

describe('PublicSettingsMessages', () => {
  it('flags a missing anchor campaign', () => {
    render(messagesWith({ campaignState: 'MISSING' }));
    expect(screen.getByTestId('campaign-missing')).toHaveTextContent(CAMPAIGN_MISSING_COPY);
  });

  it('flags a deactivated anchor campaign', () => {
    render(messagesWith({ campaignState: 'INACTIVE' }));
    expect(screen.getByTestId('campaign-inactive')).toHaveTextContent(CAMPAIGN_INACTIVE_COPY);
  });

  it('surfaces a save failure', () => {
    render(messagesWith({ actionMessage: failed }));
    expect(screen.getByText('Invalid input provided.')).toBeInTheDocument();
  });

  it('shows a save failure next to the missing-anchor warning, not instead of it', () => {
    render(messagesWith({ campaignState: 'MISSING', actionMessage: { kind: 'failed', message: 'Campaign not found.' } }));
    expect(screen.getByTestId('campaign-missing')).toBeInTheDocument();
    expect(screen.getByText('Campaign not found.')).toBeInTheDocument();
  });

  it('shows a save failure next to the inactive-anchor warning, not instead of it', () => {
    render(messagesWith({ campaignState: 'INACTIVE', actionMessage: failed }));
    expect(screen.getByTestId('campaign-inactive')).toBeInTheDocument();
    expect(screen.getByText('Invalid input provided.')).toBeInTheDocument();
  });

  it('shows a succeeded action as a success without a refresh notice', () => {
    render(messagesWith({ actionMessage: saved }));
    expect(screen.getByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.queryByTestId('refresh-failed')).not.toBeInTheDocument();
  });

  it('shows the unsaved-changes indicator instead of a confirmation', () => {
    render(messagesWith({ actionMessage: { kind: 'unsaved' } }));
    expect(screen.getByTestId('unsaved-changes')).toHaveTextContent(UNSAVED_CHANGES_COPY);
    expect(screen.queryByTestId('settings-saved')).not.toBeInTheDocument();
  });

  it('keeps the success visible and adds a retryable notice when the refresh failed', () => {
    render(messagesWith({ actionMessage: { kind: 'saved', refreshFailed: true } }));
    expect(screen.getByTestId('settings-saved')).toBeInTheDocument();
    expect(screen.getByTestId('refresh-failed')).toHaveTextContent(REFRESH_FAILED_COPY);
  });

  it('shows a failed action without any success text', () => {
    render(messagesWith({ campaignState: 'INACTIVE', actionMessage: failed }));
    expect(screen.queryByTestId('settings-saved')).not.toBeInTheDocument();
    expect(screen.queryByTestId('refresh-failed')).not.toBeInTheDocument();
  });

  it('shows a save confirmation next to the staleness warning', () => {
    render(messagesWith({ campaignState: 'INACTIVE', actionMessage: saved }));
    expect(screen.getByTestId('campaign-inactive')).toBeInTheDocument();
    expect(screen.getByTestId('settings-saved')).toBeInTheDocument();
  });

  it('confirms a saved change', () => {
    render(messagesWith({ actionMessage: saved }));
    expect(screen.getByTestId('settings-saved')).toBeInTheDocument();
  });

  it('shows no success and no failure in the healthy state', () => {
    const { container } = render(messagesWith());
    expect(container).toBeEmptyDOMElement();
  });
});

describe('PublicSettingsCapNotice', () => {
  it('is honest that the count includes deleted orders and that re-picking does not reset it', () => {
    render(<PublicSettingsCapNotice count={12} />);
    const notice = screen.getByTestId('cap-notice');
    expect(notice).toHaveTextContent('12 of 500 public orders');
    expect(notice).toHaveTextContent('includes deleted orders');
    expect(notice).toHaveTextContent('Starting a new campaign gives you a fresh limit');
    expect(notice).toHaveTextContent('re-picking this one does not');
  });

  it('reads zero when no count came back', () => {
    render(<PublicSettingsCapNotice count={null} />);
    expect(screen.getByTestId('cap-notice')).toHaveTextContent('0 of 500');
  });
});

describe('PublicSettingsCampaignSelect', () => {
  it('lists the active campaigns and reports the choice', async () => {
    const onChange = vi.fn();
    render(<PublicSettingsCampaignSelect campaigns={[campaign('CAMPAIGN#a', 'Fall sale')]} value="" onChange={onChange} />);
    await userEvent.click(screen.getByRole('combobox'));
    await userEvent.click(await screen.findByText('Fall sale (2026)'));
    expect(onChange).toHaveBeenCalledWith('CAMPAIGN#a');
  });

  it('says when there is no active campaign to anchor to', () => {
    render(<PublicSettingsCampaignSelect campaigns={[]} value="" onChange={vi.fn()} />);
    expect(screen.getByText(/no active campaign to anchor public orders to/i)).toBeInTheDocument();
  });
});

describe('PublicSettingsMethodChecklist', () => {
  it('checks the selected methods case-insensitively', () => {
    render(<PublicSettingsMethodChecklist options={['Venmo', 'Cash']} selected={['venmo']} onToggle={vi.fn()} />);
    expect((screen.getByRole('checkbox', { name: 'Venmo' }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole('checkbox', { name: 'Cash' }) as HTMLInputElement).checked).toBe(false);
  });

  it('reports a toggle', async () => {
    const onToggle = vi.fn();
    render(<PublicSettingsMethodChecklist options={['Venmo']} selected={[]} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Venmo' }));
    expect(onToggle).toHaveBeenCalledWith('Venmo', true);
  });

  it('explains an empty option list', () => {
    render(<PublicSettingsMethodChecklist options={[]} selected={[]} onToggle={vi.fn()} />);
    expect(screen.getByText(/Add a payment method under Payment Methods first/i)).toBeInTheDocument();
  });
});

describe('PublicSettingsAckCheckboxes', () => {
  const draft: SettingsDraft = { enabled: true, campaignId: '', methods: [], ackPayment: true, ackDisclosure: false };

  it('renders both mandatory acknowledgements verbatim', () => {
    render(<PublicSettingsAckCheckboxes draft={draft} onChange={vi.fn()} />);
    PUBLIC_ORDER_ACKNOWLEDGEMENTS.forEach((text) => {
      expect(screen.getByText(text)).toBeInTheDocument();
    });
  });

  it('reports each checkbox separately', async () => {
    const onChange = vi.fn();
    render(<PublicSettingsAckCheckboxes draft={draft} onChange={onChange} />);
    await userEvent.click(screen.getByRole('checkbox', { name: PUBLIC_ORDER_ACKNOWLEDGEMENTS[1] }));
    expect(onChange).toHaveBeenCalledWith('ackDisclosure', true);
  });
});

describe('PublicSettingsActions', () => {
  it('keeps Save disabled while the acknowledgements are incomplete', async () => {
    render(
      <PublicSettingsActions
        saveDisabled
        submitting={false}
        enabled={false}
        hasToken={false}
        onSave={vi.fn()}
        onDisable={vi.fn()}
        onRotate={vi.fn()}
      />,
    );
    expect(screen.getByTestId('save-settings')).toBeDisabled();
    expect(screen.queryByTestId('disable-public-orders')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rotate-token')).not.toBeInTheDocument();
  });

  it('offers disable and rotate for an enabled profile with a token', async () => {
    const onDisable = vi.fn();
    const onRotate = vi.fn();
    const onSave = vi.fn();
    render(
      <PublicSettingsActions
        saveDisabled={false}
        submitting={false}
        enabled
        hasToken
        onSave={onSave}
        onDisable={onDisable}
        onRotate={onRotate}
      />,
    );
    await userEvent.click(screen.getByTestId('save-settings'));
    await userEvent.click(screen.getByTestId('disable-public-orders'));
    await userEvent.click(screen.getByTestId('rotate-token'));
    expect(onSave).toHaveBeenCalled();
    expect(onDisable).toHaveBeenCalled();
    expect(onRotate).toHaveBeenCalled();
  });

  it('disables Disable and Rotate and shows pending labels while an action is submitting', async () => {
    const onDisable = vi.fn();
    const onRotate = vi.fn();
    render(
      <PublicSettingsActions
        saveDisabled
        submitting
        enabled
        hasToken
        onSave={vi.fn()}
        onDisable={onDisable}
        onRotate={onRotate}
      />,
    );
    expect(screen.getByTestId('save-settings')).toBeDisabled();
    expect(screen.getByTestId('save-settings')).toHaveTextContent('Saving…');
    expect(screen.getByTestId('disable-public-orders')).toBeDisabled();
    expect(screen.getByTestId('rotate-token')).toBeDisabled();
    expect(screen.getByTestId('rotate-token')).toHaveTextContent('Working…');
    expect(onDisable).not.toHaveBeenCalled();
    expect(onRotate).not.toHaveBeenCalled();
  });
});

describe('PublicSettingsShareSection', () => {
  it('renders the share view from the returned token', () => {
    render(<PublicSettingsShareSection shareUrl="https://dev.kernelworx.app/o/p/t" />);
    expect(screen.getByText('Share link')).toBeInTheDocument();
    expect(screen.getByLabelText('Public order share URL')).toHaveValue('https://dev.kernelworx.app/o/p/t');
  });

  it('renders nothing without a share URL', () => {
    const { container } = render(<PublicSettingsShareSection shareUrl={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
