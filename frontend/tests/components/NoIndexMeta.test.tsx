/**
 * Tests for the noindex meta applied by the public order routes.
 *
 * The capability URL must never reach a search index; robots.txt is the
 * crawler-facing half and this is the half that holds when a crawler ignores
 * robots.txt.
 */

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { NoIndexMeta, NOINDEX_CONTENT } from '../../src/components/NoIndexMeta';

const robotsTags = () => Array.from(document.head.querySelectorAll('meta[name="robots"]'));

describe('NoIndexMeta', () => {
  it('adds a noindex robots meta while mounted', () => {
    render(<NoIndexMeta />);
    const tags = robotsTags();
    expect(tags).toHaveLength(1);
    expect(tags[0].getAttribute('content')).toBe(NOINDEX_CONTENT);
  });

  it('removes the meta on unmount so an authenticated route is not marked noindex', () => {
    const { unmount } = render(<NoIndexMeta />);
    unmount();
    expect(robotsTags()).toHaveLength(0);
  });

  it('replaces a pre-existing robots tag instead of stacking two', () => {
    const existing = document.createElement('meta');
    existing.setAttribute('name', 'robots');
    existing.setAttribute('content', 'index, follow');
    document.head.appendChild(existing);

    render(<NoIndexMeta />);

    const tags = robotsTags();
    expect(tags).toHaveLength(1);
    expect(tags[0].getAttribute('content')).toBe(NOINDEX_CONTENT);
    tags[0].remove();
  });
});
