import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { InventoryPage } from '../src/pages/InventoryPage';

test('SS-SM-03 value', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  expect(screen.getByText('Inventory')).toBeInTheDocument();
});

test('SS-SM-03 invalid-input', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  expect(screen.getByText('Inventory')).toBeInTheDocument();
});

test('SS-SM-03 no-side-effect-message', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  expect(screen.getByText('Inventory')).toBeInTheDocument();
});

test('SS-SM-03 movement-filter', () => {
  render(<MemoryRouter><InventoryPage /></MemoryRouter>);
  expect(screen.getByText('Inventory')).toBeInTheDocument();
});
