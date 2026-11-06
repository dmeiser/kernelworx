/**
 * UnitDetailPage - detail screen for one Unit (settings, access, campaigns).
 *
 * Show & Sell Unit surface (batch C, leaves 1.6.1-1.6.3). Resolves the unit by
 * id, enforces that the caller is a Unit Admin (FORBIDDEN otherwise), and
 * presents Settings (1.6.1), Access (1.6.2), and Campaigns (1.6.3) in tabs.
 */

import React, { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@apollo/client/react';
import { Box, Tab, Tabs } from '@mui/material';
import { PageHeader } from '../components/PageHeader';
import { LoadingState } from '../components/LoadingState';
import { ErrorAlert } from '../components/ErrorAlert';
import UnitSettingsForm from './UnitSettingsForm';
import UnitAccessSection from './UnitAccessSection';
import UnitCampaignsSection from './UnitCampaignsSection';
import { GET_UNIT } from '../lib/graphql';
import { getErrorCode } from '../lib/api-utils';
import { generatedUnitDisplayName } from '../lib/unitForm';
import type { GqlUnit } from '../types';

const TABS = [
  { label: 'Settings', key: 'settings' },
  { label: 'Access', key: 'access' },
  { label: 'Campaigns', key: 'campaigns' },
] as const;

type TabKey = (typeof TABS)[number]['key'];

const unitTitle = (unit: GqlUnit): string =>
  unit.displayName || generatedUnitDisplayName(unit.unitType, unit.unitNumber, unit.city, unit.state);

const backToUnits = {
  onClick: () => window.history.back(),
  label: 'Back to units',
};

const renderPanel = (tab: TabKey, unitId: string): React.ReactElement => {
  switch (tab) {
    case 'settings':
      return <UnitSettingsForm unitId={unitId} />;
    case 'access':
      return <UnitAccessSection unitId={unitId} />;
    default:
      return <UnitCampaignsSection unitId={unitId} />;
  }
};

const UnitErrorBlock: React.FC<{ error: Error }> = ({ error }) => {
  const forbidden = getErrorCode(error) === 'FORBIDDEN';
  return (
    <Box>
      <PageHeader title="Unit" backButton={backToUnits} />
      <ErrorAlert
        message={forbidden ? 'You are not an admin of this unit.' : error.message || 'Unable to load this unit.'}
      />
    </Box>
  );
};

const UnitDetailPage: React.FC = () => {
  const { unitId } = useParams<{ unitId: string }>();
  const [tab, setTab] = useState<TabKey>('settings');

  const { data, loading, error } = useQuery<{ unit: GqlUnit }>(GET_UNIT, { variables: { unitId } });

  if (loading) return <LoadingState />;
  if (error) return <UnitErrorBlock error={error} />;
  const unit = data ? data.unit : null;
  if (!unit) return <ErrorAlert message="Unit not found." />;

  return (
    <Box>
      <PageHeader title={unitTitle(unit)} subtitle={`${unit.unitType} ${unit.unitNumber}`} backButton={backToUnits} />
      <Tabs value={tab} onChange={(_, v: TabKey) => setTab(v)} sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        {TABS.map((t) => (
          <Tab key={t.key} value={t.key} label={t.label} />
        ))}
      </Tabs>
      {renderPanel(tab, unit.unitId)}
    </Box>
  );
};

export default UnitDetailPage;
