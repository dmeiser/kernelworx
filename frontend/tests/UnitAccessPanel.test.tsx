/**
 * Unit access administration (§1.6.2) — the named tests are equal-admin,
 * revoked-code, final-grant, and direct-API denial.
 *
 * One role exists, so the screen must not invent a second: no READ/WRITE selector
 * appears anywhere. An invite is a bearer code shown once and listed only while it
 * can still be redeemed. And a Unit keeps at least one admin — the button hides that
 * rule, and the server's write condition is what makes an API call that skips the
 * button fail too.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { UnitAccessPanel } from '../src/components/UnitAccessPanel';
import {
  CREATE_UNIT_INVITE,
  LIST_UNIT_ADMINS,
  LIST_UNIT_INVITES,
  REVOKE_UNIT_ACCESS_GRANT,
  REVOKE_UNIT_INVITE,
} from '../src/lib/graphql';
import { UNIT_PAGE_SIZE } from '../src/lib/units';
import { grantFixture, inviteFixture, unitFixture } from './helpers/unitFixtures';

const UNIT_ID = 'UNIT#pack-3149';
const CALLER = 'ACCOUNT#avery';
const ADMIN_PAGE = { unitId: UNIT_ID, page: { limit: UNIT_PAGE_SIZE } };

let keySequence = 0;

beforeEach(() => {
  keySequence = 0;
  vi.stubGlobal('crypto', { randomUUID: () => `test-idem-${++keySequence}` });
});

const adminsQuery = (items: unknown[]) => ({
  request: { query: LIST_UNIT_ADMINS, variables: ADMIN_PAGE },
  result: {
    data: {
      unitAdmins: {
        __typename: 'UnitAccessGrantConnection',
        items,
        pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
      },
    },
  },
});

const invitesQuery = (items: unknown[]) => ({
  request: { query: LIST_UNIT_INVITES, variables: ADMIN_PAGE },
  result: {
    data: {
      unitInvites: {
        __typename: 'UnitInviteConnection',
        items,
        pageInfo: { __typename: 'PageInfo', endCursor: null, hasNextPage: false },
      },
    },
  },
});

function renderPanel(mocks: unknown[], unit = unitFixture(), onUnitChanged = vi.fn()) {
  render(
    <MockedProvider mocks={mocks as never}>
      <UnitAccessPanel unit={unit} callerAccountId={CALLER} onUnitChanged={onUnitChanged} />
    </MockedProvider>,
  );
  return onUnitChanged;
}

describe('UnitAccessPanel', () => {
  it('shows every admin with the one equal role, and no permission levels to choose', async () => {
    const grants = [grantFixture({ accountId: 'ACCOUNT#avery', name: 'Avery Admin' }), grantFixture()];
    renderPanel([adminsQuery(grants), invitesQuery([])]);

    const averyRow = await screen.findByTestId('admin-row-ACCOUNT#avery');
    const caseyRow = screen.getByTestId('admin-row-account-casey');
    expect(within(averyRow).getByText('Admin')).toBeInTheDocument();
    expect(within(caseyRow).getByText('Admin')).toBeInTheDocument();
    expect(within(averyRow).getByText(/\(you\)/)).toBeInTheDocument();

    // The gradient this screen must not offer.
    expect(document.querySelector('.MuiSelect-select')).toBeNull();
    expect(screen.queryByText(/READ|WRITE|view only|read only/i)).not.toBeInTheDocument();
  });

  it('will not let the last remaining admin be removed from here', async () => {
    renderPanel([adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery', name: 'Avery Admin' })]), invitesQuery([])], unitFixture({ adminCount: 1 }));

    const blocked = await screen.findByTestId('revoke-blocked-ACCOUNT#avery');
    expect(blocked).toBeDisabled();
  });

  it('revokes an invite code and drops it from the list of redeemable codes', async () => {
    const invite = inviteFixture();
    const mocks = [
      adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()]),
      invitesQuery([invite]),
      {
        request: {
          query: REVOKE_UNIT_INVITE,
          variables: { input: { unitId: UNIT_ID, inviteCode: invite.inviteCode, idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        result: { data: { revokeUnitInvite: true } },
      },
      invitesQuery([]),
    ];
    renderPanel(mocks);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId(`revoke-invite-${invite.inviteCode}`));
    await user.click(await screen.findByRole('button', { name: 'Revoke invite' }));

    expect(await screen.findByText('No invites are waiting.')).toBeInTheDocument();
    expect(screen.getByTestId('active-invite-count')).toHaveTextContent('0 active invites');
  });

  it('shows a new invite code once, at the moment it is created', async () => {
    const created = inviteFixture({ inviteCode: 'TESTCODE123456789' });
    const mocks = [
      adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()]),
      invitesQuery([]),
      {
        request: {
          query: CREATE_UNIT_INVITE,
          variables: { input: { unitId: UNIT_ID, idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        result: { data: { createUnitInvite: created } },
      },
      invitesQuery([created]),
    ];
    renderPanel(mocks);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('create-invite'));

    expect(await screen.findByTestId('invite-code-value')).toHaveTextContent('TESTCODE123456789');
    expect(await screen.findByTestId(`invite-row-${created.inviteCode}`)).toBeInTheDocument();
  });

  it('reports the server refusing a removal that would leave the Unit with no admin', async () => {
    const grants = [grantFixture({ accountId: 'ACCOUNT#avery', name: 'Avery Admin' }), grantFixture()];
    const onUnitChanged = renderPanel(
      [
        adminsQuery(grants),
        invitesQuery([]),
        {
          request: {
            query: REVOKE_UNIT_ACCESS_GRANT,
            variables: {
              input: {
                unitId: UNIT_ID,
                accountId: 'account-casey',
                version: { expectedVersion: 3 },
                idempotency: { idempotencyKey: 'test-idem-1' },
              },
            },
          },
          error: new GraphQLError('A Unit keeps at least one admin.', { extensions: { code: 'FORBIDDEN' } }),
        },
        adminsQuery(grants),
        invitesQuery([]),
      ],
      unitFixture({ adminCount: 2 }),
    );

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('revoke-account-casey'));
    await user.click(await screen.findByRole('button', { name: 'Remove admin' }));

    expect(await screen.findByText('A Unit keeps at least one admin.')).toBeInTheDocument();
    expect(await screen.findByTestId('admin-row-account-casey')).toBeInTheDocument();
    expect(onUnitChanged).toHaveBeenCalled();
  });


  it('says why an invite could not be created', async () => {
    const mocks = [
      adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()]),
      invitesQuery([]),
      {
        request: {
          query: CREATE_UNIT_INVITE,
          variables: { input: { unitId: UNIT_ID, idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        error: new GraphQLError('This Unit already has 20 invites waiting.', { extensions: { code: 'CONFLICT' } }),
      },
      invitesQuery([]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-invite'));

    expect(await screen.findByText('This Unit already has 20 invites waiting.')).toBeInTheDocument();
    expect(screen.queryByTestId('invite-code-value')).not.toBeInTheDocument();
  });

  it('names a stale Unit version as a reload, not a retry', async () => {
    const grants = [grantFixture({ accountId: 'ACCOUNT#avery', name: 'Avery Admin' }), grantFixture()];
    const onUnitChanged = renderPanel([
      adminsQuery(grants),
      invitesQuery([]),
      {
        request: {
          query: REVOKE_UNIT_ACCESS_GRANT,
          variables: {
            input: {
              unitId: UNIT_ID,
              accountId: 'account-casey',
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        error: new GraphQLError('The Unit changed underneath this write.', { extensions: { code: 'CONFLICT' } }),
      },
      adminsQuery(grants),
      invitesQuery([]),
    ]);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('revoke-account-casey'));
    await user.click(await screen.findByRole('button', { name: 'Remove admin' }));

    expect(await screen.findByText('This Unit changed while you were working. Reload it and try again.')).toBeInTheDocument();
    expect(onUnitChanged).toHaveBeenCalled();
  });

  it('offers the new code for copying, and shows an unreadable expiry as it was stored', async () => {
    const created = inviteFixture({ inviteCode: 'TESTCODE123456789', expiresAt: 'not a date' });
    const mocks = [
      adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()]),
      invitesQuery([]),
      {
        request: {
          query: CREATE_UNIT_INVITE,
          variables: { input: { unitId: UNIT_ID, idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        result: { data: { createUnitInvite: created } },
      },
      invitesQuery([created]),
    ];
    renderPanel(mocks);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-invite'));
    await user.click(await screen.findByTestId('copy-invite'));

    // Copying does not consume the code: it stays where it was shown.
    expect(screen.getByTestId('invite-code-value')).toHaveTextContent('TESTCODE123456789');
    expect(await screen.findByText('not a date')).toBeInTheDocument();
  });


  it('names each admin by whatever the grant carries', async () => {
    const grants = [
      grantFixture({ accountId: 'ACCOUNT#nameless', name: null, email: 'nameless@example.com' }),
      grantFixture({ accountId: 'ACCOUNT#faceless', name: null, email: null }),
    ];
    renderPanel([adminsQuery(grants), invitesQuery([])], unitFixture({ adminCount: 3 }));

    expect((await screen.findByTestId('admin-row-ACCOUNT#nameless')).textContent).toContain('nameless@example.com');
    expect(screen.getByTestId('admin-row-ACCOUNT#faceless').textContent).toContain('ACCOUNT#faceless');
  });

  it('says plainly when an admin is removing themselves', async () => {
    const grants = [grantFixture({ accountId: 'ACCOUNT#avery', name: 'Avery Admin' }), grantFixture()];
    renderPanel([
      adminsQuery(grants),
      invitesQuery([]),
      {
        request: {
          query: REVOKE_UNIT_ACCESS_GRANT,
          variables: {
            input: {
              unitId: UNIT_ID,
              accountId: 'ACCOUNT#avery',
              version: { expectedVersion: 3 },
              idempotency: { idempotencyKey: 'test-idem-1' },
            },
          },
        },
        result: { data: { revokeUnitAccessGrant: unitFixture({ adminCount: 1 }) } },
      },
      adminsQuery([grantFixture()]),
      invitesQuery([]),
    ]);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('revoke-ACCOUNT#avery'));
    expect(await screen.findByText('You are removing your own access. This Unit leaves your list immediately.')).toBeInTheDocument();
    await user.click(within(screen.getAllByRole('dialog').at(-1) as HTMLElement).getByRole('button', { name: 'Remove admin' }));
    await waitFor(() => expect(screen.queryByTestId('admin-row-ACCOUNT#avery')).not.toBeInTheDocument());
  });

  it('states a refusal to create an invite even when the server sends no reason', async () => {
    const grants = [grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()];
    renderPanel([
      adminsQuery(grants),
      invitesQuery([]),
      {
        request: { query: CREATE_UNIT_INVITE, variables: { input: { unitId: UNIT_ID, idempotency: { idempotencyKey: 'test-idem-1' } } } },
        error: new Error(''),
      },
      invitesQuery([]),
    ]);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId('create-invite'));

    expect(await screen.findByText('Could not create an invite.')).toBeInTheDocument();
  });

  it('keeps the invite list honest when a revoke is refused without a reason', async () => {
    const invite = inviteFixture();
    renderPanel([
      adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()]),
      invitesQuery([invite]),
      {
        request: {
          query: REVOKE_UNIT_INVITE,
          variables: { input: { unitId: UNIT_ID, inviteCode: invite.inviteCode, idempotency: { idempotencyKey: 'test-idem-1' } } },
        },
        error: new Error(''),
      },
      invitesQuery([invite]),
    ]);

    const user = userEvent.setup();
    await user.click(await screen.findByTestId(`revoke-invite-${invite.inviteCode}`));
    await user.click(await screen.findByRole('button', { name: 'Revoke invite' }));

    expect(await screen.findByText('That invite could not be revoked.')).toBeInTheDocument();
    expect(await screen.findByTestId(`invite-row-${invite.inviteCode}`)).toBeInTheDocument();
  });


  it('shows no code to share when the server answers without one', async () => {
    renderPanel([
      adminsQuery([grantFixture({ accountId: 'ACCOUNT#avery' }), grantFixture()]),
      invitesQuery([]),
      {
        request: { query: CREATE_UNIT_INVITE, variables: { input: { unitId: UNIT_ID, idempotency: { idempotencyKey: 'test-idem-1' } } } },
        result: { data: { createUnitInvite: {} } },
      },
      invitesQuery([]),
    ]);
    const user = userEvent.setup();

    await user.click(await screen.findByTestId('create-invite'));

    expect(await screen.findByText('No invites are waiting.')).toBeInTheDocument();
    expect(screen.queryByTestId('invite-code-value')).not.toBeInTheDocument();
  });
});
