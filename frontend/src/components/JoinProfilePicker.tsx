/**
 * The Scout-profile chooser on the join screen (Show & Sell §1.6.3).
 *
 * A profile with no current campaign is listed and disabled rather than hidden: the
 * account holder can then see why it cannot join (no campaign to attach) instead of
 * wondering whether the profile exists at all. Authorization stays on the server —
 * this list is only the profiles the caller already owns or holds WRITE on, and the
 * join re-checks that relationship.
 */

import React from 'react';
import { MenuItem, TextField } from '@mui/material';
/**
 * What the picker needs, which both an owned profile and a shared one carries. A
 * profile shared with WRITE is joinable by someone who does not own it, so the two
 * sources are not the same type and are not forced to be.
 */
export interface JoinableProfile {
  profileId: string;
  sellerName: string;
  latestCampaign?: { campaignId?: string | null; campaignName?: string | null } | null;
}

function profileLabel(profile: JoinableProfile): string {
  const campaign = profile.latestCampaign?.campaignName;
  if (!campaign) return `${profile.sellerName} · no campaign yet`;
  return `${profile.sellerName} · ${campaign}`;
}

interface JoinProfilePickerProps {
  profiles: JoinableProfile[];
  value: string;
  onChange: (profileId: string) => void;
  disabled?: boolean;
}

export const JoinProfilePicker: React.FC<JoinProfilePickerProps> = ({ profiles, value, onChange, disabled }) => (
  <TextField
    select
    label="Scout profile"
    value={value}
    onChange={(event) => onChange(event.target.value)}
    disabled={disabled}
    helperText="Only profiles you own or hold write access on can join."
    data-testid="join-profile"
  >
    {profiles.map((profile) => (
      <MenuItem
        key={profile.profileId}
        value={profile.profileId}
        disabled={!profile.latestCampaign?.campaignId}
        data-testid={`join-profile-option-${profile.profileId}`}
      >
        {profileLabel(profile)}
      </MenuItem>
    ))}
    {profiles.length === 0 && (
      <MenuItem value="" disabled data-testid="join-profile-empty">
        No Scout profiles found
      </MenuItem>
    )}
  </TextField>
);
