import { render, screen, within, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { BrowserRouter } from 'react-router-dom';
import { vi, beforeEach } from 'vitest';
import { MY_UNITS, CREATE_UNIT, REDEEM_UNIT_INVITE } from '../src/lib/graphql';
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

it("renders the admin's units from myUnits (explicit + generated display names)", async () => {
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
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) }]);
  expect(await screen.findByText(/No units yet/)).toBeInTheDocument();
});

it('confirms before creating a distinct unit on a duplicate (CONFLICT → duplicateConfirmed retry)', async () => {
  const user = userEvent.setup();
  renderPage([
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) },
    {
      request: { query: CREATE_UNIT, variables: () => true },
      result: {
        errors: [
          new GraphQLError('A unit with the same identity already exists', { extensions: { errorCode: 'CONFLICT' } }),
        ],
      },
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

it('sends trimmed city and state so the server-composed display name matches the preview', async () => {
  const user = userEvent.setup();
  const sentVariables: Array<Record<string, unknown>> = [];
  renderPage([
    {
      request: { query: MY_UNITS, variables: () => true },
      result: { data: { myUnits: { __typename: 'UnitConnection', items: [], pageInfo: PAGE_INFO } } },
    },
    {
      request: {
        query: CREATE_UNIT,
        variables: (v: unknown) => {
          sentVariables.push(v as Record<string, unknown>);
          return true;
        },
      },
      result: createUnitSuccess('unit-new'),
    },
    {
      request: { query: MY_UNITS, variables: () => true },
      result: { data: { myUnits: { __typename: 'UnitConnection', items: [], pageInfo: PAGE_INFO } } },
    },
  ]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  await user.click(createButtons[0]);
  await screen.findByRole('dialog');
  fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
  await user.click(await screen.findByRole('option', { name: 'Pack' }));
  fireEvent.change(screen.getByLabelText(/Unit number/i), { target: { value: '3149' } });
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: '  Aurora  ' } });
  fireEvent.change(screen.getByLabelText(/State/i), { target: { value: 'CO' } });

  const dialog = screen.getByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: /^Create Unit$/i }));

  await waitFor(() => expect(sentVariables.length).toBeGreaterThan(0));
  expect(sentVariables[0].input).toMatchObject({ city: 'Aurora', state: 'CO' });
});

it('offers a discoverable entry to the participant join flow beside the invite card', async () => {
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) }]);

  const joinLink = await screen.findByRole('link', { name: /Join unit campaign/i });
  expect(joinLink).toHaveAttribute('href', '/join-unit-campaign');
});

it('surfaces an error and a retry when loading the units fails', async () => {
  renderPage([
    {
      request: { query: MY_UNITS, variables: () => true },
      result: {
        errors: [new GraphQLError('The units list is unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })],
      },
    },
  ]);

  expect(await screen.findByText(/The units list is unavailable\./i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument();
});

it('keeps the redeem success confirmation visible while MY_UNITS refetches', async () => {
  const user = userEvent.setup();
  renderPage([
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) },
    {
      request: { query: REDEEM_UNIT_INVITE, variables: () => true },
      result: {
        data: {
          redeemUnitInvite: {
            __typename: 'UnitAccessGrant',
            accountId: 'avery-account',
            role: 'UNIT_ADMIN',
            unitId: 'unit-new',
            createdAt: '2026-11-01T00:00:00+00:00',
          },
        },
      },
    },
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([unit({ unitId: 'unit-new' })]) },
  ]);

  await screen.findByText('Units');
  await user.type(screen.getByLabelText(/Invite code/i), 'PKT3149ACTIVE001');
  await user.click(screen.getByRole('button', { name: /^Redeem$/i }));

  // The onRedeemed refetch lands: the redeemed unit now appears in the list...
  expect(await screen.findByText('Pack 3149 - Aurora, CO')).toBeInTheDocument();
  // ...and the card's success confirmation is still visible after the refetch settled,
  // not wiped by the refetch-triggered remount.
  expect(screen.getByText(/Invite redeemed/i)).toBeInTheDocument();
});

it('normalizes the unit number in the create preview like the server (007 -> 7)', async () => {
  const user = userEvent.setup();
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) }]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  await user.click(createButtons[0]);
  await screen.findByRole('dialog');
  fireEvent.mouseDown(screen.getAllByRole('combobox')[0]);
  await user.click(await screen.findByRole('option', { name: 'Pack' }));
  fireEvent.change(screen.getByLabelText(/Unit number/i), { target: { value: '007' } });
  fireEvent.change(screen.getByLabelText(/City/i), { target: { value: 'Aurora' } });
  fireEvent.change(screen.getByLabelText(/State/i), { target: { value: 'CO' } });

  // The preview composes the number the way the server does (007 -> 7), not the raw string.
  expect(await screen.findByText(/Pack 7 - Aurora, CO/)).toBeInTheDocument();
});

