import { useEffect } from 'react';

/** robots content applied to every public order page. */
export const NOINDEX_CONTENT = 'noindex, nofollow';

/**
 * Adds a `noindex` robots meta for the duration of a route.
 *
 * The public order and receipt pages carry their authorization in the URL, so
 * an indexed copy is a live capability handed to everyone who finds the search
 * result. `frontend/public/robots.txt` is the crawler-facing half; this is the
 * half that works even when a crawler ignores robots.txt.
 */
export const NoIndexMeta: React.FC = () => {
  useEffect(() => {
    document.head.querySelectorAll('meta[name="robots"]').forEach((existing) => existing.remove());
    const meta = document.createElement('meta');
    meta.setAttribute('name', 'robots');
    meta.setAttribute('content', NOINDEX_CONTENT);
    document.head.appendChild(meta);
    return () => {
      meta.remove();
    };
  }, []);

  return null;
};

export default NoIndexMeta;
