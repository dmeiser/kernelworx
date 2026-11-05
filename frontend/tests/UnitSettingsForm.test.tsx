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

const UNIT_ID = 'UNIT#unit-1';
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
  renderForm([{ request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } }]);

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
    {
      request: { query: UPDATE_UNIT, variables: match },
      result: { errors: [new GraphQLError('version changed', { extensions: { errorCode: 'CONFLICT' } })] },
    },
  ]);

  await screen.findByRole('button', { name: /Save changes/i });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  expect(await screen.findByRole('alert')).toBeInTheDocument();
});

it('sends trimmed city so the stored unit matches the generated-name preview', async () => {
  const user = userEvent.setup();
  const sentVariables: Array<Record<string, unknown>> = [];
  renderForm([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } },
    {
      request: {
        query: UPDATE_UNIT,
        variables: (v: unknown) => {
          sentVariables.push(v as Record<string, unknown>);
          return true;
        },
      },
      result: { data: { updateUnit: unit({ version: 2 }) } },
    },
  ]);

  await screen.findByRole('button', { name: /Save changes/i });
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: '  Aurora  ' } });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  await waitFor(() => expect(sentVariables.length).toBeGreaterThan(0));
  expect(sentVariables[0].input).toMatchObject({ city: 'Aurora', state: 'CO' });
});

it('reverts a cleared display name to the generated name built from the saved city/state', async () => {
  const user = userEvent.setup();
  const sentVariables: Array<Record<string, unknown>> = [];
  renderForm([
    {
      request: { query: GET_UNIT, variables: match },
      result: { data: { unit: unit({ displayName: 'Custom Troop' }) } },
    },
    {
      request: {
        query: UPDATE_UNIT,
        variables: (v: unknown) => {
          sentVariables.push(v as Record<string, unknown>);
          return true;
        },
      },
      result: { data: { updateUnit: unit({ displayName: 'Pack 3149 - Aurora, CO', version: 2 }) } },
    },
    {
      request: { query: GET_UNIT, variables: match },
      result: { data: { unit: unit({ displayName: 'Pack 3149 - Aurora, CO', version: 2 }) } },
    },
  ]);

  await screen.findByDisplayValue('Custom Troop');
  fireEvent.change(screen.getByLabelText(/Display name/i), { target: { value: '' } });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  await waitFor(() => expect(sentVariables.length).toBeGreaterThan(0));
  // A cleared display name sends the generated name from the saved city/state, not a blank.
  expect(sentVariables[0].input).toMatchObject({ displayName: 'Pack 3149 - Aurora, CO' });
  expect(await screen.findByText('Pack 3149 - Aurora, CO')).toBeInTheDocument();
});

it('builds the cleared display name from the changed city, not the old one', async () => {
  const user = userEvent.setup();
  const sentVariables: Array<Record<string, unknown>> = [];
  renderForm([
    {
      request: { query: GET_UNIT, variables: match },
      result: { data: { unit: unit({ displayName: 'Custom Troop' }) } },
    },
    {
      request: {
        query: UPDATE_UNIT,
        variables: (v: unknown) => {
          sentVariables.push(v as Record<string, unknown>);
          return true;
        },
      },
      result: { data: { updateUnit: unit({ displayName: 'Pack 3149 - Denver, CO', version: 2 }) } },
    },
    {
      request: { query: GET_UNIT, variables: match },
      result: { data: { unit: unit({ displayName: 'Pack 3149 - Denver, CO', version: 2 }) } },
    },
  ]);

  await screen.findByDisplayValue('Custom Troop');
  // Change the city AND clear the display name in the same save.
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Denver' } });
  fireEvent.change(screen.getByLabelText(/Display name/i), { target: { value: '' } });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  await waitFor(() => expect(sentVariables.length).toBeGreaterThan(0));
  // The generated name is built from the NEW city (Denver), not the old one (Aurora).
  expect(sentVariables[0].input).toMatchObject({ displayName: 'Pack 3149 - Denver, CO', city: 'Denver' });
});

it('blocks the save when the city is cleared (city presence validation, R4-02 regression)', async () => {
  const user = userEvent.setup();
  const sentVariables: Array<Record<string, unknown>> = [];
  renderForm([
    { request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } },
    {
      request: {
        query: UPDATE_UNIT,
        variables: (v: unknown) => {
          sentVariables.push(v as Record<string, unknown>);
          return true;
        },
      },
      result: { data: { updateUnit: unit({ version: 2 }) } },
    },
  ]);

  await screen.findByRole('button', { name: /Save changes/i });
  // Clearing the city would compose the display name from a blank city
  // ('Pack 3149 - , CO'), which the backend persists verbatim — so the save must be
  // blocked by presence validation, and no mutation must be sent.
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: '' } });
  await user.click(screen.getByRole('button', { name: /Save changes/i }));

  expect(await screen.findByText(/Enter the city\./i)).toBeInTheDocument();
  expect(sentVariables.length).toBe(0);
});

it('renders the shared option lists from unitTypes', async () => {
  renderForm([{ request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } }]);

  await screen.findByDisplayValue('Aurora');
  fireEvent.mouseDown(screen.getByLabelText(/Default split/i));
  expect(await screen.findByRole('option', { name: 'Split by time worked' })).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByLabelText(/Council-need basis/i));
  expect(await screen.findByRole('option', { name: 'Physical stock' })).toBeInTheDocument();
  expect(await screen.findByRole('option', { name: 'After assignments' })).toBeInTheDocument();
});

it('surfaces a load failure with the error message', async () => {
  renderForm([
    {
      request: { query: GET_UNIT, variables: match },
      result: { errors: [new GraphQLError('The unit is unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })] },
    },
  ]);
  expect(await screen.findByText(/The unit is unavailable\./i)).toBeInTheDocument();
});

it('updates the timezone, default split, and council-need basis on interaction', async () => {
  const user = userEvent.setup();
  renderForm([{ request: { query: GET_UNIT, variables: match }, result: { data: { unit: unit() } } }]);
  await screen.findByDisplayValue('Aurora');

  fireEvent.change(screen.getByLabelText(/Timezone/i), { target: { value: 'America/Chicago' } });
  expect(screen.getByDisplayValue('America/Chicago')).toBeInTheDocument();

  fireEvent.mouseDown(screen.getByLabelText(/Default split/i));
  await user.click(await screen.findByRole('option', { name: 'Split by time worked' }));
  expect(screen.getByDisplayValue('TIME_WORKED')).toBeInTheDocument();

  fireEvent.mouseDown(screen.getByLabelText(/Council-need basis/i));
  await user.click(await screen.findByRole('option', { name: 'After assignments' }));
  expect(screen.getByDisplayValue('AFTER_ASSIGNMENTS')).toBeInTheDocument();
});
