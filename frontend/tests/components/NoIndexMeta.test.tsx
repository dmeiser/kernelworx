import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { NoIndexMeta } from '../../src/components/NoIndexMeta';

const noindexMetas = () =>
  Array.from(document.head.querySelectorAll('meta[name="robots"][content="noindex"]'));

describe('NoIndexMeta', () => {
  it('adds a robots noindex meta tag to the head while mounted and removes it on unmount', () => {
    const { unmount } = render(<NoIndexMeta />);

    expect(noindexMetas()).toHaveLength(1);

    unmount();

    expect(noindexMetas()).toHaveLength(0);
  });
});
