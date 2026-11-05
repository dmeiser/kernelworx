import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { vi } from 'vitest';
import { GET_UNIT, UPDATE_UNIT } from '../src/lib/graphql';
import UnitSettingsForm from '../src/pages/UnitSettingsForm';

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
  adminCount: 1,
  version: 1,
  createdAt: '2026-11-01T00:00:00+00:00',
  updatedAt: '2026-11-01T00:00:00+00:00',
  ...over,
});

const match = () => true;

const Host: React.FC<{ onSave?: (u: unknown) => void }> = ({ onSave }) => (
  <UnitSettingsForm unitId={UNIT_ID} onSave={onSave} />
);

function renderForm(mocks: unknown[], onSave?: (u: unknown) => void) {
  return render(
    <MockedProvider mocks={mocks as never} defaultOptions={{ watchQuery: { fetchPolicy: 'no-cache' } }}>
      <Host onSave={onSave} />
    </MockedProvider>,
  );
}

it('renders the unit settings from the unit', async () => {
  renderForm([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } },
  ]);

  expect(await screen.findByText('Pack 3149 - Aurora, CO')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Save changes/i })).toBeInTheDocument();
  expect(screen.getByDisplayValue('Aurora')).toBeInTheDocument();
  expect(screen.getByText(/1 admin/i)).toBeInTheDocument();
});

it('saves the settings and reports the updated unit', async () => {
  const user = userEvent.setup();
  const onSave = vi.fn();
  renderForm(
    [
      { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } },
      { request: { query: UPDATE_UNIT, variables: match }, result: { data: { updateUnit: unit({ version: 2 }) } } },
      { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit({ version: 2 }) } } },
    ],
    onSave,
  );

  await screen.findByRole('button', { name: /Save changes/i });
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Springfield' } });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  await waitFor(() => expect(onSave).toHaveBeenCalledOnce());
  expect(onSave.mock.calls[0][0]).toMatchObject({ unitId: UNIT_ID, version: 2 });
});

it('surfaces a conflict when the save is rejected by optimistic concurrency', async () => {
  const user = userEvent.setup();
  renderForm([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } },
    { request: { query: UPDATE_UNIT, variables: match }, result: { errors: [new GraphQLError('version changed', { extensions: { errorCode: 'CONFLICT' } })] } },
  ]);

  await screen.findByRole('button', { name: /Save changes/i });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  expect(await screen.findByRole('alert')).toBeInTheDocument();
});
