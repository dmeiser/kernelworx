/**
 * Tests for PublicSettingsCapNotice.
 */
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PublicSettingsCapNotice } from '../../../src/components/public/PublicSettingsCapNotice';

describe('PublicSettingsCapNotice', () => {
  it('shows remaining capacity while under the cap', () => {
    render(<PublicSettingsCapNotice publicOrderCount={3} maxOrders={500} />);
    expect(screen.getByText(/3 out of 500 maximum orders/)).toBeInTheDocument();
    expect(screen.getByText(/497 orders remaining/)).toBeInTheDocument();
    expect(screen.getByText(/1% used/)).toBeInTheDocument();
  });

  it('shows the at-capacity warning when the count reaches the cap', () => {
    render(<PublicSettingsCapNotice publicOrderCount={500} maxOrders={500} />);
    expect(screen.getByText(/At maximum capacity!/)).toBeInTheDocument();
    expect(screen.getByText(/100% used/)).toBeInTheDocument();
  });

  it('guards against division by zero when maxOrders is zero', () => {
    render(<PublicSettingsCapNotice publicOrderCount={0} maxOrders={0} />);
    expect(screen.getByText(/0 out of 0 maximum orders/)).toBeInTheDocument();
    expect(screen.getByText(/At maximum capacity!/)).toBeInTheDocument();
    expect(screen.getByText(/0% used/)).toBeInTheDocument();
  });
});
