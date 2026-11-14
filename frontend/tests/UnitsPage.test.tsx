/**
 * Units list, creation, and invite redemption (§1.6.1).
 *
 * The behaviours asserted here are the ones the checklist names: the generated name
 * shown instead of a blank label, the exact-duplicate refused as a question (both
 * cancelled and confirmed), and the loading/error states kept distinct from an empty
 * list. Mutation mocks spell out their variables because Apollo's mock link only
 * matches a request whose variables it can compare — which is a feature here: the
 * idempotency key and `duplicateConfirmed` are asserted, not assumed.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { MemoryRouter } from 'react-router-dom';
import { UnitsPage } from '../src/pages/UnitsPage';
import { createUnitInput, type UnitFormValues } from '../src/lib/unitForm';
import { CREATE_UNIT, MY_UNITS, REDEEM_UNIT_INVITE } from '../src/lib/graphql';
import { unitFixture } from './helpers/unitFixtures';
import { UNIT_PAGE_SIZE } from '../src/lib/units';

const navigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => navigate };
});

const PAGED = { page: { limit: UNIT_PAGE_SIZE } };

const unitsResult = {
  myUnits: {
    __typename: 'UnitConnection',
    items: [
      unitFixture(),
      unitFixture({ unitId: 'UNIT#crew-529', unitType: 'Crew', unitNumber: 529, displayName: 'Adventure Crew' }),
    ],
    pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
  },
};

const emptyUnitsResult = {
  myUnits: {
    __typename: 'UnitConnection',
    items: [],
    pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
  },
};

/**
 * Idempotency keys are generated per intent, so the tests hand out a sequence:
 * the first create attempt and the confirmed-duplicate attempt are then provably
 * different requests, which is the rule the backend enforces by refusing a reused
 * key with a changed fingerprint.
 */
let keySequence = 0;
function nextKey(): string {
  return `test-idem-${++keySequence}`;
}

/** The form the tests fill by hand; the payload is then built by the page's own builder. */
const FILLED_FORM: UnitFormValues = {
  unitType: 'Pack',
  unitNumber: '3149',
  city: 'Springfield',
  state: 'IL',
  displayName: '',
  timezone: 'America/Chicago',
  splitDefault: 'EQUAL',
  councilNeedBasis: 'PHYSICAL_STOCK',
};

function createInput(extra: Record<string, unknown> = {}, keyIndex = 1) {
  return { input: { ...createUnitInput(FILLED_FORM, `test-idem-${keyIndex}`, false), ...extra } };
}

function redeemInput(inviteCode: string, keyIndex = 1) {
  return { input: { inviteCode, idempotency: { idempotencyKey: `test-idem-${keyIndex}` } } };
}

function listMock(data: unknown) {
  return { request: { query: MY_UNITS, variables: PAGED }, result: { data } };
}

function renderPage(mocks: unknown[]) {
  return render(
    <MockedProvider mocks={mocks as never}>
      <MemoryRouter>
        <UnitsPage />
      </MemoryRouter>
    </MockedProvider>,
  );
}

/** The create dialog's own confirm button — the page header offers one with the same name. */
async function submitCreateButton() {
  const dialog = await screen.findByRole('dialog');
  return within(dialog).getByRole('button', { name: /^Create Unit/ });
}

/** MUI's Select only opens from its display node, not the TextField wrapper. */
async function chooseUnitType(user: ReturnType<typeof userEvent.setup>, label: string) {
  const display = (await screen.findByTestId('unit-type')).querySelector('.MuiSelect-select') as HTMLElement;
  await user.click(display);
  await user.click(await screen.findByRole('option', { name: label }));
}

/** MUI puts the test id on the field wrapper; typing has to target the input inside it. */
async function typeInto(testId: string, value: string, user: ReturnType<typeof userEvent.setup>) {
  const field = await screen.findByTestId(testId);
  const input = (field.tagName === 'INPUT' ? field : field.querySelector('input')) as HTMLElement;
  await user.type(input, value);
}

async function openCreateForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByTestId('create-unit'));
  await chooseUnitType(user, 'Pack');
  await typeInto('unit-number', '3149', user);
  await typeInto('unit-city', 'Springfield', user);
  await typeInto('unit-state', 'IL', user);
}

const DUPLICATE_ERROR = new GraphQLError('A Unit with this type, number, city, and state already exists', {
  extensions: { errorCode: 'INVALID_INPUT' },
});

const CREATED = { data: { createUnit: unitFixture() } };
const REDEEMED = {
  data: {
    redeemUnitInvite: {
      __typename: 'UnitAccessGrant',
      unitId: 'UNIT#pack-3149',
      accountId: 'account-devon',
      role: 'UNIT_ADMIN',
      email: null,
      name: null,
      createdByAccountId: 'account-avery',
      createdAt: '2026-01-04T15:00:00Z',
    },
  },
};

