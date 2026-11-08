import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { FulfillmentPage } from '../src/pages/FulfillmentPage';

test('renders fulfillment heading', () => {
  render(<MemoryRouter><FulfillmentPage /></MemoryRouter>);
  expect(screen.getByText('Fulfillment')).toBeInTheDocument();
});

test('fulfill increments fulfilled and decrements unfulfilled', () => {
  render(<MemoryRouter><FulfillmentPage /></MemoryRouter>);
  fireEvent.click(screen.getByText('Fulfill'));
  expect(screen.getByText('1')).toBeInTheDocument();
  expect(screen.getByText('4')).toBeInTheDocument();
});

test('reverse decrements fulfilled and increments unfulfilled', () => {
  render(<MemoryRouter><FulfillmentPage /></MemoryRouter>);
  fireEvent.click(screen.getByText('Fulfill'));
  fireEvent.click(screen.getByText('Reverse'));
  expect(screen.getByText('0')).toBeInTheDocument();
  expect(screen.getByText('5')).toBeInTheDocument();
});

test('reverse at zero stays zero fulfilled', () => {
  render(<MemoryRouter><FulfillmentPage /></MemoryRouter>);
  fireEvent.click(screen.getByText('Reverse'));
  expect(screen.getByText('0')).toBeInTheDocument();
  expect(screen.getByText('6')).toBeInTheDocument();
});

test('mode and version inputs update', () => {
  render(<MemoryRouter><FulfillmentPage /></MemoryRouter>);
  fireEvent.change(screen.getByLabelText('fulfillmentMode'), { target: { value: 'X' } });
  expect(screen.getByDisplayValue('X')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('version'), { target: { value: '2' } });
  expect(screen.getByDisplayValue('2')).toBeInTheDocument();
});
