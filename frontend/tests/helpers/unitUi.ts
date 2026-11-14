/**
 * Shared interaction helpers for the §1.6 component tests.
 *
 * MUI puts a `data-testid` on the field wrapper, not on the element that takes
 * input, so `getByTestId(id)` alone returns a Box that cannot be typed into and a
 * Select whose display node has to be clicked before its options exist. Those two
 * details belong here rather than in every screen's test.
 */

import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

type User = ReturnType<typeof userEvent.setup>;

/** Type into the input inside a field wrapper carrying `testId`. */
export async function typeInto(testId: string, value: string, user: User) {
  const field = await screen.findByTestId(testId);
  const input = (field.tagName === 'INPUT' ? field : field.querySelector('input')) as HTMLElement;
  await user.type(input, value);
}

/** Replace a field's contents, for editing a value that already has one. */
export async function clearAndType(testId: string, value: string, user: User) {
  const field = await screen.findByTestId(testId);
  const input = (field.tagName === 'INPUT' ? field : field.querySelector('input')) as HTMLElement;
  await user.clear(input);
  await user.type(input, value);
}

/** Open a MUI Select by its wrapper test id and choose an option by name. */
export async function chooseOption(testId: string, optionName: string | RegExp, user: User) {
  const field = await screen.findByTestId(testId);
  await user.click(field.querySelector('.MuiSelect-select') as HTMLElement);
  await user.click(await screen.findByRole('option', { name: optionName }));
}

/** Choose an option in a Select found by its accessible name (label). */
export async function chooseOptionByName(label: string | RegExp, optionName: string | RegExp, user: User) {
  await user.click(await screen.findByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: optionName }));
}
