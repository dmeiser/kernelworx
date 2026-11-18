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

/**
 * The editable element inside a field wrapper.
 *
 * MUI puts the `data-testid` on the wrapper, and the element that takes input is an
 * `input` for a one-line field and a `textarea` for a multiline one — a helper that
 * only looked for the first would hand back null for the reason field every dialog
 * with one uses.
 */
function editableInside(field: HTMLElement): HTMLElement {
  if (field.tagName === 'INPUT' || field.tagName === 'TEXTAREA') return field;
  return field.querySelector('input, textarea') as HTMLElement;
}

/** Type into the input inside a field wrapper carrying `testId`. */
export async function typeInto(testId: string, value: string, user: User) {
  const field = await screen.findByTestId(testId);
  await user.type(editableInside(field), value);
}

/** Replace a field's contents, for editing a value that already has one. */
export async function clearAndType(testId: string, value: string, user: User) {
  const field = await screen.findByTestId(testId);
  const input = editableInside(field);
  await user.clear(input);
  await user.type(input, value);
}

/** Empty a field, for the case where the admin deletes what they typed and stops. */
export async function clearField(testId: string, user: User) {
  const field = await screen.findByTestId(testId);
  await user.clear(editableInside(field));
}

/**
 * Open a MUI Select by its wrapper test id and return the matching option.
 *
 * The option only exists once the display node has been clicked, and a test that wants
 * to read what an option says has to stop there rather than choose it.
 */
export async function findOption(testId: string, optionName: string | RegExp, user: User): Promise<HTMLElement> {
  const field = await screen.findByTestId(testId);
  await user.click(field.querySelector('.MuiSelect-select') as HTMLElement);
  return screen.findByRole('option', { name: optionName });
}

/** Open a MUI Select by its wrapper test id and choose an option by name. */
export async function chooseOption(testId: string, optionName: string | RegExp, user: User) {
  await user.click(await findOption(testId, optionName, user));
}

/** Choose an option in a Select found by its accessible name (label). */
export async function chooseOptionByName(label: string | RegExp, optionName: string | RegExp, user: User) {
  await user.click(await screen.findByRole('combobox', { name: label }));
  await user.click(await screen.findByRole('option', { name: optionName }));
}