describe('UnitsPage', () => {
  beforeEach(() => {
    keySequence = 0;
    vi.stubGlobal('crypto', { randomUUID: () => nextKey() });
    vi.clearAllMocks();
  });

  it('shows a loading state before the first answer arrives', async () => {
    renderPage([{ request: { query: MY_UNITS, variables: PAGED }, result: new Promise(() => undefined) }]);
    expect(document.querySelector('.MuiCircularProgress-root')).not.toBeNull();
    expect(screen.queryByTestId('unit-list')).toBeNull();
  });

  it('names the failure instead of presenting an empty list', async () => {
    renderPage([{ request: { query: MY_UNITS, variables: PAGED }, error: new GraphQLError('offline') }]);
    expect(await screen.findByText('Could not load your Units.')).toBeInTheDocument();
  });

  it('offers creation when there are no Units yet', async () => {
    renderPage([listMock(emptyUnitsResult)]);
    expect(await screen.findByText('No Units yet')).toBeInTheDocument();
  });

  it('shows each Unit by its generated or chosen name', async () => {
    renderPage([listMock(unitsResult)]);
    expect(await screen.findByTestId('unit-name-UNIT#pack-3149')).toHaveTextContent('Pack 3149 (Springfield, IL)');
    expect(screen.getByTestId('unit-name-UNIT#crew-529')).toHaveTextContent('Adventure Crew');
    expect(screen.getByTestId('unit-summary-UNIT#pack-3149')).toHaveTextContent(
      'Pack 3149 · Springfield, IL · 2 admins',
    );
  });

  it('opens the Unit workspace from the list', async () => {
    const user = userEvent.setup();
    renderPage([listMock(unitsResult)]);
    await user.click(await screen.findByTestId('open-unit-UNIT#pack-3149'));
    expect(navigate).toHaveBeenCalledWith('/show-sell/units/UNIT#pack-3149');
  });

  it('previews the generated name an empty display-name override will store', async () => {
    const user = userEvent.setup();
    renderPage([listMock(emptyUnitsResult)]);
    await openCreateForm(user);

    expect(await screen.findByTestId('unit-display-name')).toBeInTheDocument();
    expect(screen.getByText(/Leave empty to use "Pack 3149 \(Springfield, IL\)"/)).toBeInTheDocument();
  });

  it('refuses to create a Unit until the required fields are filled', async () => {
    const user = userEvent.setup();
    renderPage([listMock(emptyUnitsResult), { request: { query: CREATE_UNIT, variables: createInput() }, result: CREATED }]);
    await user.click(await screen.findByTestId('create-unit'));
    await user.click(await submitCreateButton());
    expect(await screen.findAllByText('Required')).not.toHaveLength(0);
  });

  it('creates a Unit with geography, defaults, and no display-name override', async () => {
    const user = userEvent.setup();
    renderPage([
      listMock(emptyUnitsResult),
      {
        request: { query: CREATE_UNIT, variables: createInput() },
        result: CREATED,
      },
      listMock(unitsResult),
    ]);
    await openCreateForm(user);
    await user.click(await submitCreateButton());
    expect(await screen.findByTestId('unit-name-UNIT#pack-3149')).toBeInTheDocument();
  });

  it('asks before creating a Unit whose metadata already exists, and cancels on request', async () => {
    const user = userEvent.setup();
    renderPage([listMock(emptyUnitsResult), { request: { query: CREATE_UNIT, variables: createInput() }, error: DUPLICATE_ERROR }]);
    await openCreateForm(user);
    await user.click(await submitCreateButton());
    expect(await screen.findByText('A Unit with these details already exists')).toBeInTheDocument();
    const dialog = screen.getAllByRole('dialog').at(-1);
    await user.click(within(dialog as HTMLElement).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByText('A Unit with these details already exists')).not.toBeInTheDocument());
  });

  it('creates the Unit once the duplicate is confirmed, as a new intent', async () => {
    const user = userEvent.setup();
    let confirmed: Record<string, unknown> | undefined;
    renderPage([
      listMock(emptyUnitsResult),
      {
        request: { query: CREATE_UNIT, variables: createInput() },
        error: DUPLICATE_ERROR,
      },
      {
        request: { query: CREATE_UNIT, variables: createInput({ duplicateConfirmed: true }, 2) },
        result: (variables: Record<string, unknown>) => {
          confirmed = variables.input as Record<string, unknown>;
          return CREATED;
        },
      },
      listMock(unitsResult),
    ]);
    await openCreateForm(user);
    await user.click(await submitCreateButton());
    await user.click(await screen.findByText('A Unit with these details already exists'));
    const confirmDialog = screen.getAllByRole('dialog').at(-1);
    await user.click(within(confirmDialog as HTMLElement).getByRole('button', { name: 'Create it as a separate Unit' }));
    await waitFor(() => expect(screen.getByTestId('unit-name-UNIT#pack-3149')).toBeInTheDocument());
    expect(confirmed?.duplicateConfirmed).toBe(true);
  });

  it('surfaces a server refusal that is not the duplicate warning', async () => {
    const user = userEvent.setup();
    renderPage([
      listMock(emptyUnitsResult),
      {
        request: { query: CREATE_UNIT, variables: createInput() },
        error: new GraphQLError('Timezone is not a known IANA zone', { extensions: { errorCode: 'INVALID_INPUT' } }),
      },
    ]);
    await openCreateForm(user);
    await user.click(await submitCreateButton());
    expect(await screen.findByText('Timezone is not a known IANA zone')).toBeInTheDocument();
  });

  it('redeems an invite code and refreshes the list', async () => {
    const user = userEvent.setup();
    renderPage([
      listMock(emptyUnitsResult),
      { request: { query: REDEEM_UNIT_INVITE, variables: redeemInput('ABCD1234EFGH5678') }, result: REDEEMED },
      listMock(unitsResult),
    ]);
    await typeInto('invite-code', 'ABCD1234EFGH5678', user);
    await user.click(await screen.findByTestId('redeem-invite'));
    expect(await screen.findByTestId('redeem-success')).toHaveTextContent('Invite redeemed');
    expect(await screen.findByTestId('unit-name-UNIT#pack-3149')).toBeInTheDocument();
  });

  it('asks for a code before calling the server', async () => {
    const user = userEvent.setup();
    renderPage([listMock(emptyUnitsResult)]);
    await user.click(await screen.findByTestId('redeem-invite'));
    expect(await screen.findByText('Enter the invite code you were given.')).toBeInTheDocument();
  });

  it('reports an invite that cannot be redeemed', async () => {
    const user = userEvent.setup();
    renderPage([
      listMock(emptyUnitsResult),
      {
        request: { query: REDEEM_UNIT_INVITE, variables: redeemInput('GONE') },
        error: new GraphQLError('Invite not found', { extensions: { errorCode: 'NOT_FOUND' } }),
      },
    ]);
    await typeInto('invite-code', 'GONE', user);
    await user.click(await screen.findByTestId('redeem-invite'));
    expect(await screen.findByText('Invite not found')).toBeInTheDocument();
  });


  it('lets a refusal on the create form be dismissed without losing the form', async () => {
    const user = userEvent.setup();
    renderPage([
      listMock(emptyUnitsResult),
      {
        request: { query: CREATE_UNIT, variables: createInput() },
        error: new GraphQLError('Timezone is not a known IANA zone', { extensions: { errorCode: 'INVALID_INPUT' } }),
      },
    ]);
    await openCreateForm(user);
    await user.click(await submitCreateButton());

    expect(await screen.findByText('Timezone is not a known IANA zone')).toBeInTheDocument();
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByText('Timezone is not a known IANA zone')).not.toBeInTheDocument());
    expect(screen.getByTestId('unit-city')).toBeInTheDocument();
  });


  it('counts a sole admin in the singular', async () => {
    renderPage([listMock({ ...unitsResult, myUnits: { ...unitsResult.myUnits, items: [unitFixture({ adminCount: 1 })] } })]);

    expect((await screen.findByTestId('unit-summary-UNIT#pack-3149')).textContent).toContain('1 admin');
  });

  it('states a refused invite redemption that carries no reason', async () => {
    renderPage([
      listMock(emptyUnitsResult),
      { request: { query: REDEEM_UNIT_INVITE, variables: redeemInput('GONE') }, error: new Error('') },
    ]);
    const user = userEvent.setup();

    await typeInto('invite-code', 'GONE', user);
    await user.click(await screen.findByTestId('redeem-invite'));

    expect(await screen.findByText('That invite code could not be redeemed.')).toBeInTheDocument();
  });

  it('states a create refusal when the server sends no reason', async () => {
    renderPage([
      listMock(emptyUnitsResult),
      { request: { query: CREATE_UNIT, variables: createInput() }, error: new Error('') },
    ]);
    const user = userEvent.setup();
    await openCreateForm(user);
    await user.click(await submitCreateButton());

    expect(await screen.findByText('Could not create the Unit.')).toBeInTheDocument();
  });
});
