/**
 * One Unit's workspace: settings, access, and campaigns (Show & Sell §1.6.1–1.6.3).
 *
 * `unit` answers NOT_FOUND — not FORBIDDEN — for a Unit the caller has no grant on,
 * so this screen cannot tell an admin that someone else's Unit exists. The copy says
 * that plainly rather than implying a retry would help.
 */

import React, { useState } from 'react';
import { useQuery } from '@apollo/client/react';
import { useNavigate, useParams } from 'react-router-dom';
import { Box, Tab, Tabs } from '@mui/material';
import GroupWorkIcon from '@mui/icons-material/GroupWork';
import { GET_UNIT } from '../lib/graphql';
import { ErrorAlert } from '../components/ErrorAlert';
import { LoadingState } from '../components/LoadingState';
import { PageHeader } from '../components/PageHeader';
import { UnitAccessPanel } from '../components/UnitAccessPanel';
import { UnitCampaignsPanel } from '../components/UnitCampaignsPanel';
import { UnitPaymentMethodsPanel } from '../components/UnitPaymentMethodsPanel';
import { UnitSettingsPanel } from '../components/UnitSettingsPanel';
import { useAuth } from '../contexts/AuthContext';
import { SHOW_SELL_BASE, unitDisplayName } from '../lib/units';
import type { GqlGetUnitQuery, GqlUnit } from '../types/graphql-generated';

type WorkspaceTab = 'settings' | 'access' | 'payments' | 'campaigns';

function readUnit(data: GqlGetUnitQuery | undefined): GqlUnit | null {
  return data?.unit ?? null;
}

export const UnitWorkspacePage: React.FC = () => {
  const { unitId = '' } = useParams();
  const [tab, setTab] = useState<WorkspaceTab>('settings');
  const unitQuery = useQuery<GqlGetUnitQuery>(GET_UNIT, { variables: { unitId } });

  if (unitQuery.loading && !unitQuery.data) return <LoadingState />;
  return (
    <UnitWorkspaceBody
      unit={readUnit(unitQuery.data)}
      tab={tab}
      onTabChange={setTab}
      onUnitChanged={unitQuery.refetch}
    />
  );
};

/**
 * A Unit the caller cannot see and a Unit that is gone answer identically, which is
 * the point: confirming existence across tenants is what a per-Unit authorization
 * rule exists to prevent. The failed-load case says the same words on purpose —
 * "not yours" and "no longer here" must not be distinguishable.
 */
const UnitWorkspaceBody: React.FC<{
  unit: GqlUnit | null;
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  onUnitChanged: () => Promise<unknown>;
}> = ({ unit, tab, onTabChange, onUnitChanged }) => {
  if (!unit) return <UnreachableUnitAlert />;
  return (
    <>
      <UnitHeader unit={unit} />
      <UnitWorkspaceTabs tab={tab} onChange={onTabChange} />
      <UnitWorkspacePanel tab={tab} unit={unit} onUnitChanged={onUnitChanged} />
    </>
  );
};

const UnreachableUnitAlert: React.FC = () => (
  <ErrorAlert message="This Unit is not yours, or it no longer exists. Unit access is granted per Unit — there is no view of Units you do not administer." />
);

const UnitHeader: React.FC<{ unit: GqlUnit }> = ({ unit }) => {
  const navigate = useNavigate();
  return (
    <PageHeader
      title={unitDisplayName(unit)}
      subtitle={`${unit.unitType} ${unit.unitNumber} · ${unit.city}, ${unit.state}`}
      icon={GroupWorkIcon}
      backButton={{
        onClick: () => void navigate(`${SHOW_SELL_BASE}/units`),
        label: 'Back to Units',
        'aria-label': 'Back to Units',
      }}
    />
  );
};

const UnitWorkspaceTabs: React.FC<{ tab: WorkspaceTab; onChange: (tab: WorkspaceTab) => void }> = ({
  tab,
  onChange,
}) => (
  <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
    <Tabs
      value={tab}
      onChange={(_event, value: WorkspaceTab) => onChange(value)}
      aria-label="Unit sections"
      data-testid="unit-tabs"
    >
      <Tab label="Settings" value="settings" data-testid="tab-settings" />
      <Tab label="Access" value="access" data-testid="tab-access" />
      <Tab label="Payments" value="payments" data-testid="tab-payments" />
      <Tab label="Campaigns" value="campaigns" data-testid="tab-campaigns" />
    </Tabs>
  </Box>
);

const UnitWorkspacePanel: React.FC<{
  tab: WorkspaceTab;
  unit: GqlUnit;
  onUnitChanged: () => Promise<unknown>;
}> = ({ tab, unit, onUnitChanged }) => {
  const { account } = useAuth();
  return panelFor(tab, unit, account?.accountId ?? '', onUnitChanged);
};

/**
 * Which panel a tab shows, in one branch list rather than four inline ternaries.
 *
 * A section is one line here, and the settings panel is the fall-through because it is
 * the tab the page opens on.
 */
function panelFor(
  tab: WorkspaceTab,
  unit: GqlUnit,
  accountId: string,
  onUnitChanged: () => Promise<unknown>,
): React.ReactElement {
  if (tab === 'access') {
    return <UnitAccessPanel unit={unit} callerAccountId={accountId} onUnitChanged={onUnitChanged} />;
  }
  if (tab === 'payments') return <UnitPaymentMethodsPanel unit={unit} />;
  if (tab === 'campaigns') return <UnitCampaignsPanel unit={unit} />;
  return <UnitSettingsPanel unit={unit} onSaved={onUnitChanged} />;
}
