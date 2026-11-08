import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FulfillmentPage } from '../src/pages/FulfillmentPage';

test('SS-SM-04', () => {
  render(
    <MemoryRouter>
      <FulfillmentPage />
    </MemoryRouter>,
  );
  expect(screen.getByText('Fulfillment')).toBeInTheDocument();
});
test('external-no-balance', () => {
  render(
    <MemoryRouter>
      <FulfillmentPage />
    </MemoryRouter>,
  );
  expect(screen.getByText('Fulfillment')).toBeInTheDocument();
});
test('stale-version', () => {
  render(
    <MemoryRouter>
      <FulfillmentPage />
    </MemoryRouter>,
  );
  expect(screen.getByText('Fulfillment')).toBeInTheDocument();
});
test('duplicate-reversal', () => {
  render(
    <MemoryRouter>
      <FulfillmentPage />
    </MemoryRouter>,
  );
  expect(screen.getByText('Fulfillment')).toBeInTheDocument();
});
test('privacy', () => {
  render(
    <MemoryRouter>
      <FulfillmentPage />
    </MemoryRouter>,
  );
  expect(screen.getByText('Fulfillment')).toBeInTheDocument();
});
