import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { vi } from 'vitest';
import { GET_UNIT, UNIT_ADMINS, UNIT_INVITES, CREATE_UNIT_INVITE, REVOKE_UNIT_ACCESS_GRANT } from '../src/lib/graphql';
import UnitAccessSection from '../src/pages/UnitAccessSection';

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    account: { accountId: 'self', email: 'self@fixtures.kernelworx.test', givenName: 'Self' },
    loading: false,
    isAuthenticated: true,
    isAdmin: false,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const PAGE_INFO = { __typename: 'PageInfo', endCursor: null, hasNextPage: false };
const UNIT_ID = 'unit-1';

const unit = (over: Record<string, unknown> = {}) => ({
  __typename: 'Unit',
  unitId: UNIT_ID,
  unitType: 'Pack',
  unitNumber: 3149,
  city: 'Aurora',
  state: 'CO',
  displayName: 'Pack 3149 - Aurora, CO',
  timezone: 'America/Denver',
  splitDefault: 'EQUAL',
  councilNeedBasis: 'PHYSICAL_STOCK',
  adminCount: 2,
  version: 1,
  createdAt: '2026-11-01T00:00:00+00:00',
  updatedAt: '2026-11-01T00:00:00+00:00',
  ...over,
});

const admin = (accountId: string, email: string, name: string) => ({
  __typename: 'UnitAccessGrant',
  unitId: UNIT_ID,
  accountId,
  email,
  name,
  role: 'UNIT_ADMIN',
  createdByAccountId: 'self',
  createdAt: '2026-11-01T00:00:00+00:00',
});

const invite = (inviteCode: string) => ({
  __typename: 'UnitInvite',
  inviteCode,
  unitId: UNIT_ID,
  createdByAccountId: 'self',
  createdAt: '2026-11-01T00:00:00+00:00',
  expiresAt: '2026-11-15T00:00:00+00:00',
});

function renderSection(mocks: unknown[]) {
  return render(
    <MockedProvider mocks={mocks as never} defaultOptions={{ watchQuery: { fetchPolicy: 'no-cache' } }}>
      <UnitAccessSection unitId={UNIT_ID} />
    </MockedProvider>,
  );
}

const match = () => true;

it('renders the unit admins and pending invites', async () => {
  renderSection([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ adminCount: 2 }) } } },
    { request: { query: UNIT_ADMINS, variables: match }, result: { data: { unitAdmins: { __typename: 'UnitAccessGrantConnection', items: [admin('self', 'self@fixtures.kernelworx.test', 'Self'), admin('other', 'other@fixtures.kernelworx.test', 'Taylor')], pageInfo: PAGE_INFO } } } },
    { request: { query: UNIT_INVITES, variables: match }, result: { data: { unitInvites: { __typename: 'UnitInviteConnection', items: [invite('ABC123')], pageInfo: PAGE_INFO } } } },
  ]);

  expect(await screen.findByText('Admins')).toBeInTheDocument();
  expect(await screen.findByText('Invites')).toBeInTheDocument();
  expect(await screen.findByText('other@fixtures.kernelworx.test')).toBeInTheDocument();
  expect(screen.getByText('ABC123')).toBeInTheDocument();
  expect(screen.getAllByText('UNIT_ADMIN').length).toBeGreaterThanOrEqual(2);
  expect(screen.getByRole('button', { name: /Create invite/i })).toBeInTheDocument();
});

it('disables removing the last admin and explains the rule', async () => {
  renderSection([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ adminCount: 1 }) } } },
    { request: { query: UNIT_ADMINS, variables: match }, result: { data: { unitAdmins: { __typename: 'UnitAccessGrantConnection', items: [admin('self', 'self@fixtures.kernelworx.test', 'Self')], pageInfo: PAGE_INFO } } } },
    { request: { query: UNIT_INVITES, variables: match }, result: { data: { unitInvites: { __typename: 'UnitInviteConnection', items: [], pageInfo: PAGE_INFO } } } },
  ]);

  expect(await screen.findByRole('button', { name: 'Remove' })).toBeDisabled();
  expect(screen.getByText(/at least one admin/i)).toBeInTheDocument();
});

