/**
 * Tests for StateAutocomplete component
 */

import { describe, test, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { StateAutocomplete } from '../src/components/StateAutocomplete';

describe('StateAutocomplete', () => {
  test('renders with default label', () => {
    const onChange = vi.fn();
    render(<StateAutocomplete value="" onChange={onChange} />);
    expect(screen.getByLabelText('State')).toBeInTheDocument();
  });

  test('renders with custom label', () => {
    const onChange = vi.fn();
    render(<StateAutocomplete value="" onChange={onChange} label="Pick a State" />);
    expect(screen.getByLabelText('Pick a State')).toBeInTheDocument();
  });

  test('calls onChange when input value changes', () => {
    const onChange = vi.fn();
    render(<StateAutocomplete value="" onChange={onChange} />);
    const input = screen.getByLabelText('State');
    fireEvent.change(input, { target: { value: 'CA' } });
    expect(onChange).toHaveBeenCalledWith('CA');
  });

  test('renders as disabled when disabled prop is true', () => {
    const onChange = vi.fn();
    render(<StateAutocomplete value="" onChange={onChange} disabled />);
    expect(screen.getByLabelText('State')).toBeDisabled();
  });

  test('shows required marker when required is true', () => {
    const onChange = vi.fn();
    render(<StateAutocomplete value="" onChange={onChange} required />);
    // MUI renders * in label for required fields
    const input = screen.getByRole('combobox');
    expect(input).toHaveAttribute('required');
  });

  test('displays current value', () => {
    const onChange = vi.fn();
    render(<StateAutocomplete value="TX" onChange={onChange} />);
    expect(screen.getByDisplayValue('TX')).toBeInTheDocument();
  });
});
