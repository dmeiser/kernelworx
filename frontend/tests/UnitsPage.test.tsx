import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { BrowserRouter } from 'react-router-dom';
import { vi, beforeEach } from 'vitest';
import { MY_UNITS, CREATE_UNIT } from '../src/lib/graphql';
import UnitsPage from '../src/pages/UnitsPage';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../src/contexts/AuthContext', () => ({
  useAuth: () => ({
    account: { accountId: 'avery-account', email: 'avery@fixtures.kernelworx.test', givenName: 'Avery' },
    loading: false,
    isAuthenticated: true,
    isAdmin: false,
    refresh: vi.fn(),
    signOut: vi.fn(),
  }),
}));

const PAGE_INFO = { __typename: 'PageInfo', endCursor: null, hasNextPage: false };

const unit = (over: Record<string, unknown> = {}) => ({
  __typename: 'Unit',
  unitId: 'unit-pack-3149-aurora',
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

const myUnits = (items: unknown[]) => ({
  data: { myUnits: { __typename: 'UnitConnection', items, pageInfo: PAGE_INFO } },
});

const createUnitSuccess = (unitId: string) => ({
  data: {
    createUnit: {
      __typename: 'UnitCreateResult',
      unit: unit({ unitId }),
      grant: {
        __typename: 'UnitAccessGrant',
        accountId: 'avery-account',
        role: 'UNIT_ADMIN',
        unitId,
        createdAt: '2026-11-01T00:00:00+00:00',
      },
    },
  },
});

function renderPage(mocks: unknown[]) {
  return render(
    <MockedProvider mocks={mocks as never} defaultOptions={{ watchQuery: { fetchPolicy: 'no-cache' } }}>
      <BrowserRouter>
        <UnitsPage />
      </BrowserRouter>
    </MockedProvider>,
  );
}

async function fillCreateUnitForm(user: ReturnType<typeof userEvent.setup>) {
  fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
  await user.click(await screen.findByRole('option', { name: 'Pack' }));
  fireEvent.change(screen.getByLabelText(/Unit number/i), { target: { value: '3149' } });
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Aurora' } });
  fireEvent.change(screen.getByLabelText(/State/i), { target: { value: 'CO' } });
}

beforeEach(() => {
  mockNavigate.mockClear();
});

it('renders the admin\'s units from myUnits (explicit + generated display names)', async () => {
  renderPage([
    {
      request: { query: MY_UNITS, variables: () => true },
      result: {
        data: {
          myUnits: {
            __typename: 'UnitConnection',
            items: [
              unit(),
              unit({ unitId: 'unit-crew-529', unitType: 'Crew', unitNumber: 529, city: 'Denver', displayName: null }),
            ],
            pageInfo: PAGE_INFO,
          },
        },
      },
    },
  ]);
  expect(await screen.findByText('Units')).toBeInTheDocument();
  expect(await screen.findByText('Pack 3149 - Aurora, CO')).toBeInTheDocument();
  expect(await screen.findByText('Crew 529 - Denver, CO')).toBeInTheDocument();
});

it('shows the empty state when the admin has no units', async () => {
  renderPage([
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) },
  ]);
  expect(await screen.findByText(/No units yet/)).toBeInTheDocument();
});

it('confirms before creating a distinct unit on a duplicate (CONFLICT → duplicateConfirmed retry)', async () => {
  const user = userEvent.setup();
  renderPage([
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) },
    {
      request: { query: CREATE_UNIT, variables: () => true },
      result: { errors: [new GraphQLError('A unit with the same identity already exists', { extensions: { errorCode: 'CONFLICT' } })] },
    },
    { request: { query: CREATE_UNIT, variables: () => true }, result: createUnitSuccess('unit-new') },
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([unit({ unitId: 'unit-new' })]) },
  ]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  await user.click(createButtons[0]);
  await screen.findByRole('dialog');
  await fillCreateUnitForm(user);

  const dialog = screen.getByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: /^Create Unit$/i }));

  // The duplicate surfaces as a confirmation, not a failure.
  await screen.findByText(/Create a distinct Unit\?/i);

  // Confirming retries with duplicateConfirmed: true and a fresh idempotency key, then succeeds.
  await user.click(screen.getByRole('button', { name: /Create distinct Unit/i }));
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/units/unit-new'));
  await waitFor(() => expect(screen.queryByText(/Create a distinct Unit\?/i)).not.toBeInTheDocument());
  expect(screen.queryByText(/already exists/i)).not.toBeInTheDocument();
});

it('surfaces an error and a retry when loading the units fails', async () => {
  renderPage([
    {
      request: { query: MY_UNITS, variables: () => true },
      result: { errors: [new GraphQLError('The units list is unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })] },
    },
  ]);

  expect(await screen.findByText(/The units list is unavailable\./i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
});
