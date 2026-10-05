/**
 * Anchor campaign picker for the public order settings.
 *
 * Only ACTIVE campaigns are offered: the server's enable-time validation GetItem
 * rejects an inactive anchor, and a dangling pointer left by a deleted campaign
 * is surfaced separately by the staleness flag rather than re-offered here.
 */

import { Box, InputLabel, MenuItem, Select, Stack } from '@mui/material';
import type { GqlCampaign } from '../../types';

interface PublicSettingsCampaignSelectProps {
  campaigns: GqlCampaign[];
  value: string;
  onChange: (campaignId: string) => void;
  /** Disabled while a settings action is outstanding. */
  disabled?: boolean;
}

export const PublicSettingsCampaignSelect: React.FC<PublicSettingsCampaignSelectProps> = ({
  campaigns,
  value,
  onChange,
  disabled = false,
}) => (
  <Box>
    <InputLabel id="public-order-campaign-label" shrink>
      Active campaign
    </InputLabel>
    <Select
      labelId="public-order-campaign-label"
      value={value}
      onChange={(event) => onChange(event.target.value)}
      label="Active campaign"
      displayEmpty
      fullWidth
      disabled={disabled}
      data-testid="campaign-select"
    >
      <MenuItem value="">
        <em>Choose a campaign</em>
      </MenuItem>
      {campaigns.map((campaign) => (
        <MenuItem key={campaign.campaignId} value={campaign.campaignId}>
          {campaign.campaignName} ({campaign.campaignYear})
        </MenuItem>
      ))}
    </Select>
    <Stack sx={{ mt: 1 }}>
      {campaigns.length === 0 ? (
        <Box sx={{ color: 'text.secondary' }}>This profile has no active campaign to anchor public orders to.</Box>
      ) : null}
    </Stack>
  </Box>
);

export default PublicSettingsCampaignSelect;
