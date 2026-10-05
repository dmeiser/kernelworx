/**
 * Per-profile public order settings: /scouts/:profileId/public-orders
 *
 * There was no per-profile settings surface before this page: `SettingsPage` is
 * account-level and `UserSettingsPage` is user-level. Note the asymmetry the
 * server enforces — payment methods live at ACCOUNT level, so every profile of
 * one account offers the same method list, while this toggle governs a single
 * profile.
 *
 * Enable, pick one active campaign, choose allowed methods case-insensitively,
 * and accept both acknowledgements; then hand out the link. Rotate, disable,
 * re-pick campaign and change methods are all supported from here.
 */

import { useParams } from 'react-router-dom';
import { Box, Divider, FormControlLabel, Grid, Paper, Switch } from '@mui/material';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import { PageHeader } from '../components/PageHeader';
import { PublicSettingsAckCheckboxes } from '../components/public/PublicSettingsAckCheckboxes';
import { PublicSettingsActions } from '../components/public/PublicSettingsActions';
import { PublicSettingsCampaignSelect } from '../components/public/PublicSettingsCampaignSelect';
import { PublicSettingsCapNotice } from '../components/public/PublicSettingsCapNotice';
import { PublicSettingsMethodChecklist } from '../components/public/PublicSettingsMethodChecklist';
import { PublicSettingsMessages } from '../components/public/PublicSettingsMessages';
import { PublicSettingsShareSection } from '../components/public/PublicSettingsShareSection';
import { usePublicOrderSettings } from '../hooks/usePublicOrderSettings';
import { buildShareUrl } from '../lib/publicOrders';
import { toUrlId } from '../lib/ids';
import type { usePublicOrderSettings as UsePublicOrderSettings } from '../hooks/usePublicOrderSettings';
import type { PublicOrderSettingsView } from '../lib/publicOrderSettings';

type SettingsState = ReturnType<typeof UsePublicOrderSettings>;

/** The share URL is re-rendered from the returned token, never stored client-side. */
function shareUrlFor(profileId: string, stored: PublicOrderSettingsView): string | null {
  const token = stored.shareToken;
  if (!token) return null;
  return buildShareUrl(toUrlId(profileId), token);
}

function headerSubtitle(profile: { sellerName: string } | null): string {
  return profile ? `Share link for ${profile.sellerName}` : 'Let buyers order from a shared link or QR code';
}

const SettingsFormCard: React.FC<{ settings: SettingsState }> = ({ settings }) => {
  const stored = settings.stored;
  return (
    <Paper elevation={0} sx={{ p: 3, mb: 3 }}>
      <FormControlLabel
        control={
          <Switch
            checked={settings.draft.enabled}
            disabled={settings.submitting}
            onChange={(event) => settings.setEnabled(event.target.checked)}
          />
        }
        label="Accept public orders"
      />

      <Grid container spacing={2} sx={{ mt: 0.5 }}>
        <Grid size={{ xs: 12, sm: 7 }}>
          <PublicSettingsCampaignSelect
            campaigns={settings.activeCampaigns}
            value={settings.draft.campaignId}
            onChange={settings.setCampaignId}
            disabled={settings.submitting}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 5 }}>
          <PublicSettingsCapNotice count={stored.publicOrderCount} />
        </Grid>
      </Grid>

      <Divider sx={{ my: 2 }} />
      <PublicSettingsMethodChecklist
        options={settings.methodOptions}
        selected={settings.draft.methods}
        onToggle={settings.toggleMethod}
        disabled={settings.submitting}
      />
      <Divider sx={{ my: 2 }} />

      {settings.acksRequired ? <PublicSettingsAckCheckboxes draft={settings.draft} onChange={settings.setAck} /> : null}

      <PublicSettingsActions
        saveDisabled={settings.saveDisabled}
        submitting={settings.submitting}
        enabled={stored.enabled}
        hasToken={Boolean(stored.shareToken)}
        onSave={() => void settings.save()}
        onDisable={() => void settings.disable()}
        onRotate={() => void settings.rotateToken()}
      />
    </Paper>
  );
};

const SettingsContent: React.FC<{ profileId: string; settings: SettingsState }> = ({ profileId, settings }) => (
  <Box>
    <PageHeader title="Public Orders" subtitle={headerSubtitle(settings.profile)} />

    <PublicSettingsMessages
      campaignState={settings.stored.campaignState}
      actionMessage={settings.actionMessage}
    />

    <SettingsFormCard settings={settings} />

    <PublicSettingsShareSection shareUrl={settings.stored.enabled ? shareUrlFor(profileId, settings.stored) : null} />
  </Box>
);

export const ProfilePublicOrdersSettingsPage: React.FC = () => {
  const params = useParams<{ profileId: string }>();
  const profileId = params.profileId ? decodeURIComponent(params.profileId) : '';
  const settings = usePublicOrderSettings(profileId);

  if (settings.settingsError) {
    return <ErrorAlert message={`Failed to load public order settings: ${settings.settingsError.message}`} />;
  }
  // The form is seeded from the stored blob, so it must not be interactive
  // before that read lands: an edit made against an unknown state would be
  // clobbered when the settings arrive.
  if (!settings.settingsLoaded) return <LoadingState />;

  return <SettingsContent profileId={profileId} settings={settings} />;
};

export default ProfilePublicOrdersSettingsPage;