it('confirms before removing an admin, then closes on success', async () => {
  const user = userEvent.setup();
  renderSection([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ adminCount: 2 }) } } },
    { request: { query: UNIT_ADMINS, variables: match }, result: { data: { unitAdmins: { __typename: 'UnitAccessGrantConnection', items: [admin('self', 'self@fixtures.kernelworx.test', 'Self'), admin('other', 'other@fixtures.kernelworx.test', 'Taylor')], pageInfo: PAGE_INFO } } } },
    { request: { query: UNIT_INVITES, variables: match }, result: { data: { unitInvites: { __typename: 'UnitInviteConnection', items: [], pageInfo: PAGE_INFO } } } },
    { request: { query: REVOKE_UNIT_ACCESS_GRANT, variables: match }, result: { data: { revokeUnitAccessGrant: unit({ adminCount: 1, version: 2 }) } } },
    { request: { query: UNIT_ADMINS, variables: match }, result: { data: { unitAdmins: { __typename: 'UnitAccessGrantConnection', items: [admin('self', 'self@fixtures.kernelworx.test', 'Self')], pageInfo: PAGE_INFO } } } },
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ adminCount: 1, version: 2 }) } } },
  ]);

  const removeButtons = await screen.findAllByRole('button', { name: 'Remove' });
  await user.click(removeButtons[1]);

  await screen.findByText('Remove this admin?');
  const confirm = within(screen.getByRole('dialog')).getByRole('button', { name: 'Remove' });
  await user.click(confirm);

  await waitFor(() => expect(screen.queryByText('Remove this admin?')).not.toBeInTheDocument());
});

it('creates an invite without surfacing an error on success', async () => {
  const user = userEvent.setup();
  renderSection([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ adminCount: 2 }) } } },
    { request: { query: UNIT_ADMINS, variables: match }, result: { data: { unitAdmins: { __typename: 'UnitAccessGrantConnection', items: [admin('self', 'self@fixtures.kernelworx.test', 'Self')], pageInfo: PAGE_INFO } } } },
    { request: { query: UNIT_INVITES, variables: match }, result: { data: { unitInvites: { __typename: 'UnitInviteConnection', items: [invite('ABC123')], pageInfo: PAGE_INFO } } } },
    { request: { query: CREATE_UNIT_INVITE, variables: match }, result: { data: { createUnitInvite: invite('NEWINV') } } },
  ]);

  await screen.findByRole('button', { name: /Create invite/i });
  await user.click(screen.getByRole('button', { name: /Create invite/i }));

  await new Promise((r) => setTimeout(r, 0));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('surfaces an error when creating an invite fails', async () => {
  const user = userEvent.setup();
  renderSection([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ adminCount: 2 }) } } },
    { request: { query: UNIT_ADMINS, variables: match }, result: { data: { unitAdmins: { __typename: 'UnitAccessGrantConnection', items: [admin('self', 'self@fixtures.kernelworx.test', 'Self')], pageInfo: PAGE_INFO } } } },
    { request: { query: UNIT_INVITES, variables: match }, result: { data: { unitInvites: { __typename: 'UnitInviteConnection', items: [], pageInfo: PAGE_INFO } } } },
    { request: { query: CREATE_UNIT_INVITE, variables: match }, result: { errors: [new GraphQLError('Too many invites', { extensions: { errorCode: 'RATE_LIMIT_EXCEEDED' } })] } },
  ]);

  await screen.findByRole('button', { name: /Create invite/i });
  await user.click(screen.getByRole('button', { name: /Create invite/i }));

  expect(await screen.findByRole('alert')).toBeInTheDocument();
});
