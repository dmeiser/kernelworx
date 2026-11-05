import { describe, expect, it } from 'vitest';
import { generatedUnitDisplayName } from '../../src/lib/unitForm';

/**
 * The backend composes the generated display name as
 * `f"{type} {num} - {city}, {state}"` over the exact strings it receives and
 * stores them verbatim. The client sends the trimmed city/state and renders the
 * preview from the same values, so the preview must equal that f-string output.
 */
describe('generatedUnitDisplayName', () => {
  it('renders the server format for the trimmed values it is given', () => {
    expect(generatedUnitDisplayName('Pack', 3149, 'Aurora', 'CO')).toBe('Pack 3149 - Aurora, CO');
  });

  it('preserves interior whitespace so the preview equals the stored value', () => {
    expect(generatedUnitDisplayName('Troop', 7, 'New  York', 'NY')).toBe('Troop 7 - New  York, NY');
  });

  it('matches the server-composed name for whitespace-padded input sent through the forms', () => {
    const sentCity = '  Aurora  '.trim();
    const sentState = ' CO '.trim();
    expect(generatedUnitDisplayName('Pack', 3149, sentCity, sentState)).toBe(
      `Pack 3149 - ${sentCity}, ${sentState}`,
    );
  });
});
