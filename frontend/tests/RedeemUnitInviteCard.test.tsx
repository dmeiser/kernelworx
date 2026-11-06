import { render, screen, fireEvent } from '@testing-library/react';
import { vi, describe, it, expect, beforeEach } from 'vitest';
import { MockedProvider } from '@apollo/client/testing/react';
import { GraphQLError } from 'graphql';
import { REDEEM_UNIT_INVITE } from '../src/lib/graphql';
import RedeemUnitInviteCard from '../src/pages/RedeemUnitInviteCard';

const renderCard = (mocks: unknown[]) =>
  render(
    <MockedProvider mocks={mocks as never} defaultOptions={{ watchQuery: { fetchPolicy: 'no-cache' } }}>
      <RedeemUnitInviteCard />
    </MockedProvider>,
  );

describe('RedeemUnitInviteCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the self-service redemption card', () => {
    renderCard([]);
    expect(screen.getByText('Redeem an invite')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^Redeem$/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/Invite code/i)).toBeInTheDocument();
  });

  it('redeems a valid invite code and confirms success', async () => {
    renderCard([
      {
        request: { query: REDEEM_UNIT_INVITE, variables: () => true },
        result: {
          data: {
            redeemUnitInvite: {
              accountId: '11111111-1111-4111-8111-111111111111',
              role: 'UNIT_ADMIN',
              unitId: 'unit-pack-3149-aurora',
              createdAt: '2026-11-01T00:00:00+00:00',
            },
          },
        },
      },
    ]);
    fireEvent.change(screen.getByLabelText(/Invite code/i), { target: { value: 'PKT3149ACTIVE001' } });
    fireEvent.click(screen.getByRole('button', { name: /^Redeem$/i }));
    expect(await screen.findByText(/Invite redeemed/i)).toBeInTheDocument();
  });

  it('surfaces a mapped error when redemption fails', async () => {
    renderCard([
      {
        request: { query: REDEEM_UNIT_INVITE, variables: () => true },
        result: { errors: [new GraphQLError('not found', { extensions: { errorCode: 'NOT_FOUND' } })] },
      },
    ]);
    fireEvent.change(screen.getByLabelText(/Invite code/i), { target: { value: 'PKT3149ACTIVE001' } });
    fireEvent.click(screen.getByRole('button', { name: /^Redeem$/i }));
    expect(await screen.findByText(/The requested resource was not found/i)).toBeInTheDocument();
  });

  it('does not submit an empty invite code', () => {
    renderCard([]);
    fireEvent.click(screen.getByRole('button', { name: /^Redeem$/i }));
    expect(screen.getByText(/Enter the 16-character invite code/i)).toBeInTheDocument();
  });
});
