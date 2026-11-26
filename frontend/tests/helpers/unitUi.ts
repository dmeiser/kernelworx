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

/**
 * Runs `run` with the browser reporting a `width`-pixel viewport.
 *
 * A Kernel runs Show & Sell from the sales floor with a phone in one hand, so the
 * narrow layout is a requirement and not a preference. MUI asks `matchMedia` how wide
 * the window is and its breakpoint hooks read `innerWidth`; jsdom reports a desktop
 * width for both, so a test that never replaces them only ever sees the desktop
 * layout, and a control a phone hides or a table a phone cannot fit passes anyway.
 */
export async function withViewport<T>(width: number, run: () => Promise<T>): Promise<T> {
  const kept = ['innerWidth', 'outerWidth', 'matchMedia'].map(
    (key) => [key, Object.getOwnPropertyDescriptor(window, key)] as const,
  );
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'outerWidth', { configurable: true, value: width });
  Object.defineProperty(window, 'matchMedia', { configurable: true, writable: true, value: responsiveMedia(width) });
  try {
    return await run();
  } finally {
    for (const [key, descriptor] of kept) {
      if (descriptor) Object.defineProperty(window, key, descriptor);
    }
  }
}

/** Answers the min/max-width queries MUI asks, measured against `width`. */
export function responsiveMedia(width: number) {
  return (query: string) => {
    const max = /max-width:\s*(\d+)px/.exec(query);
    const min = /min-width:\s*(\d+)px/.exec(query);
    const matches = (max === null || width <= Number(max[1])) && (min === null || width >= Number(min[1]));
    return {
      matches,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => true,
    };
  };
}

/**
 * Tabs until the named control has focus.
 *
 * The walk is the assertion: a control that is `display: none` at this width, or that
 * sits outside a dialog's focus trap, is never reached and the loop throws.
 */
export async function focusByTab(element: HTMLElement, user: User): Promise<void> {
  for (let step = 0; step < 15; step += 1) {
    if (document.activeElement === element) return;
    await user.tab();
  }
  throw new Error(`Tab never reached ${element.getAttribute('data-testid') ?? element.getAttribute('aria-label')}`);
}

/**
 * The nearest element that scrolls sideways, i.e. the one holding content wider than itself.
 *
 * A phone cannot hold a wide table and the page does not scroll sideways, so the rows
 * have to scroll inside their own container. jsdom performs no layout — `scrollWidth`
 * reads 0 whatever the markup is — so what a test can prove is the shape that makes a
 * wide column reachable at all: the table sits in a container whose x overflow is
 * `auto` or `scroll`, and not directly in a box that clips or spills.
 */
export function scrollContainerOf(element: HTMLElement): HTMLElement | null {
  let node: HTMLElement | null = element.parentElement;
  while (node) {
    const overflowX = getComputedStyle(node).overflowX;
    if (overflowX === 'auto' || overflowX === 'scroll') return node;
    node = node.parentElement;
  }
  return null;
}