it('updates the optional display name and timezone fields and closes on Cancel', async () => {
  const user = userEvent.setup();
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) }]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  await user.click(createButtons[0]);
  const dialog = await screen.findByRole('dialog');

  fireEvent.change(within(dialog).getByLabelText(/Display name/i), { target: { value: 'My Pack' } });
  fireEvent.change(within(dialog).getByLabelText(/Timezone/i), { target: { value: 'America/Chicago' } });
  fireEvent.mouseDown(within(dialog).getByLabelText(/Default split/i));
  await user.click(await screen.findByRole('option', { name: 'Split by time worked' }));
  fireEvent.mouseDown(within(dialog).getByLabelText(/Council-need basis/i));
  await user.click(await screen.findByRole('option', { name: 'After assignments' }));

  await user.click(within(dialog).getByRole('button', { name: /^Cancel$/i }));
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

it('blocks submit and names the first missing required field', async () => {
  const user = userEvent.setup();
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) }]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  await user.click(createButtons[0]);
  const dialog = await screen.findByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: /^Create Unit$/i }));

  expect(await screen.findByText(/Choose the unit type\./i)).toBeInTheDocument();
});

it('opens a unit\'s detail when its card is clicked', async () => {
  const user = userEvent.setup();
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([unit()]) }]);

  const card = await screen.findByTestId('unit-card-unit-pack-3149-aurora');
  await user.click(card);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/units/unit-pack-3149-aurora'));
});

it('offers Create Unit from the empty state and opens the dialog', async () => {
  const user = userEvent.setup();
  renderPage([{ request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) }]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  // The second "Create Unit" is the empty state's action (the first is the page header's).
  await user.click(createButtons[createButtons.length - 1]);
  expect(await screen.findByRole('dialog')).toBeInTheDocument();
});

it('recovers from a units load failure when Retry is clicked', async () => {
  const user = userEvent.setup();
  renderPage([
    {
      request: { query: MY_UNITS, variables: () => true },
      result: { errors: [new GraphQLError('The units list is unavailable.', { extensions: { errorCode: 'INTERNAL_ERROR' } })] },
    },
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([unit()]) },
  ]);

  expect(await screen.findByRole('button', { name: /Retry/i })).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /Retry/i }));
  expect(await screen.findByText('Pack 3149 - Aurora, CO')).toBeInTheDocument();
});

it('surfaces a create failure without closing the dialog', async () => {
  const user = userEvent.setup();
  renderPage([
    { request: { query: MY_UNITS, variables: () => true }, result: myUnits([]) },
    {
      request: { query: CREATE_UNIT, variables: () => true },
      result: { errors: [new GraphQLError('The unit could not be created.', { extensions: { errorCode: 'INTERNAL_ERROR' } })] },
    },
  ]);

  const createButtons = await screen.findAllByRole('button', { name: /^Create Unit$/i });
  await user.click(createButtons[0]);
  await screen.findByRole('dialog');
  await fillCreateUnitForm(user);
  const dialog = screen.getByRole('dialog');
  await user.click(within(dialog).getByRole('button', { name: /^Create Unit$/i }));

  expect(await screen.findByText(/An internal error occurred/i)).toBeInTheDocument();
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
